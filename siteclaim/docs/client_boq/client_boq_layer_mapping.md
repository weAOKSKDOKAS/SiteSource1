# Client→BOQ Workflows — Layer Mapping for SiteSource

How each task in the two workflows (document review, cost estimate) maps to a processing layer, and how that becomes runnable pipeline stages inside the SiteSource product. Companion to `reviewing_a_construction_contract_with_ai.md` (workflow 1) and `estimating_process.md` (workflow 2).

---

## The framing (one collision to resolve first)

Two "layer" vocabularies are in play. They describe the same thing, so this doc uses one unified set of buckets.

- The 60/30/10 triage: Deterministic / Rule-based / AI-judgment.
- SiteSource's four layers: Layer 1 deterministic rules · Layer 2 Claude · Layer 3 database · Layer 4 human gates.

Unified buckets used below:

- Deterministic — code, math, database/table lookups, template fills, file parsing. Reproducible, no drift. (SiteSource Layer 1 + Layer 3.)
- Rule-based — routing and threshold logic with known criteria (section→trade, delivery method, "LD cap > 10% → flag"). Predictable branching. (Also SiteSource Layer 1, separated out here.)
- AI-judgment — reading unstructured documents into structure, drafting scope/reasoning, fuzzy matching, explaining. Draft-only. (SiteSource Layer 2 Claude.)
- Human gate — approval overlay on top of any output. Sits above the three buckets, not inside them. (SiteSource Layer 4.)

The anchor rule, unchanged from the main app: the AI never writes a decision value. Every number, verdict, match confirmation, risk flag, route, or price is produced by deterministic math or a rule, then confirmed at a human gate. AI proposes and drafts; it never decides.

60/30/10 is not a headcount here. A document-reasoning product runs a lot of reading and drafting through AI, so by task count the AI bucket looks larger than 10%. What stays at 0% AI is decision authority. That is the number that matters.

---

## Workflow 1 — Document Review

Goal restated for the product: ingest the client's document set, check it against the criteria library, and produce an alignment/departure register a human approves. The register's verdict is the decision value.

| # | Task | Bucket | What actually runs it | Decision value? |
|---|------|--------|----------------------|-----------------|
| 1a | Extract text from client PDFs | Deterministic | pymupdf | no |
| 1b | OCR scanned pages | Deterministic | Tesseract | no |
| 1c | Read documents into structured items (clauses, scope lines, refs) | AI | llm_client → JSON (text→DeepSeek, image→Claude) | no — reading, not deciding |
| 2 | Summarise project docs → commercial-risk summary | AI | LLM draft, human-reviewed | no — draft |
| 3 | Load acceptable-terms / criteria library | Deterministic | file/table load | no |
| 4 | Load departure-register template | Deterministic | file load | no |
| 5a | Match each contract clause ↔ criteria entry (semantic) | AI | LLM proposes candidate match | no — proposal |
| 5b | Verdict: does the clause breach the acceptable position? | Rule-based | numeric threshold vs criteria (e.g. LD cap %, retention %, notice days) | yes → rule, then human |
| 5c | Draft departure wording + rationale | AI | LLM draft | no — draft |
| 6 | Scope alignment: contract scope vs priced scope (gaps, silent assumptions, responsibility creep) | AI proposes / Rule confirms | LLM flags candidates; order-of-precedence is a defined hierarchy (rule) | verdict → human gate |
| 7 | Program check: unrealistic durations, mobilisations, milestones on critical path, LD exposure | AI proposes / Deterministic where structured | LLM flags candidates; critical-path + LD recompute = math | flag → rule; verdict → human |
| 8 | Cash-flow profile from payment terms + program | Deterministic | math / spreadsheet | numbers deterministic |
| 9 | Assemble alignment/departure register into template | Deterministic | template fill | no |
| 10 | Verify every clause citation exists and matches the source | Deterministic | index/locus lookup against parsed doc | no — anti-hallucination guard |
| 11 | Approve register (aligns / departs) | Human gate | user in browser | the verdict |

Note on task 10: this is the citation-check idea from the review doc, moved from an external tool into the product as a deterministic lookup. The parsed document is already in structured form from task 1, so confirming "clause 9.9 exists and says what the register claims" is a lookup, not something the AI is trusted to self-check.

---

## Workflow 2 — Cost Estimate

Goal restated for the product: from the same document context, build up a cost and read profitability. Price and the profitable/not verdict are decision values. This is largely the left-track Estimator concept the main app already carries (currently corpus-gated).

| # | Task | Bucket | What actually runs it | Decision value? |
|---|------|--------|----------------------|-----------------|
| 1 | Tender & scope review: inclusions, exclusions, ambiguities, conflicts | AI | LLM draft, human-reviewed | no — draft |
| 2 | Generate clarifying questions + assumptions | AI | LLM draft | no — draft |
| 3 | Break scope into activities / pricing-schedule structure | AI proposes / Deterministic holds | LLM drafts breakdown; schedule is a data structure | structure → human-confirmed |
| 4 | Classify direct vs indirect | Rule-based | known categories; fuzzy ones AI-suggested | route → rule |
| 5 | Decide delivery method (self-perform / sublet / SoR / hybrid) | Rule-based + Human | routing + human choice | decision → human |
| 6 | Break activity into resources (labour / plant / materials / subcontract) | AI proposes | LLM drafts resource list | no — draft |
| 7a | Read quantities from BOQ | Deterministic | parse BOQ | no |
| 7b | Take-off quantities from drawings (no BOQ) | Human (AI-assisted) | human measures; AI may assist | quantity → human |
| 8 | Apply productivity → labour hours, crew size, duration | Deterministic | math (qty ÷ productivity) | numbers deterministic |
| 9 | Rate lookup (labour / plant / material / subcontract rates) | Deterministic | rates table / corpus / market-rate source | rates are data |
| 10 | Quantities × rates = cost | Deterministic | math / spreadsheet | price — deterministic, never AI |
| 11 | Indirect costs & allowances | Deterministic | formula (duration × rate, % × value) | numbers deterministic |
| 12 | Estimate validation: scope coverage, quantity sense, rate benchmarking | Rule-based flags | threshold checks vs benchmark bands | flags → rule; verdict → human |
| 13 | Profitability: cost + margin vs budget / competitive price | Deterministic + Human gate | math, then human | profitable/not — math + human |
| 14 | Draft letter of offer / qualifications | AI | LLM draft; price and terms pulled from the estimate | no — draft |

---

## The decision values (the tasks that must never touch AI)

Pulled out so they are unmissable in the build. Each is deterministic or rule-based, then human-gated.

- Does a clause breach our position (review) — numeric threshold vs criteria, then human.
- Aligns / departs verdict on the register (review) — human gate over rule outputs.
- Every quantity × rate cost line (estimate) — spreadsheet math.
- Indirects and allowances (estimate) — formula.
- Profitable / not (estimate) — math, then human.
- Any clause citation in the register — deterministic lookup, not AI self-report.

AI's entire job across both workflows: turn documents into structured data, propose candidate matches and gaps, and draft prose (summaries, rationale, clarifying questions, the offer letter). All draft, all human-reviewed, none of it authoritative.

---

## The database question, resolved

Neither new workflow depends on the procurement contact database. What each needs instead:

- Review needs the criteria library (a data file or table — the same shape as the acceptable-terms tables in the review doc: category → check → acceptable position → red flag) plus the parsed-document store.
- Estimate needs a rates source — a rates table holding labour/plant/material/subcontract and productivity rates. This is the pricing / market-conditions data you intuited earlier; it is the estimate's "database," and it is separate from contractor contacts. For a simple first version this can be a seeded rates table or manual rate entry, since the main app's Estimator corpus is still empty.

So the earlier worry ("is the DB even there, and isn't review about market rates not contacts?") is correct and it is fine: you are not reusing the procurement DB, you are adding two small new data sources.

---

## How this becomes runnable stages in SiteSource

Same pattern as the procurement pipeline: numbered stages, heavy work in sync background jobs, human gates as browser approval steps, LLM reached by API only where the bucket says AI. The dev-time map (CONTEXT.md, routing rows) is separate from this and just helps Claude Code navigate.

```
backend/client_boq/
├── CONTEXT.md                     # dev map: which stage is which bucket
├── reference/                     # the 2 workflow docs + criteria MD
├── review/
│   ├── 01_ingest.py               # Deterministic (pymupdf/Tesseract) + AI (structure)
│   ├── 02_context_summary.py      # AI draft
│   ├── 03_criteria_match.py       # AI propose → Rule confirm
│   ├── 04_scope_align.py          # AI propose → Rule (precedence)
│   ├── 05_program_check.py        # AI propose → Deterministic (CPM/LD)
│   ├── 06_cashflow.py             # Deterministic
│   ├── 07_register_assemble.py    # Deterministic (template fill)
│   └── 08_citation_verify.py      # Deterministic (lookup guard)
├── estimate/
│   ├── 01_scope_review.py         # AI draft
│   ├── 02_schedule.py             # AI propose → Deterministic structure
│   ├── 03_cost_buildup.py         # Deterministic (qty × rate)
│   ├── 04_indirects.py            # Deterministic
│   ├── 05_validate.py             # Rule-based flags
│   └── 06_offer.py                # AI draft
├── rates.py / rates table         # estimate rate source
├── criteria_loader.py             # loads the pluggable criteria file
├── models.py                      # new pydantic + DB tables (prefixed, no collision)
└── router.py                      # new /client-boq routes + human-gate endpoints
```

Rules carried over from the main app, applied here:

- Heavy stages (ingest, cost build-up) are sync def background jobs, never async def.
- The DEMO path stays fully offline — the AI stages have a DEMO fixture path with no network call.
- No referenced criterion or spec is silently dropped — if a criterion cannot be resolved against the documents, stage 03/04 flags it, it does not skip.
- Each human gate is an explicit approval endpoint; nothing commits without it.

---

## Judgment calls to confirm before the build prompt

Four decisions that change the stages. My recommendation on each; correct any against how you actually work.

1. Quantity take-off with no BOQ (estimate 7b). Recommend: human-measured for v1, AI only assists. Drawing take-off is exactly where AI is least reliable, and it feeds the price. Do not automate it yet.

2. Rate source (estimate 9). Recommend: a seeded rates table with manual override for v1, rather than waiting on the corpus. It unblocks the estimate without the empty Estimator corpus.

3. Criteria breach verdict (review 5b). Recommend: pure threshold rule where the criterion is numeric (LD %, retention %, notice days, liability cap), and a human gate for qualitative criteria the rule cannot judge. Keep AI out of the verdict either way.

4. Do the two workflows chain? Recommend for simple-first: independent, sharing only the parsed-document context. Review produces its register; estimate runs on the same documents. The review's flags feeding the estimate is a later enhancement, not v1.

Once these are set, the next artifact is the Phase 1 (review) build prompt for Claude Code, grounded against the real branch structure.
