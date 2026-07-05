"""Typed contracts for the Estimator (Phase 3) — the left-track priced-tender build.

Money/quantities are ``Optional[float]`` throughout: an estimate is rate-primary and
rate-optional, the human prices every line, and a quantity is never invented. See the
mega-prompt Phase 3 and ``docs/PRODUCT_ARCHITECTURE_benchmark_estimator.md``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from schemas.models import TradeWorkPackage


# ---------------------------------------------------------------------------
# Estimate project
# ---------------------------------------------------------------------------
class EstimateProject(BaseModel):
    id: int
    name: str
    trade: str = ""
    client: str = ""
    contract_ref: str = ""
    status: str = "draft"          # draft | submitted | awarded | closed
    provenance: str = "live"       # demo | live
    source: str = ""               # routing | manual | from-package
    run_ref: str = ""
    package_key: str = ""
    scope_of_works: str = ""
    notes: str = ""
    created_at: str = ""
    closed_at: str = ""
    item_count: int = 0
    priced_item_count: int = 0
    total: Optional[float] = None  # sum of the computable amounts only (never fabricated)


class EstimateProjectCreate(BaseModel):
    name: str
    trade: str = ""
    client: str = ""
    contract_ref: str = ""
    notes: str = ""


class EstimateProjectUpdate(BaseModel):
    name: Optional[str] = None
    trade: Optional[str] = None
    client: Optional[str] = None
    contract_ref: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    scope_of_works: Optional[str] = None


class FromPackageRequest(BaseModel):
    """Seed an estimate from a routed self-perform package (or any TradeWorkPackage). The
    package's SoR items become the initial estimate lines (unpriced — the human prices)."""

    package: TradeWorkPackage
    project_name: str = ""
    run_ref: str = ""
    client: str = ""
    contract_ref: str = ""


# ---------------------------------------------------------------------------
# Estimate items
# ---------------------------------------------------------------------------
class EstimateItem(BaseModel):
    id: int
    estimate_id: int
    item_ref: str
    description: str = ""
    unit: str = ""
    qty: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None
    section: str = ""
    source: str = ""


class EstimateItemInput(BaseModel):
    item_ref: str
    description: str = ""
    unit: str = ""
    qty: Optional[float] = None
    rate: Optional[float] = None
    section: str = ""


class EstimateItemsRequest(BaseModel):
    items: list[EstimateItemInput] = Field(default_factory=list)


class EstimateItemUpdate(BaseModel):
    description: Optional[str] = None
    unit: Optional[str] = None
    qty: Optional[float] = None
    rate: Optional[float] = None
    section: Optional[str] = None


# ---------------------------------------------------------------------------
# Draft (P3b) — the L2 scope-of-works + candidate item skeleton. The model proposes
# item refs/descriptions/units only; it never invents a quantity or a rate.
# ---------------------------------------------------------------------------
class EstimateDraftItem(BaseModel):
    item_ref: str = ""
    description: str = ""
    unit: str = ""


class EstimateDraft(BaseModel):
    """The LLM output (parsed by ``complete_json``)."""

    scope_of_works: str = ""
    items: list[EstimateDraftItem] = Field(default_factory=list)


class EstimateDraftResult(BaseModel):
    """The draft endpoint's response: the refreshed estimate plus what the draft added."""

    estimate: EstimateProject
    scope_of_works: str = ""
    added_item_refs: list[str] = Field(default_factory=list)
    trade_mapped: bool = True   # False when the trade is off-taxonomy (surfaced, never dropped)


# ---------------------------------------------------------------------------
# Rate precedent (P3c) — corpus-gated. Retrieval only; the person prices.
# ---------------------------------------------------------------------------
class RateWarning(BaseModel):
    reason_code: str
    count: int = 0


class RatePrecedent(BaseModel):
    item_id: Optional[int] = None
    item_ref: str = ""
    tier: int = 0                 # 1 exact ref | 2 similar description | 0 no precedent
    matched_ref: str = ""
    similarity: Optional[float] = None
    sample_count: int = 0
    rate_low: Optional[float] = None
    rate_median: Optional[float] = None
    rate_high: Optional[float] = None
    rate_warnings: list[RateWarning] = Field(default_factory=list)


class RateSuggestions(BaseModel):
    estimate_id: int
    corpus_empty: bool = True     # True in live pre-archive — the honest empty state
    corpus_size: int = 0
    suggestions: list[RatePrecedent] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Error / omission check (P3d) — reports only; never edits or prices.
# ---------------------------------------------------------------------------
class EstimateFinding(BaseModel):
    kind: str                     # omission | unit_mismatch | unpriced | rubric | scope_gap
    severity: str = "warning"     # warning | info
    item_ref: str = ""
    message: str = ""
    source: str = ""              # rules | rubric | estimate-check


class EstimateCheckRequest(BaseModel):
    """The tender requirements to check the estimate against (optional — when empty, the
    omission/unit checks are skipped and only the rubric + unpriced checks run)."""

    tender: list[EstimateItemInput] = Field(default_factory=list)


class EstimateCheckResult(BaseModel):
    estimate_id: int
    findings: list[EstimateFinding] = Field(default_factory=list)
    tender_checked: bool = False
    rubric_size: int = 0


class EstimateScopeGap(BaseModel):
    item_ref: str = ""
    message: str = ""


class EstimateCheckDraft(BaseModel):
    """The L2 output (parsed by ``complete_json``) — scope obligations with no priced line."""

    scope_gaps: list[EstimateScopeGap] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Letter of offer (P3e) — a draft; the person owns and issues the final letter.
# ---------------------------------------------------------------------------
class LetterOfOffer(BaseModel):
    subject: str = ""
    body: str = ""
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Estimate -> benchmark capture (P4c) — a self-performed job feeds the corpus on award.
# ---------------------------------------------------------------------------
class ToBenchmarkResult(BaseModel):
    estimate: EstimateProject
    benchmark_project_id: int
    tender_item_count: int
