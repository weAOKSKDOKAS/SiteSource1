# Stage 02 — Validate (Layer 1: Rules Engine)

## Inputs

- `ExtractedFacts` (`schemas.models`) — the output of Stage 01.
- `rules_engine.sopo_config` — all statutory constants (and `rules_engine.business_days` for day arithmetic).
- Layer 3 reference (read-only): `references/sopo_ordinance/overview.md`.

## Process

The deterministic Rules Engine (pure Python, no ML) runs every statutory check
against the facts — mandatory particulars (SOPO s.18: claim in writing,
identifies the work, states amount & basis), threshold applicability for the
contract type, and reference-date sanity — grading each as fatal, warning, or
info. It then computes every live deadline (payment response, payment due,
adjudication windows), counting in CALENDAR or WORKING days as each section
requires (via `business_days`, which supports both the adjudication and Part 4
working-day definitions). **This is where legal correctness lives.**

## Outputs

- `ValidityReport` (a list of `Check`) and `DeadlineSet` (a list of `Deadline`),
  both from `schemas.models`. A fatal check here blocks Stage 03.
