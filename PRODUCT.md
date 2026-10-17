# Ringleader

> Inferred from the build brief without a user interview (autonomous run). Assumptions are marked.

## What it is

A fraud ring investigation desk. An analyst picks one suspicious account from a queue; an agent expands
through shared devices, phones, cards, addresses and IPs in FalkorDB, finds the ring, shows every Cypher
query it ran and the path behind every link, and proposes freezes that only a human can approve.

Built for Graph Hacks (WeMakeDevs x FalkorDB), Track 01: Agents That Act on Connected Data.

## Who uses it

- **Fraud analyst** (primary, assumed): works a queue all day, needs to clear alerts fast and defend each
  decision later. Trusts evidence, distrusts scores with no path behind them.
- **Hackathon judge** (secondary): opens the live demo once, wants to see in under a minute that the graph
  does real work and that the agent cannot act alone.

## Scene of use

Desktop browser, long sessions, often a second monitor, office or home lighting. The canvas is the
centre of attention; text panels flank it. Mobile is a courtesy (read a case), not a work surface.

## Jobs

1. Pick an alert and see the ring appear around it, link by link.
2. Read why each account is implicated, with the identifier chain that connects it.
3. See the exact Cypher that produced each step.
4. Approve or reject each proposed freeze, by name, and see the account status change.
5. Reopen an old case and replay what the agent did.

## Voice

Plain, specific, calm. Controls name their action ("Freeze 4 accounts", not "Submit"). Numbers are
money or counts, never a bare score without its reasons. No alarm theatre.

## Mode

Operate. The analyst completes a task. Scanability and consistency outrank expression; the brand lives in
the graph canvas and in the typographic precision of the evidence.

## Constraints

- Plain HTML, CSS and JavaScript served by FastAPI; one external library at most (graph layout).
- Free fonts only (Google Fonts). No paid assets.
- Must work with the deterministic rules provider when no model key exists.

## Not in scope

Account management, authentication, multi-tenant, mobile-first workflows.
