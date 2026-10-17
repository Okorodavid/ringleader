# Submission guide

Deadline: 18 October 2026, 11:59 PM IST. Track entered: **Track 01, Agents That Act on Connected Data**.

## What the submission form needs

| Requirement | Where it is |
|---|---|
| Public source repository | Push this `ringleader/` folder to a public GitHub repo (see below) |
| README with setup instructions and graph data model | `README.md`, sections Setup and Graph data model |
| The Cypher queries the product depends on | `README.md`, section The Cypher the product depends on (9 queries) |
| Demo video | Record with the script below, 2 to 3 minutes |
| Live deployment or complete local setup | Local setup is in README; see Deploy below for a free host |
| Track(s) entered | Track 01 |
| AI-use disclosure | `README.md`, section AI-use disclosure |

## Push to GitHub (free)

From the `ringleader` folder:

```bash
git init
git add .
git commit -m "Ringleader: fraud ring investigator on FalkorDB for Graph Hacks"
gh repo create ringleader --public --source . --push
```

`.env` is ignored by `.gitignore`, so the FalkorDB password never leaves this machine. Judges use
`.env.example` with their own FalkorDB.

## Deploy for free (optional, strengthens the entry)

Render, Railway and Fly all run a FastAPI app on a free plan. Build command `pip install -r requirements.txt`,
start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and set the `FALKORDB_*`, `PROVIDER`
and `GEMINI_*` variables from your `.env` in the host's environment settings. Run `python -m app.seed`
once from your machine; the cloud graph is shared.

## Demo video script (2 to 3 minutes)

1. **The problem, 15 seconds.** "Fraud rings hide in relationships. Two accounts with different names
   can be one operator sharing a phone with a third. That is a graph question."
2. **The queue, 15 seconds.** Open the desk. Point at an alert: "fan-in to acc_0392 which spends at
   cash-out merchants". Say the queue is a cheap rule; the investigator does the work.
3. **The investigation, 60 seconds.** Click the alert. Narrate the exhibits as they appear: profile,
   shared identifiers, expand_ring to three hops, identifier fan-out ("this phone is used by four
   accounts"), velocity ("all created the same week"), money_flow ("NGN 3.2M converges on one account that
   spends at crypto merchants"), prior_cases. Open one Cypher block. Point at the board filling in.
4. **The verdict, 20 seconds.** Read the RING stamp, the summary, one member's reason. Click "show path"
   and say "that line is the shortest chain of shared identifiers; it is the proof."
5. **The gate, 20 seconds.** "The investigator cannot freeze anything." Untick one action, click
   Approve selected, show the statuses change to frozen and the queue update.
6. **The negative, 20 seconds.** Type `acc_0374` (a household) into the box. Show "No ring" and the
   sentence about long-standing accounts and small mutual transfers. "A one-hop lookup flags this family;
   the graph clears it. That is the eval table in the README: recall 1.0 against 0.89."
7. **Close, 10 seconds.** "Take FalkorDB out and nothing here works. Every answer is a traversal with
   its query attached."

## Blog post outline (AirPods prize)

Title idea: "A phone used by four accounts: finding fraud rings with three-hop Cypher and an agent that
cannot press the button."

1. Why attributes fail and relationships work (the household example).
2. The data model, with the two-hop shared-identifier query.
3. `expand_ring` and why bounded variable-length paths are enough here, plus the honest limit (hub IPs).
4. Money flow as motive: fan-in to a sink, and the merchant category query.
5. The approval gate: Case, Action, and the only query that writes `Account.status`.
6. Eval: graph vs one-hop baseline, with the numbers and what the baseline gets wrong.
7. What Gemini did differently from the rules, and what it got right.
8. Limits and what we would build next.
