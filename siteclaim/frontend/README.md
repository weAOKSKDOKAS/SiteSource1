# SiteSource frontend

A 5-step review-gate wizard (React + TypeScript + Vite + Tailwind) over the
SiteSource pipeline: **Ingest → Shortlist → Dispatch → Level → Recommend**. A
person can edit at every gate (approve firms, edit a rate, override the award);
each step calls its own API endpoint with whatever they left, so an edit flows
through the later stages (the ICM review-gate pattern). No backend storage — the
working state lives in React state.

## Run it

Two terminals, from `siteclaim/`:

```bash
# 1) backend (offline demo mode) — from siteclaim/backend
DEMO_MODE=true uvicorn api:app --reload --port 8000

# 2) frontend — from siteclaim/frontend
npm install   # first time only
npm run dev
```

Then open http://localhost:5173 and load the demo tender (Kwun Tong Commercial
Tower — Cat-A office fit-out).

- **Ingest** splits the tender into four trades incl. electrical.
- **Shortlist** ranks firms per trade with cited evidence; the cheapest, strongest-
  matching electrical firm — *Subcontractor E (illustrative)* — is demoted and
  marked **recommend against** for an active winding-up petition and two safety
  prosecutions. This is the hero.
- **Dispatch** approves firms (the human gate) and sends trade-only bundles to a
  mock outbox.
- **Level** corrects an understated bid line and an unpriced provisional sum, which
  changes the ranking; download the Excel comparison.
- **Recommend** recommends the clean runner-up, recommends against the flagged firm
  with cited evidence, shows the bid distribution against the historical band, and
  records the human award.

The API base defaults to `http://localhost:8000`; override with `VITE_API_BASE`.

> SiteSource is decision support. The seed data is synthetic and illustrative; the
> award is always a human decision.
