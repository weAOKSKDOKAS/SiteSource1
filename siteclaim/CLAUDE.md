# CLAUDE.md — SiteClaim (Layer 0 orientation)

> Re-read this file first to orient. It is the map; the folders are the
> architecture. Coordination lives in the filesystem, not in a framework.

## What SiteClaim is

SiteClaim is a **SOPO-compliant payment-claim drafting copilot** for Hong Kong
construction subcontractors. SOPO = the **Construction Industry Security of
Payment Ordinance (Cap. 652)**. A subcontractor uploads messy evidence (invoices, site
records, emails, the contract) and SiteClaim helps them produce a payment claim
that is valid under the Ordinance, and tells them the statutory deadlines that
follow from serving it.

It is built as an **ICM (Interpretable Context Methodology) workspace**: the
folder structure *is* the architecture, and stages hand off **plain typed data**
(the Pydantic models in `backend/schemas/models.py`). There is **no agent
framework** — no LangChain, CrewAI, or AutoGen. The pipeline is a sequence of
numbered stage folders under `backend/pipeline/`.

## The one principle

**The LLM never decides the law; it fills and drafts. The Rules Engine checks.**

If you are ever tempted to have Claude judge validity or compute a deadline,
stop — that belongs in Layer 1.

## Four layers

- **Layer 1 — Rules Engine** (`backend/rules_engine/`): pure Python,
  deterministic. **Legal correctness lives here.** Every statutory number is in
  `sopo_config.py`; CALENDAR-vs-WORKING day arithmetic is in `business_days.py`. No ML.
- **Layer 2 — Claude (LLM)**: reads messy input, extracts facts, drafts prose.
  Used in stages 01 and 03 (and an optional self-review in 04).
- **Layer 3 — RAG grounding** over a curated SOPO + CIC corpus in
  `backend/references/`. Stable across runs.
- **Layer 4 — Human-in-the-loop** approval gate (stage 05). Nothing is served on
  a respondent without explicit human sign-off.

## Five-stage pipeline (`backend/pipeline/`)

Each stage folder has a `CONTEXT.md` contract with `## Inputs`, `## Process`,
`## Outputs`. Flow is strictly forward — a stage only reads outputs of earlier
stages.

1. **stage_01_extract** — `SourceMaterial` → `ExtractedFacts` (Layer 2).
2. **stage_02_validate** — `ExtractedFacts` → `ValidityReport` + `DeadlineSet`
   (Layer 1).
3. **stage_03_draft** — facts + reports → `ClaimDraft` (Layer 2, grounded in
   Layer 3).
4. **stage_04_audit** — `ClaimDraft` vs facts → `AuditReport` (Layer 1, optional
   Layer 2 self-review).
5. **stage_05_review** — everything → approved `ClaimDraft` (Layer 4).

A **fatal** `Check` in Stage 02 blocks Stage 03. No claim leaves Stage 05
without human sign-off.

## Where everything lives

| Path | What it is |
| --- | --- |
| `backend/schemas/models.py` | The typed contracts every stage passes. Read this to know the data. |
| `backend/rules_engine/sopo_config.py` | **ALL** statutory parameters, each tagged with a SOPO reference and a SOURCED or `# UNVERIFIED` tier. |
| `backend/rules_engine/business_days.py` | CALENDAR-vs-WORKING day arithmetic for deadlines (the distinction is load-bearing). |
| `backend/rules_engine/tests/` | Smoke tests for Layer 1. |
| `backend/pipeline/stage_NN_*/CONTEXT.md` | Per-stage contract. |
| `backend/references/` | Layer 3 corpus (ordinance overview, CIC templates). |
| `backend/fixtures/` | Serialised stage objects for tests/dev. |
| `backend/api.py` | Thin FastAPI entry point (scaffold). |
| `frontend/` | Empty until Phase 5. |
| `CONTEXT.md` (root) | Pipeline routing in brief. |

## ⚠️ Legal-safety note

Statutory values in `sopo_config.py` are tagged in two tiers: **SOURCED** (from a
secondary law-firm summary, still to be cross-checked against the e-legislation
Cap.652 text) and **`# UNVERIFIED`** (unconfirmed placeholders). All of them must
be validated by a quantity surveyor or construction lawyer before any output is
relied upon. SiteClaim assists drafting; it does not give legal advice.

## Status

**Layer 1 (Rules Engine) is built and tested. Pipeline stages 01–03 are
implemented and run offline end-to-end (`backend/pipeline/run_pipeline.py`):**

- **stage_01_extract** — `SourceMaterial` → `ExtractedFacts` (Layer 2).
- **stage_02_validate** — LLM-as-judge confidence review + deterministic
  `ValidityReport` + `DeadlineSet` (Layer 1).
- **stage_03_draft** — facts + reports → `ClaimDraft` (structured fields +
  `rendered_markdown`); missing/low-confidence fields become flagged
  placeholders, a fatal check prints a "NOT FILEABLE" banner citing Layer 1.

Stages 04 (audit) and 05 (human review) and the `frontend/` are not built yet.
Statutory values in `sopo_config.py` remain SOURCED/UNVERIFIED pending QS/lawyer
sign-off.
