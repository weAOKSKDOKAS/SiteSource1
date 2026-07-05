"""Typed contracts for the unified project dashboard (Phase 4).

A read-model that assembles a tender's run across the tracks — routing decisions, the
left-track estimates, and the benchmark link — from the existing tables keyed by ``run_ref``.
No cost data lives here; the benchmark tables stay authoritative.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from schemas.estimate import EstimateProject


class DashboardPackage(BaseModel):
    package_key: str
    trade: str = ""
    scope_summary: str = ""
    recommended_route: str = ""
    chosen_route: Optional[str] = None
    track: str = "undecided"           # left (self-perform) | right (sublet) | undecided
    estimate_id: Optional[int] = None  # the seeded left-track estimate, when present
    decided_by: str = ""


class ProjectSummary(BaseModel):
    run_ref: str
    name: str = ""
    provenance: str = "live"
    package_count: int = 0
    self_perform_count: int = 0
    sublet_count: int = 0
    estimate_count: int = 0
    benchmark_project_id: Optional[int] = None


class ProjectDashboard(BaseModel):
    run_ref: str
    name: str = ""
    provenance: str = "live"
    packages: list[DashboardPackage] = Field(default_factory=list)
    estimates: list[EstimateProject] = Field(default_factory=list)
    benchmark_project_id: Optional[int] = None
