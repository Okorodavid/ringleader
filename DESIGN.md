# Ringleader design system

## World

**The case file.** Fraud analysts live in evidence: statements, exhibits, chain-of-custody notes, the
string-and-pins board of an investigation. The surface is paper under office daylight, ink for text,
one red for what is flagged, and the graph canvas is the evidence board where the ring is pinned up link
by link. The rut (a dark "SOC terminal" with neon edges) is deliberately refused: the analyst works this
for hours, and a terminal costume reads as theatre, not evidence.

Signature: every agent step is an **exhibit**. It is numbered, it names the tool, it shows the Cypher
that ran, and its timing. The verdict is a stamped line, not a glowing badge.

## Tokens

Ground: `--paper #f6f2ea` (warm off-white), `--paper-2 #efe9dd` (panels), `--rule #d9d1c2` (hairlines),
`--rule-strong #c4baa7` (input borders, the decision bar's top rule).
Ink: `--ink #1d1a16`, `--ink-2 #4a443b` (secondary, tinted from ink, never gray), `--ink-3 #635b4f`
(meta text; 5.6:1 on panels, darkened from #7a7265 which failed AA at 3.9:1).
Flag red: `--flag #b3261e`, tint `--flag-bg #f7e4e1`. Safe green: `--safe #2f6b3a`, tint `--safe-bg #e3eee4`.
Hold amber (monitor): `--hold #8a5a00`, tint `--hold-bg #f5ead3`.
Graph: account `#1d1a16`, device `#3b5a86`, phone `#6a4c93`, card `#2f6b3a`, address `#8a5a00`, ip `#7a7265`,
money edge `#b3261e`, identifier edge `#8f8574` at 55% opacity.

Type: display **Newsreader** (serif, 500/600, optical sizing), body **IBM Plex Sans** 400/500/600,
code **IBM Plex Mono** for Cypher and ids only. Scale: 12 / 13 / 14 / 16 / 20 / 28 / 40 px. Body measure
capped at 68ch. Tabular numerals in every count and amount.

Space: 4px scale (4, 8, 12, 16, 24, 32, 48). Panels separated by hairline rules, not shadows. Radius 3px
on controls, 6px on panels. Shadows only on the floating tooltip: `0 6px 18px -8px rgba(29,26,22,.35)`.

Board: after the layout settles it fits the ring to the canvas (zoom capped at 1.3). Tracing a link dims
everything off the path to 18% and holds until Esc or a click on empty board.

Decisions: proposed actions sit directly under the verdict. The decision bar is sticky, names the
approver, labels the count ("Freeze 7 accounts") and asks for an inline confirmation before writing.

Motion: one authored moment, the ring appearing on the board: nodes enter from the seed with an
exponential ease-out, edges draw in after. Everything else is instant. `prefers-reduced-motion` skips the
entrance.

Browser surfaces: selection in flag tint, caret ink, focus ring 2px flag red offset 2px, scrollbars
thin in `--rule`, underline offset 3px.

## Layout

Three columns on desktop: queue (280px) · board (fluid) · case (420px). Header carries the product name,
graph health, and the provider switch. Below 1024px the board stacks above the case; the queue becomes a
horizontal strip.
