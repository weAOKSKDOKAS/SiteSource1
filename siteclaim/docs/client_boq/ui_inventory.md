# Frontend UI Inventory — for designing client_boq screens

**Purpose.** The `client_boq` review→estimate workflow has **no frontend today** (it is API-only). This
document inventories the *existing* SiteSource frontend so a designer who has never seen the code can
propose new client_boq screens that fit the established system. Everything below is grounded in real
files under `siteclaim/frontend/src/`. It describes what *is*, not what *should be*.

Stack (verified): **React 18 + TypeScript + Vite 6 + Tailwind CSS v4**, single-page app, no router
library (navigation is React state). Build: `npm run build` (`tsc --noEmit && vite build`) — verified
to compile cleanly. Dev: `npm run dev` (Vite, `localhost:5173`).

The design system has an internal name: **"Atlas"** (see the header comment in `src/index.css`).

---

## 1. Layout skeleton — how a page is composed, and where a new tab plugs in

### The shell (`src/App.tsx`)
`App.tsx` is the single top-level component. It renders one shell for every screen (`App.tsx:516-528`):

```
<div className="min-h-screen">
  <Header demoMode view onNavigate={setView} />        // sticky top bar (components.tsx)
  <main className="mx-auto max-w-6xl px-5 py-8">        // the one content column, max-width 6xl (72rem)
    { sideView ? <FullWidthPage/> : <WizardGrid/> }     // two layout modes (below)
  </main>
  <IngestIndicator … />                                 // a floating, always-mounted progress pill
</div>
```

Two layout modes share that `<main>` column:
- **Full-width page** — used by the non-wizard tabs (Estimator, Benchmark, Projects, Database). The page
  component owns its own internal layout. Selected via the `sideView` flag (`App.tsx:514`).
- **Wizard grid** — a two-column grid `lg:grid-cols-[16rem_1fr]` (`App.tsx:531`): a **left rail Stepper**
  (16rem) + the active step's content. This is the pattern most relevant to client_boq (see §4).

### The tab mechanism (`src/components.tsx`)
- `TopView` is a string union of tab ids (`components.tsx:24`):
  `"wizard" | "estimator" | "benchmark" | "database" | "projects"`.
- `NAV` is an array of `{ view, label, enabled }` (`components.tsx:27-33`) that `Header` maps into tab
  buttons (`components.tsx:44-66`). An `enabled: false` entry renders a greyed, non-clickable label with a
  "coming in …" tooltip — the established way to show a not-yet-built tab.
- `App.tsx` holds the current tab in `const [view, setView] = useState<TopView>("wizard")` (`App.tsx:41`)
  and `Header` calls `onNavigate={setView}`.

### Where a new "Client → BOQ" tab plugs in (exact insertion points)
Four edits, all mechanical and matching existing precedent:
1. **`components.tsx:24`** — add the id to the union: `… | "client_boq"`.
2. **`components.tsx:27-33`** — add a row to `NAV`: `{ view: "client_boq", label: "Client → BOQ", enabled: true }`
   (or `enabled: false` to show it as "coming soon" first).
3. **`App.tsx:514`** — add `"client_boq"` to the `sideView` OR-chain so it renders full-width (or leave it
   out and give it a wizard-style grid instead — see §4).
4. **`App.tsx:520-529`** — add a branch to the render conditional: `view === "client_boq" ? <ClientBoqPage/> : …`.

No other file needs to change to add a tab. New API methods go in `api.ts` (§5).

---

## 2. Design tokens — the palette, type, spacing actually in use

All tokens live in **`src/index.css`** under Tailwind v4's `@theme { … }` block (`index.css:16-72`). Token
*names* are preserved so every utility class (`text-ink`, `bg-brand`, `rounded-card`) resolves to these.

### Colour (the palette is semantic and *reserved* — do not repurpose)
The `index.css` header comment states the rule explicitly: signal colours are load-bearing.

| Token (class stem) | Hex | Reserved meaning |
| --- | --- | --- |
| `ink` / `ink-soft` / `ink-faint` | `#0f1b2d` / `#46566b` / `#8a98ab` | headings / body / muted text |
| `paper` / `paper-soft` | `#eef2f7` / `#f6f9fc` | app background / lighter panel |
| `card` | `#ffffff` | card surface |
| `line` / `line-soft` | `#dbe3ec` / `#eaeff5` | hairlines / softer hairlines |
| `brand` / `brand-bright` / `brand-bg` | `#1f6feb` / `#4c8dff` / `#e7f0fe` | **brand blue = Layer-2 / Claude / AI accent** |
| `ok` / `ok-bg` | `#2ea56a` / `#e4f5ec` | **recommended / approved ONLY** |
| `warn` / `warn-bg` | `#d99513` / `#fbefd6` | **human gate / Layer-4 ONLY (amber)** |
| `bad` / `bad-bg` | `#e5484d` / `#fce9e9` | **fatal flags ONLY** |
| `violet` / `violet-bg` | `#6e56cf` / `#ede9fb` | **database / Layer-3** |
| `teal` / `teal-bg` | `#0fb5a6` / `#def5f2` | accent |

For client_boq this maps naturally: AI-drafted content → `brand`; human-gate / approval steps → `warn`
(amber); a confirmed/approved state → `ok`; a fatal/`rule_flagged`/`citation_failed` line → `bad`. Reuse
the existing `LayerBadge` semantics (§3) rather than inventing colours.

### Typography (`index.css:47-50`)
- `font-sans` = **Spline Sans** (body, default).
- `font-mono` = **Spline Sans Mono** — used via the `.tabular` class (`index.css:105-108`) for **all codes,
  references, IDs, and numbers** ("instrument data"). Any clause id, criterion id, or price should be mono.
- `font-display` = **Bricolage Grotesque** — headings only (`font-display` class).
- `font-serif` = used **only** inside `.doc` (`index.css:139+`), the rendered-document surface (a legal
  instrument look). This is the natural home for a rendered offer letter / departure register document.
- ⚠️ These are web fonts referenced by name only; I did **not** find a `@font-face`/font-loading link in
  the repo, so they currently fall back to system fonts unless the host page loads them (see §6).

### Spacing / radius / shadow / tracking
- Spacing is **default Tailwind scale** (grep shows `px-4 py-2.5`, `gap-2`, `p-5`, `mt-1.5`, etc.) — no custom
  spacing tokens. The content column is `max-w-6xl px-5 py-8` (`App.tsx:519`).
- `rounded-card` = 16px (`--radius-card`), `shadow-card` = soft deep card shadow, `shadow-glow` = brand CTA
  glow (`index.css:64-66`). Buttons use `rounded-lg`; pills `rounded-full`; inputs/tiles `rounded-xl`.
- `tracking-eyebrow` (0.1em) for uppercase labels; `tracking-display` (-0.02em) for display headings
  (`index.css:69-70`).
- Gradients: `.bg-navy-depth`, `.bg-brand-violet` (the primary CTA fill), `.text-brand-violet`, and
  subtle `.tint-*` washes (`index.css:65-89`).

### Motion (`index.css:112-140`)
A small reserved "motion kit": `ssRise` (one-shot card entrance), `ssScan` (a live "processing" sweep),
`ssDot`/`ssLive`/`ssPulse` (working indicators). All are guarded by `@media (prefers-reduced-motion)`
which freezes them (`index.css:131-137`). Rule from the comment: motion is **for meaning only** (entrance,
live/processing), never on static chrome.

### Dark / light
**Single light theme only.** Verified: no `dark:` utility classes anywhere in `src/`, and no
`prefers-color-scheme` query. `@theme` defines only the light values; `body` is `--color-paper`. A new
screen should assume light surfaces and not attempt dark-mode variants.

---

## 3. Component vocabulary — the reusable pieces

Two files hold the shared kit: **`src/ui.tsx`** (generic design-system atoms) and **`src/components.tsx`**
(app-specific molecules). Use these before building anything new.

### From `src/ui.tsx`
| Component | File:line | One-line usage |
| --- | --- | --- |
| `Button` | `ui.tsx:59` | CTA; `variant="primary"` (brand→violet gradient + glow) / `"ghost"` (outlined) / `"subtle"` (text); `loading` shows a spinner. |
| `Spinner` / `LoadingDots` | `ui.tsx:77` / `ui.tsx:83` | inline "working" indicators (`LoadingDots` for composing/streaming states). |
| `ScanLine` | `ui.tsx:100` | a brand sweep across the top edge of a surface while a stage runs (put in a `relative` box). |
| `Card` | `ui.tsx:112` | the base surface: hairline + `shadow-card` + 16px radius + `ssRise` entrance. Everything sits in Cards. |
| `StatCallout` | `ui.tsx:118` | a single big number + label ("instrument reading"); tones `ink/brand/ok/violet`. Good for status counts, totals. |
| `SectionHeader` | `ui.tsx:131` | display-type section title + optional lead + right slot. |
| `LayerBadge` | `ui.tsx:144` | the architecture chip: `L1 rules` / `L2 Claude` / `L3 database` / `L4 human gate`. Use to tag AI vs rule vs gate. |
| `Modal` | `ui.tsx:157` | centered pop-up; Escape/backdrop close; `wide` for larger review surfaces; content scrolls inside, never the page. **This is the approval-pop-up primitive.** |
| `Drawer` | `ui.tsx:206` | right slide-in detail panel (record-on-click); `eyebrow`/`tone`/`footer`; scrim + blur. Used for firm/variance records. |
| `MonoLabel` | `ui.tsx:280` | tiny uppercase mono field label inside detail views. |
| `Docket` | `ui.tsx:289` | a citable code tile (label + mono code on a soft panel) — the "reference/docket" look. |
| `Collapse` | `ui.tsx:300` | a collapsible sub-section with a rotating chevron + optional count. |
| `ErrorBanner` / `InfoNotice` | `ui.tsx:326` / `ui.tsx:334` | red error banner / amber notice strip. |
| `InfoDot` | `ui.tsx:339` | a focusable "ⓘ" carrying context as a tooltip. |
| `SeverityTag` | `ui.tsx:16` | a status chip: `fatal` (red) / `warning` (amber) / `info` (blue) with a dot. |
| `MatchChip` | `ui.tsx:30` | a tabular "% match" chip with an "unassessed" empty state — a good pattern for any scored/optional metric. |
| `cx(...)` | `ui.tsx:5` | the classNames helper used everywhere. |

### From `src/components.tsx`
| Component | File:line | One-line usage |
| --- | --- | --- |
| `Header` | `components.tsx:35` | the sticky frosted top bar with brand mark, demo-mode pill, and the `NAV` tabs. |
| `Stepper` | `components.tsx:95` | the left-rail vertical stepper for a gated wizard (states: active/done/upcoming; unreachable steps disabled). **Reuse for the client_boq gated sequence.** |
| `StepHeading` | `components.tsx:160` | a step's h1 + lead paragraph. |
| `StepNav` | `components.tsx:169` | the Back / Continue footer for a step (`nextLabel`, `loading`, `nextDisabled`). |
| `Pill` | `components.tsx:328` | small rounded status pill; tones `neutral/ok/bad/brand/violet/warn`. The workhorse status chip. |
| `RiskFlagList` / `EvidenceList` | `components.tsx:221` / `:201` | render risk flags with cited evidence — the "every claim has a citation" pattern client_boq's register also needs. |
| `FirmRecord` | `components.tsx:254` | a full record body inside a Drawer (Docket + Collapses). A template for a "departure detail" drawer. |
| `GmailStatusPill` | `components.tsx:344` | a self-fetching integration-health pill (hidden in DEMO). |

### Formatting helpers (`src/format.ts`)
`hkd(n)` whole-dollar HK$; `money(n)` HK$ with cents + `—` for null; `pct(n)`; `tradeLabel(key)`
(`mechanical_plumbing` → "Mechanical Plumbing"). Note money is **HK$** here; client_boq's demo letter uses
`$` — a formatter decision to make consciously (see §6).

---

## 4. The Sourcing wizard pattern (the one to reuse)

The client_boq flow (review → **approve** → scope → **approve** → estimate → outputs) is a *gated linear
sequence with human approval gates* — structurally the same as the Sourcing wizard. Study these:

### The stepper + step model (`components.tsx:9-19`, `App.tsx`)
- `STEPS` is a fixed array of labels; `StepIndex = 1..6`; `GATE_HINT` gives each step a one-line subtitle.
- `App.tsx` owns the wizard state: `const [step, setStep] = useState<StepIndex>(1)` and
  `const [maxReached, setMaxReached] = useState<StepIndex>(1)` (`App.tsx:46-47`).
- **How a step gates the next:** two helpers (`App.tsx:126-156`):
  - `advance(to)` — moves to a step and bumps `maxReached` so it becomes navigable.
  - `invalidateAfter(keep)` — when the operator edits an earlier gate, **all later state is cleared and
    `maxReached` is pulled back**, so a downstream decision can never rest on stale upstream data. The code
    comment names this "the ICM review-gate rule." The `Stepper` renders steps beyond `maxReached` as
    disabled (`components.tsx:125-129`). **This is exactly the guarantee client_boq's gates need** (a
    re-run review must invalidate an approved scope/estimate).
- The wizard advances only after a successful backend call — e.g. the routing gate confirms, then
  `shortlistScope` runs and `advance(3)` (`App.tsx:265-282`). Each step's "Continue" is wired to an async
  action wrapped in a shared `run()` helper that sets `loading`/`error` (`App.tsx:114-124`).

### The approval-modal pattern (`src/steps/StepDispatch.tsx`)
The dispatch step is the closest analog to a client_boq approval gate:
- The step shows a summary + an "open the review pop-up" button gated by an `approvedCount`
  (`StepDispatch.tsx:236-259`).
- A local `const [reviewOpen, setReviewOpen] = useState(false)` drives a `Modal` (`ui.tsx:157`) containing
  `DispatchReviewModal` (`StepDispatch.tsx:331-354`) — an editable review surface (per-firm subject/body).
- **Edits persist in App-level state**, and **only the explicit confirm commits** to the backend
  (`StepDispatch.tsx:357-359` comment). Nothing is sent silently.
- Precedent: use a `Modal` (centered) for a focused approve/edit action; use a `Drawer` (side) for
  read-only record detail. Both live in `ui.tsx`.

For client_boq, the natural mapping is: a **Stepper** with steps *Review · Approve register · Scope ·
Approve scope · Estimate · Outputs*; the register/scope approvals as **Modal** review surfaces that write
back via the approve endpoints; `invalidateAfter` semantics to keep the gates honest.

### The job-polling UX (`src/useIngestJob.ts` + `src/IngestProgress.tsx`)
The review-ingest is long-running, exactly like the procurement ingest — reuse this pattern verbatim:
- `useIngestJob(onDone)` (`useIngestJob.ts`) is an **app-level hook** holding one job snapshot
  (`phase: "uploading" | "processing" | "done" | "error"`, plus `stage`, `progress`, `warnings`,
  `summary`). It kicks off `api.ingestUpload(files, {onUploaded, onProgress})` and updates the snapshot.
- A **generation guard** (`genRef`) makes cancel/navigation race-proof: a superseded poll's late callback
  is dropped, never yanking the user (`useIngestJob.ts:36-45`, `:64-66`). `start`/`cancel`/`dismiss`/`retry`
  are exposed.
- The actual polling lives in `api.ts::pollIngestStatus` (`api.ts:92-117`): `setTimeout(tick, 1500)`, no
  ceiling, tolerant of a few transient failures, gives up on a 404 (job gone). DEMO returns the result
  inline with no polling.
- `IngestProgress.tsx` renders the floating, non-blocking indicator (`IngestIndicator`), mounted once in
  `App.tsx` so it survives tab navigation.

client_boq's `/client-boq/review/run` and `/estimate/run` already return the **same job envelope shape**
(`{job_id, status, stage, result}` in live; inline `{status:"done", result}` in DEMO) — so this hook and
poller can be reused with almost no change.

---

## 5. How `api.ts` is structured, and what adding /client-boq looks like

`src/api.ts` is a **single flat object literal** exported as `api` (`api.ts:131-309`), one method per
endpoint, built on tiny helpers:
- `const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000"` (`api.ts:48`) — the backend base
  URL, override via a Vite env var.
- `handle<T>(res)` unwraps JSON and throws `Error(detail)` on non-2xx, reading FastAPI's `{detail}` shape
  (`api.ts:50-62`) — so every call rejects with a human-readable message the UI shows in an `ErrorBanner`.
- `get<T>` / `post<T>` / `patch<T>` / `del<T>` (`api.ts:64-86`) — thin `fetch` wrappers.
- Multipart upload uses a raw `XMLHttpRequest` (`api.ts:159-201`) so the progress modal gets a real
  "upload complete" tick; JSON calls use `fetch`.
- All request/response types are imported from `src/types.ts` (a single 691-line type module).

**Adding client_boq calls** = add methods to that object and types to `types.ts`. Example shape (matches
the existing style; the backend routes already exist):
```ts
// review
reviewRun: (files: File[], projectName: string) => { /* multipart, like ingestUpload */ },
reviewRegister: (setId: string) => get<ReviewRegister>(`/client-boq/review/register/${setId}`),
reviewApprove: (setId: string, decisions: Record<number,string>, approved: boolean) =>
  post<GateState>("/client-boq/review/approve", { set_id: setId, decisions, approved }),
// estimate
estimateScope: (setId: string) => post<ScopeState>("/client-boq/estimate/scope", { set_id: setId }),
scopeApprove: (setId: string, amended_summary: string, approved: boolean) =>
  post<ScopeGate>("/client-boq/estimate/scope/approve", { set_id: setId, amended_summary, approved }),
clientBoqRun: (setId: string, margin_pct: number, schedule: unknown) =>
  post<EstimatePayload>("/client-boq/estimate/run", { set_id: setId, margin_pct, schedule }),
estimateWorkbookUrl: (setId: string) => BASE + `/client-boq/estimate/${setId}/workbook`,  // file link
estimateLetter: (setId: string) => get<LetterPayload>(`/client-boq/estimate/${setId}/letter`),
```
Note the **binary/file endpoints** (workbook `.xlsx`) follow the existing "return a URL string" convention
(cf. `api.ts:244 tenderComparisonUrl`, `:266 actualsTemplateUrl`) rather than fetching bytes.

---

## 6. Inconsistencies / fragilities a new page should avoid copying

Grounded observations, not opinions:

1. **No fonts are actually loaded.** `index.css` names Bricolage Grotesque / Spline Sans / Spline Sans Mono
   but I found no `@font-face` or `<link>` loading them. Today they silently fall back to system fonts. A
   new page should not assume the branded type renders — and whoever ships should add font loading once,
   centrally.
2. **Currency is inconsistent across the two products.** `format.ts` formats money as **HK$**
   (`hkd`/`money`), but the client_boq backend renders the offer letter/workbook in plain **`$`** with cents
   (e.g. `$6,985,002.25`). A client_boq screen must decide its currency presentation deliberately rather
   than reflexively reusing `hkd()`.
3. **No auth / no user context in the client.** `api.ts` sends no auth header or credentials; there is no
   login state anywhere. A new page cannot assume a "current user."
4. **Navigation is hand-rolled React state, not a router.** There are no URLs/deep links — `view` and
   `step` are in-memory only. A refresh resets to the Sourcing wizard, step 1. A client_boq screen inherits
   this: no shareable/bookmarkable state, no browser back button.
5. **Wizard state lives entirely in `App.tsx`** (already ~729 lines). The Sourcing wizard threads dozens of
   `useState`s and callbacks through one component. Copying that approach for client_boq would bloat
   `App.tsx` further; a self-contained page component (like `EstimatorPage`/`BenchmarkPage`, which own their
   state) is the cleaner precedent to follow.
6. **`theme.ts` colours are a separate, non-reserved palette.** It defines government-register badge colours
   (BD/DEVB/LD…) that intentionally sit *outside* the reserved Atlas signal palette. Don't confuse these
   with the semantic tokens — they're identity colours for a specific data showcase, not general UI colour.
7. **The bundle is already ~685 KB JS** (one chunk, verified at build). Adding a large new page with heavy
   deps (e.g. a spreadsheet grid) should be weighed against that; there is no code-splitting today.
8. **`enabled: false` tabs are the only "coming soon" affordance.** There is no feature-flag system; a
   partially-built client_boq tab would either be fully wired or shown disabled via the `NAV` flag.

---

### One-paragraph orientation for the designer
Everything is a **`Card`** on a light `paper` background inside a single **max-w-6xl** column under a sticky
**`Header`**. Colour is **semantic and reserved** (blue = AI, amber = human gate, green = approved, red =
fatal, violet = database). Numbers/codes are **mono**. A gated multi-step flow uses the left-rail **`Stepper`**
+ per-step content with **`advance`/`invalidateAfter`** keeping gates honest; approvals happen in a centered
**`Modal`**; record detail slides in as a **`Drawer`**; long jobs use the **`useIngestJob` + poll** pattern
with a floating indicator. Build client_boq screens from these primitives and they will look native.
