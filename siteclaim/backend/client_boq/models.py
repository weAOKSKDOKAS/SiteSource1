"""Typed contracts for the client_boq module (pydantic) + the module's own DB tables.

Two things live here:

1. **Pydantic schemas** — the plain-data handoffs between the review and estimate
   stages, mirroring the main app's ``schemas/models.py`` discipline (a stage reads
   and writes typed models, no shared mutable state). Every AI stage's ``target_model``
   is one of these, so ``llm_client.complete_json`` validates the model's JSON output
   against a strict schema (the consistency mechanism, in place of a temperature knob).

2. **The module's own SQLite tables** (``client_boq_*``) — created lazily with
   ``CREATE TABLE IF NOT EXISTS`` from :func:`init_tables`, over a connection from the
   shared ``db.store.get_connection`` (which honours ``SITESOURCE_DB``). This keeps the
   module self-contained: ``db/schema.sql`` and ``db/seed.py`` are never touched, and no
   existing table is altered. The tables hold the durable state the workflows need —
   the parsed-document set, the approved departure register (the review→estimate gate),
   and the estimate — nothing the procurement pipeline knows about.

SCAFFOLD NOTE: schemas here are intentionally lean (the fields each stage is expected to
produce). Stage bodies are not implemented yet; fields will be tightened as the review
and estimate logic lands. No workflow logic lives in this file.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from pydantic import BaseModel, Field

# A raw uploaded file as the module receives it, matching the main app's ingest tuple
# shape ``(filename, content_type, bytes)`` so ``pipeline.documents.extract_document``
# can be reused unchanged.
RawUpload = tuple[str, Optional[str], bytes]


# ===========================================================================
# Criteria library (input to REVIEW s03) — produced by criteria_loader.py
# ===========================================================================
class Criterion(BaseModel):
    """One acceptable-terms row from ``review_criteria.md``. ``is_placeholder`` is True for the
    empty ``OK-01`` extension row (no acceptable position yet) — loaded, never silently dropped."""

    id: str                       # e.g. "TP-04"
    category_id: str              # prefix, e.g. "TP"
    category: str                 # "Time & Progress"
    clause_area: str
    acceptable_position: str = ""
    why_it_matters: str = ""
    red_flag: str = ""
    is_placeholder: bool = False


class ThresholdRule(BaseModel):
    """A numerically-checkable red flag from the 'Deterministic threshold checks' table — the ONLY
    rows the rule layer pre-flags. The rule raises the flag; the human still confirms the departure."""

    id: str                       # references a Criterion.id, e.g. "TP-04"
    rule: str                     # human-readable predicate, e.g. "LD cap absent, or LD cap > 10%"
    extract_field: str            # the field the AI must extract from the contract to evaluate it


class CriteriaLibrary(BaseModel):
    """The parsed criteria library. ``criteria`` are the populated acceptable-terms rows;
    ``placeholders`` holds empty extension rows (OK-01); ``threshold_rules`` is the numeric subset."""

    criteria: list[Criterion] = Field(default_factory=list)
    placeholders: list[Criterion] = Field(default_factory=list)
    threshold_rules: list[ThresholdRule] = Field(default_factory=list)

    def category_ids(self) -> set[str]:
        return {c.category_id for c in self.criteria}


# ===========================================================================
# Rates (input to ESTIMATE s03) — produced by rates.py
# ===========================================================================
class RateRow(BaseModel):
    """One hand-editable rate from ``client_boq/data/rates.csv``. Category is one of
    labour / plant / material / subcontract / productivity."""

    rate_id: str
    category: str
    code: str
    description: str = ""
    unit: str = ""
    rate: float = 0.0
    currency: str = ""
    source: str = ""
    notes: str = ""


# ===========================================================================
# REVIEW workflow handoffs
# ===========================================================================
class ClauseItem(BaseModel):
    """One structured item read out of the document set — a contract clause or scope line."""

    ref: str = ""                 # clause reference as printed, e.g. "9.9"
    text: str = ""
    source_doc: str = ""
    page: Optional[int] = None


class ParsedDocumentSet(BaseModel):
    """REVIEW s01 output, and the shared parsed-document store the estimate reads too."""

    set_id: str = ""
    name: str = ""
    slug: str = ""
    clauses: list[ClauseItem] = Field(default_factory=list)


class ContextSummary(BaseModel):
    """REVIEW s02 — a compact commercial-risk summary (AI draft, human-reviewed)."""

    summary: str = ""
    scope_responsibilities: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)


class DepartureItem(BaseModel):
    """One register line. The AI proposes ``criterion_id``/``rationale``/``proposed_position`` and
    extracts ``extracted_value``; the rule layer may set ``rule_flagged``; the ``verdict`` is ALWAYS a
    human gate — never AI-written (starts ``unreviewed``)."""

    item: int = 0
    clause: str = ""
    criterion_id: str = ""            # AI-proposed match
    extracted_value: str = ""         # AI-extracted field (for threshold rows)
    rule_flagged: bool = False        # deterministic pre-flag (numeric criteria only)
    amendment_proposal: str = ""      # AI draft
    rationale: str = ""               # AI draft
    verdict: str = "unreviewed"       # unreviewed | departs | aligns — HUMAN gate only
    status: str = "open"              # open | closed


class DepartureRegister(BaseModel):
    """REVIEW s07 assembled register — the workflow's decision surface. ``approved`` is the
    review→estimate gate; the estimate refuses to run until a human sets it True (s07/router)."""

    set_id: str = ""
    project: str = ""
    items: list[DepartureItem] = Field(default_factory=list)
    approved: bool = False


class ScopeAlignmentFinding(BaseModel):
    """REVIEW s04 — a scope gap / silent assumption / responsibility-creep candidate (AI proposes,
    precedence rule confirms)."""

    kind: str = ""                    # gap | silent_assumption | responsibility_creep | precedence
    description: str = ""
    contract_ref: str = ""
    priced: Optional[bool] = None


class ProgramFinding(BaseModel):
    """REVIEW s05 — a program/constructability risk (AI proposes; durations / LD exposure recomputed
    deterministically)."""

    kind: str = ""                    # duration | sequencing | mobilisation | milestone | ld_exposure
    description: str = ""
    recomputed_value: str = ""


class CashflowPoint(BaseModel):
    period: str = ""
    inflow: float = 0.0
    outflow: float = 0.0
    net: float = 0.0
    cumulative: float = 0.0


class CashflowProfile(BaseModel):
    """REVIEW s06 — deterministic cash-flow profile from payment terms + program."""

    points: list[CashflowPoint] = Field(default_factory=list)
    negative_periods: list[str] = Field(default_factory=list)


class CitationCheck(BaseModel):
    """REVIEW s08 — one register clause checked against the parsed source (deterministic lookup,
    the anti-hallucination guard). ``found`` False means the cited clause is not in the documents."""

    clause: str = ""
    found: bool = False
    note: str = ""


# ===========================================================================
# ESTIMATE workflow handoffs
# ===========================================================================
class ScopeReviewNote(BaseModel):
    kind: str = ""                    # inclusion | exclusion | ambiguity | conflict | assumption
    text: str = ""


class ScopeReviewResult(BaseModel):
    """ESTIMATE s01 — inclusions/exclusions/ambiguities + clarifying questions (AI draft)."""

    notes: list[ScopeReviewNote] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class ScheduleActivity(BaseModel):
    """One priced-schedule activity. ``direct`` classifies direct vs indirect (rule-based)."""

    activity_id: str = ""
    description: str = ""
    unit: str = ""
    direct: bool = True


class PricingSchedule(BaseModel):
    """ESTIMATE s02 — the pricing-schedule structure (AI proposes the breakdown; the schedule
    itself is a deterministic data structure)."""

    activities: list[ScheduleActivity] = Field(default_factory=list)


class CostLine(BaseModel):
    """ESTIMATE s03 — one deterministic quantity × rate line. Never AI-written."""

    activity_id: str = ""
    description: str = ""
    qty: float = 0.0
    unit: str = ""
    rate_id: str = ""
    rate: float = 0.0
    amount: float = 0.0               # qty * rate — computed, never proposed


class CostBuildup(BaseModel):
    lines: list[CostLine] = Field(default_factory=list)
    direct_total: float = 0.0


class IndirectCost(BaseModel):
    label: str = ""
    basis: str = ""                   # e.g. "duration × rate" | "% × value"
    amount: float = 0.0


class IndirectsResult(BaseModel):
    """ESTIMATE s04 — indirects & allowances (deterministic formulas)."""

    items: list[IndirectCost] = Field(default_factory=list)
    indirect_total: float = 0.0


class ValidationFlag(BaseModel):
    kind: str = ""                    # scope_coverage | quantity_sense | rate_benchmark
    message: str = ""


class ValidationResult(BaseModel):
    """ESTIMATE s05 — rule-based validation flags (verdict stays human)."""

    flags: list[ValidationFlag] = Field(default_factory=list)


class LetterOfOffer(BaseModel):
    """ESTIMATE s06 — the offer letter draft (AI draft). ``price`` is injected from the deterministic
    cost build-up (s03/s04), NEVER written by the model."""

    body: str = ""
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    price: float = 0.0


# ===========================================================================
# The module's own DB tables — lazy, self-contained (see module docstring)
# ===========================================================================
# Every table is prefixed ``client_boq_`` so it can never collide with an existing
# table, and every statement is ``IF NOT EXISTS`` so init is idempotent and never
# drops or alters anything the seed built.
_DDL = [
    """
    CREATE TABLE IF NOT EXISTS client_boq_document_sets (
        set_id     TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        slug       TEXT NOT NULL,
        status     TEXT NOT NULL DEFAULT 'ingested',  -- ingested | reviewed | estimated
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS client_boq_review_registers (
        set_id       TEXT PRIMARY KEY,
        register_json TEXT NOT NULL DEFAULT '{}',
        approved      INTEGER NOT NULL DEFAULT 0,  -- the review->estimate gate (0/1)
        approved_at   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS client_boq_estimates (
        set_id        TEXT PRIMARY KEY,
        estimate_json TEXT NOT NULL DEFAULT '{}',
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]


def init_tables(conn: sqlite3.Connection) -> None:
    """Create the ``client_boq_*`` tables if they are absent (idempotent). Deterministic infra —
    not workflow logic. Call once per connection before touching the module's tables."""
    for stmt in _DDL:
        conn.execute(stmt)
    conn.commit()
