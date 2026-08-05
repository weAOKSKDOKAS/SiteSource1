# Handoff: SiteSource · Tender Desk

## Overview

A Hong Kong main contractor receives a public-works tender — roughly 180 documents, a bill of quantities, and thirty-odd drawings. SiteSource helps them **read it, price it, and not lose it on paperwork.**

It is deliberately **not** an estimator. The governing rule, which explains almost every decision in this design:

> **If two good estimators would get the same answer, it is clerical and the app does it.
> If two good estimators would disagree, it is judgement and the app asks.**

The app finds documents, transcribes tables, adds columns up, remembers the costs every rate must cover, and redoes all of it the day an addendum lands. The person decides how fast his crews drill, which holes need a platform, what he carries versus queries, and what the margin is.

The worked example throughout is a ground-investigation contract: **ND/2025/04 · San Tin Technopole**, 411 pages, 91 boreholes, 21 trial pits.

### The flow

The app opens on the **desk** — a shelf of live tenders. Opening one enters six steps, four of which end in a gate:

| Step | Gate | What the human does |
|---|---|---|
| **Documents** | Gate 1 — Approve the split | Confirms the monolithic PDF was cut into the right parts, every page accounted for |
| **Register** | Gate 2 — Close the register | Confirms / dismisses / queries every clause that costs money |
| **Scope** | Gate 3 — Freeze the scope | Turns confirmed departures, open queries and amendments into the scope of record |
| **Site** | no gate — a warning that travels | Assigns an access class to every hole; groups holes that drill alike |
| **Price** | Sweep — the only hard stop | Prices the bill from group build-ups; routes costs no bill item asks for |
| **Offer** | — | The letter, as a draft |

## About the design files

`sitesource_ui_reference.dc.html` is a **design reference written in HTML** — a prototype of intended look and behaviour, not production code to lift. Recreate it in the target codebase using that codebase's own patterns.

The file needs `support.js` (bundled alongside) to render. **Do not port `support.js` or its `<x-dc>` / `{{ }}` / `<sc-for>` syntax into the product.** Read the markup for structure and exact values; rewrite it idiomatically.

Two frames are **interactive** — open the file in a browser and click them:
- **§07 Site › Holes** — click A/B/C on any tile; the rail reconciliation and the Price warning follow. The 12 visible tiles need **10 A and 2 B** to reach the bill’s 80 / 11 exactly — all three rail states are reachable that way.
- **§08 Site › Groups** — type in the four fields; days, blend and group cost recompute.

## Fidelity

**High fidelity for layout, type, colour and copy. Low fidelity for data** — all figures are a plausible worked example, not a real tender.

The **map crops in Site › Holes are placeholders** (CSS grid + contour lines, labelled as such). The real component crops one 300-dpi render per drawing sheet, ninety-one ways in CSS, centred on each station's surveyed coordinates and registered against the grid marks printed on the sheet. No new image pipeline. A PNG export of a real sheet is all that is needed to wire it.

## Design language

### The palette

Warm paper and brass against a cool-navy ink. Every token below is exact and final.

**Ink and navy** — `#0c1a28` app bar and dark buttons · `#112233` primary text · `#18324a` active toggle on dark · `#1e3a52` **authorship: a rule wrote this** · `#20364a` borders on dark · `#2c3a48` body and clause text · `#2f6e8a` **authorship: uncovered clause, addenda** · `#4c6478` disabled glyph on dark · `#61707e` secondary text · `#8a97a3` labels and meta · `#9fb4c6` dim text on dark · `#b4c6d6` disabled control text · `#dce4ea` chart track · `#e4ebf2` badge fill · `#eef3f8` info tint, selected rail row

**Paper** — `#eae6dc` the desk behind everything · `#f3f1eb` panels and the step strip · `#faf9f6` cards and rails · `#fffdf7` inputs and unaccepted cards · `#ffffff` a rendered page · `#e3ded3` border · `#f0ede5` hairline between rows · `#cec7b8` strong border

**Brass** — `#bd9a5f` **authorship: a model proposed this** / primary accent · `#c28a2e` queried, vision-OCR, warning · `#dcc79a` light accent border · `#f0e2c8` accent tint **and the page highlighter fill** · `#f8f0df` selected row or card · `#f6ebd0` queried row · `#856636` accent text · `#9e7c45` accent text light · `#221a0c` text on a brass fill

**Semantics** — positive `#3c8a63` / `#235740` / tint `#deebe2` · negative `#c25539` **authorship: a check on this failed** / `#8a3826` / `#a8432b` / tint `#f4e1d9` · warning `#c28a2e` / `#856636` / `#f0e2c8`

### The one rule that is not decoration

```
navy  #1E3A52   a deterministic rule wrote this
brass #BD9A5F   a model proposed this
red   #C25539   a check on this failed
```

This carries meaning nothing else replaces. **If the palette is ever remapped onto a host design system, these three survive the remap.** Note also that a person's avatar colour (Library › Team) is only a colour — navy, brass and red can never be reassigned to a person.

### Type — roles, not preferences

- **Libre Franklin** — the interface
- **Source Serif 4** — the argument: clause text, rationale, letter prose, scope prose
- **IBM Plex Mono** — anything a machine produced, or that must be compared digit by digit

Serif carries the argument, sans carries the interface, mono carries every figure. **Mixing them blurs who said what**, which is the one thing this product must not do.

Sizes are exact pixels, not a scale: `8–8.5px` chips and micro-labels · `9–9.5px` explanatory notes and mono meta · `10–10.5px` secondary UI · `11–12.5px` body · `13–17px` headings · `19–24px` a headline figure. Tracking: `.12em` on all-caps mono section labels, `.1em` on chips. Radii: mark 2 · chip 3 · button 4 · card 6 · pill 20.

### Motion

`press 160ms` · `tint 120ms` · `expand 200ms` · `pane 220ms`. Pressables scale to `0.97` on active. **List rows do not animate on selection — colour only, geometry never moves.** Nothing staggers. `prefers-reduced-motion` reduces everything to `0.01ms`.

## The layout system

Every working screen is **three panes**: RAIL (the index, the totals, the filters — 180–420px, folds to 44) · MIDDLE (the work itself, ≥320px) · DOCUMENT (the evidence — a real page with the quote highlighted, ≥480px). Both dividers drag; the divider is 9px, `#eae6dc`, bordered `#cec7b8` both sides, `cursor: col-resize`, five 3px `#8a97a3` dots.

**Why the document is always on screen:** the product's promise is *you never have to trust a number — the thing it came from is one click away.* The right pane is that promise made structural.

**Degradation, in a fixed order** as the window narrows, stopping at the first step that fits:
1. the middle shrinks toward 320px
2. the rail folds to a 44px strip of counts
3. the document pane collapses to a vertical tab (`DocTab`, §15)

A deliberate user fold is never overridden by the automatic one.

**Two screens deviate on purpose:** **Scope** is two-pane (fixed 266px rail, no document — nothing on it is a quotation) and **Offer** has no rail at all.

## Global chrome

**App bar** — `#0c1a28`, padding `9px 16px`, `gap: 8px`. Five nav controls at the left, in this order, each 26–28×24px, radius 4, `1px solid #20364a`, glyph `#9fb4c6`, then a `1px × 18px #20364a` divider before the title:

| Control | Behaviour |
|---|---|
| **☰ Navigation sidebar** | Toggles the 206px nav sidebar ↔ a 48px icon rail. Persist per user. |
| **▯ Side panel** | Toggles **the current tab's own rail**. A separate control from ☰. Brass border and fill when the rail is folded; dimmed to 40% on library screens and on Offer, which have no rail to fold. |
| **⌕ Search** | Command search, `Ctrl-K`. Scope: tenders, clients, part titles, criterion ids, clause text. |
| **← Back** | History back. From a tender screen this returns to the desk. |
| **→ Forward** | Dimmed `#4c6478` when there is nowhere to go. |

Right of the bar: an overlapping avatar stack of everyone with the tender open (22px, initials, `1.5px solid #0c1a28`, `margin-left: -6px`), then the deadline ("closes 23 Jan · 6 days ▾") on a tender screen or the signed-in user elsewhere.

**Step strip** — full width directly under the app bar, `#f3f1eb`, bottom border `1px solid #e3ded3`, padding `0 18px`. Each step `flex: none; white-space: nowrap`, padding `9px 14px`, separated by a `#cec7b8` `›`. Current: 600 weight `#112233` with `inset 0 -2px 0 #bd9a5f`. Another open step: 600 weight `#2c3a48` with `inset 0 -2px 0 #dcc79a`. Unopened: 500 weight `#61707e`. Each carries a mono 9px state chip: `✓ SPLIT APPROVED` / `✓ DONE` / `✓ FROZEN` green · `OPEN · SHOWN` brass · `⚠ 9 HOLES UNASSIGNED` / `⚠ 6 UNPRICED` amber · `WAITS ON THE SCOPE` / `READY` / `EMPTY` faint.

**No step is ever disabled.** A step that has not run opens and states what it is waiting for (`WaitingOn`, §15). This replaced a padlock design: locking a tab produces dead ends; a step that opens and explains itself does not.

**Nav sidebar** (206px, `#f3f1eb`) — **+ New tender** brass at the top, then: *Tender desk · Archived · Awaiting response*; `LIBRARY` — *Rates · Outputs · Criteria · Team · Settings*; user at the foot. Collapsed rail is 48px of 28px icon buttons.

## The library / tender rule

This decides which screen anything belongs on.

| the **library** — what your company knows | **this tender** — what this job needs |
|---|---|
| unit prices: labour, plant, materials, subcontract | the bill of quantities and the station schedule |
| your normal outputs — 20 m/day soil, 10 rock, 5% decay per 20 m | *this* ground's outputs where they differ |
| your normal coefficients — PM 0.33, 8 h shift, mobilisation 4 days | the hole groups and their access classes |
| acceptable contract positions | the margin, the sweep and its routing |
| the team, the letterhead | quotes obtained for this job |

**A tender inherits the library and may override anything — and the override is always visible.** Three chips, used identically for rates and for outputs:

```
850.00 ⟨BOOK⟩      inherited from the library
920.00 ⟨YOURS⟩     typed here, for this job only
  0.00 ⟨MISSING⟩   named something not in the book. Priced at zero and flagged.
```

`BOOK` renders `#eef3f8` fill / `#1e3a52` text / `1px solid #b4c6d6`. `YOURS` renders `#f0e2c8` / `#856636` / `1px solid #dcc79a`.

## Screens

Each numbered section below corresponds to a section in the reference file.

**§00 The desk** — three shelves as tabs (Desk / Archived / Awaiting response), ownership filter, sort. Drop tile first in the grid: `1.5px dashed #bd9a5f` on `#f8f0df`, 44px brass `+` circle. **The whole page is a drop target**; the tile is where the affordance is stated.

*Folder card*: an 84×13px tab, radius `5px 5px 0 0`, `margin-left: 16px` above a white body with radius 8 and `box-shadow: 0 2px 8px rgba(12,26,40,.07)`. **Tab and top border are coloured by what needs doing, not by stage**: brass where you left off, red behind, blue still ingesting, grey normal. Contents in order — tender ref (mono) · project name · client · package · owner avatar top right · **days to close** (mono 21px, red at ≤7 days) · **the provenance of that date** in mono 8.5px: `READ FROM COT cl. 4.2 · p.11`, or `NO DATE IN THE COT — SET IT BY HAND`, or `READING THE DATE…` · six 4px gate segments · stage line · **one generated sentence of what is blocking it**, never a status word like "in progress" · footer with a state badge and who touched it last.

**The closing date is a finding like any other.** It is read from the Conditions of Tender during ingest, it carries its citation, it can fail, and a failed read must be confirmed by hand rather than silently defaulted.

**§01 Library › Outputs** *(NEW)* — productivity, on-site, shared resources, markup. Single pane. Each row: label, optional `⌞` explanation, value (mono 14px right-aligned), unit, `✎`. The closing note earns its place: *"Nothing here is a fact about a tender. It is what your company knows, and it is the thing worth arguing about once rather than every bid."*

**§02 Library › Rates, Criteria, Team, Settings** —
- **Rates**: id, category, description, unit, rate, source (`seed` / `you`), `✎`. One row edits at a time. A non-numeric rate gets a `1.5px solid #c25539` border and a dark tooltip: *"A rate must be a number — a bad rate never silently becomes 0."* Archived rows sit at 55% opacity with an `ARCHIVED` chip and a line naming how many live estimates still reference them.
- **Criteria**: the column that matters is **how it is checked** — navy swatch + `cap ≤ 10% · a rule` versus brass outline + `judgement · a model`. **This screen is where the register's authorship colours are decided**, so it shows them at source. Disable, never delete; disabled rows explain that estimates run earlier still show the criterion because they were checked against it.
- **Team**: 32px avatar, name, role, colour name, `✎`. No login.
- **Settings**: model choice (framed as how much typing you are saved, never as something that changes a number), letterhead, currency and rounding. Footer: *"There is nothing here that can change a price. That is deliberate."*

**§03 Documents** *(Gate 1)* — rail: the binder (pages, parts, confidence tier), revisions (Rev 0 / Rev 1 / Rev 2 with an `⚠ 2 parts amended` strip), then the 12 parts with index, title, page range, scan badge. Middle: the split banner — a 11px segment bar with one segment per part **coloured by scan status**, so an unread part shows as a red band in the page distribution — then **Approve the split** (brass) and **Edit the page bounds**, with the consequence stated beside them. Below, one card per part:
- *normal* (`01-CT`): brass border = the model wrote the summary. `WHAT IT IS` → key obligations → `PRICE IMPACT` chip. Note that the desk's closing date came from clause 4.2 of this part.
- *amended* (`04-PS`): blue, with a nested white panel listing what Rev 2 changed clause by clause, and revision pills ending in `Rev 2 · current`.
- *unread* (`08-GEO`): red, **no summary, no obligations, no price note** — because there is nothing to summarise. States that nothing downstream cites these pages.

Actions per card are two 30×28 icon buttons — `⟳` read again, `✎` edit page bounds — then `showing in the document →`.

**§04 Register** *(Gate 2)* — rail: `CHECKS` as parents (Criteria 28, Scope 14, Programme 6, Cash flow 3), each nesting a `FROM:` list of authors with counts. Then `STATUS`, `QUERY BATCHES`, `ADDENDA`. **Counts are always of the full tender, never the filtered list** — and the rail says so in words: *"a tally that moves when you filter cannot be trusted to tell you what is there."*

Row anatomy: item number (mono 13px) · authorship badge · criterion · clause + page pushed right · **rationale** in Source Serif 4 12.5px/1.55 (the only field present on every row, so it is the readable body text) · optional quoted-from-the-page and position blocks on `2px solid` left borders · then **Confirm / Dismiss / Query**, none pre-selected.

Row states: selected `#f8f0df` + `border-left: 3px solid #bd9a5f` · queried `#f6ebd0` with the query text in an editable white box and a `✓ IN BUILD 3` chip · citation failed `#f4e1d9` with **Confirm dead** (`1px dashed #cec7b8`, text `#b4c6d6`) and the reason where the button is · confirmed `#f3f1eb`, green attribution chip naming the person and date, verdict row replaced by `Undo`.

`/review/approve` is the **only** writer of a verdict; a model structurally cannot call it, and the screen says so.

Gate footer: `#0c1a28`, two-tone progress bar (brass confirmed, amber queried) bottom left, **Close the register & open the scope** right.

**§05 Scope** *(Gate 3, two-pane)* — 266px fixed rail: `SOURCES` (departures confirmed, queries open, amendments), a `NOT ACCEPTED` block on `#f6ebd0`, then the composition of the scope of record. No document pane, and the rail explains why: *"nothing on this screen is a quotation — every line is something you are saying, not something you read."*

Card states: **unaccepted** (`#fffdf7` on `1px solid #dcc79a`) shows the drafted text under a `2px solid #bd9a5f` rule labelled *"not yours until you accept it"*, with **Accept it as mine · Edit the prose · Delete the line** — any of the three makes it yours. **Accepted** shows plain body text, a `YOU` badge, `✓ ACCEPTED`, and attribution. **Verbatim from the register** shows a `#e4ebf2` chip, text on a `2px solid #1e3a52` rule, and a note that it is locked because editing it would mean the letter and the register no longer agree.

**Freeze the scope** is disabled while a pre-filled guess is unaccepted — and *not* by open queries. The distinction is stated on the card itself: *"an unanswered query does not block pricing, but a model's suggestion standing behind a price with nobody's name on it does."*

**§06 Site › Schedule** *(NEW)* — rail: stations, `ROWS THAT ADD UP` (length = soil + rock on every row), `AGAINST THE BILL` with a ✓ per reconciled quantity and **one amber row where the bill and the drawing disagree** (52 read, 54 billed). Only that row is styled. Rail note: *"The bill is the check on our reading. A disagreement is worth more than a match."* Middle: the station table, clicking a row scrolls the document pane to that station. A trial-pit row is tinted red because it is not a borehole group.

**§07 Site › Holes** *(NEW, interactive)* — **the screen that carries the whole idea.** The client bills 80 Class A and 11 Class B rig moves and never says which holes; hunting across five 1:2000 sheets becomes ninety-one small pictures.

Rail: `THE CLIENT BILLS` (80 / 11) above `YOU HAVE` (live counts), then a reconciliation strip with **three states** — amber `#f6ebd0` / `#c28a2e` while any hole is unassigned, green `#deebe2` / `#3c8a63` when the count agrees, **red `#f4e1d9` / `#c25539` when everything is assigned but your count disagrees with the bill** ("One of you is wrong — raise it as a query"). In the reference the 79 off-screen holes are all decided (70 A, 9 B), so the 12 visible tiles need exactly 10 A and 2 B to reach green; assigning an eleventh A reaches red. Then what the classes mean, and the note: *"No document says which eleven. Your count is the only check there is."*

Tile: a 96px `MapCrop` window, then station id, depth, strata, the model's hint on one brass-swatched line, and a `⟨A⟩ B C` segmented control. **Class C is helicopter access and the bill has no item for it** — choosing it shows `→ SENT TO THE SWEEP` and routes the hole there rather than pricing it at nothing. `▪road 40 m` is the only thing a model contributes here, so it is brass, and it is optional: the tile is designed so you can classify from the picture alone.

**Site has no gate.** An unassigned hole cannot stop you pricing, but the Price step carries `⚠ N HOLES UNASSIGNED` live, and the sweep will not settle while one is open.

Second frame: the one-at-a-time alternative — queue on the left, a large crop, schedule facts and the model's hint on the right, keyboard classification (`↑ ↓` to move, `A · B · C` to classify), and the count consequence stated on the button (`8 → 9`). Use the grid for the easy eighty and this for the nine hard calls.

**§08 Site › Groups** *(NEW, interactive)* — a group is your judgement about which holes drill alike; nothing in the documents draws these lines. Left column `YOURS`: rigs, soil output, rock output, decay, platform build — each with `BOOK`/`YOURS` chips. Right column `DERIVED`: soil days, rock days, depth decay, drilling days, on site per rig, blended rate of work, cost per day, group cost. **The blend turns red above 9 m/day** with *"faster than you have ever managed on this hill"* — that number exists so you can catch it before any money is involved.

**It does not price as you type.** Days and blend recompute locally because they are exact and cheap; the rate comes from the server when you leave. The screen says so.

A `BASIS` textarea gates the group's *readiness*, not its price: *"The group stays 'not ready' until you write why. A number nobody can explain is a number nobody can defend."*

**§09 Price › Bill** — rail: the price, cost, margin (with a note that the book's default is 33% and this tender's is 15%), the bills, and state counts. **An unpriced row is red, never blank** — item 2.6 shows `⚠ none` with the consequence spelled out: *"Leave it blank and the contract deems it covered by the other rates — 100 m of obstruction drilling, free, for the life of the contract."* Bill 9 is padlocked; the client priced it.

**§10 Price › Working** — **the screen that decides whether he trusts it.** Rate at the top, then the derivation tree, indented, each line either a computation or a leaf with `▸ show me` / `▸ change`:

```
RATE  1,104.15 / m
= cost 2,539,545 ÷ 2,300 m                    ✓ EXTENSION CHECKS
    cost = build-up 2,208,300 × 1.15 margin      ▸ change
    build-up = Σ groups, soil share only
      ▸ Roadside  68 holes  1,780 m  1,540,200    865.28/m
      ▸ Hillside  23 holes    520 m    668,100  1,284.81/m
    2,300 m ← Σ soil depths, GI/210 · 91 stations  ▸ show me
    1.15    ← your margin, set 3 Aug by J. Dai    ▸ change
    Sweep spread of 52,000 is NOT inside this rate ▸ open the sweep
```

Below: `WHAT THIS RATE MUST COVER · 12 heads · 3 NOT COVERED`. **The list is read from the SMM by a rule; the ticks are the human's** — every tick carries a name and a date, and unticked heads offer `→ route it`. The footer states why: *"a machine cannot know what you put in your number. Three unticked heads is not an error; it is a decision waiting."*

**You never see a bare number.** Every `▸ show me` opens the document pane at that clause, highlighted. Second frame inverts the screen — coverage becomes the page, the rate becomes a dark summary strip — for the final read-through.

**§11 Price › Resources** — shaped like the spreadsheet he already trusts, with the same nine cost classes in the rail. Every quantity that came from a driver or a formula says so on a `⌞` line beneath it: `15 days ← drilling days ÷ rigs + 4`, `soil ⌈45/30⌉ = 2 + rock ⌈72/4⌉ = 18`, `π (0.04 m)² × 132 m × 1000`. **Nothing is typed that could be derived** — which is the only way it survives an addendum.

**§12 Price › Sweep** — **the only hard stop in the app.** Costs the contract makes yours that no bill item asks for. Each: title, amount, the clause with `▸ show me`, where it came from, then four routes as a 2×2 grid — **query it · load onto [item ▾] · spread it · accept the risk**. Settled costs collapse to a green chip with attribution.

Settle is disabled with the reason stated: *"Anything left unrouted is priced at nothing, and the contract deems an unpriced item 'covered by the other rates' — work you have agreed to do free for the life of the contract."* It also will not settle while a hole is unassigned in Site — which is where the missing Site gate actually lands.

Accepting a risk requires a written reason, stored with a name and a date: *"A risk somebody took deliberately and one nobody noticed look identical six months later."*

**§13 Offer** *(no rail)* — full width. Structured / Markdown toggle, Copy, Download. A legend distinguishes `VERBATIM` (navy) / `DRAFTED` (brass) / `INJECTED` (grey). Sections carry authorship badges; the pricing schedule is `INJECTED` and not editable here.

**Appendix A splits in two.** `A1 · CARRIED FROM THE DEPARTURE REGISTER, WORD FOR WORD` — navy left rules, with the note *"the wording is the wording you approved and cannot drift."* `A2 · DRAFTED FROM THE SCOPE OF RECORD — A PROPOSAL` — brass left rules, *"read every line before this goes out; the words are a draft, the meaning is yours."* Appendix B lists queries outstanding at the date of tender.

Closes on `#f4e1d9` with a `2px solid #c25539` top border: **this is a draft and nothing on this screen sends it** — and it names the two things still open upstream rather than pretending they are settled.

**§14 The overlays** — right-hand sheets, 78–80% width, `#faf9f6` on `1px solid #cec7b8` with `box-shadow: -8px 0 24px rgba(12,26,40,.16)`, over the work at `rgba(12,26,40,.28)`. **No modal system.** The work stays visible so you can see what the panel is about to change.
- **RFI panel** — the line being added in a brass-bordered card, then what is already in the batch with `×` removes. Export stamps the date, freezes the batch read-only, opens the next.
- **Addendum panel** — proposes which parts it replaces (with "wrong? change the mapping before approving — the page numbers everything cites depend on it"), lists what will change clause by clause, then an amber panel naming exactly what approving will re-open: register lines back to undecided, a scope line losing its acceptance, a bill re-priced, a query already answered. **It commits nothing until approved.**

**§15 The four states** — `DocTab` (a 30px vertical tab, label rotated, when the document pane is collapsed) · `WaitingOn` (title, explanation, one or two actions, and the reassurance that a model only ever saves typing) · `ErrorNote` (one strip at the top, the backend's own sentence in **mono, unrewritten** — a paraphrase hides which part failed — plus a plain-language consequence) · `RailFolded` (44px, big mono figures, no label longer than four letters, still answering the only question the rail has to).

## Component inventory

Everything is hand-rolled. **No grid library, no form library, no component library, no icon set, no virtualisation, no modal system.** Icons are unicode: `☰ ▯ ⌕ ← → ‹ ◈ ◇ ⟳ ✎ × ⚠ ✓ ✕ − + ✛ ⌞ ⌈ ⌉` — replace with the codebase's icon set where one exists.

| component | purpose |
|---|---|
| `Rail` / `RailFolded` | left index; folded shows big mono counts |
| `Divider` | draggable, 9px main / 5px subtle |
| `DocTab` | vertical tab when the document pane is collapsed |
| `StepStrip` | the six-step breadcrumb with done / open / waiting states |
| `PageView` | the document pane — lazy pages, typed zoom 25–400%, fractional highlights |
| `Chip` · `Pill` | small labels; colour always supplied by the caller |
| `SectionLabel` | all-caps mono block heading, `.12em` |
| `Button` | brass · dark · outline · amber · ghost, plus `disabledReason` as a tooltip |
| `IconButton` | 30×28 square glyph button |
| `Card` | bordered surface with a selected state |
| `Consequence` | a short sentence beside a gate button saying what it will do |
| `WaitingOn` | empty state for a step that has not run |
| `ErrorNote` | one strip at the top; backend sentences shown **unrewritten** |
| `AuthorSwatch` / `AuthorBadge` | the navy / brass / red authorship mark |
| `Avatar` | initials in a hashed colour |
| `SourceChip` | the `⟨BOOK⟩` / `⟨YOURS⟩` / `⟨MISSING⟩` triad |
| **`MapCrop`** *(new)* | a CSS-cropped window of a drawing, centred on a station |
| **`Segmented`** *(new)* | the `⟨A⟩ B C` control |
| **`Derivation`** *(new)* | the indented `= cost ÷ metres` tree with `▸ show me` leaves |

## Writing rules

The copy is part of the design. Do not rewrite it into conventional UI voice.

- **Say what will happen, not what to do.** *"Freezing refuses while a pre-filled guess is unaccepted"*, not *"Please accept all fallbacks"*.
- **Name the consequence in money or in risk.** *"work you have agreed to do free for the life of the contract"*.
- **Never blame the user.** A red border carries a tooltip explaining the rule, not a scolding.
- **Quote the contract verbatim** when the contract is the reason.
- **Admit what is not known.** *"No document says which eleven. Your count is the only check there is."*
- Every rail block closes with one 9.5px faint sentence saying what its numbers mean.
- Sentence case throughout. No exclamation marks. No "oops".

## State management

App-level: `navSidebarOpen`, `history[]`, `searchQuery`, `currentUser`, `teamMembers[]`, `library` (`rates[]`, `outputs{}`, `criteria[]`, `settings{}`).

`tenders[]`: id, ref, name, client, package, ownerId, stage, closeDate, `closeDateSource {clause, page, status: found | not_found | reading}`, gateStates[], blockingSummary, badges[], lastTouchedBy, lastTouchedAt, shelf (`desk | archived | awaiting`).

Per tender: `parts[]` (id, title, pageStart, pageEnd, scanStatus, revision, summary, obligations[], priceImpact) · `manifest` (coverage, gaps[], overlaps[], tier, approved) · `findings[]` (id, author, check, criterionId, clause, page, rationale, quote, position, citationOk, verdict, verdictBy, verdictAt, queryText, batchId) · `scopeLines[]` (section, title, author, accepted, acceptedBy, text, sourceRef) · `stations[]` (id, easting, northing, gl, soil, rock, st, pz, accessClass, groupId) · `groups[]` (id, name, holeIds[], rigs, soilOut, rockOut, decay, platformCost, basis) · `bills[]` / `items[]` (ref, description, qty, unit, rate, rateSource, coverageHeads[], locked) · `sweepCosts[]` (title, amount, clauseRef, origin, routing, reason, routedBy, routedAt) · `batches[]` · `addenda[]` (rev, issuedAt, proposedMapping[], deltas[], applied) · `offer` (sections[], appendixA1[], appendixA2[]).

Gate transitions are server-side and one-way-with-consequence. Approving the split freezes part bounds; closing the register injects confirmed positions into the scope and Appendix A1; freezing the scope opens pricing. **Reopening a gate invalidates everything built after it** — warn explicitly, naming what will be dropped. Per §8.3: reopening the scope *throws the estimate away* rather than recomputing it quietly.

## Files

| File | What it holds |
|---|---|
| `sitesource_ui_reference.dc.html` | All 21 frames in 16 sections. §07 and §08 are interactive. |
| `support.js` | Runtime the reference needs to render. **Reference only — do not port.** |
| `README.md` | This document. |

## Open questions

The design assumes the first option in each case.

1. **The risk preview has nowhere to live.** Programme conflict (the 11-day access clash, $50,000 max LD exposure) and the cash-flow forecast were drawn against Scope, but §8.3 makes Scope two-pane with no room for them. Recommendation: a fifth Price view beside Sweep. Not yet drawn.
2. **`accepted_by` may not exist.** §05 treats *"accept it as mine"* as an act distinct from editing the prose. If the backend has only an author field, it needs a separate acceptance field, or the two acts collapse and the gate loses its meaning.
3. **Group cost → bill item apportionment.** A group's cost covers both soil and rock metres, which are separate bill items. §10 shows a soil share apportioned by metre; the exact rule is a backend decision and the spec does not state it. (Note: the spec's own figures for §8.4c — 38.4 drilling days, blend factor 2.4 — do not reconcile with 520 m of soil at 9 m/day, so the frames use an internally exact derivation instead. A screen whose whole argument is "check my working" cannot show working that does not.)
4. **Where the sweep spread lands.** Frames put it as its own line in the bill total, outside the metre rates. The spec sketched it inside the build-up, but then the arithmetic does not produce 1,104.15 — and a spread hidden inside a metre rate is the thing this app exists to expose.
5. **Two people in one register** — is a verdict locked to its author, or may anyone overturn anyone's? Presence via the avatar stack is assumed; row-level locking is not.
6. **Who may pass a gate** — any role restriction, and is a second approver ever required for Gate 3 or the sweep?
