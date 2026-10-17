# Ringleader

**One suspicious account in. The whole ring out. Every link explained. Nothing frozen without a human.**

**Live demo:** https://ringleader-six.vercel.app · **Source:** https://github.com/Okorodavid/ringleader

The live demo runs on Vercel's free plan against a FalkorDB Cloud free-tier instance. The first request
after idle takes a few seconds while the function starts.

Ringleader is a fraud ring investigator built on [FalkorDB](https://www.falkordb.com) for Graph Hacks
(WeMakeDevs x FalkorDB), **Track 01: Agents That Act on Connected Data**.

An analyst picks one account from the alert queue. The investigator walks the graph: it expands through
shared devices, phones, cards, addresses and IPs up to three identifier hops, measures how new each account
is and where its money goes, checks earlier cases, and comes back with a verdict, the list of implicated
accounts, the reason for each, and the shortest identifier chain that connects them. It proposes freezes.
It cannot execute them. A human approves each action by name, and only then does an account's status change.

Every step shows the exact Cypher that ran. Take FalkorDB out and nothing works: the expansion, the ring
membership, the cash-out detection, the explanation paths, and the case memory are all traversals.

## Track

Track 01, Agents That Act on Connected Data: the agent uses graph traversals and multi-hop reasoning as
its tools, acts on what it finds (proposed freezes behind a human gate), and every result is explainable
by the path that produced it.

## Why a graph

Fraud rings hide in relationships, not attributes. Two accounts with different names, emails and cards
can still be the same operator if they log in from one phone that a third account also uses. That is a
two-hop question (`account -> identifier <- account`), and a ring is a chain of such hops. A row store or a
vector index can tell you what an account *looks like*; only a traversal tells you what it is *connected to*,
and a missing path is a real negative, not a low similarity score.

The hard negative in the dataset is the household: four people who share a home address and a tablet and
send each other small transfers. A one-hop attribute match flags them. The graph investigator does not,
because it also reads account age, the fan-in of money into one sink, and what that sink spends on.

## Setup

Requirements: Python 3.11+, a FalkorDB (any of the three options below), and optionally a free Gemini key.

**FalkorDB**, pick one:

- Docker: `docker run -p 6379:6379 -it --rm falkordb/falkordb:latest`
- FalkorDB Cloud free tier: create an instance at https://app.falkordb.cloud and copy host, port, password.
- Self-hosted FalkorDB.

Then:

```bash
python -m venv .venv
. .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill in FALKORDB_* ; set PROVIDER=gemini and GEMINI_API_KEY for the LLM investigator
python -m app.seed          # loads the synthetic dataset (idempotent; add --reset to start clean)
uvicorn app.main:app --port 8000
```

Open http://localhost:8000. Pick an alert. Watch the board.

No model key? Leave `PROVIDER=rules`. The rules investigator calls the same graph tools in a fixed order
and scores with an explainable rule; it is deterministic, free, and what the evals run on.

## Graph data model

Nodes

| Label | Key | Properties |
|---|---|---|
| `Account` | `id` | name, email, created_at, country, kyc_level, **status** (active, monitored, frozen) |
| `Device` | `id` | fingerprint, os |
| `Phone` | `id` | number |
| `Card` | `id` | last4, bin, issuer |
| `Address` | `id` | street, city |
| `IP` | `id` | addr |
| `Merchant` | `id` | name, category (crypto, giftcards and electronics are cash-out categories) |
| `Transaction` | `id` | amount, currency, ts, status |
| `Case` | `id` | opened_at, seed, verdict, confidence, summary, status, provider, trace (the step log as JSON) |
| `Action` | `id` | type (freeze, monitor), target, reason, status (pending, approved, rejected), approved_by, approved_at |

Relationships

```
(Account)-[:USED_DEVICE {first_seen,last_seen,count}]->(Device)
(Account)-[:HAS_PHONE   {first_seen,last_seen,count}]->(Phone)
(Account)-[:OWNS_CARD   {first_seen,last_seen,count}]->(Card)
(Account)-[:LIVES_AT    {first_seen,last_seen,count}]->(Address)
(Account)-[:LOGGED_FROM {first_seen,last_seen,count}]->(IP)
(Account)-[:SENT]->(Transaction)-[:TO]->(Account)          peer transfer
(Account)-[:SENT]->(Transaction)-[:AT]->(Merchant)         purchase
(Case)-[:SEED]->(Account)
(Case)-[:IMPLICATES {reason,score,role}]->(Account)
(Case)-[:EVIDENCE {kind,note}]->(Device|Phone|Card|Address|IP)
(Case)-[:PROPOSES]->(Action)
```

Indexes: range index on `id` for every node label, plus `Account.status`.

The identifier relationships are the ring fabric. Money relationships are the motive. Case relationships
are the memory: the next investigation that touches any of these accounts sees the earlier verdict.

## The Cypher the product depends on

Each investigator tool is one or two read-only queries, run through `GRAPH.RO_QUERY` with a timeout and a
write-keyword guard (`app/db.py`). The UI prints them verbatim as numbered exhibits.

**1. Profile** (`account_profile`)

```cypher
MATCH (a:Account {id: $id})
OPTIONAL MATCH (a)-[r:USED_DEVICE|HAS_PHONE|LIVES_AT|OWNS_CARD|LOGGED_FROM]->(x)
RETURN a.id AS id, a.name AS name, a.email AS email, a.created_at AS created_at, a.status AS status,
       a.kyc_level AS kyc_level, a.country AS country,
       collect({rel: type(r), kind: labels(x)[0], id: x.id, count: r.count}) AS identifiers
```

**2. Shared identifiers, two hops** (`shared_identifiers`)

```cypher
MATCH (a:Account {id: $id})-[:USED_DEVICE|HAS_PHONE|LIVES_AT|OWNS_CARD|LOGGED_FROM]->(x)<-[:USED_DEVICE|HAS_PHONE|LIVES_AT|OWNS_CARD|LOGGED_FROM]-(b:Account)
WHERE a <> b
WITH b, collect(DISTINCT {kind: labels(x)[0], id: x.id}) AS via
RETURN b.id AS account, b.name AS name, b.created_at AS created_at, b.status AS status,
       via, size(via) AS shared_count
ORDER BY shared_count DESC, account
LIMIT 50
```

**3. Expand the ring, up to three identifier hops** (`expand_ring`)

```cypher
MATCH p = (a:Account {id: $id})-[:USED_DEVICE|HAS_PHONE|LIVES_AT|OWNS_CARD|LOGGED_FROM*2..6]-(b:Account)
WHERE a <> b
WITH b, min(length(p)) / 2 AS hops
RETURN b.id AS account, b.name AS name, b.created_at AS created_at, b.status AS status, hops
ORDER BY hops, account
LIMIT 100
```

**4. Identifier fan-out: who else uses these identifiers** (`identifier_fanout`)

```cypher
MATCH (a:Account)-[:USED_DEVICE|HAS_PHONE|LIVES_AT|OWNS_CARD|LOGGED_FROM]->(x)
WHERE a.id IN $ids
WITH DISTINCT x
MATCH (x)<-[:USED_DEVICE|HAS_PHONE|LIVES_AT|OWNS_CARD|LOGGED_FROM]-(u:Account)
WITH x, collect(DISTINCT u.id) AS users
WHERE size(users) >= 2
RETURN x.id AS identifier, labels(x)[0] AS kind, size(users) AS account_count, users
ORDER BY account_count DESC, identifier
LIMIT 100
```

**5. Velocity: age and money through each account** (`velocity`)

```cypher
MATCH (a:Account)
WHERE a.id IN $ids
OPTIONAL MATCH (a)-[:SENT]->(t:Transaction)
WITH a, count(t) AS sent_count, coalesce(sum(t.amount), 0) AS sent_total
OPTIONAL MATCH (a)<-[:TO]-(r:Transaction)
RETURN a.id AS account, a.created_at AS created_at, a.kyc_level AS kyc_level, a.status AS status,
       sent_count, sent_total, count(r) AS received_count, coalesce(sum(r.amount), 0) AS received_total
ORDER BY account
```

**6. Money flow: where the cluster's money converges, and what the sink spends on** (`money_flow`)

```cypher
MATCH (s:Account)-[:SENT]->(t:Transaction)-[:TO]->(d:Account)
WHERE s.id IN $ids AND NOT d.id IN $ids_excluded
WITH d, collect(DISTINCT s.id) AS senders, sum(t.amount) AS total, count(t) AS tx_count
RETURN d.id AS sink, d.name AS name, d.status AS status, d.created_at AS created_at,
       size(senders) AS sender_count, senders, total, tx_count
ORDER BY sender_count DESC, total DESC
LIMIT 10
```

```cypher
MATCH (a:Account {id: $id})-[:SENT]->(t:Transaction)-[:AT]->(m:Merchant)
WITH m.category AS category, count(t) AS tx_count, sum(t.amount) AS total
RETURN category, tx_count, total, category IN $risky AS risky
ORDER BY total DESC
```

**7. Explain a link: the shortest identifier chain between two accounts** (`explain_link`)

```cypher
MATCH (a:Account {id: $a}), (b:Account {id: $b})
MATCH p = (a)-[:USED_DEVICE|HAS_PHONE|LIVES_AT|OWNS_CARD|LOGGED_FROM*2..8]-(b)
RETURN p
ORDER BY length(p)
LIMIT 1
```

**8. Prior cases: memory that compounds** (`prior_cases`)

```cypher
MATCH (c:Case)-[r:SEED|IMPLICATES]->(a:Account)
WHERE a.id IN $ids
WITH c, collect(DISTINCT a.id) AS accounts
RETURN c.id AS case_id, c.verdict AS verdict, c.confidence AS confidence, c.status AS status,
       c.opened_at AS opened_at, c.summary AS summary, accounts
ORDER BY opened_at DESC
LIMIT 10
```

**9. Approval: the only query that changes an account, and only a human runs it**

```cypher
MATCH (c:Case {id: $case_id})-[:PROPOSES]->(x:Action {status: 'pending'})
WHERE x.id IN $action_ids
SET x.status = 'approved', x.approved_by = $who, x.approved_at = $ts
WITH x
MATCH (a:Account {id: x.target})
SET a.status = CASE x.type WHEN 'freeze' THEN 'frozen' WHEN 'monitor' THEN 'monitored' ELSE a.status END
RETURN x.id AS action_id, x.type AS type, a.id AS account, a.status AS status
```

The alert queue (`/api/alerts`) uses two more: fan-in into accounts that spend at cash-out merchants, and
identifiers used by three or more accounts. They are cheap rules; the investigator does the real work.

## How the investigator decides

Both providers call the same tools. The **rules** provider scores every account in the cluster:

| Signal | Points |
|---|---|
| shares identifiers with other cluster accounts (2 per identifier, max 6) | 0 to 6 |
| account is 21 days old or younger | 3 |
| sent money to the cluster's cash-out sink | 3 |
| is the sink (3 or more senders and NGN 100k, or any cash-out spend) | 4 (+1 for cash-out spend) |

Flag at 6. Three or more flagged accounts is a ring. A household member shares two identifiers (4 points),
is years old, and has no sink, so it stays under the line. The **gemini** provider gets the tool
descriptions, a protocol, and the same definition of a ring versus a household, and must finish by calling
`submit_findings` with the same structured schema. Its reasons must cite identifiers or transfers the tools
returned.

## Approval gate

The investigator writes a `Case` with `PROPOSES` edges to `Action` nodes in status `pending`. The API
exposes `POST /api/cases/{id}/decide` with the action ids and the approver's name. Approving runs query 9;
rejecting marks the action rejected. Nothing else in the codebase writes `Account.status`. Tests prove that
accounts stay `active` after an investigation and change only after approval.

## Eval

`evals/cases.json` is a frozen set of 21 seeds: 12 ring seeds (two members and the cash-out account of each
planted ring), 4 household seeds, 5 ordinary accounts. Ground truth comes from the generator and is never
loaded into the graph. Two systems are scored on recall and precision of flagged accounts:

- **graph investigator** (rules provider): the full tool protocol above
- **one-hop baseline**: flag the seed and everything that shares a direct identifier with it, which is
  what an attribute lookup or a similarity search can do

Run `python -m app.evaluate` to print the table and write `evals/report_rules.json`. The measured numbers
are in that file and in the Results section below.

## Results

Measured on FalkorDB Cloud (free tier, ap-south-1) on 2026-10-17, rules provider, 21 frozen cases.
Full per-case table in `evals/report_rules.json`.

| | Ring recall | Ring precision | Verdict accuracy |
|---|---|---|---|
| Graph investigator (3-hop expansion + behaviour) | 1.00 | 1.00 | 1.00 (21 of 21) |
| One-hop attribute baseline | 0.89 | 1.00 | 0.81 (17 of 21) |

Where the baseline loses: it never reaches the members two identifiers away from the seed (recall 0.69 to
0.71 when the seed is the cash-out account), and it calls all four households a ring because they share an
address and a tablet. The graph investigator walks three hops to the far members and reads age, fan-in
and cash-out spend to clear the households.

The Gemini provider was run once on the same cloud graph (seed `acc_0376`, the first member of the
largest planted ring). It called account_profile, expand_ring, identifier_fanout, velocity, money_flow,
prior_cases and explain_link, then submitted a ring verdict at 0.98 confidence naming all 10 ring accounts,
with the cash-out account's reason citing the shared device, the shared IP, the NGN 4.77M fan-in and the
NGN 4.14M spent on gift cards, crypto and electronics. The run took seven minutes on the free tier.

The test in `tests/test_eval.py` re-measures these numbers and asserts: graph ring recall at least 0.8,
precision at least 0.9, graph recall above the baseline, and every household seed judged benign by the
graph while the baseline flags it.

Screenshots from the live desk are in `docs/`: the queue, a ring found around `acc_0384`, an explained
path, the approval, the case list, and a household correctly cleared.

## Dataset

Synthetic, generated by `app/generator.py` from one seed: 360 ordinary accounts, 4 households, 4 planted
rings (sizes 5, 6, 9, 12, each with a cash-out account), around 3,400 transactions. No real people, no real
data. Ring accounts are new, share burner phones and devices, and funnel money into one account that
spends at crypto and gift-card merchants. Households are old accounts sharing one address and one tablet.

## Project layout

```
app/generator.py   synthetic data and ground truth
app/seed.py        idempotent MERGE loader, indexes
app/db.py          FalkorDB client, read-only guard, timeouts
app/tools.py       the graph tools (queries 1 to 8) and the canvas subgraph
app/agent.py       rules investigator, Gemini investigator, event stream
app/cases.py       Case and Action persistence, approval (query 9)
app/evaluate.py    frozen eval and baseline
app/main.py        FastAPI API and static UI
web/               the desk: queue, evidence board (d3-force), case panel
docs/              screenshots of the live desk
evals/             frozen eval set and the measured report
tests/             one file per gate in GATES.md
GATES.md           the completion ledger: every outcome, its check command, and its evidence
```

## Honest limits

- The dataset is synthetic and small; the rules' thresholds are tuned to it. Real fraud has more noise,
  shared public Wi-Fi IPs, and family cards. Treat the scoring as a worked example, not a model.
- `expand_ring` uses a bounded variable-length pattern, not a community-detection algorithm. On a graph
  with hub identifiers (a carrier-grade NAT IP) it needs an identifier degree cap.
- The Gemini provider runs on the free tier with retries on 429; it is slower and not deterministic. On
  2026-10-17 a single free-tier call to `gemini-flash-latest` took about a minute, so a full Gemini
  investigation can take ten minutes. The rules provider answers in under thirty seconds. The free tier
  also caps this model at 20 requests per day per project; one investigation uses about nine, so expect
  two Gemini investigations a day on a free key. When the quota is gone the desk says so and stops; the
  rules provider keeps working.
- No authentication: the approver's name is whatever the client sends.
- Single graph, single tenant.

## AI-use disclosure

Built with Claude (Anthropic) as an AI coding assistant for code, queries, tests and this README, directed
and reviewed by the participant. The Gemini free tier powers the optional LLM investigator at runtime. The
graph model, the rule design, and the choice of what the agent may and may not do are the participant's.

## License

MIT
