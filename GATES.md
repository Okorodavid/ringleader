# Gates: Ringleader fraud ring investigator

OWNS: app/**, scripts/**, tests/**, web/**, data/**, evals/**, README.md, requirements.txt, .env.example, GATES.md

Scope: an agent that takes one suspicious account, expands through shared identifiers in FalkorDB to find the ring, explains every link with the Cypher path, and freezes accounts only after a human approves

- [x] G0: this ledger states outcomes that can fail
  CHECK: node C:\Users\Uche\.claude\skills\unlazy\scripts\gate-lint.mjs GATES.md
  EXPECT: LINT OK
  EVIDENCE: automatic-evidence=v1; definition-sha256=d2ab0d2d654162bb0742e0508c164c60d2b963e8734130018d1bf4dcb5c8060b; exit=0; EXPECT=matched; output-sha256=07de1a3fdbb119780824944843dcfc7da4b1349f87411f5d2df255b3caa7c614; output-bytes=150; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries

- [x] G1: synthetic dataset is deterministic, contains planted rings and a benign household, and ground truth never leaks into graph rows
  CHECK: .venv\Scripts\python scripts\gate.py generator
  EXPECT: GATE OK generator
  EVIDENCE: automatic-evidence=v1; definition-sha256=6896086ddf698e3ad9700465f1d71c319bfab9b5f7e21c4a094aa6950e463b81; exit=0; EXPECT=matched; output-sha256=834c3cef4f5b90e11ccbd7774e23e556330967be793be54ef576098213eadf0e; output-bytes=119; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries

- [x] G2: seeding is idempotent and the live FalkorDB graph holds the generated node and edge counts after two consecutive loads
  CHECK: .venv\Scripts\python scripts\gate.py seed
  EXPECT: GATE OK seed
  EVIDENCE: automatic-evidence=v1; definition-sha256=2aecfa9128865aa97b69eb53917b747a6c9fec4c4c4ea9d43c0507e4150e41dd; exit=0; EXPECT=matched; output-sha256=ad4a6d08df3f72a2a421e4310af140ca673ccfa1bc91923508f42d4f8714685b; output-bytes=125; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries

- [x] G3: each graph tool returns the planted structure (shared identifiers at two hops, ring members at three identifier hops, cash-out sink, shortest explanation path) and refuses write Cypher
  CHECK: .venv\Scripts\python scripts\gate.py tools
  EXPECT: GATE OK tools
  EVIDENCE: automatic-evidence=v1; definition-sha256=429054e0d3eaf385803d170dd85eed54305d7d8d76b969946d4641ecf8296d72; exit=0; EXPECT=matched; output-sha256=f16486c6390369ca3f32dda0b4a5e49dc4d1ce7b426f3f68e151699a979f64bb; output-bytes=117; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries

- [x] G4: the offline rule-based investigator finds at least 80 percent of a planted ring from one seed account and flags zero members of the benign household
  CHECK: .venv\Scripts\python scripts\gate.py agent
  EXPECT: GATE OK agent
  EVIDENCE: automatic-evidence=v1; definition-sha256=09e3cd7bef4efbd943f365f8c0016998d56ecca31e3d57b0ce54685198794681; exit=0; EXPECT=matched; output-sha256=69c32b620dd0a84954b61c95192df8200daeb815dd21d3fffcc827038217b92e; output-bytes=127; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries

- [x] G5: no account status changes until a human approves; after approval the named accounts are frozen and the Action nodes record who approved
  CHECK: .venv\Scripts\python scripts\gate.py approval
  EXPECT: GATE OK approval
  EVIDENCE: automatic-evidence=v1; definition-sha256=a89a088928efbc4bed6399ed539e2e0457a71df2142bc9fd26f3aacaaf6c5f9c; exit=0; EXPECT=matched; output-sha256=fe22931b84b2aa6f301f29089aaac4242e145613165da2fe00ee66b75b6c6fb4; output-bytes=119; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries

- [x] G6: on the frozen eval set the graph investigator's member recall beats the one-hop attribute baseline and precision stays at or above 0.9
  CHECK: .venv\Scripts\python scripts\gate.py eval
  EXPECT: GATE OK eval
  EVIDENCE: automatic-evidence=v1; definition-sha256=5e0e5cb5ca97db48b9884e15d5edffb9ad1f4af1b2e798caab5a6da3bb1dae61; exit=0; EXPECT=matched; output-sha256=a37459bd0aaa0ff3ded675d55fa0cf4dc464852225272ea2f050b798aaddfe70; output-bytes=126; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries

- [x] G7: HTTP API serves alerts, runs an investigation end to end, persists the case with its evidence paths, and approves actions
  CHECK: .venv\Scripts\python scripts\gate.py api
  EXPECT: GATE OK api
  EVIDENCE: automatic-evidence=v1; definition-sha256=30ad479a713db1e2eef65bb66fc679a1366bd024664ad91590e81d49d9b47a28; exit=0; EXPECT=matched; output-sha256=fb264089df47e59ec3ffd9b41b22b2a5410d5a728b8eb5189a63cb34b65bc231; output-bytes=613; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries

- [x] G8: the web UI renders the alert queue, animates the ring expansion on the graph canvas, shows each tool's Cypher, and the approve button changes account status, verified in a browser with a screenshot
  EVIDENCE: 2026-10-17 headless Chrome 1440x900 via Playwright against FalkorDB Cloud: docs/01-queue.png (13 alerts), docs/02-ring-found.png (acc_0404 -> RING, 13 implicated, 9 exhibits with Cypher), docs/03-explain-path.png, docs/04-approved.png (10 actions "approved · analyst", members "frozen", toast "10 actions approved · case closed"), docs/06-benign-household.png (acc_0374 -> No ring), docs/07-mobile.png (390px, no horizontal overflow); zero console or page errors in both runs

- [ ] G9: the Gemini-backed investigator completes a live investigation of a ring seed and submits structured findings through the submit_findings tool
  CHECK: .venv\Scripts\python scripts\gate.py gemini
  EXPECT: GATE OK gemini
  EVIDENCE: pending

- [x] G10: README documents setup, the graph data model, every Cypher query the product depends on, the track entered, AI-use disclosure, and honest limits
  CHECK: .venv\Scripts\python scripts\gate.py readme
  EXPECT: GATE OK readme
  EVIDENCE: automatic-evidence=v1; definition-sha256=6fc23be8e4710fd0736dce68d82fe5d9236fe1a81f6dc6dc62fd1c101dee312c; exit=0; EXPECT=matched; output-sha256=200b7b222b6a4868fc77564f45ebb7123daa8aaec62030b47c860931351a5da2; output-bytes=116; shell=C:\WINDOWS\system32\cmd.exe; cwd=C:\Users\Uche\Desktop\build grok bot\ringleader; path=5a6819e24e10/39 entries
