# SiteSource — Live Engine Build Plan

> Working reference for the build sessions that turn SiteSource from a demo into a
> live engine. Written in English to sit alongside `CLAUDE.md` and `CONTEXT.md` and
> to be read by Claude Code. Drop it at repo root as `BUILD_PLAN.md`.
>
> Status: framework agreed. Phase B (shortlist decouple) landed and verified. The
> rest of this doc is the plan for the remaining work.

---

## 0. The one idea to hold onto

The pitched flow (document in → AI reads and splits → send to subcontractors → replies
come back → auto Excel comparison) is two different kinds of work wearing one coat.

- **The engine** is the pipeline plumbing: read, split, route, dispatch, parse, level,
  export. It is real, mostly already coded in the live path, and it is commodity. Two
  falsifiable evals proved a well-prompted chatbot matches it on reading, splitting,
  parsing and leveling. Building it gives a working product with real time savings for
  a procurement team, and it earns a pilot. It does not, on its own, defend against a
  competitor.
- **The moat** is the risk cross-reference applied at award time against a fused data
  asset a generic chatbot cannot reach. It is the defensible piece, and it is a
  data-acquisition problem before it is a coding one.

Why build the commodity engine anyway: it is the wedge that unlocks the moat data. No
main contractor hands over its closeout archive on the strength of a slide. It hands it
over after seeing a working tool save its buying team real hours. So the engine is a
prerequisite for the archive, and the archive is the durable asset.

Design rule that follows from this: every hour of build effort is checked against
"does this deepen the data asset or the assembly at decision time, or is it plumbing?"
Plumbing gets built to be correct and boring; the data asset gets the care.

---

## 1. Verified current state of the code

Numbers below are read from the actual build (the `NOVA-main` tree and the committed
`sitesource.db`), not from memory. Re-verify before quoting anywhere public.

| Thing | Value | Real or illustrative |
| --- | --- | --- |
| Firms in `sitesource.db` | 156 | 140 real + 16 illustrative |
| Real public-record firms | 140 | 134 building-trade + 6 ground-investigation (v2); real HK gov sources |
| Flagged real firms | 46 | 11 debarment, 36 safety-prosecution, 1 winding-up |
| Illustrative demo firms | 16 | `F-EL-01`…`F-JF-03`, fabricated |
| EOS closeout records | 16 | All attached to the 16 illustrative firms, fabricated |
| Trade pricing rows | seed set | Illustrative (`PX:` references are invented) |
| Backend tests | 92 pass, 1 skip | Verified in this build (memory's 122 is stale) |

What is genuinely real and working in the live path (behind `DEMO_MODE`):

- Document vision ingest (`pipeline/documents.py`, PDF → base64 PNG).
- Scope split by trade (`stage_01_ingest`, LLM read + Layer-1 taxonomy check).
- Reply parsing from a returned Schedule of Rates (`stage_04_level.parse_bid_reply`).
- Leveling arithmetic and Excel export (`rules_engine/leveling.py`, `export_xlsx.py`).
- The LLM client has a real Anthropic path and a real DeepSeek path, lazily imported.

What makes it a demo rather than an engine, and nothing more than these three:

1. `DEMO_MODE` short-circuits every LLM call to a baked fixture.
2. The risk data has a fabricated layer (the 16 EOS records) and an un-refreshable one
   (the 134 public records were assembled once, with no live scraper).
3. Dispatch is a mock outbox (a JSON file), and there is no inbound channel for replies.

---

## 2. The pitched flow mapped to code reality

| # | Pitched step | Code status | Where |
| --- | --- | --- | --- |
| 1 | AI reads uploaded document | Live path exists | `documents.py` + `stage_01_ingest` |
| 2 | AI splits into sections per trade | Live path exists | `stage_01_ingest` → `ScopePackages` |
| 3 | Send relevant bundle to each subcontractor | Mock only; no real email, no attachments, no contacts | `stage_03_dispatch` + `db/outbox.py` |
| 4 | Subcontractor replies with BQ, parsed | Parser exists; no inbound channel | `stage_04_level.parse_bid_reply` |
| 5 | Auto Excel comparison | Exists | `stage_04_level/export_xlsx.py` |

Steps 1, 2, 4 and 5 are coded in the live path and need `DEMO_MODE` off plus an API
key. The real gaps are step 3 (real send with real attachments to real contacts) and
the inbound side of step 4 (catching the reply). The shortlist and the data problem sit
between step 2 and step 3, and Phase B addresses the structural half of that.

---

## 3. The structural trap, and the fix that landed (Phase B)

The trap. The shortlist only draws from firms that carry an assessable EOS closeout
record (`store.shortlistable_firms_for_trade`, called inside `cross_reference`). Every
EOS record belongs to one of the 16 illustrative firms. The 134 real firms are the
coverage pool and are never shortlisted. So deleting the fabricated data empties the
shortlist: the real firms have no closeout record, and the only firms that have one are
the fakes about to be removed. The demo hero (the one screen where the data changes a
decision) runs live through `cross_reference`, so it is exposed to any change here.

The fix (done and verified). `cross_reference` now takes `include_public`.

- `include_public=False` (default) keeps the assessed-firm behaviour. The demo
  scenarios rely on this, so it stays the default and the hero catch is untouched.
- `include_public=True` opens the shortlist to the full screened pool for the trade
  (`store.firms_for_trade`). Every registered firm is a candidate, ordered by the
  public risk screen: fatal-flagged firms demoted last by ranking, and among clean
  firms the spotless ones ahead of those carrying a warning. The closeout semantic
  match stays a soft enrichment feature and is 0 for a firm with no closeout history.

Threaded through `stage_02_shortlist.shortlist(..., include_public=...)` and the
`/shortlist` endpoint (`ShortlistRequest.include_public`, default `False`). Five new
tests in `db/tests/test_cross_reference_public.py`; full suite 92 pass / 1 skip.

Verified effect on the electrical trade, committed DB:

- Default mode: 4 illustrative firms, `F-EL-02` on top, `F-EL-01` demoted last (fatal).
- Public mode: 33 firms, 29 of them real (was 0), flagged firms demoted, spotless first.

What this buys, and the boundary it draws. Phase B makes the engine able to shortlist
real firms. It does not clean the data. Removing the 16 fabricated firms and their EOS
records is a separate data step (see Phase C). The mode flag is what lets those two
happen independently: the demo can keep its illustrative firms via the default mode,
while the live engine runs public mode against a clean database. Practically that means
two seed profiles rather than one shared database (spec in Phase C).

---

## 4. Architecture: the brain and the nervous system

> **Update (landed):** n8n was REMOVED. It was the transport on both email directions
> and failed repeatedly in production (ConnectionRefused with n8n down, weekly OAuth
> expiry in Testing mode, the trigger silently not firing) while requiring a second
> always-on process. The backend now talks to the Gmail API directly:
> `pipeline/gmail_client.py` (OAuth + drafts), `/dispatch/drafts` (one Gmail DRAFT per
> enquiry — the human gate holds), and `pipeline/reply_poller.py` (a background poller
> feeding the same processing path as `/inbound-reply`, idempotent on the Gmail message
> id). See `siteclaim/docs/EMAIL_SETUP.md`. The section below is kept as the original
> design discussion.

Silver asked about n8n. It helps, in specific places. The division below keeps the
intelligence testable and version-controlled and uses n8n only for glue.

The brain — FastAPI + the pipeline (stays in Python, stays typed, stays tested):

- read / classify / split / route documents (`stage_01`)
- shortlist cross-reference and risk screen (`stage_02`, `rules_engine`, `db`)
- bundle assembly and per-trade SoR sheet (`stage_03`)
- reply parse, leveling, Excel export (`stage_04`)
- risk-adjusted recommendation (`stage_05`)

The nervous system — n8n (triggers, transport, connectors, notifications):

- dispatch send: SMTP or Gmail node emails each bundle with its attachments
- inbound capture: IMAP or Gmail trigger catches a subcontractor reply, pulls the
  attachment, and POSTs it to `/level`
- scheduled refresh: a cron trigger hits the public sources and POSTs new records to a
  DB refresh endpoint (Phase C)
- human notifications: approval requests and "reply received" pings

The rule of thumb. A decision or a computation is Python; a trigger, a transport or a
connector can be n8n. n8n calls the brain's endpoints and never reimplements them. If
scope-splitting logic starts living in n8n nodes, it loses its tests and its place in
the architecture, so that line holds.

Cost note. n8n is one more service to run or host. It earns that for email I/O and
scheduling, since it removes hand-written IMAP polling and attachment handling. If the
MVP would rather not run another service, Python's own email libraries or an email API
(Postmark, Resend) can send and receive; the inbound-email-triggers-pipeline flow is
simply cleaner in n8n.

---

## 5. Document routing and attachments (the feature Silver specified)

Requirement: on upload, the AI reads and splits each section by itself, and each
subcontractor email carries only the relevant files so they know what to price.

Current state. `bundle_doc_refs` is a list of text labels, not real files. So the email
names documents but attaches nothing. This feature has to be built from there, and
`bundle_doc_refs` becomes real file paths or attachment objects (a small schema change
on `DispatchBundle`).

Design.

1. Classify. The AI tags each document or section as general (every trade needs it:
   form of tender, conditions, general preliminaries) or trade-specific (which trade:
   particular spec, SoR, drawings for that trade). This extends `stage_01` and produces
   a document-to-trade routing map.
2. Per-trade SoR sheet. The pipeline already extracts `sor_items` per trade in
   `ScopePackages`. Generate a clean per-trade sheet of the priceable items, which is
   the thing the subcontractor fills in.
3. Assemble the bundle. For each trade: general documents (whole) + that trade's
   specific documents (whole) + the generated SoR sheet.
4. Human review (Layer 4). The operator sees the proposed routing and adjusts before
   send. This gate already exists as approve-before-dispatch.
5. Dispatch. Email with real attachments through the n8n send node or Python email.

The risk to respect. Slicing pages out of a single combined tender PDF and sending a
subcontractor a partial legal document is contractually dangerous: a dropped clause or
a broken cross-reference means they price against an incomplete document, and any
resulting difference lands back on the main contractor. So the safe pattern:

- Prefer routing whole relevant files. Real tenders usually arrive as a set of files
  per discipline, so most cases are covered by choosing which files go to which trade.
- The generated SoR sheet is labelled an excerpt, with the full package available on
  request. It is a derived summary that sits beside the real documents.
- If a combined PDF must be split, do page-range routing behind mandatory human review;
  silent auto-slicing of legal text is off the table.

---

## 6. Build phases

Order is chosen so the engine can shortlist real firms before the fabricated data is
removed, and so the plumbing is correct before the data asset is deepened.

### Phase A — Engine live (plumbing, the enabler)

Goal: the pipeline runs end to end on real data, not fixtures.

- Turn off `DEMO_MODE` on the live path and wire the API key. Confirm a real tender PDF
  reads, splits and returns `ScopePackages`.
- Real email out (SMTP or email API, or the n8n send node) with real attachments.
- Address book of subcontractor contacts (a table keyed by firm and trade).
- Inbound channel: email intake (n8n IMAP/Gmail trigger → `/level`) or, for the first
  cut, a file-upload endpoint the operator uses to drop replies in.

Eval first: not needed. The two prior evals already cover read/split/parse/level. This
is plumbing, built to be correct.

### Phase B — Decouple shortlist from the EOS gate (DONE)

Goal: the engine can shortlist real firms on real public signals. Delivered in
section 3. Closeout is now enrichment, not a gate.

### Phase C — Real public data, made refreshable and clean

Goal: the 134/46 becomes data that can be refreshed, and the live database holds only
real firms.

- Two seed profiles. `seed --profile demo` builds the current 150-firm database (real +
  illustrative) for pitching. `seed --profile live` builds a clean 134-firm database
  for the live engine. This is what lets the false data be removed from the live path
  without breaking the demo.
- A refresh routine per source (DEVB approved lists, Labour Department prosecutions,
  Companies Registry winding-up), driven by an n8n cron trigger into a DB refresh
  endpoint. Start semi-automated; a human confirms new flags before they land.
- Fix the debarment links that point at generic index pages rather than specific
  records (deep-link or drop them).

Honesty note for the pitch: everything in this layer is public, so it is the correct
floor of coverage and not the moat. Say so plainly.

### Phase D — The moat: partner-contractor archive (a BD track)

Goal: the EOS/closeout layer becomes real. This is business development, not a coding
sprint. What the code needs ready is the data contract in section 7, so that the day a
partner says yes, ingestion is a script rather than a project. VSL is the named target,
and the drainage tender (GE/2026/14) already sits in their world, which is the way in.

---

## 7. Partner-archive data contract (prepare now, ingest later)

The one non-public risk category is operational performance: delay, rework, defects,
closeout slippage, claims behaviour. It is what the EOS layer captures and the only part
of the design a competitor cannot assemble from public sources. To turn a partner's
archive into that layer, ask for these fields per past subcontract:

- firm identity (name, and BR number if available, for entity resolution)
- trade and project name
- contract value and final account value
- planned completion date and actual completion date (the slippage)
- rework or defect notes, and any liquidated-damages or claims history
- a short closeout narrative if one exists (the text the semantic match runs on)

Format: a spreadsheet export is enough for the first partner. Ingestion maps these to
`project_closeouts` and, where narrative text exists, to a fresh closeout embedding.
Once present, the same `cross_reference` uses the match as enrichment automatically, so
no new stage is needed.

---

## 8. Eval-first discipline

The rule: run a chatbot-substitution eval on any core claim before building on it.

- Read a real HK tender and split scope: already evalled, commodity. Do not invest
  defensibility here; build it to be reliable.
- Parse a returned BQ and level it: already evalled, commodity. Same.
- The one eval that comes out in our favour is the risk cross-reference, because a
  chatbot has no access to the fused data. That is the screen to protect and deepen.

So new build effort earns an eval only when it claims a defensibility advantage. Plumbing
does not; the data asset does.

---

## 9. Operational notes

Run (Windows, from memory of the working setup):

- Backend: `cd siteclaim\backend`, `$env:DEMO_MODE="true"`, `uvicorn api:app --port 8000`.
- Frontend: `cd siteclaim\frontend`, `npm run dev`, open `localhost:5173`.
- Re-seed if needed: `python -m db.seed` (current profile keeps 134/46 + 16 illustrative).
- Imports are rooted at `backend/` (`from pipeline...`, `from db...`), never
  `from backend.pipeline...`.

The shortlist mode. Default is assessed-firm (`include_public=False`), which is what the
demo and any pitch run uses. The live engine sets `include_public=True` on `/shortlist`.
Point the live engine at the clean `live` seed profile once Phase C splits the profiles.

First user. Internal-first: Silver operates the engine on a real tender. Real-send and
the address book move up in priority only when a pilot contractor (VSL) is lined up.

Constraints that still hold from the deck work: illustrative firms never count in the
134/46 figures; the cautionary firm in any scenario stays fictional; human approval of
the final award is always disclosed.

---

## 10. Done, and the next three tasks

Done so far:

- Phase B shortlist decouple, verified, demo preserved (section 3).
- Phase A engine-live plumbing. All behind the existing gates, all offline-safe
  (DEMO_MODE and a dry-run both keep every path off the network):
  - Real routed attachments (section 5): `DispatchBundle.attachments`
    (`BundleAttachment`), whole-file routing (general vs trade-specific via
    `TenderDocument.trades`), and a generated per-trade SoR sheet labelled an excerpt
    (`stage_03_dispatch/attachments.py`). `bundle_doc_refs` keeps its old behaviour.
  - Real email send (`stage_03_dispatch/mailer.py`): stdlib SMTP, gated three ways
    (off in DEMO_MODE, off on `dry_run`, off unless `SMTP_HOST` is set), falling back
    to the mock outbox otherwise; a firm with no address-book contact is marked
    `send_failed`, never silently dropped.
  - Address book: a `contacts` table keyed by (firm, trade), `store.contact_for` /
    `store.all_contacts`, `GET /contacts`, seeded with illustrative contacts.
  - Live tender uploads persisted to a per-tender `Workspace` so dispatch can attach
    the real originals; inbound reply upload at `POST /level-upload`.
  - Model override (`ANTHROPIC_MODEL`) and a documented `.env.example`.
- Phase C real-data work. Public, refreshable, and clean:
  - Seed profile split: `python -m db.seed --profile {demo,live}`. `demo` (default,
    unchanged) is the 150-firm pitch DB; `live` is the clean 134 real-firm DB (no
    illustrative firms, EOS, pricing, or contacts), built to `sitesource_live.db`.
    `store.get_connection` honours `SITESOURCE_DB` so the live engine opens the clean
    DB with no code change. Coverage stays 134/46 in both.
  - Refreshable public data (`db/refresh.py`, `POST /refresh/{stage,pending,confirm,reject}`):
    an operator/n8n POSTs new public records; they stage to `staged_firms`/`staged_flags`
    and only land after a human confirm. Idempotent (fingerprint dedupe), provenance
    forced to `public_register`, and gated off in DEMO_MODE. No live scraper is built.
  - Debarment links cleaned: the 2 debarment flags that pointed at the generic DEVB
    search index are de-linked (reference blanked, source annotated); no fabricated
    deep link, the 11-debarment / 46-flagged figures unchanged.
- Phase D code-ready (`db/ingest_closeouts.py`): a partner-archive closeout ingest
  script (CSV/JSON) that resolves each record to a firm (BR, else name, else a new
  `partner_archive` firm), writes `project_closeouts` (+ award history, delayed→warning),
  and bakes a closeout embedding in the DB's own embed space — so `cross_reference`
  uses it as enrichment automatically. Partner firms never inflate the 134/46 figures.

Immediate next, in order:

1. Phase D BD track: land a partner-contractor archive (VSL) and run the ingest script
   against a real closeout export — the moat becomes real (this is business development,
   the code is ready).
2. Phase A hardening once a pilot is lined up: n8n IMAP/Gmail inbound trigger into
   `/level-upload`, real subcontractor contacts in the address book, and a live SMTP
   run against a real tender.
3. Phase C automation: an n8n cron per public source (DEVB, Labour Department, Companies
   Registry) feeding `POST /refresh/stage`, with the human confirm at `/refresh/pending`.

Anything that adds a defensibility claim gets an eval before it gets built.
