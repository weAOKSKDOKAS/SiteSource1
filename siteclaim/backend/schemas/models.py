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

from pydantic import BaseModel, Field, model_validator


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
    """Lifecycle of a :class:`DispatchBundle`.

    ``sent_mock`` is the offline/demo transport (recorded to a JSON outbox, no
    network). ``sent`` is a real email genuinely handed to an SMTP server on the
    live path; ``send_failed`` records a firm the mailer could not send to (e.g. no
    address-book contact), so a partial send is never silently swallowed.
    """

    DRAFTED = "drafted"
    APPROVED = "approved"
    SENT_MOCK = "sent_mock"
    SENT = "sent"
    SEND_FAILED = "send_failed"


class AttachmentKind(str, Enum):
    """What role a :class:`BundleAttachment` plays in a dispatched bundle.

    ``general`` documents every trade needs (form of tender, conditions, general
    preliminaries); ``trade_specific`` documents routed to one trade only; and the
    ``sor_sheet`` — the per-trade Schedule-of-Rates excerpt the pipeline generates
    for the subcontractor to price.
    """

    GENERAL = "general"
    TRADE_SPECIFIC = "trade_specific"
    SOR_SHEET = "sor_sheet"


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
    qty: Optional[float] = None  # a real SoR line often has no quantity column


class TradeWorkPackage(BaseModel):
    """The scope for one trade, split out of the tender."""

    trade: str
    scope_summary: str
    sor_items: list[SorItem] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)  # which tender doc each came from

    @model_validator(mode="before")
    @classmethod
    def _accept_package_name_drift(cls, data):
        """Robustness shim: some models (observed on Sonnet 5) name the field
        ``package_name`` instead of ``trade``. If a package carries ``package_name``
        but no ``trade``, move it — so a minor drift degrades to a normalisable trade
        (Layer 1's ``validate_scope`` still maps it) instead of a 500 and a
        corrective-retry. Narrow by design: the ingest prompt is the real fix; this
        only catches that exact drift and does nothing when ``trade`` is present."""
        if isinstance(data, dict) and data.get("package_name") and not data.get("trade"):
            data = {**data, "trade": data["package_name"]}
        return data


class TenderDocument(BaseModel):
    doc_type: DocType
    filename: str
    trades: list[str] = Field(default_factory=list)  # empty = general (every trade); else routed only to these


class TenderPackage(BaseModel):
    """Stage 01 input: the four tender documents for a project."""

    project_name: str
    description: str = ""
    documents: list[TenderDocument] = Field(default_factory=list)


class ScopePackages(BaseModel):
    """Stage 01 output: the tender split into one package per trade."""

    project_name: str = ""  # injected from the tender in ingest; a model may omit it
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


class Contact(BaseModel):
    """A subcontractor address-book entry (Layer 3) — where a trade's RFQ is sent."""

    firm_id: str
    trade: str
    email: str
    contact_name: str = ""
    phone: str = ""
    note: str = ""


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
class BundleAttachment(BaseModel):
    """A real file to attach to a firm's dispatch email (Phase A document routing).

    ``source_path`` is the file on disk to attach when it exists (a whole tender
    document routed to this trade, or the generated SoR sheet). It is ``None`` when
    the bundle is described but no working file has been produced yet (the offline
    demo, where the tender filenames are labels rather than real uploads). The
    mailer attaches only the attachments whose ``source_path`` points at a real file.
    """

    filename: str
    kind: AttachmentKind
    trade: Optional[str] = None  # None for a general document; set for trade-specific / SoR sheet
    source_path: Optional[str] = None
    generated: bool = False  # True for the SoR sheet the pipeline produces (a derived excerpt)
    label: str = ""


class DispatchBundle(BaseModel):
    """The document bundle + composed email sent to one firm.

    ``bundle_doc_refs`` are the human-readable labels shown in the UI/outbox;
    ``attachments`` are the routed real files (general docs + this trade's docs + the
    generated SoR sheet) the mailer actually attaches on the live path.
    """

    firm_id: str
    firm_name: str
    trade: str
    bundle_doc_refs: list[str] = Field(default_factory=list)  # only this trade's docs (labels)
    attachments: list[BundleAttachment] = Field(default_factory=list)
    email_subject: str = ""
    email_body: str = ""
    status: DispatchStatus = DispatchStatus.DRAFTED


class DispatchSet(BaseModel):
    """Stage 03 output: the per-firm bundles."""

    bundles: list[DispatchBundle] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_bundle_list(cls, data):
        """Robustness shim: a model sometimes returns a bare top-level array of bundle
        objects instead of the ``{"bundles": [...]}`` envelope. Wrap it — the content is
        right, only the envelope is wrong. Narrow by design: the compose prompt is the
        real fix; this only catches that exact drift and is a no-op when the model
        already returns the object."""
        if isinstance(data, list):
            return {"bundles": data}
        return data


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
    "AttachmentKind",
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
    "Contact",
    "Candidate",
    "ShortlistSet",
    # stage 03
    "BundleAttachment",
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
