// Ringleader desk. Plain JS, d3 for the force layout, server-sent events for the live investigation.

const $ = (id) => document.getElementById(id);
const shortDate = (iso) => (iso ? iso.slice(0, 10) : "");
const stamp = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return shortDate(iso);
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const narrow = () => window.matchMedia("(max-width: 900px)").matches;
const FLAG_AT = 6; // rules provider: accounts scoring at or above this are flagged (app/agent.py FLAG_THRESHOLD)

const state = {
  provider: "rules",
  current: null,        // account id under investigation
  caseId: null,
  exhibits: 0,
  flagged: new Set(),
  cashout: new Set(),
  frozen: new Set(),
  members: new Map(),   // id -> member row of the case on screen
  seed: null,
  abort: null,
  alerts: [],
  openCases: new Map(), // seed -> newest case still pending review
  pathing: false,
  confirming: false,
};

const analystName = () => {
  try { return localStorage.getItem("ringleader.analyst") || ""; } catch { return ""; }
};
const saveAnalystName = (v) => { try { localStorage.setItem("ringleader.analyst", v); } catch { /* private mode */ } };

// ------------------------------------------------------------------ health
async function loadHealth() {
  const el = $("health");
  try {
    const h = await (await fetch("/api/health")).json();
    el.classList.toggle("ok", h.ok);
    el.classList.toggle("bad", !h.ok);
    $("health-text").textContent = h.ok ? `FalkorDB · ${h.graph}` : "Graph unreachable";
    el.title = h.ok ? `Connected to ${h.host}` : (h.error || `No answer from ${h.host}`);
    const gem = $("provider-gemini");
    gem.disabled = !h.gemini_configured;
    gem.closest("label").title = h.gemini_configured
      ? "Gemini picks which graph tools to call and writes the verdict. Free-tier quota applies."
      : "Add GEMINI_API_KEY to .env to enable";
    if (!h.ok) toast("The graph is not answering. Check the FalkorDB settings, then reload.", 8000);
    return h.ok;
  } catch {
    el.classList.add("bad");
    $("health-text").textContent = "API unreachable";
    return false;
  }
}

// ------------------------------------------------------------------ queue
function alertStatus(a) {
  if (a.status === "frozen") return { label: "frozen", cls: "frozen" };
  if (state.openCases.has(a.account)) return { label: "case open", cls: "open" };
  return { label: a.status || "", cls: a.status || "" };
}

function queueItem(a, kind) {
  const li = document.createElement("li");
  const b = document.createElement("button");
  b.type = "button";
  if (kind === "alert") {
    const s = alertStatus(a);
    b.dataset.id = a.account;
    b.innerHTML = `
      <span class="id">${esc(a.account)}</span>
      <span class="status ${esc(s.cls)}">${esc(s.label)}</span>
      <span class="name">${esc(a.name)}</span>
      <span class="why">${esc(a.reason)}</span>`;
    b.addEventListener("click", () => {
      const open = state.openCases.get(a.account);
      if (open && a.status !== "frozen") openCase(open.id); else investigate(a.account);
    });
  } else {
    b.dataset.id = a.id;
    b.dataset.seed = a.seed;
    const status = a.status === "pending_review" ? `${a.pending_actions} pending` : (a.status || "").replace("_", " ");
    b.innerHTML = `
      <span class="id">${esc(a.seed)}</span>
      <span class="status ${esc(a.verdict)}">${esc({ ring: "ring", benign: "no ring", uncertain: "uncertain" }[a.verdict] || a.verdict)}</span>
      <span class="name">${esc(stamp(a.opened_at))} · ${esc(plural(a.implicated, "account"))} · ${esc(status)}</span>
      <span class="why">${esc(a.id)} · ${esc(a.provider)}</span>`;
    b.addEventListener("click", () => openCase(a.id));
  }
  li.appendChild(b);
  return li;
}

function renderAlerts() {
  const ol = $("alerts");
  ol.removeAttribute("aria-busy");
  ol.innerHTML = "";
  if (!state.alerts.length) {
    ol.innerHTML = `<li class="empty-row">No alerts tripped. Seed the graph with <code>python -m app.seed</code>.</li>`;
  }
  // Frozen accounts are already handled; keep them, but at the bottom.
  const sorted = [...state.alerts].sort((x, y) => (x.status === "frozen") - (y.status === "frozen"));
  sorted.forEach((a) => ol.appendChild(queueItem(a, "alert")));
  markCurrent();
  renderBoardStart();
}

async function loadAlerts() {
  try {
    const { alerts } = await (await fetch("/api/alerts")).json();
    state.alerts = alerts;
    renderAlerts();
  } catch {
    $("alerts").removeAttribute("aria-busy");
    $("alerts").innerHTML = `<li class="empty-row">Could not load alerts. <button type="button" class="link" id="retry-alerts">Try again</button></li>`;
    $("retry-alerts")?.addEventListener("click", loadAlerts);
  }
}

async function loadCases() {
  const ol = $("cases");
  try {
    const { cases } = await (await fetch("/api/cases")).json();
    state.openCases = new Map();
    for (const c of cases) if (c.status === "pending_review" && !state.openCases.has(c.seed)) state.openCases.set(c.seed, c);
    ol.innerHTML = "";
    if (!cases.length) ol.innerHTML = `<li class="empty-row">No cases yet. Investigate an alert and its case is filed here.</li>`;
    cases.forEach((c) => ol.appendChild(queueItem(c, "case")));
    if (state.alerts.length) renderAlerts(); else markCurrent();
  } catch {
    ol.innerHTML = `<li class="empty-row">Could not load cases.</li>`;
  }
}

function markCurrent() {
  document.querySelectorAll(".list button").forEach((b) => {
    const on = b.dataset.id === state.caseId || (!b.dataset.seed && b.dataset.id === state.current);
    if (on) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
  });
}

function nextAlert() {
  const order = [...$("alerts").querySelectorAll("button[data-id]")].map((b) => b.dataset.id);
  const fresh = state.alerts.filter((a) => a.status !== "frozen" && !state.openCases.has(a.account) && a.account !== state.current);
  const start = Math.max(0, order.indexOf(state.current));
  const pick = order.slice(start + 1).concat(order.slice(0, start)).find((id) => fresh.some((a) => a.account === id));
  if (pick) investigate(pick); else toast("Every alert in the queue has a case or is frozen.");
}

function renderBoardStart() {
  const btn = $("board-start");
  const top = state.alerts.find((a) => a.status !== "frozen");
  if (!top) { btn.hidden = true; $("board-start-why").textContent = ""; return; }
  const open = state.openCases.get(top.account);
  btn.hidden = false;
  btn.textContent = open ? `Open the case on ${top.account}` : `Investigate ${top.account}`;
  btn.onclick = () => (open ? openCase(open.id) : investigate(top.account));
  $("board-start-why").textContent = `Top of the queue: ${top.reason}.`;
}

// ------------------------------------------------------------------ board (d3-force)
const svg = d3.select("#canvas");
let sim, root, gEdges, gNodes, zoom, userZoomed = false, nodesById = new Map(), nodes = [], edges = [];
const R = { Account: 9, Device: 5.5, Phone: 5.5, Card: 5.5, Address: 5.5, IP: 4.5 };

function initCanvas() {
  const desc = $("canvas-desc")?.textContent || "Empty board. No account is under investigation.";
  svg.selectAll("*").remove();
  svg.append("desc").attr("id", "canvas-desc").text(desc);
  svg.append("defs").html(`<marker id="arrow" viewBox="0 0 10 10" refX="14" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#b3261e"/></marker>`);
  root = svg.append("g").attr("class", "root");
  gEdges = root.append("g").attr("class", "edges");
  gNodes = root.append("g").attr("class", "nodes");
  zoom = d3.zoom().scaleExtent([0.3, 3]).on("zoom", (ev) => {
    root.attr("transform", ev.transform);
    if (ev.sourceEvent) userZoomed = true;
  });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.call(zoom.transform, d3.zoomIdentity);
  userZoomed = false;
  const { width, height } = svg.node().getBoundingClientRect();
  sim = d3.forceSimulation()
    .force("link", d3.forceLink().id((d) => d.id).distance((l) => (l.type === "PAID" ? 110 : 62)).strength(0.55))
    .force("charge", d3.forceManyBody().strength(-260))
    .force("collide", d3.forceCollide().radius((d) => R[d.kind] + (d.kind === "Account" ? 18 : 8)))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .on("tick", tick)
    .on("end", () => { if (!userZoomed) fitView(true); });
  nodes = []; edges = []; nodesById = new Map();
  state.pathing = false;
  svg.classed("pathing", false);
  $("fit").hidden = true;
  $("board-empty").hidden = false;
}

function tick() {
  gEdges.selectAll("line").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
  gNodes.selectAll("g.node").attr("transform", (d) => `translate(${d.x},${d.y})`);
}

function fitView(animate = true) {
  if (!nodes.length) return;
  const { width, height } = svg.node().getBoundingClientRect();
  if (!width || !height) return;
  const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y);
  const pad = 36;
  const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad + 14;
  const legend = narrow() ? 0 : 44; // keep the ring clear of the legend strip
  const k = Math.max(0.45, Math.min(1.3, Math.min(width / (x1 - x0), (height - legend) / (y1 - y0)) * 0.9));
  const t = d3.zoomIdentity.translate(width / 2, (height - legend) / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
  const target = animate && !reducedMotion() ? svg.transition().duration(450).ease(d3.easeCubicOut) : svg;
  target.call(zoom.transform, t);
  userZoomed = false;
}

function mergeGraph(data, { entering = true } = {}) {
  const { width, height } = svg.node().getBoundingClientRect();
  const seedNode = state.seed ? nodesById.get(state.seed) : null;
  const ox = seedNode ? seedNode.x : width / 2, oy = seedNode ? seedNode.y : height / 2;
  let added = 0;
  for (const n of data.nodes) {
    if (!nodesById.has(n.id)) {
      const node = { ...n, x: ox + (Math.random() - 0.5) * 30, y: oy + (Math.random() - 0.5) * 30, fresh: entering };
      nodesById.set(n.id, node); nodes.push(node); added++;
    } else {
      Object.assign(nodesById.get(n.id), { status: n.status });
    }
  }
  const have = new Set(edges.map((e) => `${e.source.id || e.source}|${e.type}|${e.target.id || e.target}`));
  for (const e of data.edges) {
    const key = `${e.src}|${e.type}|${e.dst}`;
    if (!have.has(key) && nodesById.has(e.src) && nodesById.has(e.dst)) {
      edges.push({ source: e.src, target: e.dst, type: e.type, count: e.count, total: e.total, fresh: entering });
      have.add(key);
    }
  }
  $("board-empty").hidden = nodes.length > 0;
  $("fit").hidden = nodes.length === 0;
  render();
  sim.nodes(nodes); sim.force("link").links(edges); sim.alpha(added ? 0.9 : 0.3).restart();
}

function render() {
  const lines = gEdges.selectAll("line").data(edges, (d) => `${d.source.id || d.source}|${d.type}|${d.target.id || d.target}`);
  lines.exit().remove();
  lines.enter().append("line").attr("class", (d) => `edge ${d.type}${d.fresh ? " entering" : ""}`).merge(lines)
    .attr("class", (d) => `edge ${d.type}${d.lit ? " lit" : ""}`);

  const groups = gNodes.selectAll("g.node").data(nodes, (d) => d.id);
  groups.exit().remove();
  const enter = groups.enter().append("g").attr("class", (d) => `node ${d.kind}${d.fresh ? " entering" : ""}`)
    .call(d3.drag().on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; userZoomed = true; })
      .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }))
    .on("mouseenter", showTip).on("mousemove", moveTip).on("mouseleave", hideTip);
  enter.append("circle").attr("class", "ring").attr("r", (d) => R[d.kind] + 4);
  enter.append("circle").attr("class", "body").attr("r", (d) => R[d.kind]);
  enter.append("text").attr("dy", (d) => R[d.kind] + 13).attr("text-anchor", "middle")
    .text((d) => (d.kind === "Account" ? d.id : ""));
  enter.merge(groups).attr("class", (d) => nodeClass(d));
}

function nodeClass(d) {
  const c = ["node", d.kind];
  if (d.id === state.seed) c.push("seed");
  if (state.flagged.has(d.id)) c.push("flagged");
  if (state.cashout.has(d.id)) c.push("cashout");
  if (d.status === "frozen" || state.frozen.has(d.id)) c.push("frozen");
  if (d.lit) c.push("lit");
  return c.join(" ");
}

function lightPath(ids, label) {
  const set = new Set(ids);
  for (const n of nodes) n.lit = set.has(n.id);
  for (const e of edges) e.lit = set.has(e.source.id) && set.has(e.target.id);
  state.pathing = true;
  svg.classed("pathing", true);
  render();
  if (label) $("board-sub").textContent = `Path: ${label}. Esc clears it.`;
}

function clearPath() {
  if (!state.pathing) return;
  for (const n of nodes) n.lit = false;
  for (const e of edges) e.lit = false;
  state.pathing = false;
  svg.classed("pathing", false);
  render();
  boardSummary();
}

function boardSummary() {
  if (!state.seed) return;
  const n = state.flagged.size;
  $("board-sub").textContent = n ? `${plural(n, "account")} flagged around ${state.seed}` : `No ring around ${state.seed}`;
}

function showTip(ev, d) {
  const t = $("tooltip");
  const m = state.members.get(d.id);
  const extra = d.kind === "Account"
    ? `${esc(d.label)} · opened ${shortDate(d.created_at)} · ${esc(d.status || "")}${m ? `<br><b>${esc(m.role)}</b> · ${Number(m.score).toFixed(0)} pts` : ""}`
    : esc(d.kind);
  t.innerHTML = `<div class="id">${esc(d.id)}</div><div class="meta">${extra}</div>`;
  t.hidden = false; moveTip(ev);
}
function moveTip(ev) {
  const t = $("tooltip"); const r = svg.node().getBoundingClientRect();
  const x = Math.min(ev.clientX - r.left + 14, r.width - t.offsetWidth - 8);
  t.style.left = `${Math.max(8, x)}px`; t.style.top = `${ev.clientY - r.top + 14}px`;
}
function hideTip() { $("tooltip").hidden = true; }

async function drawAccounts(ids, opts) {
  if (!ids.length) return;
  const res = await fetch(`/api/graph?ids=${encodeURIComponent(ids.slice(0, 150).join(","))}`);
  if (!res.ok) return;
  const { data } = await res.json();
  mergeGraph(data, opts);
}

function describeBoard(f) {
  const cash = (f.members || []).find((m) => m.role === "cashout");
  $("canvas-desc").textContent = `${f.verdict === "ring" ? "Ring" : f.verdict === "benign" ? "No ring" : "Uncertain"} around ${state.seed}. `
    + `${plural((f.members || []).length, "account")} flagged${cash ? `; ${cash.id} is the cash-out account` : ""}. `
    + "The implicated accounts are listed in the case panel.";
}

// ------------------------------------------------------------------ case panel
function resetCase(accountId) {
  state.current = accountId; state.caseId = null; state.exhibits = 0; state.seed = accountId;
  state.flagged = new Set(); state.cashout = new Set(); state.frozen = new Set(); state.members = new Map();
  state.confirming = false;
  initCanvas();
  $("canvas-desc").textContent = `Investigating ${accountId}.`;
  $("case-empty").hidden = true;
  $("exhibit-list").innerHTML = "";
  $("exhibits").hidden = false;
  $("members").hidden = true; $("actions").hidden = true;
  $("rerun").hidden = true;
  $("verdict").hidden = false;
  $("verdict").className = "verdict running";
  $("verdict").innerHTML = `<p class="live">Investigating ${esc(accountId)} with the ${esc(state.provider)} investigator…</p>
    <div class="verdict-skel" aria-hidden="true"><span></span><span></span><span></span></div>`;
  $("case-sub").textContent = `${accountId} · in progress`;
  $("board-sub").textContent = `Expanding from ${accountId}`;
  markCurrent();
  if (narrow()) $("board").scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
}

function addExhibit(ev, { reveal = false, quiet = false } = {}) {
  const ol = $("exhibit-list");
  const li = document.createElement("li");
  if (ev.type === "thought") {
    li.className = "note";
    li.innerHTML = `<p class="thought">${esc(ev.text)}</p>`;
  } else if (ev.type === "error") {
    li.className = "note";
    li.innerHTML = `<p class="error">${esc(ev.message)}</p>`;
  } else {
    state.exhibits++;
    const queries = ev.result?.queries || ev.queries || [];
    const ms = queries.reduce((s, q) => s + (q.run_ms || 0), 0);
    const rows = queries.reduce((s, q) => s + (Array.isArray(q.rows) ? q.rows.length : (q.rows || 0)), 0);
    li.innerHTML = `
      <div class="head">
        <span class="num">${state.exhibits}</span>
        <span class="tool">${esc(ev.name)}</span>
        <span class="ms">${ms.toFixed(1)} ms · ${plural(rows, "row")}</span>
        <span class="summary">${esc(ev.summary || "")}</span>
        <details><summary>Cypher (${queries.length})</summary>${queries.map((q) => `<pre>${esc(q.cypher)}${Object.keys(q.params || {}).length ? "\n-- params " + esc(JSON.stringify(q.params)) : ""}</pre>`).join("")}</details>
      </div>`;
  }
  ol.appendChild(li);
  if (reveal) {
    li.classList.add("flash");
    li.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
  } else if (!quiet && !state.caseId && !narrow()) {
    // Follow the live run inside the case panel. On a phone the panel is the page, so stay on the board.
    li.scrollIntoView({ block: "nearest" });
  }
}

function renderFindings(f, members, actions, caseMeta) {
  const v = $("verdict");
  $("case-body").scrollTop = 0;
  v.className = `verdict ${f.verdict}`;
  const word = { ring: "Ring", benign: "No ring", uncertain: "Uncertain" }[f.verdict] || f.verdict;
  v.innerHTML = `<div class="stamp">${esc(word)}</div>
    <p class="conf">Confidence ${Math.round((f.confidence || 0) * 100)}%${caseMeta ? ` · ${esc(caseMeta.id)} · ${esc(caseMeta.provider)} · opened ${esc(stamp(caseMeta.opened_at))}` : ""}</p>
    <p class="summary">${esc(f.summary || "")}</p>`;

  state.members = new Map((members || []).map((x) => [x.id, x]));
  const m = $("members");
  m.hidden = false;
  const list = (members || []).map((x) => `
    <li data-member="${esc(x.id)}">
      <span class="id">${esc(x.id)}</span>
      <span class="role ${esc(x.role)}">${esc(x.role)}</span>
      <span class="score" title="Rules score. ${FLAG_AT} points or more puts an account on the list.">${Number(x.score).toFixed(0)} pts${x.status ? ` · ${esc(x.status)}` : ""}</span>
      <span class="reason">${esc(x.reason)}</span>
      ${x.id !== state.seed ? `<button type="button" class="link path-btn" data-explain="${esc(x.id)}" aria-label="Show the identifier chain from ${esc(state.seed)} to ${esc(x.id)}">Show the link to ${esc(state.seed)}</button>` : ""}
      <p class="chain" hidden></p>
    </li>`).join("");
  m.innerHTML = `<h3>${plural(members?.length || 0, "implicated account")} <span class="hint">scored on shared identifiers, account age and money flow; ${FLAG_AT} pts or more is flagged</span></h3>
    <ul>${list || '<li class="reason">None. The links around this account look like ordinary life, not a ring.</li>'}</ul>`;
  m.querySelectorAll("[data-explain]").forEach((b) => b.addEventListener("click", () => explain(state.seed, b.dataset.explain, b)));

  renderActions(actions || []);
  describeBoard({ ...f, members });
}

function actionLabel(selected) {
  const freeze = selected.filter((x) => x.type === "freeze").length;
  const other = selected.length - freeze;
  if (!selected.length) return "Select actions to approve";
  if (!other) return `Freeze ${plural(freeze, "account")}`;
  if (!freeze) return `Approve ${plural(other, "action")}`;
  return `Freeze ${freeze}, approve ${plural(other, "other action")}`;
}

function renderActions(actions) {
  const a = $("actions");
  a.hidden = false;
  state.confirming = false;
  if (!actions.length) {
    a.innerHTML = `<h3 id="actions-title">Proposed actions</h3><p class="gate">Nothing proposed. No account changes.</p>`;
    return;
  }
  const pending = actions.filter((x) => x.status === "pending");
  const filed = Boolean(state.caseId);
  a.innerHTML = `<h3 id="actions-title">${pending.length ? `${plural(pending.length, "proposed action")}, waiting for you` : "Decisions"}</h3>
    <ul>${actions.map((x) => {
      const mem = state.members.get(x.target);
      return `
      <li class="action ${x.status === "pending" ? "" : "decided"}" title="${esc(x.reason)}">
        ${x.status === "pending" ? `<input type="checkbox" id="act-${esc(x.id)}" data-action="${esc(x.id)}" data-type="${esc(x.type)}" data-target="${esc(x.target)}" checked>` : `<span aria-hidden="true"></span>`}
        <label for="act-${esc(x.id)}"><span class="type ${esc(x.type)}">${esc(x.type)}</span> <span class="target">${esc(x.target)}</span>${mem ? ` <span class="role-tag ${esc(mem.role)}">${esc(mem.role)}</span>` : ""}</label>
        <span class="state ${esc(x.status)}">${esc(x.status)}${x.approved_by ? ` · ${esc(x.approved_by)}` : ""}</span>
      </li>`;
    }).join("")}</ul>
    ${pending.length ? `
    <div class="bar" id="decide-bar">
      <div class="who"><label for="who">Approving as</label><input id="who" type="text" maxlength="120" placeholder="Your name" value="${esc(analystName())}" autocomplete="name"></div>
      <div class="buttons">
        <button type="button" class="btn btn-danger" id="approve" ${filed ? "" : "disabled"}></button>
        <button type="button" class="btn btn-ghost" id="reject" ${filed ? "" : "disabled"}>Reject</button>
      </div>
      <p class="gate">${filed ? "The investigator cannot freeze anything. Approving writes your name on each action and changes the account status." : "Filing the case before anything can be approved…"}</p>
    </div>` : `
    <div class="bar done">
      <p class="gate">All actions decided. The account statuses on the board reflect them.</p>
      <button type="button" class="btn" id="next-alert">Next alert</button>
    </div>`}`;
  a.querySelectorAll("input[data-action]").forEach((i) => i.addEventListener("change", syncDecideBar));
  $("who")?.addEventListener("input", (e) => saveAnalystName(e.target.value.trim()));
  $("approve")?.addEventListener("click", () => confirmDecision(true));
  $("reject")?.addEventListener("click", () => confirmDecision(false));
  $("next-alert")?.addEventListener("click", nextAlert);
  syncDecideBar();
}

function selectedActions() {
  return [...document.querySelectorAll("#actions input[data-action]:checked")]
    .map((i) => ({ id: i.dataset.action, type: i.dataset.type, target: i.dataset.target }));
}

function syncDecideBar() {
  const sel = selectedActions();
  const ap = $("approve"), rj = $("reject");
  if (!ap) return;
  ap.textContent = actionLabel(sel);
  const ready = Boolean(state.caseId) && sel.length > 0;
  ap.disabled = !ready; rj.disabled = !ready;
  rj.textContent = sel.length ? `Reject ${sel.length}` : "Reject";
}

function confirmDecision(approve) {
  const sel = selectedActions();
  if (!sel.length || !state.caseId) return;
  const who = ($("who")?.value || "").trim();
  if (!who) { $("who").focus(); toast("Type your name first. It is written on every action you decide."); return; }
  saveAnalystName(who);
  state.confirming = true;
  const names = sel.map((x) => x.target);
  const list = names.length > 4 ? `${names.slice(0, 3).join(", ")} and ${names.length - 3} more` : names.join(", ");
  const verb = approve ? actionLabel(sel).replace(/^Freeze/, "freeze").replace(/^Approve/, "approve") : `reject ${plural(sel.length, "action")}`;
  const bar = $("decide-bar");
  bar.classList.add("confirm", approve ? "approve" : "reject");
  bar.innerHTML = `
    <p class="confirm-q">${esc(who)}, ${esc(verb)}${approve ? `: ${esc(list)}` : ""}?</p>
    <p class="gate">${approve ? "Their status changes in the graph now, with your name on each action." : "The proposals are closed and no account changes."}</p>
    <div class="buttons">
      <button type="button" class="btn ${approve ? "btn-danger" : ""}" id="confirm-yes">${approve ? "Confirm freeze" : "Confirm reject"}</button>
      <button type="button" class="btn btn-ghost" id="confirm-no">Back</button>
    </div>`;
  $("confirm-yes").addEventListener("click", () => decide(approve, sel.map((x) => x.id), who));
  $("confirm-no").addEventListener("click", () => openCase(state.caseId, { keepBoard: true, focusActions: true }));
  $("confirm-yes").focus();
}

async function decide(approve, ids, who) {
  const yes = $("confirm-yes");
  if (yes) { yes.disabled = true; yes.textContent = approve ? "Freezing…" : "Rejecting…"; }
  let res;
  try {
    res = await fetch(`/api/cases/${state.caseId}/decide`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action_ids: ids, who, approve }) });
  } catch {
    toast("The decision did not reach the server. Nothing changed; try again.", 6000);
    if (yes) { yes.disabled = false; yes.textContent = approve ? "Confirm freeze" : "Confirm reject"; }
    return;
  }
  if (!res.ok) {
    toast(`The server refused the decision (${res.status}). Nothing changed.`, 6000);
    await openCase(state.caseId, { keepBoard: true });
    return;
  }
  const out = await res.json();
  if (approve) for (const row of out.applied) if (row.status === "frozen") state.frozen.add(row.account);
  toast(approve
    ? `${plural(out.applied.length, "action")} approved by ${who}. Case ${(out.case_status || "").replace("_", " ")}.`
    : `${plural(ids.length, "action")} rejected. Case ${(out.case_status || "").replace("_", " ")}.`);
  await openCase(state.caseId, { keepBoard: true, focusActions: true });
  loadCases();
  loadAlerts();
}

async function explain(a, b, button) {
  if (button) { button.disabled = true; button.textContent = "Tracing…"; }
  let data, queries;
  try {
    const res = await fetch(`/api/tools/explain_link?account_a=${encodeURIComponent(a)}&account_b=${encodeURIComponent(b)}`);
    if (!res.ok) throw new Error(String(res.status));
    ({ data, queries } = await res.json());
  } catch (err) {
    toast(`Could not trace ${a} to ${b} (${err.message}).`);
    if (button) { button.disabled = false; button.textContent = `Show the link to ${a}`; }
    return;
  }
  const chainText = data.connected ? [a, ...data.chain.map((c) => c.id)].join(" → ") : `${a} and ${b} share no identifier chain`;
  addExhibit({ type: "tool", name: "explain_link", summary: data.connected ? `${a} → ${data.chain.map((c) => `${c.kind}:${c.id}`).join(" → ")}` : chainText, result: { queries } });
  if (button) {
    button.disabled = false; button.textContent = `Show the link to ${a}`;
    const p = button.parentElement.querySelector(".chain");
    if (p) { p.hidden = false; p.textContent = chainText; }
  }
  if (data.connected) {
    const ids = [a, ...data.chain.map((c) => c.id)];
    await drawAccounts(ids.filter((id) => id.startsWith("acc_")), { entering: false });
    lightPath(ids, chainText);
  }
}

// ------------------------------------------------------------------ investigation stream
async function investigate(accountId) {
  if (state.abort) state.abort.abort();
  const ctrl = new AbortController(); state.abort = ctrl;
  resetCase(accountId);
  await drawAccounts([accountId]);
  let res;
  try {
    res = await fetch("/api/investigate", { method: "POST", signal: ctrl.signal, headers: { "content-type": "application/json" }, body: JSON.stringify({ account_id: accountId, provider: state.provider }) });
  } catch (err) { if (err.name !== "AbortError") fail(`Could not start: ${err.message}`); return; }
  if (!res.ok) {
    const body = (await res.text()).slice(0, 200);
    fail(res.status === 404 ? `account ${accountId} not found`
      : res.status === 422 ? "That is not a valid account id. Account ids look like acc_0391."
      : `The server refused the investigation (${res.status}). ${body}`);
    return;
  }
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
        const data = block.split("\n").find((l) => l.startsWith("data: "));
        if (!data) continue;
        let ev; try { ev = JSON.parse(data.slice(6)); } catch { continue; }
        if (state.abort !== ctrl) return; // a newer investigation took over
        await handleEvent(ev);
      }
    }
  } catch (err) {
    if (err.name !== "AbortError") fail(`The stream broke: ${err.message}. Run it again.`);
  }
}

function fail(msg) {
  const missing = /^account (.+) not found$/.exec(msg || "");
  if (missing) msg = `There is no account called ${missing[1]}. Check the id; account ids look like acc_0391.`;
  if (!nodes.length) $("board-sub").textContent = "Nothing to pin.";
  $("verdict").className = "verdict uncertain";
  $("verdict").innerHTML = `<div class="stamp">Stopped</div><p class="summary">${esc(msg)}</p>`;
  $("case-sub").textContent = `${state.current} · stopped`;
  $("rerun").hidden = !state.current || state.exhibits === 0;
  if (state.exhibits === 0 && !$("exhibit-list").children.length) $("exhibits").hidden = true;
}

async function handleEvent(ev) {
  switch (ev.type) {
    case "tool": {
      addExhibit(ev);
      const d = ev.result?.data || {};
      if (ev.name === "shared_identifiers") await drawAccounts([state.seed, ...(d.neighbours || []).map((n) => n.account)]);
      if (ev.name === "expand_ring") { const ids = [state.seed, ...(d.candidates || []).map((c) => c.account)]; await drawAccounts(ids); $("board-sub").textContent = `${plural(ids.length, "account")} within 3 identifier hops of ${state.seed}`; }
      if (ev.name === "money_flow" && d.sinks?.length) await drawAccounts([d.sinks[0].sink, ...d.sinks[0].senders], { entering: true });
      if (ev.name === "explain_link" && d.connected) { await drawAccounts([d.from, d.to], { entering: false }); }
      break;
    }
    case "thought": addExhibit(ev); break;
    case "findings": {
      const f = ev.findings;
      state.flagged = new Set(f.members.map((m) => m.id));
      state.cashout = new Set(f.members.filter((m) => m.role === "cashout").map((m) => m.id));
      await drawAccounts([...state.flagged], { entering: true });
      render();
      renderFindings(f, f.members, f.proposed_actions.map((a, i) => ({ ...a, id: `pending-${i}`, status: "pending" })));
      boardSummary();
      break;
    }
    case "case": {
      state.caseId = ev.case_id;
      const c = ev.case;
      renderFindings(c, c.members, c.actions, c);
      $("case-sub").textContent = `${state.seed} · case filed ${stamp(c.opened_at)}`;
      $("rerun").hidden = false;
      loadCases(); markCurrent();
      $("case-title").focus({ preventScroll: true });
      break;
    }
    case "error": if (ev.recoverable) addExhibit(ev); else fail(ev.message); break;
    default: break;
  }
}

// ------------------------------------------------------------------ replay a stored case
async function openCase(caseId, { keepBoard = false, focusActions = false } = {}) {
  if (!keepBoard && state.abort) { state.abort.abort(); state.abort = null; }
  const res = await fetch(`/api/cases/${caseId}`);
  if (!res.ok) { toast("That case could not be found. It may have been reset."); return; }
  const c = await res.json();
  if (!keepBoard) {
    resetCase(c.seed);
    $("verdict").className = "verdict running";
    for (const step of c.trace || []) addExhibit(step.type === "tool" ? { ...step, result: { queries: step.queries.map((q) => ({ ...q, rows: q.rows })) } } : step, { quiet: true });
    const ids = [c.seed, ...c.members.map((m) => m.id)];
    state.flagged = new Set(c.members.map((m) => m.id));
    state.cashout = new Set(c.members.filter((m) => m.role === "cashout").map((m) => m.id));
    await drawAccounts(ids, { entering: true });
  }
  state.caseId = c.id; state.current = c.seed;
  for (const m of c.members) if (m.status === "frozen") state.frozen.add(m.id);
  render();
  renderFindings(c, c.members, c.actions, c);
  const status = (c.status || "").replace("_", " ");
  $("case-sub").textContent = `${c.seed} · ${status}`;
  $("rerun").hidden = false;
  if (!keepBoard) boardSummary();
  markCurrent();
  if (focusActions) ($("approve") || $("next-alert") || $("case-title")).focus({ preventScroll: false });
  else if (!keepBoard) $("case-title").focus({ preventScroll: true });
}

// ------------------------------------------------------------------ misc
let toastTimer;
function toast(msg, ms = 4500) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), ms);
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function selectTab(tab, focus = false) {
  document.querySelectorAll('[role="tab"]').forEach((t) => {
    const on = t === tab;
    t.setAttribute("aria-selected", on ? "true" : "false");
    t.tabIndex = on ? 0 : -1;
  });
  $("alerts").hidden = tab.dataset.tab !== "alerts"; $("cases").hidden = tab.dataset.tab !== "cases";
  if (tab.dataset.tab === "cases") loadCases();
  if (focus) tab.focus();
}
const tabs = [...document.querySelectorAll('[role="tab"]')];
tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    selectTab(tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length], true);
  });
});

function moveInList(step) {
  const list = !$("alerts").hidden ? $("alerts") : $("cases");
  const items = [...list.querySelectorAll("button[data-id]")];
  if (!items.length) return;
  let i = items.indexOf(document.activeElement);
  if (i < 0) i = Math.max(0, items.findIndex((b) => b.getAttribute("aria-current") === "true"));
  else i = Math.min(items.length - 1, Math.max(0, i + step));
  items[i].focus();
  items[i].scrollIntoView({ block: "nearest" });
}

document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const typing = e.target.closest("input, textarea, select, [contenteditable]");
  if (e.key === "Escape") {
    if (state.confirming) { openCase(state.caseId, { keepBoard: true, focusActions: true }); return; }
    clearPath(); hideTip(); return;
  }
  if (typing) return;
  if (e.key === "j") { e.preventDefault(); moveInList(1); }
  else if (e.key === "k") { e.preventDefault(); moveInList(-1); }
  else if (e.key === "n") { e.preventDefault(); nextAlert(); }
  else if (e.key === "f") { e.preventDefault(); fitView(true); }
  else if (e.key === "/") { e.preventDefault(); $("lookup-id").focus(); }
});

svg.on("click", (ev) => { if (ev.target === svg.node()) clearPath(); });
$("fit").addEventListener("click", () => fitView(true));
$("rerun").addEventListener("click", () => { if (state.current) investigate(state.current); });
$("provider").addEventListener("change", (e) => { state.provider = e.target.value; });
$("lookup").addEventListener("submit", (e) => { e.preventDefault(); const id = $("lookup-id").value.trim(); if (id) investigate(id); });
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (!sim) return;
    const { width, height } = svg.node().getBoundingClientRect();
    sim.force("center", d3.forceCenter(width / 2, height / 2));
    if (!userZoomed) fitView(false);
  }, 150);
});

initCanvas();
// Health, the queue and the open cases load in parallel: one round trip before the desk is usable.
loadHealth().then((ok) => { if (!ok) $("alerts").innerHTML = `<li class="empty-row">The queue needs the graph. Check the FalkorDB settings and reload.</li>`; });
loadAlerts();
loadCases();
