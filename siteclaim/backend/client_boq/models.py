"""Typed contracts for the client_boq module (pydantic) + the module's own DB tables.

Two things live here:

1. **Pydantic schemas** — the plain-data handoffs between the review and estimate stages,
   mirroring the main app's ``schemas/models.py`` discipline (a stage reads and writes typed
   models, no shared mutable state). Every AI stage's ``target_model`` is one of these, so
   ``llm_client.complete_json`` validates the model's JSON output against a strict schema (the
   consistency mechanism, in place of a temperature knob).

2. **The module's own SQLite tables** (``client_boq_*``) — created lazily with
   ``CREATE TABLE IF NOT EXISTS`` from :func:`init_tables`, over a connection from the shared
   ``db.store.get_connection``. Self-contained: ``db/schema.sql`` and ``db/seed.py`` are never
   touched, and no existing table is altered.

Decision-value discipline (the hard constraint): the AI proposes and drafts, never decides. That is
enforced structurally here — the AI's stage-03 target model (:class:`DepartureProposalSet`) has NO
status/verdict field at all, so the model *cannot* write a breach verdict. Deterministic rule code
(``client_boq/rules.py``) and the human approve endpoint are the only writers of a departure's
``status``.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from pydantic import BaseModel, Field

# A raw uploaded file as the module receives it, matching the main app's ingest tuple shape
# ``(filename, content_type, bytes)`` so ``pipeline.documents.extract_document`` can be reused.
RawUpload = tuple[str, Optional[str], bytes]


# ---------------------------------------------------------------------------
# Departure status vocabulary (single lifecycle field on a register line)
# ---------------------------------------------------------------------------
# Who writes each value:
#   rule_flagged   — deterministic rule code (a numeric threshold breached)      [rules.py]
#   candidate      — a qualitative AI-proposed match the human must judge         [s03]
#   uncovered      — a clause that matched no criterion                           [s03]
#   unresolved     — a criterion no clause resolved                               [s03]
#   citation_failed— a cited clause not found / not supported in the documents    [s08]
#   confirmed      — a human accepted the departure                               [approve endpoint ONLY]
#   dismissed      — a human rejected the departure                               [approve endpoint ONLY]
STATUS_RULE_FLAGGED = "rule_flagged"
STATUS_CANDIDATE = "candidate"
STATUS_UNCOVERED = "uncovered"
STATUS_UNRESOLVED = "unresolved"
STATUS_CITATION_FAILED = "citation_failed"
STATUS_CONFIRMED = "confirmed"
STATUS_DISMISSED = "dismissed"

# The statuses a human approve decision may set — the ONLY verdict writer.
HUMAN_VERDICTS = {STATUS_CONFIRMED, STATUS_DISMISSED}


# ===========================================================================
# Criteria library (input to REVIEW s03) — produced by criteria_loader.py
# ===========================================================================
class Criterion(BaseModel):
    """One acceptable-terms row from ``review_criteria.md``. ``is_placeholder`` is True for the
    empty ``OK-01`` extension row (no acceptable position yet) — loaded, never silently dropped."""

    id: str
    category_id: str
    category: str
    clause_area: str
    acceptable_position: str = ""
    why_it_matters: str = ""
    red_flag: str = ""
    is_placeholder: bool = False


class ThresholdRule(BaseModel):
    """A numerically-checkable red flag from the 'Deterministic threshold checks' table — the ONLY
    rows the rule layer pre-flags. The rule raises the flag; the human still confirms the departure."""

    id: str
    rule: str
    extract_field: str


class CriteriaLibrary(BaseModel):
    """The parsed criteria library. ``criteria`` are the populated acceptable-terms rows;
    ``placeholders`` holds empty extension rows (OK-01); ``threshold_rules`` is the numeric subset."""

    criteria: list[Criterion] = Field(default_factory=list)
    placeholders: list[Criterion] = Field(default_factory=list)
    threshold_rules: list[ThresholdRule] = Field(default_factory=list)

    def category_ids(self) -> set[str]:
        return {c.category_id for c in self.criteria}

    def by_id(self, criterion_id: str) -> Optional[Criterion]:
        for c in (*self.criteria, *self.placeholders):
            if c.id == criterion_id:
                return c
        return None

    def threshold_ids(self) -> set[str]:
        return {t.id for t in self.threshold_rules}


# ===========================================================================
# Rates (input to ESTIMATE s03) — produced by rates.py
# ===========================================================================
class RateRow(BaseModel):
    """One hand-editable rate from ``client_boq/data/rates.csv``."""

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
    """One structured item read out of the document set — a contract clause or scope line.
    ``clause_id`` is the stable identity s08 verifies citations against."""

    clause_id: str = ""           # stable id, e.g. "9.9"
    ref: str = ""                 # as printed (may equal clause_id), e.g. "Clause 9.9"
    heading: str = ""
    text: str = ""
    source_doc: str = ""
    page: Optional[int] = None


class ParsedDocumentSet(BaseModel):
    """REVIEW s01 output, and the shared parsed-document store the estimate reads too. Persisted at
    ``artifacts/client_boq/parsed.json``."""

    set_id: str = ""
    name: str = ""
    slug: str = ""
    documents: list[str] = Field(default_factory=list)   # source filenames, in upload order
    clauses: list[ClauseItem] = Field(default_factory=list)

    def clause_index(self) -> dict[str, ClauseItem]:
        """clause_id → clause, for the s08 citation lookup."""
        return {c.clause_id: c for c in self.clauses if c.clause_id}


class ContextSummary(BaseModel):
    """REVIEW s02 — the structured commercial-risk summary from the review doc (AI draft, human-
    reviewed). Draft only; no verdicts."""

    summary: str = ""
    scope_responsibilities: list[str] = Field(default_factory=list)   # scope affecting price
    obligations: list[str] = Field(default_factory=list)              # testing/inspection/cert/permit
    client_assumptions: list[str] = Field(default_factory=list)       # client assumptions/constraints
    interfaces: list[str] = Field(default_factory=list)               # interfaces with other trades
    clarifications: list[str] = Field(default_factory=list)           # items to clarify or exclude


class DepartureProposal(BaseModel):
    """REVIEW s03 **AI output item** — a proposal only. Deliberately carries NO status/verdict field,
    so the model cannot write a decision value. The AI proposes the matched ``criterion_id`` (or ""
    for a clause that matches nothing), extracts the threshold ``extracted_value`` where the criterion
    is numeric, quotes the supporting ``cited_text``, and drafts ``amendment_proposal`` /
    ``rationale`` / ``proposed_position``."""

    clause_id: str = ""
    criterion_id: str = ""            # "" means: this clause matched no criterion
    extracted_value: str = ""         # the field named in the threshold table (numeric criteria)
    cited_text: str = ""              # the quote the departure relies on (s08 containment-checks it)
    amendment_proposal: str = ""      # draft
    rationale: str = ""               # draft
    proposed_position: str = ""       # draft


class DepartureProposalSet(BaseModel):
    """The wrapper the AI returns for s03 (fixture field ``departures``). One proposal per clause the
    AI read; ``criterion_id == ""`` marks a clause that matched nothing (becomes ``uncovered``)."""

    departures: list[DepartureProposal] = Field(default_factory=list)


class DepartureItem(BaseModel):
    """One assembled register line (the workflow's line-item record). ``status`` is set by rule code
    (rule_flagged), s03 (candidate/uncovered/unresolved), s08 (citation_failed), or the human approve
    endpoint (confirmed/dismissed) — never by the AI. Negotiation columns (``client_response`` /
    ``contractor_response``) start empty; ``register_status`` is the review-doc Open/Closed column."""

    item: int = 0
    clause: str = ""                  # cited clause_id ("" for an unresolved criterion)
    criterion_id: str = ""            # matched criterion ("" for an uncovered clause)
    category: str = ""
    clause_area: str = ""
    extracted_value: str = ""
    cited_text: str = ""
    amendment_proposal: str = ""
    rationale: str = ""
    proposed_position: str = ""
    status: str = STATUS_CANDIDATE
    rule_ref: str = ""                # the threshold rule id that fired (rule_flagged only)
    citation_note: str = ""           # why a citation failed (s08)
    client_response: str = ""         # negotiation (human)
    contractor_response: str = ""     # negotiation (human)
    register_status: str = "open"     # Open | Closed (the review-doc status column)


class DepartureSet(BaseModel):
    """REVIEW s03 final output. The wrapper field ``departures`` matches the locked decision; this is
    the *computed* result (never loaded from the AI fixture — that is :class:`DepartureProposalSet`),
    so it also carries ``aligned_criteria``: numeric criteria the rule resolved as compliant (no
    departure line), recorded so a resolved-and-fine criterion is never mistaken for unresolved."""

    departures: list[DepartureItem] = Field(default_factory=list)
    aligned_criteria: list[str] = Field(default_factory=list)


class DepartureRegister(BaseModel):
    """REVIEW s07 assembled register — the workflow's decision surface, structured per the review doc
    (header fields + line items). ``approved`` is the review→estimate gate; the DB table is the
    source of truth for the gate, this object is persisted to ``artifacts/client_boq/register.json``
    as a convenience copy. ``aligned_criteria`` records numeric criteria the rule resolved as
    compliant (no departure line) so nothing is silently dropped."""

    set_id: str = ""
    # Header fields (review doc):
    project: str = ""
    contract_type: str = ""
    package: str = ""
    subcontract_reference: str = ""
    subcontractor_name: str = ""
    submission_date: str = ""
    # Body:
    items: list[DepartureItem] = Field(default_factory=list)
    aligned_criteria: list[str] = Field(default_factory=list)   # criterion ids resolved as compliant
    slice2_pending: list[str] = Field(default_factory=list)     # e.g. ["scope_alignment","program","cashflow"]
    approved: bool = False


# --- slice-2 handoffs (kept from scaffold; stages s04–s06 remain stubs) -----
class ScopeAlignmentFinding(BaseModel):
    kind: str = ""
    description: str = ""
    contract_ref: str = ""
    priced: Optional[bool] = None


class ScopeAlignmentSet(BaseModel):
    findings: list[ScopeAlignmentFinding] = Field(default_factory=list)


class ProgramFinding(BaseModel):
    kind: str = ""
    description: str = ""
    recomputed_value: str = ""


class ProgramFindingSet(BaseModel):
    findings: list[ProgramFinding] = Field(default_factory=list)


class CashflowPoint(BaseModel):
    period: str = ""
    inflow: float = 0.0
    outflow: float = 0.0
    net: float = 0.0
    cumulative: float = 0.0


class CashflowProfile(BaseModel):
    points: list[CashflowPoint] = Field(default_factory=list)
    negative_periods: list[str] = Field(default_factory=list)


class CitationCheck(BaseModel):
    """REVIEW s08 — one register clause checked against the parsed source (deterministic lookup).
    ``found`` False means the cited clause_id is absent; ``supported`` False means the cited_text is
    not contained in the clause. Either failure marks the line ``citation_failed`` — kept visible."""

    item: int = 0
    clause: str = ""
    found: bool = False
    supported: bool = True
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.found and self.supported


# ===========================================================================
# ESTIMATE workflow handoffs (unchanged from scaffold — stages remain stubs)
# ===========================================================================
class ScopeReviewNote(BaseModel):
    kind: str = ""
    text: str = ""


class ScopeReviewResult(BaseModel):
    notes: list[ScopeReviewNote] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class ScheduleActivity(BaseModel):
    activity_id: str = ""
    description: str = ""
    unit: str = ""
    direct: bool = True


class PricingSchedule(BaseModel):
    activities: list[ScheduleActivity] = Field(default_factory=list)


class CostLine(BaseModel):
    activity_id: str = ""
    description: str = ""
    qty: float = 0.0
    unit: str = ""
    rate_id: str = ""
    rate: float = 0.0
    amount: float = 0.0


class CostBuildup(BaseModel):
    lines: list[CostLine] = Field(default_factory=list)
    direct_total: float = 0.0


class IndirectCost(BaseModel):
    label: str = ""
    basis: str = ""
    amount: float = 0.0


class IndirectsResult(BaseModel):
    items: list[IndirectCost] = Field(default_factory=list)
    indirect_total: float = 0.0


class ValidationFlag(BaseModel):
    kind: str = ""
    message: str = ""


class ValidationResult(BaseModel):
    flags: list[ValidationFlag] = Field(default_factory=list)


class LetterOfOffer(BaseModel):
    body: str = ""
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    price: float = 0.0


# ===========================================================================
# The module's own DB tables — lazy, self-contained (see module docstring)
# ===========================================================================
_DDL = [
    """
    CREATE TABLE IF NOT EXISTS client_boq_document_sets (
        set_id       TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        slug         TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'ingested',  -- ingested | reviewed | estimated
        parsed_json  TEXT NOT NULL DEFAULT '{}',
        summary_json TEXT NOT NULL DEFAULT '{}',
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS client_boq_review_registers (
        set_id        TEXT PRIMARY KEY,
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
    """Create the ``client_boq_*`` tables if absent (idempotent). Deterministic infra, not workflow
    logic. Call once per connection before touching the module's tables."""
    for stmt in _DDL:
        conn.execute(stmt)
    conn.commit()
