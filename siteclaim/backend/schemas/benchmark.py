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
