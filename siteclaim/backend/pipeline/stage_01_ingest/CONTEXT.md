# Stage 01 — Ingest (Layer 2 split, Layer 1 taxonomy check)

## Inputs
- `TenderPackage` — the four tender documents (Method of Measurement, Particular
  Specification, Tender Addendum, Schedule of Rates).

## Process
Layer 2 (Claude) reads the documents and splits the scope into one
`TradeWorkPackage` per trade — a scope summary plus the relevant SoR items and
`source_refs`. It only splits and extracts; it never prices or judges a firm.
Layer 1 validates every returned trade against `references/rubrics/trade_taxonomy.md`
(deterministic; an off-taxonomy trade is mapped to the nearest canonical trade or
flagged). DEMO_MODE reads a baked `ScopePackages` fixture.

## Outputs
- `ScopePackages` — `project_name` + one `TradeWorkPackage` per trade.

## Document classification for per-trade routing (`classify.py`, Layer 2)
On the **live upload path only**, each uploaded document is classified by trade so the
right whole originals reach each subcontractor. `classify_documents` runs one
classification per document from its own first one or two rendered pages, normalises the
returned labels against the taxonomy (unmapped → surfaced + routed general), and writes
the result to `TenderDocument.trades`. Empty `trades` = general (every trade). Whole-file
routing only — no page is ever sliced. `/ingest-upload` returns the scope split **and**
the tagged tender so the client passes the tender to `/dispatch`. In DEMO_MODE the tender
is returned untagged (classification never runs), so the demo scenarios and the hero
catch are untouched.

### Manual live check (not covered by the offline tests)
The offline tests drive classification with a scripted client / fixture. The **live LLM
path** must be verified by hand with a real key over the actual GE/2026/14 files:

```
# manual: live document-classification smoke (real key, DEMO_MODE off)
#   cd siteclaim/backend
#   export ANTHROPIC_API_KEY=...        # a real key
#   unset DEMO_MODE                     # or DEMO_MODE=false
#   uvicorn api:app --port 8000
#   curl -sS -F project_name='GE-2026-14' \
#        -F files=@PS-S07.pdf -F files=@PS-S26.pdf -F files=@Clarification.pdf \
#        -F files=@MoM.pdf   -F files=@SR-01.pdf   http://localhost:8000/ingest-upload | jq '.tender.documents'
# Expect on .tender.documents[].trades:
#   - PS-S07  -> ground_investigation (v2: 'geotechnical' / 'ground investigation' now
#               resolve to the real GI trade; no longer routed general).
#   - PS-S26  -> tree / landscape -> external_works (maps via the existing 'landscap' synonym).
#   - Clarification, MoM, and the combined SR-01 -> [] (general, whole file to everyone).
# Also confirm the GI wiring end to end (live, DEMO off, against sitesource_live.db):
#   - the SR-01 scope split produces a ground_investigation package, and
#   - POST /shortlist {scope, include_public:true} returns the seeded real GI firms
#     (GCE, Chung Shun, Castco, DrilTech, Kin Wing, Intrafor), clean, ordered by the screen.
# Then POST the returned .tender to /dispatch (with scope, approvals) and confirm each
# trade's bundle carries the correct whole originals plus its generated SoR sheet.
```

The live classification is verified by this manual run; the offline tests do **not**
exercise the real LLM path. Keep those two claims separate.
