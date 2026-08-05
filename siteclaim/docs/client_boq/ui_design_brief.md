# START HERE — brief for Claude Code

You are implementing an existing, finished design. **Do not redesign anything.** Every colour, size, weight and sentence in the reference has been decided and reviewed.

## The three files

| File | What to do with it |
|---|---|
| `sitesource_ui_reference.dc.html` | **Open it in a browser and look at it.** 21 frames in 16 sections. Read the markup for structure and exact values. |
| `README.md` | The specification. Palette, type roles, layout system, every screen, component inventory, writing rules, state shape, open questions. |
| `support.js` | Only there so the reference renders. **Never port it, never import it, never copy its `<x-dc>` / `{{ }}` / `<sc-for>` syntax.** |

Two frames are live — click them before writing code: **§07 Site › Holes** (assign access classes, watch the rail reconcile) and **§08 Site › Groups** (type an output, watch the derivation move).

## What to build it in

The target codebase's own framework and patterns. If none exists: React + TypeScript + Vite, plain CSS or CSS-in-JS. **No component library, no grid library, no form library, no icon set, no modal system, no virtualisation** — the design is hand-rolled on purpose and a component library will fight every one of its decisions.

Extract the palette into CSS custom properties or a theme object first, using the names in README § *The palette*. Then build the shared components in README § *Component inventory* before any screen.

## Build order

Follow this. Each step is usable before the next begins.

1. **Tokens and chrome** — palette, the three font roles, `AppBar` with the five nav controls, `StepStrip`, `NavSidebar`, `Rail`/`RailFolded`, `Divider`, `Card`, `Chip`, `Button` (with `disabledReason`), `SectionLabel`, `Consequence`, `WaitingOn`, `ErrorNote`, `Avatar`, `AuthorBadge`, `SourceChip`. §15 of the reference shows the four states these must support.
2. **The desk** (§00) — the shelf, the folder card, the drop target. Everything else is reachable from here.
3. **Library › Outputs** (§01) then **Rates, Criteria, Team, Settings** (§02). Small, self-contained, and every later screen inherits from them. `SourceChip` (`BOOK` / `YOURS` / `MISSING`) is defined here and reused everywhere.
4. **The three-pane shell** — the layout, both draggable dividers, and the degradation order in README § *The layout system*, including `DocTab`. Get this right once; five screens sit in it.
5. **`PageView`** — the document pane. Lazy pages, typed zoom 25–400%, fractional highlights. Every screen's credibility depends on it.
6. **Documents** (§03) → **Register** (§04) → **Scope** (§05). Gates 1–3.
7. **Site** (§06, §07, §08). `MapCrop`, `Segmented`. Crops are one render per sheet, cropped N ways in CSS from surveyed coordinates — no image pipeline.
8. **Price** (§09–§12). `Derivation` is the component that matters most in the whole app.
9. **Offer** (§13), then the **overlays** (§14).

## Non-negotiables

Break any of these and the product stops meaning what it means.

1. **The authorship triad survives everything.** `#1E3A52` navy = a deterministic rule wrote this. `#BD9A5F` brass = a model proposed this. `#C25539` red = a check on this failed. If the host design system replaces the palette, these three stay. A person's avatar colour is never one of them.
2. **Three type roles, never mixed.** Libre Franklin = interface. Source Serif 4 = the argument. IBM Plex Mono = anything a machine produced or that must be compared digit by digit.
3. **No verdict, tick, or acceptance is ever pre-filled.** A model may propose; only the human's action writes. `/review/approve` is the sole writer of a register verdict and a model structurally cannot call it.
4. **No step is ever disabled.** A step that has not run opens and states what it is waiting for.
5. **An unpriced bill row is red, never blank.** A blank is a promise to work for free for the life of the contract.
6. **Counts in a rail are of the full set, never the filtered one.**
7. **Every number opens.** `▸ show me` must land on the clause in the document pane, highlighted. A number with no path back to a document is a bug.
8. **Backend error text is shown unrewritten.** A paraphrase hides which part failed.
9. **The copy is the design.** Say what will happen, not what to do. Name the consequence in money or risk. Never blame the user. See README § *Writing rules*.
10. **List rows do not animate on selection** — colour only, geometry never moves.

## Gotchas

- A `⌞` line under a quantity means it is **derived**, not typed. If you find yourself adding an input for it, the driver is missing.
- Group arithmetic (days, blend) recomputes **locally as you type** because it is exact and cheap. The **rate** comes from the server, once, on leaving the screen. Do not price on keystroke.
- The tender closing date is a **finding**: it carries a citation, it can fail, and a failed read must be confirmed by hand — never silently defaulted.
- Scope is two-pane and Offer has no rail. These are deliberate deviations, not oversights.
- The Sweep is the app's **only hard stop**. Everything else warns and lets you past.
- If the codebase registers tabs in a list (e.g. `TAB_IDS` in `routes.ts`), adding `Site` there is a silent-failure edit. Put it on the PR checklist.

## Before you finish

- Read README § *Open questions* — six items the design assumes an answer to. Ask the product owner rather than guessing, especially **`accepted_by` as a field distinct from author** (without it Gate 3 loses its meaning).
- Replace the placeholder `MapCrop` tiles with real crops once a drawing sheet is available.
- The `Price › Risk` view (programme clash, cash-flow forecast) is **not yet designed** — it has no home since Scope became two-pane. Do not invent it; ask for the design.
