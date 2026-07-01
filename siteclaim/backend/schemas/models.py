"""SiteSource typed data contracts — the plain-data handoff between stages.

Every pipeline stage consumes and produces the Pydantic v2 models defined here.
No shared mutable state, no framework "memory": a stage reads one or more of these
objects, does its work, and writes the next. Every model is JSON-serialisable
(``model_dump_json`` / ``model_validate_json``), so a stage boundary can be an
in-process call, a fixture on disk, or an HTTP payload — the contract is identical.

Layering reminder (see ``CLAUDE.md``):

* **Layer 2 (Claude)** populates :class:`ScopePackages`, :class:`BidReply`, the
  email bodies on :class:`DispatchBundle`, and the recommendation rationale.
* **Layer 1 (rules engine)** populates :class:`RiskFlag`, :class:`ArithmeticFinding`,
  :class:`LevelledBid`, and the ranking on :class:`Recommendation`.
* **Layer 3 (database)** populates :class:`FirmProfile` and :class:`Evidence`.

The LLM never invents a number, a risk flag, or a ranking — those come from Layer 1
and the database. Provenance is first-class: every signal carries :class:`Evidence`
with a source and a citable reference; every candidate carries a ``match_score``.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class Severity(str, Enum):
    """Shared severity scale for risk flags and arithmetic findings."""

    FATAL = "fatal"  # demotes/excludes a firm regardless of price
    WARNING = "warning"  # a concern the human reviewer should weigh
    INFO = "info"  # advisory / informational only


class SignalType(str, Enum):
    """The kind of database signal an :class:`Evidence` records."""

    GRADE = "grade"
    AWARD_HISTORY = "award_history"
    SAFETY_PROSECUTION = "safety_prosecution"
    WINDING_UP = "winding_up"
    DEBARMENT = "debarment"
    ADJUDICATION = "adjudication"
    DISTRESS_FILING = "distress_filing"  # financial-distress filing short of winding-up
    CLOSEOUT_PERFORMANCE = "closeout_performance"
    PRICING = "pricing"


class DocType(str, Enum):
    """The four tender documents that make up a :class:`TenderPackage`."""

    METHOD_OF_MEASUREMENT = "method_of_measurement"
    PARTICULAR_SPECIFICATION = "particular_specification"
    TENDER_ADDENDUM = "tender_addendum"
    SCHEDULE_OF_RATES = "schedule_of_rates"


class DispatchStatus(str, Enum):
    """Lifecycle of a :class:`DispatchBundle` (mock outbox — nothing is really sent)."""

    DRAFTED = "drafted"
    APPROVED = "approved"
    SENT_MOCK = "sent_mock"
    DRAFTED_GMAIL = "drafted_gmail"  # the bundles were POSTed to n8n, which created Gmail drafts


# ---------------------------------------------------------------------------
# Generic primitive (kept from the chassis)
# ---------------------------------------------------------------------------
class Check(BaseModel):
    """A single deterministic rule outcome (generic Layer 1 primitive)."""

    name: str
    passed: bool
    severity: Severity
    rule_ref: str  # which rubric rule fired
    explanation: str


# ---------------------------------------------------------------------------
# Evidence + risk
# ---------------------------------------------------------------------------
class Evidence(BaseModel):
    """A cited database signal — the grounding that a chatbot cannot reach."""

    source: str  # e.g. "Companies Registry", "Project closeout 2024-Tseung Kwan O"
    signal_type: SignalType
    snippet: str
    reference: str  # a citation or URL-like locator


class RiskFlag(BaseModel):
    """A deterministic risk finding from ``rules_engine.risk_scoring``."""

    severity: Severity
    label: str
    rule_ref: str  # which risk rule fired
    evidence: list[Evidence] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 01 — tender ingest -> scope packages
# ---------------------------------------------------------------------------
class SorItem(BaseModel):
    """One Schedule-of-Rates line a trade package is responsible for."""

    item_ref: str
    description: str
    unit: str
    qty: float


class TradeWorkPackage(BaseModel):
    """The scope for one trade, split out of the tender."""

    trade: str
    scope_summary: str
    sor_items: list[SorItem] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)  # which tender doc each came from


class TenderDocument(BaseModel):
    doc_type: DocType
    filename: str


class TenderPackage(BaseModel):
    """Stage 01 input: the four tender documents for a project."""

    project_name: str
    description: str = ""
    documents: list[TenderDocument] = Field(default_factory=list)


class ScopePackages(BaseModel):
    """Stage 01 output: the tender split into one package per trade."""

    project_name: str
    packages: list[TradeWorkPackage] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Layer 3 — firm profiles and shortlist
# ---------------------------------------------------------------------------
class FirmProfile(BaseModel):
    """A subcontractor's fused database record (Layer 3 — the moat)."""

    firm_id: str
    name: str
    registered_grade: str
    value_band: str
    trades: list[str] = Field(default_factory=list)
    public_flags: list[RiskFlag] = Field(default_factory=list)
    closeout_summary: str = ""
    award_history: list[str] = Field(default_factory=list)
    # Register-fused fields (the real CIC register). enquiry_email is what Dispatch
    # reads to draft the enquiry; description is the short factual blurb.
    enquiry_email: str = ""
    description: str = ""
    # The raw registered specialties ({code, group, specialty}) and registration date
    # from the CIC register, kept so the shortlist scorer can tell an exact specialty
    # match from an incidental (GI-expanded) one. Empty for non-register firms.
    registered_trades: list[dict] = Field(default_factory=list)
    reg_date: str = ""


class Candidate(BaseModel):
    """A shortlisted firm for a trade, with its match score, evidence, and risk."""

    firm: FirmProfile
    trade: str
    match_score: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    recommended_against: bool = False  # set by ranking when a fatal flag fires


class ShortlistSet(BaseModel):
    """Stage 02 output: ranked candidates per trade."""

    per_trade: dict[str, list[Candidate]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 03 — dispatch
# ---------------------------------------------------------------------------
class DispatchBundle(BaseModel):
    """The document bundle + composed email sent to one firm (mock outbox)."""

    firm_id: str
    firm_name: str
    trade: str
    bundle_doc_refs: list[str] = Field(default_factory=list)  # only this trade's docs
    email_subject: str = ""
    email_body: str = ""
    status: DispatchStatus = DispatchStatus.DRAFTED


class DispatchSet(BaseModel):
    """Stage 03 output: the per-firm bundles."""

    bundles: list[DispatchBundle] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 04 — bid replies and leveling
# ---------------------------------------------------------------------------
class BidLineItem(BaseModel):
    item_ref: str
    description: str
    unit: str
    qty: float
    rate: Optional[float] = None
    amount: Optional[float] = None


class BidReply(BaseModel):
    """A subcontractor's priced reply (a returned Schedule of Rates)."""

    firm_id: str
    trade: str
    line_items: list[BidLineItem] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    claimed_total: Optional[float] = None


class ArithmeticFinding(BaseModel):
    """A deterministic leveling correction (Layer 1)."""

    location: str  # e.g. 'line_items[3]'
    issue: str
    corrected_value: float
    severity: Severity


class LevelledBid(BaseModel):
    """Stage 04 output: one bid normalized onto the common scope basis."""

    firm_id: str
    firm_name: str
    trade: str
    normalized_total: float
    corrected_total: float
    arithmetic_findings: list[ArithmeticFinding] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    scope_gaps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 05 — recommendation
# ---------------------------------------------------------------------------
class RankedFirm(BaseModel):
    firm_id: str
    firm_name: str
    corrected_total: float
    # Like-for-like total (corrected price + peer-valued scope gaps). Defaults to 0.0
    # for callers that don't carry it; ranking falls back to corrected_total then.
    normalized_total: float = 0.0
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    recommended_against: bool = False
    reason: str = ""


class BidDistributionPoint(BaseModel):
    firm_name: str
    corrected_total: float


class HistoricalBand(BaseModel):
    low: float
    median: float
    high: float


class Recommendation(BaseModel):
    """Stage 05 output: the risk-adjusted recommendation for a trade."""

    trade: str
    recommended_firm_id: Optional[str] = None
    ranked: list[RankedFirm] = Field(default_factory=list)
    rationale: str = ""
    bid_distribution: list[BidDistributionPoint] = Field(default_factory=list)
    historical_band: Optional[HistoricalBand] = None


__all__ = [
    # enums
    "Severity",
    "SignalType",
    "DocType",
    "DispatchStatus",
    # generic primitive
    "Check",
    # evidence + risk
    "Evidence",
    "RiskFlag",
    # stage 01
    "SorItem",
    "TradeWorkPackage",
    "TenderDocument",
    "TenderPackage",
    "ScopePackages",
    # layer 3 + shortlist
    "FirmProfile",
    "Candidate",
    "ShortlistSet",
    # stage 03
    "DispatchBundle",
    "DispatchSet",
    # stage 04
    "BidLineItem",
    "BidReply",
    "ArithmeticFinding",
    "LevelledBid",
    # stage 05
    "RankedFirm",
    "BidDistributionPoint",
    "HistoricalBand",
    "Recommendation",
]
