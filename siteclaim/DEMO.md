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

## The three scenarios (one selector on the first screen)

| Scenario | Trade | What it shows |
| --- | --- | --- |
| **Clean** | Joinery & fitting-out | A shortlist of strong firms, a clean leveling with no corrections, a confident recommendation (Artisan Interior, F-JF-01). |
| **Hero** | Electrical | The cheapest, best-matching bidder — *Subcontractor E (illustrative)*, F-EL-01 — looks clean on the bid sheet but the cross-reference flags an **active winding-up petition** and **two safety prosecutions**. Recommended against despite the lowest price; the clean runner-up Vantage E&M (F-EL-02) wins. |
| **Messy** | Electrical | A reply hides an understated line, an **unpriced provisional sum**, and an **exclusion**; leveling corrects the total (+HK$2.0m) and the cheapest *clean* bid changes to F-EL-02. |

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

## The one principle

The LLM reads, splits, composes, and explains. The deterministic rules engine
computes and checks (arithmetic, risk flags, ranking). The proprietary fused
database makes the recommendation defensible. **The LLM never invents a number, a
risk flag, or a ranking** — and the data it cross-references is what a generic
chatbot cannot reach.

> The seed data is synthetic and illustrative; the named cautionary firm is
> fictional. The award is always a human decision.
