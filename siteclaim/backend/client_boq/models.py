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
# The third thing a human can decide about a departure: neither accept it nor press it, but ASK.
# A queried line stays open and does NOT block review approval — the submission deadline does not
# move because the client has not replied. The forcing function is the freeze gate, where every
# unanswered query must become an answer or a stated priced assumption.
STATUS_QUERY = "query"

# The statuses a human approve decision may set — the ONLY verdict writer.
HUMAN_VERDICTS = {STATUS_CONFIRMED, STATUS_DISMISSED, STATUS_QUERY}
# Verdicts that close a register line. A query is a verdict — a human decided to ask — but it
# leaves the line open, because the question is not yet answered.
CLOSING_VERDICTS = {STATUS_CONFIRMED, STATUS_DISMISSED}

# ---------------------------------------------------------------------------
# RFI lifecycle — the conversation with the client
# ---------------------------------------------------------------------------
# Where the question came from. `pricing` matters: many real questions surface only when someone
# tries to put a number on something, long after the contract review is finished.
RFI_FROM_REGISTER = "register"
RFI_FROM_PRICING = "pricing"
RFI_FROM_MANUAL = "manual"
RFI_ORIGINS = (RFI_FROM_REGISTER, RFI_FROM_PRICING, RFI_FROM_MANUAL)

RFI_DRAFT = "draft"          # raised, not yet sent
RFI_SENT = "sent"            # in a batch that went to the client
RFI_ANSWERED = "answered"    # the client replied
RFI_OVERTAKEN = "overtaken"  # an addendum changed the clause before any reply arrived
RFI_WITHDRAWN = "withdrawn"  # we no longer need the answer
RFI_STATUSES = (RFI_DRAFT, RFI_SENT, RFI_ANSWERED, RFI_OVERTAKEN, RFI_WITHDRAWN)
# Still waiting on the client. This is the count that must be visible, and the set the freeze
# gate has to empty before a number can be committed.
RFI_OPEN = {RFI_DRAFT, RFI_SENT}


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
# INGEST workflow handoffs (s00 — the front door, before REVIEW)
# ===========================================================================
# The canonical part taxonomy. A tender binder's parts are named differently by every
# issuer (an NEC4 package says "Works Information", a CIC in-house form says "Assignment
# Brief"), but they serve the same functional roles. Downstream prompts address the
# CATEGORY, never the source-specific title, so a new tender family needs no new prompts.
PART_CATEGORIES = (
    "tender-instructions",    # how to bid: conditions of tender, instructions to tenderers
    "tender-conditions",      # special/supplementary conditions governing the bidding process
    "bid-forms",              # what the bidder fills in and signs: form of tender, schedules
    "scope",                  # what is to be built: works information, assignment brief
    "specifications",         # how it must be built: general/particular specification
    "drawings",               # the drawing set
    "pricing",                # bills of quantities, schedules of rates, fee proposals
    "contract-conditions",    # the contract itself: general/particular conditions
    "contract-data",          # the filled-in parts of the contract: contract data, appendices
    "site-information",       # ground investigation, surveys, existing conditions
    "safety-requirements",    # safety plans, contractor's safety requirements
    "admin-forms",            # vendor registration, declarations, probity forms
    "other",                  # honestly uncategorised — never a dumping ground for a guess
)

# Confidence ladder (see ingest/pdfops.py). A LOWER tier is a better-grounded split.
# Tier 4 is a degraded SUCCESS, never a failure — the document still ingests as one part.
TIER_BOOKMARKS = 1     # the PDF's own outline, validated
TIER_TOC = 2           # the document's printed table of contents, offset-verified
TIER_HEURISTIC = 3     # divider/header detection over a page digest
TIER_WHOLE = 4         # no reliable structure — one part, flagged for manual splitting

# How a document entered the set. This is the revision's CAUSE, and it is load-bearing: the
# addendum-acknowledgement returnable must list the client's addenda and NOT our own corrections,
# so the two cannot share a label. Modelled on the real ND/2025/04 package, where documents carry
# their revision in the filename (BQ-0 -> BQ-1 -> BQ-2) and each addendum ships only the
# replacements it affects.
DOC_BASE = "base"                  # the tender as first issued
DOC_CORRECTION = "correction"      # we re-uploaded a document to fix our own mistake
DOC_ADDENDUM = "addendum"          # the client amended the contract. Binding. Acknowledge it.
DOC_CLARIFICATION = "clarification"  # the client answered a question. Expressly NOT contractual.
DOC_KINDS = (DOC_BASE, DOC_CORRECTION, DOC_ADDENDUM, DOC_CLARIFICATION)

# Kinds of change an addendum makes to a part, as its own change table describes them.
CHANGE_REPLACE_PAGES = "replace-pages"
CHANGE_ADD_PART = "add-part"
CHANGE_DELETE_PART = "delete-part"
CHANGE_TEXTUAL = "textual-amendment"
CHANGE_KINDS = (CHANGE_REPLACE_PAGES, CHANGE_ADD_PART, CHANGE_DELETE_PART, CHANGE_TEXTUAL)


class OutlineNode(BaseModel):
    """One entry of the PDF's own bookmark outline, with its destination resolved."""

    title: str = ""
    page: Optional[int] = None    # 1-based physical page; None when the destination is broken
    depth: int = 1


class PartSpec(BaseModel):
    """One part of a split document set. ``start``/``end`` are 1-based INCLUSIVE physical
    pages of the source PDF — the contract between the planning call and the splitter."""

    n: int = 0
    abbr: str = ""                # short human tag, e.g. "CT", used in folder names
    slug: str = ""
    title: str = ""
    start: int = 1
    end: int = 1
    category: str = "other"       # one of PART_CATEGORIES
    scanned: bool = False         # no usable text layer; read via vision or flagged honestly
    source_doc: str = ""          # which uploaded file these pages come from (blank = the binder)
    rev: int = 0                  # which revision of this part these pages are (0 = as first issued)

    @property
    def part_id(self) -> str:
        """Stable within a set: the zero-padded ordinal plus the abbreviation."""
        return f"{self.n:02d}-{(self.abbr or self.slug or 'part').lower()}"

    def page_count(self) -> int:
        return max(0, self.end - self.start + 1)


class SplitManifest(BaseModel):
    """The pivot artifact of ingest, and its human gate. Produced by the planning call,
    validated and cut by deterministic code, editable by a human, then re-split for free."""

    set_id: str = ""
    source_doc: str = ""          # the uploaded filename this manifest splits
    pages: int = 0                # the source's physical page count
    prefix: str = ""              # filename prefix for the emitted part PDFs
    tier: int = TIER_BOOKMARKS
    tier_reason: str = ""         # why this tier — shown to the human at the gate
    parts: list[PartSpec] = Field(default_factory=list)
    approved: bool = False
    # Measured at inspection and carried here so it survives every later edit of the parts:
    # re-cutting the manifest must not lose which pages have no text layer.
    scanned_pages: list[int] = Field(default_factory=list)

    def coverage(self) -> int:
        return sum(p.page_count() for p in self.parts)


class InspectReport(BaseModel):
    """Deterministic read of an uploaded PDF: no model, no network. The input to planning."""

    filename: str = ""
    pages: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)
    outline: list[OutlineNode] = Field(default_factory=list)
    outline_depth_used: int = 2
    page_chars: list[int] = Field(default_factory=list)   # extracted chars per page
    scanned_pages: list[int] = Field(default_factory=list)  # 1-based, below the char threshold
    total_chars: int = 0
    toc_text: str = ""            # text of the pages that look like the document's own contents
    draft: SplitManifest = Field(default_factory=SplitManifest)


class PlannedSplit(BaseModel):
    """The planning call's output — a REFINEMENT of the deterministic draft, not a fresh
    invention. The model renames, categorises, merges and splits the draft's parts; code
    then validates the arithmetic and performs the cut. Deliberately carries no approval
    flag and no tier: the model cannot promote its own confidence or open its own gate."""

    parts: list[PartSpec] = Field(default_factory=list)
    notes: str = ""               # why it departed from the draft, for the human at the gate


class ChangeEntry(BaseModel):
    """One row of an addendum's OWN change table, as printed in the addendum letter.

    Advisory only. Tender Addendum No.1 of the reference package states its remarks are
    "neither exhaustive nor guaranteed to be accurate" and that the tenderer must check the
    replacement pages. So this navigates a human to the right pages; the replacement document
    is the authority on what actually changed.
    """

    document: str = ""            # the document the addendum names, as printed
    pages: str = ""               # the pages it names, as printed, e.g. "PS7/45"
    description: str = ""


class ProposedMapping(BaseModel):
    """Which existing part an uploaded replacement document supersedes."""

    filename: str = ""
    part_id: str = ""             # "" when nothing matched — surfaced, never guessed
    kind: str = CHANGE_REPLACE_PAGES
    reason: str = ""


class AddendumPlan(BaseModel):
    """The planning call's read of an addendum: what it says it changed, and which of our parts
    each replacement file supersedes. Proposal only — the human gate commits the revisions."""

    ref: str = ""
    changes: list[ChangeEntry] = Field(default_factory=list)
    mappings: list[ProposedMapping] = Field(default_factory=list)
    notes: str = ""


class RFIItem(BaseModel):
    """One question to the client. Raised by a human, never by a model.

    A question carries its citation so the client can find what we are asking about, and so the
    answer can be matched back to the register line that prompted it.
    """

    rfi_id: str = ""
    number: int = 0                   # position within its batch, as printed in the letter
    origin: str = RFI_FROM_REGISTER
    register_item: Optional[int] = None   # the register line this came from, when it came from one
    part_id: str = ""
    clause: str = ""
    page: Optional[int] = None
    question: str = ""
    context: str = ""                 # what we currently understand, so the client sees the premise
    status: str = RFI_DRAFT
    batch_id: str = ""
    answer: str = ""
    answered_by: str = ""             # the document that carried the answer, when one did
    raised_at: str = ""
    answered_at: str = ""

    def is_open(self) -> bool:
        return self.status in RFI_OPEN


class RFIBatch(BaseModel):
    """A set of questions sent to the client as one numbered letter.

    Batched rather than sent one at a time because that is how tender queries actually go out:
    the reference package shows two rounds, TC1 and TC2, each a single numbered letter.
    """

    batch_id: str = ""
    ref: str = ""                     # e.g. "Technical Query No. 1"
    sent_at: str = ""
    letter_md: str = ""
    items: list[RFIItem] = Field(default_factory=list)


class RFILetterDraft(BaseModel):
    """The AI's contribution to a query letter: covering prose only.

    The questions themselves are the human's words, reproduced verbatim, and the numbering and
    citations are code-injected. The model writes the wrapper, never the substance.
    """

    salutation: str = ""
    opening: str = ""
    closing: str = ""


# Clauses that change how you BID rather than what you price. Found in both reference tenders,
# and the reason they matter is timing: a tender that penalises qualifications wants its problem
# clauses raised as queries before the cut-off, not carried to submission as departures. Learning
# that at submission is learning it too late.
RULE_QUALIFICATIONS_PENALISED = "qualifications-penalised"
RULE_NO_ALTERATIONS = "no-alterations"
RULE_ALTERNATIVES_NOT_CONSIDERED = "alternatives-not-considered"
RULE_QUERY_CUTOFF = "query-cutoff"
RULE_SUBMISSION_DEADLINE = "submission-deadline"
RULE_TWO_ENVELOPE = "two-envelope"
RULE_KINDS = (
    RULE_QUALIFICATIONS_PENALISED, RULE_NO_ALTERATIONS, RULE_ALTERNATIVES_NOT_CONSIDERED,
    RULE_QUERY_CUTOFF, RULE_SUBMISSION_DEADLINE, RULE_TWO_ENVELOPE,
)


class StrategyFlag(BaseModel):
    """A tender condition that changes how the bid should be run.

    Quoted, never paraphrased, and always cited: the whole value is that a human can check it
    against the document. Real examples from the two reference tenders:

      "Any qualification of the tender may cause the tender to be disqualified."
          -- ND/2025/04, General Conditions of Tender GCT 4, page 6
      "Any qualification of tender or of the tender documents may cause the tender to be
       disqualified."
          -- CIC (325), Conditions of Tender 4.26, page 8
    """

    kind: str = ""                # one of RULE_KINDS
    clause: str = ""              # as printed, e.g. "GCT 4" or "4.26"
    page: Optional[int] = None    # page of the SOURCE document
    quote: str = ""               # the clause's own words


# Whose words a piece of prose is in. Used by BOTH the ingest context cards and the scope items,
# and defined once here because it is one rule, not two: a model's draft and a person's decision
# must never look alike, and editing anything transfers ownership to the person who edited it.
BADGE_AI = "ai"
BADGE_USER = "user"
SCOPE_BADGES = (BADGE_AI, BADGE_USER)


class PartContext(BaseModel):
    """The interpreted context for one part — the structured twin of its markdown card.
    ``readable`` false means we could not read it; the card says so rather than guessing."""

    part_id: str = ""
    title: str = ""
    category: str = "other"
    readable: bool = True
    summary: str = ""                                        # plain-language, for a non-expert
    key_points: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)     # what it requires of the contractor
    commercial_flags: list[str] = Field(default_factory=list)  # price/risk-bearing content
    feeds: list[str] = Field(default_factory=list)           # part_ids this one governs
    strategy_flags: list[StrategyFlag] = Field(default_factory=list)  # how to BID, not what to price
    notes: str = ""
    # Whose words this card is in. The same rule as ScopeItem, for the same reason: a model's
    # reading and a person's correction of it must never be mistakable for one another. Editing
    # a card stamps `user`; re-interpreting it puts `ai` back, because that IS a fresh reading.
    badge: str = BADGE_AI


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
    part_id: str = ""             # the ingest part this clause came from ("" when not split)


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


# Where a register line came from — so s04/s05/s06 findings live in the ONE register, tagged.
SOURCE_CRITERIA = "criteria"           # s03 criteria match
SOURCE_SCOPE_ALIGNMENT = "scope_alignment"  # s04
SOURCE_PROGRAM = "program"             # s05
SOURCE_CASHFLOW = "cashflow"           # s06 (verdict-needing findings only; the curve is a section)


class DepartureItem(BaseModel):
    """One assembled register line (the workflow's line-item record). ``status`` is set by rule code
    (rule_flagged), s03/s04/s05 (candidate/uncovered/unresolved), s08 (citation_failed), or the human
    approve endpoint (confirmed/dismissed) — never by the AI. ``source`` tags which check produced the
    line. Negotiation columns start empty; ``register_status`` is the review-doc Open/Closed column."""

    item: int = 0
    clause: str = ""                  # cited clause_id ("" for an unresolved criterion / an input gap)
    criterion_id: str = ""            # matched criterion ("" for an uncovered clause / s04-s06 finding)
    category: str = ""
    clause_area: str = ""
    extracted_value: str = ""
    cited_text: str = ""
    amendment_proposal: str = ""
    rationale: str = ""
    proposed_position: str = ""
    status: str = STATUS_CANDIDATE
    source: str = SOURCE_CRITERIA     # criteria | scope_alignment | program | cashflow
    kind: str = ""                    # finding sub-type for s04/s05/s06 (e.g. "precedence", "input_missing")
    rule_ref: str = ""                # the rule id that fired (rule_flagged only)
    citation_note: str = ""           # why a citation failed (s08)
    page: Optional[int] = None        # MEASURED page of the cited text, set by s08's physical guard
    client_response: str = ""         # negotiation (human)
    contractor_response: str = ""     # negotiation (human)
    register_status: str = "open"     # Open | Closed (the review-doc status column)


class AlignedItem(BaseModel):
    """A numeric criterion the rule resolved as COMPLIANT — no departure line, but surfaced in the
    register's 'aligned' section with the value and why it passes (locked decision 2A), so a
    resolved-and-fine criterion is never mistaken for unresolved and never silently dropped."""

    criterion_id: str = ""
    clause_area: str = ""
    clause: str = ""
    extracted_value: str = ""
    why: str = ""


class DepartureSet(BaseModel):
    """REVIEW s03 final output. The wrapper field ``departures`` matches the locked decision; this is
    the *computed* result (never loaded from the AI fixture — that is :class:`DepartureProposalSet`),
    so it also carries ``aligned``: numeric criteria the rule resolved as compliant."""

    departures: list[DepartureItem] = Field(default_factory=list)
    aligned: list[AlignedItem] = Field(default_factory=list)


class CashflowPoint(BaseModel):
    period: str = ""                  # "M1", "M2", …
    inflow: float = 0.0               # receipts that month
    outflow: float = 0.0             # cost that month
    net: float = 0.0
    cumulative: float = 0.0


class CashflowSection(BaseModel):
    """REVIEW s06 output attached to the register as its own section (locked decision 3A) — a curve
    plus findings, not line items. Verdict-needing commercial adjustments become tagged line items
    (``source == cashflow``) instead."""

    points: list[CashflowPoint] = Field(default_factory=list)
    negative_periods: list[str] = Field(default_factory=list)
    working_capital_peak: float = 0.0   # most-negative cumulative (the funding requirement)
    findings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class DepartureRegister(BaseModel):
    """REVIEW s07 assembled register — the ONE decision surface (locked decision 3A), structured per
    the review doc (header fields + line items). All checks fold in here: s03 criteria, s04 scope,
    s05 program as tagged line ``items``; s06 cash flow as the ``cashflow`` section; compliant numeric
    criteria as the ``aligned`` section. ``approved`` is the review→estimate gate (the DB table is the
    source of truth); this object is also persisted to ``artifacts/client_boq/register.json``."""

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
    aligned: list[AlignedItem] = Field(default_factory=list)
    cashflow: Optional[CashflowSection] = None
    approved: bool = False


# --- slice-2 handoffs -------------------------------------------------------
class ScopeAlignmentFinding(BaseModel):
    """s04 AI-proposed scope finding. ``contract_ref``/``cited_text`` let it flow through s08 citation
    verification like any line; ``priced`` records whether the AI thinks the item was priced."""

    kind: str = ""                    # gap | inconsistency | silent_assumption | responsibility_creep
    description: str = ""
    contract_ref: str = ""
    cited_text: str = ""
    priced: Optional[bool] = None


class ScopeAlignmentSet(BaseModel):
    findings: list[ScopeAlignmentFinding] = Field(default_factory=list)


class ProgramFinding(BaseModel):
    """s05 AI-proposed program risk. Numeric fields (when the AI extracts them) feed the DETERMINISTIC
    recompute — the AI never computes the exposure itself."""

    kind: str = ""                    # duration | sequencing | access | mobilisation | milestone | ld_exposure
    description: str = ""
    contract_ref: str = ""
    cited_text: str = ""
    ld_rate_per_day: Optional[float] = None
    program_days: Optional[float] = None
    ld_cap_value: Optional[float] = None
    scope_mobilisations: Optional[int] = None
    program_mobilisations: Optional[int] = None
    recomputed_value: str = ""        # set by the deterministic recompute, never by the AI


class ProgramFindingSet(BaseModel):
    findings: list[ProgramFinding] = Field(default_factory=list)


# The physical half of citation verification (see review/s08_citation_verify.py). Three outcomes,
# because a failed lookup has two very different causes and lumping them together is what makes a
# warning worth ignoring.
LOCATED = "located"              # found on a page; the page number is measured, not claimed
UNVERIFIABLE = "unverifiable"    # the part cannot be searched (scanned, or no text layer)
NOT_LOCATED = "not_located"      # searchable, corroborated by its neighbours, still not found
LOCATION_VERDICTS = (LOCATED, UNVERIFIABLE, NOT_LOCATED)


class Highlight(BaseModel):
    """Where a quotation sits on its page, as fractions of page width and height.

    Fractions rather than points so a viewer can overlay them at any zoom or render scale
    without knowing what DPI the page was rasterised at.
    """

    page: int = 0                 # 1-based, in the document the part was cut from
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0


class CitationLocation(BaseModel):
    """The result of physically looking for a quotation in the document."""

    verdict: str = UNVERIFIABLE
    page: Optional[int] = None    # measured, never the page the model claimed
    match: str = "none"           # exact | fragment | none
    matched_text: str = ""        # what actually matched, when only a fragment did
    highlights: list[Highlight] = Field(default_factory=list)
    note: str = ""


class CitationCheck(BaseModel):
    """REVIEW s08 — one register clause checked against the source.

    Two independent guards, and they answer different questions:

    * the **parse** guard (``found``/``supported``): does the cited clause exist in the structured
      parse, and does the quoted text sit inside it? A lookup, no PDF involved.
    * the **physical** guard (``location``): can the quotation actually be found on a page of the
      document? This is what turns a claimed page number into a measured one, and what supplies
      the rectangles a viewer highlights.
    """

    item: int = 0
    clause: str = ""
    found: bool = False
    supported: bool = True
    note: str = ""
    location: Optional[CitationLocation] = None

    @property
    def ok(self) -> bool:
        return self.found and self.supported


# ===========================================================================
# ESTIMATE workflow handoffs (unchanged from scaffold — stages remain stubs)
# ===========================================================================
class ScopeReviewNote(BaseModel):
    """One scope note. ``kind`` is one of inclusion | exclusion | ambiguity | conflict | assumption
    (estimating doc step 1). ``source`` distinguishes the AI draft from deterministically-injected
    register context (``register``)."""

    kind: str = ""
    text: str = ""
    source: str = "draft"             # "draft" | "register"


class ScopeReviewResult(BaseModel):
    """ESTIMATE s01 output (AI draft + injected register context). ``summary`` is the scope statement;
    it is what an ``amended_summary`` at the scope gate overrides. Draft only — no verdicts, no numbers."""

    summary: str = ""
    notes: list[ScopeReviewNote] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


# --- the scope of record, item by item (the freeze gate) --------------------
SCOPE_QUALIFICATIONS = "qualifications"   # terms we are not accepting as drafted
SCOPE_FALLBACKS = "fallbacks"             # what an unanswered query has been priced on
SCOPE_LOGISTICS = "logistics"             # execution boundaries — access, sequence, attendance
SCOPE_SECTIONS = (SCOPE_QUALIFICATIONS, SCOPE_FALLBACKS, SCOPE_LOGISTICS)

# Where a scope source can come from. Derived on every read, never stored: the register, the
# open questions, and the amendments are each already the authority on their own contents, and
# a second copy here would go stale the moment a verdict changed.
SOURCE_DEPARTURE = "departure"
SOURCE_RFI = "rfi"
SOURCE_ADDENDUM = "addendum"


class ScopeItem(BaseModel):
    """One line of the scope of record — written into the offer letter word for word.

    ``badge`` is the load-bearing field. A model's suggestion and a person's decision must never
    look alike on the page, so editing a line always stamps it ``user``: you edited it, you own it.

    ``is_fallback`` + ``accepted`` are the freeze gate itself. An unanswered query has to become
    either an answer or a stated priced assumption before a number can be committed, and a
    fallback nobody has accepted is neither — it is a machine's guess sitting where a decision
    should be. It is carried, counted and shown, but it is not priced until somebody accepts it.
    """

    item_id: str = ""
    section: str = SCOPE_QUALIFICATIONS
    title: str = ""
    badge: str = BADGE_AI
    is_fallback: bool = False
    accepted: bool = False
    text: str = ""
    source_ref: str = ""              # e.g. "departure:7", "rfi:rfi-003" ("" = written here)
    updated_at: str = ""

    def is_priced(self) -> bool:
        """Whether this line may stand behind a number. A fallback needs accepting first."""
        return (not self.is_fallback) or self.accepted


class ScopeSource(BaseModel):
    """Something the scope COULD be built from, and whether it has been. Always derived."""

    source_ref: str = ""
    group: str = SOURCE_DEPARTURE
    label: str = ""
    meta: str = ""
    section: str = SCOPE_QUALIFICATIONS   # the section it would map into
    text: str = ""                        # seed prose, when there is any
    mapped: bool = False


class EstimateScope(BaseModel):
    """The persisted scope record for the estimate's first step + its human gate. ``amended_summary``
    (when non-empty) is the approved scope of record and wins over the draft's ``summary``; the
    original draft is retained. ``approved`` is the estimate's second gate (mirrors the review gate)."""

    set_id: str = ""
    draft: ScopeReviewResult = Field(default_factory=ScopeReviewResult)
    amended_summary: str = ""
    approved: bool = False

    def summary_of_record(self) -> str:
        return self.amended_summary.strip() or self.draft.summary


# --- ESTIMATE input (the structured pricing schedule; request payload in live, fixture in DEMO) ---
class ResourceLine(BaseModel):
    """One priced resource within a direct activity. Either name a CSV rate via ``resource_ref`` OR
    give an ``inline_rate``; ``productivity`` (output units per hour) converts a work quantity into
    hours before the rate is applied (qty ÷ productivity = hours; hours × rate = amount)."""

    description: str = ""
    resource_ref: str = ""            # rate_id in rates.csv (blank when inline)
    inline_rate: Optional[float] = None
    qty: float = 0.0
    unit: str = ""
    productivity: Optional[float] = None


class ScheduleItem(BaseModel):
    """One schedule item. ``category`` is declared by the payload — 'direct' (priced from resource
    lines) or 'indirect' (computed from a ``basis``). Any other value is left for s05 to flag as
    ``unclassified_item`` (never guessed). Indirect bases: 'lump' (``amount``), 'per_week'
    (``rate`` × schedule ``duration_weeks``), 'pct_of_direct' (``pct`` × direct subtotal)."""

    item_id: str = ""                 # assigned by s02 when blank
    description: str = ""
    category: str = ""                # "direct" | "indirect" | (other → unclassified)
    unit: str = ""
    lines: list[ResourceLine] = Field(default_factory=list)   # direct items
    basis: str = ""                   # indirect items: lump | per_week | pct_of_direct
    amount: Optional[float] = None    # lump
    rate: Optional[float] = None      # per_week rate
    pct: Optional[float] = None       # pct_of_direct


class EstimateSchedule(BaseModel):
    """The structured pricing schedule. Quantities are given (no take-off in this slice).
    ``duration_weeks`` feeds per_week indirects."""

    duration_weeks: Optional[float] = None
    items: list[ScheduleItem] = Field(default_factory=list)


# --- ESTIMATE output (the priced estimate) ---
class CostLine(BaseModel):
    """One priced resource line with a full, hand-recomputable trace: the quantity, the rate and
    where it came from (csv|inline|missing), any productivity conversion, and the amount."""

    item_id: str = ""
    description: str = ""
    resource_ref: str = ""
    qty: float = 0.0
    unit: str = ""
    productivity: Optional[float] = None
    hours: Optional[float] = None     # qty ÷ productivity, when productivity is given
    rate: float = 0.0
    rate_source: str = ""             # "csv" | "inline" | "missing"
    amount: float = 0.0


class CostActivity(BaseModel):
    item_id: str = ""
    description: str = ""
    category: str = "direct"
    unit: str = ""
    lines: list[CostLine] = Field(default_factory=list)
    activity_total: float = 0.0


class IndirectLine(BaseModel):
    item_id: str = ""
    label: str = ""
    basis: str = ""                   # lump | per_week | pct_of_direct
    detail: str = ""                  # how it was computed (hand-checkable)
    amount: float = 0.0


class EstimateFlag(BaseModel):
    """A rule-raised flag on the estimate — surfaced for the human, never blocking, never a verdict."""

    kind: str = ""                    # missing_rate | zero_or_negative_qty | empty_activity | rate_outlier | unclassified_item
    item_id: str = ""
    message: str = ""


class EstimateTotals(BaseModel):
    total_direct: float = 0.0
    total_indirect: float = 0.0
    total_cost: float = 0.0
    margin_pct: float = 0.0
    price: float = 0.0
    margin_amount: float = 0.0        # price − total_cost (readout only; no profitable/not verdict)


class Estimate(BaseModel):
    """The full priced estimate persisted to the tables + ``artifacts/client_boq/estimate.json``."""

    set_id: str = ""
    duration_weeks: Optional[float] = None
    activities: list[CostActivity] = Field(default_factory=list)   # direct
    indirects: list[IndirectLine] = Field(default_factory=list)
    unclassified: list[ScheduleItem] = Field(default_factory=list)  # items with a bad category (flagged)
    flags: list[EstimateFlag] = Field(default_factory=list)
    totals: EstimateTotals = Field(default_factory=EstimateTotals)


class LetterMeta(BaseModel):
    """The offer-letter header fields — CODE-INJECTED from the run request, never AI-written. Sensible
    demo defaults so a letter renders without every field supplied."""

    company_name: str = "SiteSource Contracting Ltd"
    company_address: str = "Unit 1, Example Industrial Building, Kwun Tong, Hong Kong"
    contact_name: str = "The Estimator"
    contact_number: str = "+852 0000 0000"
    project: str = ""            # defaults to the document set name
    client_name: str = "the Client"
    date: str = ""               # as supplied; blank renders a placeholder (kept deterministic for tests)
    ref: str = ""                # defaults to the project
    validity_days: int = 90


class LetterDraft(BaseModel):
    """The AI-DRAFTED parts of the offer letter (the only parts a model writes). Seeded from the
    approved scope. Everything else — price, header fields, the pricing-schedule table, and the
    confirmed-departure Appendix A bullets — is injected by code."""

    intro: str = ""
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    additional_conditions: list[str] = Field(default_factory=list)  # AI Appendix-A conditions from the scope


class LetterAppendixItem(BaseModel):
    text: str = ""
    source: str = "draft"        # "register" (confirmed departure, verbatim) | "draft" (AI condition)


class PricingScheduleRow(BaseModel):
    item_id: str = ""
    description: str = ""
    total: float = 0.0


class LetterOfOffer(BaseModel):
    """The assembled offer letter (a DRAFT for human editing; nothing sends it). Carries the
    structured pieces plus the rendered ``markdown``. ``price``/``price_str`` and the
    ``pricing_schedule`` are injected from the persisted estimate; ``appendix`` is the confirmed
    departures (source ``register``, verbatim) followed by AI conditions (source ``draft``)."""

    set_id: str = ""
    meta: LetterMeta = Field(default_factory=LetterMeta)
    intro: str = ""                                              # AI
    price: float = 0.0                                          # injected
    price_str: str = ""                                        # injected, formatted
    inclusions: list[str] = Field(default_factory=list)         # AI
    exclusions: list[str] = Field(default_factory=list)         # AI
    pricing_schedule: list[PricingScheduleRow] = Field(default_factory=list)  # injected
    appendix: list[LetterAppendixItem] = Field(default_factory=list)
    markdown: str = ""                                          # the assembled letter


# ===========================================================================
# The module's own DB tables — lazy, self-contained (see module docstring)
# ===========================================================================
# A part's STABLE identity. What a part IS does not change when the client amends it: the Bill
# of Quantities is still the Bill of Quantities at Rev 2. Everything a revision can change lives
# in client_boq_part_revisions instead. Named separately because the migration recreates it.
_PARTS_DDL = """
    CREATE TABLE IF NOT EXISTS client_boq_parts (
        set_id       TEXT NOT NULL,
        part_id      TEXT NOT NULL,                    -- "01-inv"; stable within a set
        n            INTEGER NOT NULL DEFAULT 0,
        abbr         TEXT NOT NULL DEFAULT '',
        slug         TEXT NOT NULL DEFAULT '',
        title        TEXT NOT NULL DEFAULT '',
        category     TEXT NOT NULL DEFAULT 'other',
        PRIMARY KEY (set_id, part_id)
    )
    """

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
    """
    CREATE TABLE IF NOT EXISTS client_boq_estimate_scope (
        set_id          TEXT PRIMARY KEY,
        scope_json      TEXT NOT NULL DEFAULT '{}',   -- the s01 draft (ScopeReviewResult)
        amended_summary TEXT NOT NULL DEFAULT '',      -- human-edited scope of record (wins when set)
        approved        INTEGER NOT NULL DEFAULT 0,    -- the scope gate (0/1) — second estimate gate
        approved_at     TEXT
    )
    """,
    # The scope of record, item by item — the freeze gate.
    #
    # The estimate's scope started as one summary plus a flat list of notes, which is enough to
    # brief a pricing run and not enough to sign. Freezing needs three things that a paragraph
    # cannot carry: WHERE each line came from (so nothing walks into the scope on its own),
    # WHOSE WORDS it is in (a model's suggestion and a person's decision must not look alike),
    # and whether an unanswered query has been turned into an assumption somebody accepted.
    #
    # `source_ref` is what makes mapping one-way and idempotent: the sources list is derived on
    # every read from the register, the RFI store and the change log, and a source is "already
    # mapped" precisely when a row here points at it.
    """
    CREATE TABLE IF NOT EXISTS client_boq_scope_items (
        set_id      TEXT NOT NULL,
        item_id     TEXT NOT NULL,
        section     TEXT NOT NULL DEFAULT 'qualifications',  -- one of SCOPE_SECTIONS
        title       TEXT NOT NULL DEFAULT '',
        badge       TEXT NOT NULL DEFAULT 'ai',              -- ai | user — whose words these are
        is_fallback INTEGER NOT NULL DEFAULT 0,   -- stands in for an answer the client never gave
        accepted    INTEGER NOT NULL DEFAULT 0,   -- a fallback nobody accepted is NOT priced
        text        TEXT NOT NULL DEFAULT '',     -- goes into the offer letter word for word
        source_ref  TEXT NOT NULL DEFAULT '',     -- the source it was mapped from ('' = written here)
        updated_at  TEXT,
        PRIMARY KEY (set_id, item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS client_boq_letters (
        set_id      TEXT PRIMARY KEY,
        letter_json TEXT NOT NULL DEFAULT '{}'         -- the assembled LetterOfOffer (draft)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS client_boq_manifests (
        set_id        TEXT PRIMARY KEY,
        manifest_json TEXT NOT NULL DEFAULT '{}',      -- the SplitManifest (the edit surface)
        tier          INTEGER NOT NULL DEFAULT 1,      -- confidence ladder 1..4
        approved      INTEGER NOT NULL DEFAULT 0,      -- the manifest gate (0/1) — the FIRST gate
        approved_at   TEXT
    )
    """,
    _PARTS_DDL,
    # Every file that ever entered the set, in arrival order. An addendum is a document in its
    # own right (the real package ships "Tender Addendum No.1.pdf" alongside its replacements),
    # and `seq` is what lets the history be replayed to any point: "the tender as at TA#1".
    """
    CREATE TABLE IF NOT EXISTS client_boq_documents (
        set_id      TEXT NOT NULL,
        doc_id      TEXT NOT NULL,
        filename    TEXT NOT NULL DEFAULT '',
        kind        TEXT NOT NULL DEFAULT 'base',      -- base|correction|addendum|clarification
        ref         TEXT NOT NULL DEFAULT '',          -- e.g. "Tender Addendum No.1"
        seq         INTEGER NOT NULL DEFAULT 0,        -- arrival order; the "tab" ordering
        received_at TEXT NOT NULL DEFAULT (datetime('now')),
        note        TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (set_id, doc_id)
    )
    """,
    # One row per revision of a part. NOTHING here is ever deleted or overwritten by a new
    # revision: Rev 0 survives Rev 1 (the user's rule), so the history can always be read back.
    # The operative revision is simply the highest rev, derived rather than stored, so no flag
    # can drift out of step with reality.
    """
    CREATE TABLE IF NOT EXISTS client_boq_part_revisions (
        set_id       TEXT NOT NULL,
        part_id      TEXT NOT NULL,
        rev          INTEGER NOT NULL DEFAULT 0,
        doc_id       TEXT NOT NULL DEFAULT '',         -- the document that introduced this revision
        start_page   INTEGER NOT NULL DEFAULT 1,       -- 1-based inclusive, in that document
        end_page     INTEGER NOT NULL DEFAULT 1,
        scanned      INTEGER NOT NULL DEFAULT 0,
        source_doc   TEXT NOT NULL DEFAULT '',         -- the filename the pages were cut from
        pdf_path     TEXT NOT NULL DEFAULT '',         -- where this revision was materialised
        context_json TEXT NOT NULL DEFAULT '{}',       -- the PartContext (interpreted twin)
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (set_id, part_id, rev)
    )
    """,
    # The change table an addendum declares about itself. ADVISORY ONLY: Tender Addendum No.1
    # states its own remarks are "neither exhaustive nor guaranteed to be accurate" and that the
    # tenderer must check the replacement pages. So this navigates the human to the right pages;
    # it is never the operative record of what changed.
    # Questions to the client. `status` is the lifecycle; `answered_by` records which document
    # carried the reply, so an answer that arrived as an addendum is traceable to it.
    """
    CREATE TABLE IF NOT EXISTS client_boq_rfi_items (
        set_id        TEXT NOT NULL,
        rfi_id        TEXT NOT NULL,
        number        INTEGER NOT NULL DEFAULT 0,
        origin        TEXT NOT NULL DEFAULT 'register',
        register_item INTEGER,
        part_id       TEXT NOT NULL DEFAULT '',
        clause        TEXT NOT NULL DEFAULT '',
        page          INTEGER,
        question      TEXT NOT NULL DEFAULT '',
        context       TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'draft',
        batch_id      TEXT NOT NULL DEFAULT '',
        answer        TEXT NOT NULL DEFAULT '',
        answered_by   TEXT NOT NULL DEFAULT '',
        raised_at     TEXT NOT NULL DEFAULT (datetime('now')),
        answered_at   TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (set_id, rfi_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS client_boq_rfi_batches (
        set_id    TEXT NOT NULL,
        batch_id  TEXT NOT NULL,
        ref       TEXT NOT NULL DEFAULT '',
        sent_at   TEXT NOT NULL DEFAULT '',
        letter_md TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (set_id, batch_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS client_boq_changes (
        set_id      TEXT NOT NULL,
        change_id   TEXT NOT NULL,
        doc_id      TEXT NOT NULL DEFAULT '',
        part_id     TEXT NOT NULL DEFAULT '',          -- blank until mapped to a part
        kind        TEXT NOT NULL DEFAULT 'replace-pages',
        pages       TEXT NOT NULL DEFAULT '',          -- as the addendum prints it, e.g. "PS7/45"
        description TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (set_id, change_id)
    )
    """,
]


def _migrate_parts_to_revisions(conn: sqlite3.Connection) -> None:
    """One-time, idempotent move of pre-revision part rows into the revision model.

    Before revisions existed, ``client_boq_parts`` carried the page range, the cut PDF path and
    the interpreted context directly. Those columns now live in ``client_boq_part_revisions``.
    A part's context costs real model calls to produce, so this copies the existing rows forward
    as Rev 0 rather than dropping them and making the user re-ingest.

    Detected by shape, not by a version number, because this repo has no migration framework.
    A no-op on any database created after the change.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(client_boq_parts)")}
    if not columns or "start_page" not in columns:
        return  # either no table yet, or already the new shape

    # Read only what this particular database actually has. `CREATE TABLE IF NOT EXISTS` never
    # alters an existing table, so a long-lived database can be sitting on ANY earlier column set
    # — a scratch DEMO database here was still missing `source_doc`, added mid-development. Ask
    # for a column that is not there and the whole migration dies on a SELECT.
    wanted = ["set_id", "part_id", "n", "abbr", "slug", "title", "category",
              "start_page", "end_page", "scanned", "source_doc", "pdf_path", "context_json"]
    available = [c for c in wanted if c in columns]
    rows = [
        dict(row) for row in conn.execute(f"SELECT {', '.join(available)} FROM client_boq_parts")
    ]
    defaults = {"n": 0, "abbr": "", "slug": "", "title": "", "category": "other",
                "start_page": 1, "end_page": 1, "scanned": 0, "source_doc": "",
                "pdf_path": "", "context_json": "{}"}
    rows = [{**defaults, **row} for row in rows]

    for row in rows:
        # The pre-revision world had exactly one document per set: the original upload.
        conn.execute(
            """
            INSERT OR IGNORE INTO client_boq_documents (set_id, doc_id, filename, kind, ref, seq)
            VALUES (?, 'doc-0', ?, ?, 'As issued', 0)
            """,
            (row["set_id"], row["source_doc"] or "", DOC_BASE),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO client_boq_part_revisions
                (set_id, part_id, rev, doc_id, start_page, end_page, scanned, source_doc,
                 pdf_path, context_json)
            VALUES (?, ?, 0, 'doc-0', ?, ?, ?, ?, ?, ?)
            """,
            (row["set_id"], row["part_id"], row["start_page"], row["end_page"], row["scanned"],
             row["source_doc"], row["pdf_path"], row["context_json"]),
        )

    conn.execute("ALTER TABLE client_boq_parts RENAME TO client_boq_parts_pre_revisions")
    conn.execute(_PARTS_DDL)  # recreate it in the slim, identity-only shape
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO client_boq_parts (set_id, part_id, n, abbr, slug, title, category)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (row["set_id"], row["part_id"], row["n"], row["abbr"], row["slug"], row["title"],
             row["category"]),
        )
    conn.execute("DROP TABLE client_boq_parts_pre_revisions")
    conn.commit()


def init_tables(conn: sqlite3.Connection) -> None:
    """Create the ``client_boq_*`` tables if absent (idempotent). Deterministic infra, not workflow
    logic. Call once per connection before touching the module's tables.

    The DDL runs FIRST so the revision tables exist for the migration to write into; the
    ``CREATE TABLE IF NOT EXISTS`` for parts is a no-op while an old-shaped table is still there,
    and the migration replaces it.
    """
    for stmt in _DDL:
        conn.execute(stmt)
    _migrate_parts_to_revisions(conn)
    conn.commit()
