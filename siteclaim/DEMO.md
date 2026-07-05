# SiteSource — demo runbook

Everything runs **offline** (DEMO_MODE): the seeded database and baked fixtures
drive the whole pipeline, so the demo needs no network and reproduces identically
on every run.

## Start it (one command)

```bash
bash scripts/demo.sh          # or:  make demo
```

This seeds the database if needed, starts the API in DEMO_MODE on `:8000`, and
starts the wizard on `:5173`. Open <http://localhost:5173> and pick a scenario.

> First run installs frontend deps. Backend deps: `pip install -r backend/requirements.txt`
> (the demo only needs the standard library + FastAPI; numpy/openpyxl are used by
> a couple of stages, sentence-transformers is **not** needed in DEMO_MODE).

## The scenarios (one selector on the first screen)

| Scenario | Trade(s) | What it shows |
| --- | --- | --- |
| **Golden** | Full walkthrough | The whole product in one confirm-routing. The Kwun Tong 4-package tender splits two ways: **electrical + mechanical & plumbing** to **sublet** (two leveling sections, two awards — the cheapest mechanical bidder carries an **unpaid adjudication**, recommended against despite price) and **fire services + joinery** to **self-perform** (their estimates open with real **rate precedent** from the benchmark corpus, with an *over-ran on rate* warning on one line each). Routing split → per-section sourcing with the risk catch → self-perform estimator with live precedent. |
| **Hero** | Electrical | The cheapest, best-matching bidder — *Subcontractor E (illustrative)*, F-EL-01 — looks clean on the bid sheet but the cross-reference flags an **active winding-up petition** and **two safety prosecutions**. Recommended against despite the lowest price; the clean runner-up Vantage E&M (F-EL-02) wins. |
| **Messy** | Electrical | A reply hides an understated line, an **unpriced provisional sum**, and an **exclusion**; leveling corrects the total (+HK$2.0m) and the cheapest *clean* bid changes to F-EL-02. |
| **Two-trade** | Electrical + M&P | Route both to sublet: two leveling sections and two risk-adjusted awards. The cheapest mechanical bidder carries an unpaid adjudication — recommended against despite price. |

## The five-minute path

1. **Ingest** — pick a scenario; Claude splits the tender into trades.
2. **Shortlist** — ranked firms per trade with cited evidence; the hero trade is
   expanded, and the flagged firm is marked *recommend against* with its citations.
3. **Dispatch** — approve firms (the human gate), send trade-only bundles to the
   mock outbox (nothing leaves the machine).
4. **Level** — corrected totals, scope gaps and exclusions called out; edit a rate
   and recompute; download the Excel.
5. **Recommend** — the risk-adjusted ranking, the bid distribution against the
   historical band, Claude's rationale, and the human award.

## The unified engine — one tender, both tracks

The top nav carries the tender past sourcing into the full engine. Every screen is
offline in DEMO_MODE, and each AI output is a **suggestion a human confirms**.

- **Routing** — after ingest splits the tender, the AI recommends **self-perform vs
  sublet** per package with a rationale and the coverage signal (register firms,
  assessable subcontractors, in-house history). A person decides; the recommendation is
  advisory. Sublet packages go **right** (the sourcing wizard above); self-perform
  packages go **left** (the estimator) and their estimate is seeded on confirm.
- **Estimator** (the left track) — build our own priced tender: the AI drafts the
  scope-of-works and a candidate item skeleton (never a quantity), suggests **rate
  precedent** from the benchmark corpus with **"over-ran on rate" warnings**, checks the
  estimate for **omissions / unit mismatches / scope gaps**, and drafts a **letter of
  offer**. The human prices every line and owns the offer.
- **Benchmark** — for a completed project, the priced tender vs the actual outturn,
  item-matched behind a human confirm gate into variance records. The **EOS field
  report** narrative then explains **why** each line moved: the reason candidate (e.g.
  `standing_time`, `omission_at_tender`) and its supporting sentence sit on the variance
  row; a person confirms the code.
- **Projects** — one view of a run: its packages, each package's track and decision, the
  left-track estimates, and where it sits in the lifecycle (analysed → routed →
  sourcing / estimating → awarded → benchmarked).

### The unified demo run (Projects → "DEMO — Illustrative GI + Fit-out Tender")

One seeded run shows the whole loop offline: an **electrical** package routed *sublet*
(→ sourcing) and a **ground-investigation** package where the AI leaned sublet but the
team **overrode** it to *self-perform* (→ a priced estimate). Open that estimate and the
GI lines light up with rate precedent from the corpus and a **standing-time** rate
warning; the run links to the completed benchmark project whose **EOS narrative** explains
the outturn variance. Ingest → route → estimate + source → benchmark ← EOS, from one seed.

## The one principle

The LLM reads, splits, drafts, and explains. The deterministic rules engine computes and
checks (arithmetic, risk flags, ranking, variance). A proprietary fused database — public
records + private closeout reports — makes the decision defensible. **The LLM never invents
a number, a risk flag, a ranking, a match, or a reason** — and the data it cross-references
is what a generic chatbot cannot reach. The moat is that data applied at the moment of a
decision, never the AI's reasoning.

## Honesty footnotes (kept visible in the pitch)

- Coverage is **140 real public-register firms / 46 flagged** (134 building-trade + 6
  ground-investigation). The illustrative firms — including the named cautionary electrical
  firm — are **present-but-excluded** in the demo profile and **absent** in live.
- The **benchmark, EOS, and estimator-precedent** layers are **illustrative** until a real
  partner archive exists: the demo profile carries a fictional scenario, the live profile
  ships the empty state honestly (`/benchmark/summary` reads zero, rate suggestion reads
  "no corpus yet"). No rate history or rubric entry is fabricated to look fuller.
- The award, every rate, every match, every reason code, and the letter of offer are
  **human decisions**. The AI proposes; a person confirms.
