"""Typed contracts for the Benchmark estimator (Phase B1).

Kept in a dedicated module (not ``schemas.models``) because the estimating track is a
distinct feature surface. Money/quantities are ``Optional[float]`` throughout — a
Schedule of Rates is rate-primary and rate-only lines are first-class (mirrors
``BidLineItem``). See ``docs/PRODUCT_ARCHITECTURE_benchmark_estimator.md``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
class Project(BaseModel):
    id: int
    name: str
    trade: str = ""
    client: str = ""
    contract_ref: str = ""
    status: str = "open"            # open | closed
    provenance: str = "live"        # demo | live (the /benchmark/summary discriminator)
    source: str = ""               # tender-upload | pipeline-link | manual | demo
    notes: str = ""
    created_at: str = ""
    closed_at: str = ""
    tender_item_count: int = 0
    actual_item_count: int = 0
    variance_count: int = 0


class ProjectCreate(BaseModel):
    name: str
    trade: str = ""
    client: str = ""
    contract_ref: str = ""
    notes: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    trade: Optional[str] = None
    client: Optional[str] = None
    contract_ref: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None    # 'open' | 'closed'


# ---------------------------------------------------------------------------
# Tender snapshot (the priced tender)
# ---------------------------------------------------------------------------
class TenderItem(BaseModel):
    id: int
    project_id: int
    item_ref: str
    description: str = ""
    unit: str = ""
    qty: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None
    section: str = ""
    source: str = ""
    source_doc: str = ""


class TenderUploadResponse(BaseModel):
    project_id: int
    source: str
    item_count: int
    items: list[TenderItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Actuals (the outturn / final account)
# ---------------------------------------------------------------------------
class ActualItem(BaseModel):
    id: int
    project_id: int
    item_ref: str = ""
    description: str = ""
    unit: str = ""
    qty: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None
    section: str = ""
    granularity: str = "item"       # item | section | project
    source: str = ""
    source_doc: str = ""


class ActualsUploadResponse(BaseModel):
    project_id: int
    source: str
    item_count: int
    granularities: list[str] = Field(default_factory=list)  # distinct granularities seen
    items: list[ActualItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reason vocabulary
# ---------------------------------------------------------------------------
class ReasonCode(BaseModel):
    code: str
    label: str
    description: str = ""
    category: str = ""


# ---------------------------------------------------------------------------
# Matching (the tiered proposal — the confirm gate is the sole writer)
# ---------------------------------------------------------------------------
class MatchPair(BaseModel):
    tier: int                       # 1 exact | 2 embedding | 3 unmatched
    similarity: Optional[float] = None
    tender: Optional[TenderItem] = None
    actual: Optional[ActualItem] = None


class MatchProposal(BaseModel):
    project_id: int
    tier1: list[MatchPair] = Field(default_factory=list)
    tier2: list[MatchPair] = Field(default_factory=list)
    tier3: list[MatchPair] = Field(default_factory=list)


class MatchConfirm(BaseModel):
    tender_item_id: Optional[int] = None
    actual_item_id: Optional[int] = None
    match_tier: int = 3


class ConfirmMatchesRequest(BaseModel):
    confirm: list[MatchConfirm] = Field(default_factory=list)
    confirmed_by: str = "operator"


# ---------------------------------------------------------------------------
# Variance records
# ---------------------------------------------------------------------------
class VarianceRecord(BaseModel):
    id: int
    project_id: int
    tender_item_id: Optional[int] = None
    actual_item_id: Optional[int] = None
    item_ref: str = ""
    granularity: str = "item"
    match_tier: Optional[int] = None
    tender_rate: Optional[float] = None
    actual_rate: Optional[float] = None
    tender_qty: Optional[float] = None
    actual_qty: Optional[float] = None
    tender_amount: Optional[float] = None
    actual_amount: Optional[float] = None
    rate_delta: Optional[float] = None
    rate_delta_pct: Optional[float] = None
    amount_delta: Optional[float] = None
    amount_delta_qty: Optional[float] = None
    amount_delta_rate: Optional[float] = None
    reason_code: str = ""
    reason_note: str = ""
    tagged_by: str = ""
    confirmed_at: str = ""
    source: str = ""
    suggested_reason: Optional[str] = None  # a deterministic hint; the human still sets the code


class ReasonRequest(BaseModel):
    reason_code: str
    note: str = ""
    tagged_by: str = "operator"


class BenchmarkSummary(BaseModel):
    projects: int = 0
    tender_items: int = 0
    actual_items: int = 0
    variance_records: int = 0
    reasoned_records: int = 0
    coverage_by_trade: dict[str, int] = Field(default_factory=dict)
    coverage_by_granularity: dict[str, int] = Field(default_factory=dict)
