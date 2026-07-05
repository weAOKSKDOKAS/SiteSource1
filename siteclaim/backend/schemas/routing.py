"""Typed contracts for the routing gate (Phase 1) — self-perform vs sublet.

After ingest splits a tender into packages, the AI recommends a route per package with a
rationale (advisory); a human confirms each (the Layer-4 gate). See mega-prompt Phase 1.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from schemas.models import ScopePackages

# The two routes.
SELF_PERFORM = "self_perform"
SUBLET = "sublet"
ROUTES = (SELF_PERFORM, SUBLET)


class RoutePackage(BaseModel):
    """One package's routing state: the AI recommendation + the deterministic signal, and
    the human's decision once made."""

    id: Optional[int] = None
    package_key: str
    trade: str = ""
    scope_summary: str = ""
    recommended_route: str = SUBLET
    rationale: str = ""
    signals: dict = Field(default_factory=dict)
    chosen_route: Optional[str] = None   # null until a human decides (the L4 gate)
    decided_by: str = ""
    decided_at: str = ""
    source: str = ""


class RouteProposal(BaseModel):
    run_ref: str
    packages: list[RoutePackage] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    scope: ScopePackages
    run_ref: str = ""            # defaults to a slug of scope.project_name


class RouteDecision(BaseModel):
    package_key: str
    chosen_route: str            # self_perform | sublet


class ConfirmRoutesRequest(BaseModel):
    run_ref: str
    decisions: list[RouteDecision] = Field(default_factory=list)
    decided_by: str = "operator"
    scope: Optional[ScopePackages] = None   # supplied so a self-perform decision seeds its estimate (P4b)


class RouteDecisionResult(BaseModel):
    run_ref: str
    packages: list[RoutePackage] = Field(default_factory=list)
    sublet_packages: list[str] = Field(default_factory=list)        # -> existing shortlist path
    self_perform_packages: list[str] = Field(default_factory=list)  # -> estimator (Phase 3)
    estimate_ids: dict[str, int] = Field(default_factory=dict)      # package_key -> seeded estimate id (P4b)


# -- the LLM output (parsed by complete_json) --------------------------------
class RouteSuggestion(BaseModel):
    package_key: str
    recommended_route: str = SUBLET
    rationale: str = ""


class RouteSuggestionSet(BaseModel):
    suggestions: list[RouteSuggestion] = Field(default_factory=list)
