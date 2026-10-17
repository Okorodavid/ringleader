// Ringleader desk. Plain JS, d3 for the force layout, server-sent events for the live investigation.

const $ = (id) => document.getElementById(id);
const fmtNGN = (v) => "NGN " + Math.round(v).toLocaleString("en-NG");
const shortDate = (iso) => (iso ? iso.slice(0, 10) : "");

const state = {
  provider: "rules",
  current: null,        // account id under investigation
  caseId: null,
  exhibits: 0,
  flagged: new Set(),
  cashout: new Set(),
  frozen: new Set(),
  seed: null,
  abort: null,
};

// ------------------------------------------------------------------ health
async function loadHealth() {
  const el = $("health");
  try {
    const h = await (await fetch("/api/health")).json();
    el.classList.toggle("ok", h.ok);
    el.classList.toggle("bad", !h.ok);
    $("health-text").textContent = h.ok ? `FalkorDB · ${h.graph}` : `FalkorDB unreachable at ${h.host}`;
    const gem = $("provider-gemini");
    gem.disabled = !h.gemini_configured;
    gem.closest("label").title = h.gemini_configured ? "Gemini chooses which graph tools to call" : "Add GEMINI_API_KEY to .env to enable";
    if (!h.ok) toast(`The graph at ${h.host} is not answering. Start FalkorDB or fix .env, then reload.`, 8000);
    return h.ok;
  } catch (err) {
    el.classList.add("bad");
    $("health-text").textContent = "API unreachable";
    return false;
  }
}

// ------------------------------------------------------------------ queue
function queueItem(a, kind) {
  const li = document.createElement("li");
  const b = document.createElement("button");
  b.type = "button";
  b.dataset.id = kind === "alert" ? a.account : a.id;
  const status = kind === "alert" ? (a.status || "") : (a.verdict || "");
  b.innerHTML = `
    <span class="id">${esc(kind === "alert" ? a.account : a.id)}</span>
    <span class="status ${esc(status)}">${esc(status)}</span>
    <span class="name">${esc(kind === "alert" ? a.name : `${a.seed} · ${a.implicated} implicated`)}</span>
    <span class="why">${esc(kind === "alert" ? a.reason : `${shortDate(a.opened_at)} · ${a.pending_actions} pending · ${a.provider}`)}</span>`;
  b.addEventListener("click", () => (kind === "alert" ? investigate(a.account) : openCase(a.id)));
  li.appendChild(b);
  return li;
}

async function loadAlerts() {
  const ol = $("alerts");
  ol.innerHTML = "";
  try {
    const { alerts } = await (await fetch("/api/alerts")).json();
    if (!alerts.length) ol.innerHTML = `<li class="empty-row">No alerts tripped. Seed the graph with <code>python -m app.seed</code>.</li>`;
    alerts.forEach((a) => ol.appendChild(queueItem(a, "alert")));
  } catch {
    ol.innerHTML = `<li class="empty-row">Could not load alerts.</li>`;
  }
  markCurrent();
}

async function loadCases() {
  const ol = $("cases");
  ol.innerHTML = "";
  try {
    const { cases } = await (await fetch("/api/cases")).json();
    if (!cases.length) ol.innerHTML = `<li class="empty-row">No cases yet. Investigate an alert and one will be filed here.</li>`;
    cases.forEach((c) => ol.appendChild(queueItem(c, "case")));
  } catch {
    ol.innerHTML = `<li class="empty-row">Could not load cases.</li>`;
  }
}

function markCurrent() {
  document.querySelectorAll(".list button").forEach((b) => {
    b.setAttribute("aria-current", b.dataset.id === state.current || b.dataset.id === state.caseId ? "true" : "false");
  });
}

// ------------------------------------------------------------------ board (d3-force)
const svg = d3.select("#canvas");
let sim, gEdges, gNodes, nodesById = new Map(), nodes = [], edges = [];
const R = { Account: 9, Device: 5.5, Phone: 5.5, Card: 5.5, Address: 5.5, IP: 4.5 };

function initCanvas() {
  svg.selectAll("*").remove();
  svg.append("defs").html(`<marker id="arrow" viewBox="0 0 10 10" refX="14" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#b3261e"/></marker>`);
  const root = svg.append("g").attr("class", "root");
  gEdges = root.append("g").attr("class", "edges");
  gNodes = root.append("g").attr("class", "nodes");
  svg.call(d3.zoom().scaleExtent([0.3, 3]).on("zoom", (ev) => root.attr("transform", ev.transform)));
  const { width, height } = svg.node().getBoundingClientRect();
  sim = d3.forceSimulation()
    .force("link", d3.forceLink().id((d) => d.id).distance((l) => (l.type === "PAID" ? 90 : 48)).strength(0.6))
    .force("charge", d3.forceManyBody().strength(-160))
    .force("collide", d3.forceCollide().radius((d) => R[d.kind] + 8))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .on("tick", tick);
  nodes = []; edges = []; nodesById = new Map();
}

function tick() {
  gEdges.selectAll("line").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
  gNodes.selectAll("g.node").attr("transform", (d) => `translate(${d.x},${d.y})`);
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
    .call(d3.drag().on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }))
    .on("mouseenter", showTip).on("mousemove", moveTip).on("mouseleave", hideTip);
  enter.append("circle").attr("class", "ring").attr("r", (d) => R[d.kind] + 4);
  enter.append("circle").attr("class", "body").attr("r", (d) => R[d.kind]);
  enter.append("text").attr("dy", (d) => R[d.kind] + 12).attr("text-anchor", "middle")
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

function lightPath(ids) {
  const set = new Set(ids);
  for (const n of nodes) n.lit = set.has(n.id);
  for (const e of edges) e.lit = set.has(e.source.id) && set.has(e.target.id);
  render();
  setTimeout(() => { for (const n of nodes) n.lit = false; for (const e of edges) e.lit = false; render(); }, 2600);
}

function showTip(ev, d) {
  const t = $("tooltip");
  const extra = d.kind === "Account" ? `${esc(d.label)} · opened ${shortDate(d.created_at)} · ${esc(d.status || "")}` : d.kind;
  t.innerHTML = `<div class="id">${esc(d.id)}</div><div class="meta">${extra}</div>`;
  t.hidden = false; moveTip(ev);
}
function moveTip(ev) { const t = $("tooltip"); const r = svg.node().getBoundingClientRect(); t.style.left = `${ev.clientX - r.left + 14}px`; t.style.top = `${ev.clientY - r.top + 14}px`; }
function hideTip() { $("tooltip").hidden = true; }

async function drawAccounts(ids, opts) {
  if (!ids.length) return;
  const res = await fetch(`/api/graph?ids=${encodeURIComponent(ids.slice(0, 150).join(","))}`);
  if (!res.ok) return;
  const { data } = await res.json();
  mergeGraph(data, opts);
}

// ------------------------------------------------------------------ case panel
function resetCase(accountId) {
  state.current = accountId; state.caseId = null; state.exhibits = 0; state.seed = accountId;
  state.flagged = new Set(); state.cashout = new Set(); state.frozen = new Set();
  initCanvas();
  $("case-empty").hidden = true;
  $("exhibit-list").innerHTML = "";
  $("exhibits").hidden = false;
  $("members").hidden = true; $("actions").hidden = true;
  $("verdict").hidden = false;
  $("verdict").className = "verdict running";
  $("verdict").innerHTML = `<p class="live">Investigating ${esc(accountId)} with the ${esc(state.provider)} investigator…</p>`;
  $("case-sub").textContent = `${accountId} · in progress`;
  $("board-sub").textContent = `Expanding from ${accountId}`;
  markCurrent();
}

function addExhibit(ev) {
  const ol = $("exhibit-list");
  const li = document.createElement("li");
  if (ev.type === "thought") {
    li.innerHTML = `<div class="head"><span class="num"></span><span class="thought">${esc(ev.text)}</span></div>`;
  } else if (ev.type === "error") {
    li.innerHTML = `<div class="head"><span class="num"></span><span class="error">${esc(ev.message)}</span></div>`;
  } else {
    state.exhibits++;
    const queries = ev.result?.queries || ev.queries || [];
    const ms = queries.reduce((s, q) => s + (q.run_ms || 0), 0);
    const rows = queries.reduce((s, q) => s + (Array.isArray(q.rows) ? q.rows.length : (q.rows || 0)), 0);
    li.innerHTML = `
      <div class="head">
        <span class="num">${state.exhibits}</span>
        <span class="tool">${esc(ev.name)}</span>
        <span class="ms">${ms.toFixed(1)} ms · ${rows} rows</span>
        <span class="summary">${esc(ev.summary || "")}</span>
        <details><summary>Cypher (${queries.length})</summary>${queries.map((q) => `<pre>${esc(q.cypher)}${Object.keys(q.params || {}).length ? "\n-- params " + esc(JSON.stringify(q.params)) : ""}</pre>`).join("")}</details>
      </div>`;
  }
  ol.appendChild(li);
  if (!state.caseId) li.scrollIntoView({ block: "nearest" });
}

function renderFindings(f, members, actions, caseMeta) {
  const v = $("verdict");
  $("case-body").scrollTop = 0;
  v.className = `verdict ${f.verdict}`;
  const stamp = { ring: "Ring", benign: "No ring", uncertain: "Uncertain" }[f.verdict] || f.verdict;
  v.innerHTML = `<div class="stamp">${esc(stamp)}</div>
    <p class="conf">Confidence ${Math.round((f.confidence || 0) * 100)}%${caseMeta ? ` · case ${esc(caseMeta.id)} · ${esc(caseMeta.provider)}` : ""}</p>
    <p class="summary">${esc(f.summary || "")}</p>`;

  const m = $("members");
  m.hidden = false;
  const list = (members || []).map((x) => `
    <li>
      <span class="id">${esc(x.id)}</span>
      <span class="role ${esc(x.role)}">${esc(x.role)}</span>
      <span class="score">${Number(x.score).toFixed(0)} pts${x.status ? ` · ${esc(x.status)}` : ""}</span>
      <span class="reason">${esc(x.reason)} ${x.id !== state.seed ? `<button type="button" data-explain="${esc(x.id)}">show path</button>` : ""}</span>
    </li>`).join("");
  m.innerHTML = `<h3>${members?.length || 0} implicated account${members?.length === 1 ? "" : "s"}</h3><ul>${list || '<li class="reason">None. The links around this account look like ordinary life, not a ring.</li>'}</ul>`;
  m.querySelectorAll("[data-explain]").forEach((b) => b.addEventListener("click", () => explain(state.seed, b.dataset.explain)));

  renderActions(actions || []);
}

function renderActions(actions) {
  const a = $("actions");
  a.hidden = false;
  if (!actions.length) {
    a.innerHTML = `<h3>Proposed actions</h3><p class="gate">Nothing proposed. No account changes.</p>`;
    return;
  }
  const pending = actions.filter((x) => x.status === "pending");
  a.innerHTML = `<h3>Proposed actions</h3>
    <ul>${actions.map((x) => `
      <li class="action">
        ${x.status === "pending" ? `<input type="checkbox" id="act-${esc(x.id)}" data-action="${esc(x.id)}" checked aria-label="Select ${esc(x.type)} ${esc(x.target)}">` : `<span></span>`}
        <label for="act-${esc(x.id)}"><span class="type ${esc(x.type)}">${esc(x.type)}</span> <span class="target">${esc(x.target)}</span></label>
        <span class="state ${esc(x.status)}">${esc(x.status)}${x.approved_by ? ` · ${esc(x.approved_by)}` : ""}</span>
        <span class="reason">${esc(x.reason)}</span>
      </li>`).join("")}</ul>
    <div class="bar">
      <button type="button" class="btn btn-danger" id="approve" ${pending.length ? "" : "disabled"}>Approve selected</button>
      <button type="button" class="btn btn-ghost" id="reject" ${pending.length ? "" : "disabled"}>Reject selected</button>
      <p class="gate">${pending.length ? "The investigator cannot freeze anything. Approving writes your name on each action and changes the account status." : "All actions decided."}</p>
    </div>`;
  $("approve")?.addEventListener("click", () => decide(true));
  $("reject")?.addEventListener("click", () => decide(false));
}

async function decide(approve) {
  const ids = [...document.querySelectorAll("#actions input[data-action]:checked")].map((i) => i.dataset.action);
  if (!ids.length) { toast("Select at least one action."); return; }
  const who = "analyst";
  const res = await fetch(`/api/cases/${state.caseId}/decide`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action_ids: ids, who, approve }) });
  if (!res.ok) { toast(`Decision failed: ${res.status}`); return; }
  const out = await res.json();
  if (approve) for (const row of out.applied) if (row.status === "frozen") state.frozen.add(row.account);
  toast(approve ? `${out.applied.length} action${out.applied.length === 1 ? "" : "s"} approved · case ${out.case_status}` : `${ids.length} rejected · case ${out.case_status}`);
  await openCase(state.caseId, { keepBoard: true });
  loadCases();
  loadAlerts();
}

async function explain(a, b) {
  const res = await fetch(`/api/tools/explain_link?account_a=${encodeURIComponent(a)}&account_b=${encodeURIComponent(b)}`);
  const { data, queries } = await res.json();
  addExhibit({ type: "tool", name: "explain_link", summary: data.connected ? `${a} → ${data.chain.map((c) => `${c.kind}:${c.id}`).join(" → ")}` : `${a} and ${b} are not connected through identifiers`, result: { queries } });
  if (data.connected) {
    const ids = [a, ...data.chain.map((c) => c.id)];
    await drawAccounts(ids.filter((id) => id.startsWith("acc_")), { entering: false });
    lightPath(ids);
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
  if (!res.ok) { fail(`Server refused: ${res.status} ${(await res.text()).slice(0, 200)}`); return; }
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
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
      await handleEvent(ev);
    }
  }
}

function fail(msg) {
  $("verdict").className = "verdict uncertain";
  $("verdict").innerHTML = `<div class="stamp">Stopped</div><p class="summary">${esc(msg)}</p>`;
  $("case-sub").textContent = `${state.current} · stopped`;
}

async function handleEvent(ev) {
  switch (ev.type) {
    case "tool": {
      addExhibit(ev);
      const d = ev.result?.data || {};
      if (ev.name === "shared_identifiers") await drawAccounts([state.seed, ...(d.neighbours || []).map((n) => n.account)]);
      if (ev.name === "expand_ring") { const ids = [state.seed, ...(d.candidates || []).map((c) => c.account)]; await drawAccounts(ids); $("board-sub").textContent = `${ids.length} accounts within 3 identifier hops of ${state.seed}`; }
      if (ev.name === "money_flow" && d.sinks?.length) await drawAccounts([d.sinks[0].sink, ...d.sinks[0].senders], { entering: true });
      if (ev.name === "explain_link" && d.connected) { await drawAccounts([d.from, d.to], { entering: false }); lightPath([d.from, ...d.chain.map((c) => c.id)]); }
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
      $("board-sub").textContent = f.verdict === "ring" ? `${f.members.length} accounts flagged around ${state.seed}` : `No ring around ${state.seed}`;
      break;
    }
    case "case": {
      state.caseId = ev.case_id;
      const c = ev.case;
      renderFindings(c, c.members, c.actions, c);
      $("case-sub").textContent = `${state.seed} · ${c.verdict} · case ${c.id}`;
      loadCases(); markCurrent();
      break;
    }
    case "error": addExhibit(ev); if (!ev.recoverable) fail(ev.message); break;
    default: break;
  }
}

// ------------------------------------------------------------------ replay a stored case
async function openCase(caseId, { keepBoard = false } = {}) {
  const res = await fetch(`/api/cases/${caseId}`);
  if (!res.ok) { toast("Case not found."); return; }
  const c = await res.json();
  if (!keepBoard) {
    resetCase(c.seed);
    $("verdict").className = "verdict running";
    for (const step of c.trace || []) addExhibit(step.type === "tool" ? { ...step, result: { queries: step.queries.map((q) => ({ ...q, rows: q.rows })) } } : step);
    const ids = [c.seed, ...c.members.map((m) => m.id)];
    state.flagged = new Set(c.members.map((m) => m.id));
    state.cashout = new Set(c.members.filter((m) => m.role === "cashout").map((m) => m.id));
    await drawAccounts(ids, { entering: true });
  }
  state.caseId = c.id; state.current = c.seed;
  for (const m of c.members) if (m.status === "frozen") state.frozen.add(m.id);
  render();
  renderFindings(c, c.members, c.actions, c);
  $("case-sub").textContent = `${c.seed} · ${c.verdict} · case ${c.id} · ${c.status.replace("_", " ")}`;
  if (!keepBoard) $("board-sub").textContent = `Replaying case ${c.id}`;
  markCurrent();
}

// ------------------------------------------------------------------ misc
let toastTimer;
function toast(msg, ms = 3500) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), ms); }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

document.querySelectorAll('[role="tab"]').forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll('[role="tab"]').forEach((t) => t.setAttribute("aria-selected", t === tab ? "true" : "false"));
  $("alerts").hidden = tab.dataset.tab !== "alerts"; $("cases").hidden = tab.dataset.tab !== "cases";
  if (tab.dataset.tab === "cases") loadCases();
}));
$("provider").addEventListener("change", (e) => { state.provider = e.target.value; });
$("lookup").addEventListener("submit", (e) => { e.preventDefault(); const id = $("lookup-id").value.trim(); if (id) investigate(id); });
window.addEventListener("resize", () => { if (sim) { const { width, height } = svg.node().getBoundingClientRect(); sim.force("center", d3.forceCenter(width / 2, height / 2)).alpha(0.2).restart(); } });

initCanvas();
loadHealth().then((ok) => { if (ok) loadAlerts(); else $("alerts").innerHTML = `<li class="empty-row">The queue needs the graph. Start FalkorDB and reload.</li>`; });
