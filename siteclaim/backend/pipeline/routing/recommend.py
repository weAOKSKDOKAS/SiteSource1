"""The AI route recommendation (Phase P1c — Layer 2, suggestion only).

One batched ``complete_json`` call (purpose ``route-suggest``): given each package's scope
plus its Layer-1 signal, draft self-perform vs sublet + a rationale. It RECOMMENDS; a human
decides. DEMO reads a baked fixture. A deterministic FALLBACK guarantees a recommendation
even with no key / no network / a package the model didn't cover — so routing never
hard-fails and always has a proposal to show.
"""

from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from pipeline.llm_client import LLMClient, demo_mode
from schemas.routing import ROUTES, SELF_PERFORM, SUBLET, RouteSuggestionSet

ROUTE_SUGGESTIONS_FIXTURE = "cases/routing/route_suggestions.json"

_SYSTEM = (
    "You advise a Hong Kong main contractor whether to SELF-PERFORM a work package in-house "
    "or SUBLET it to a subcontractor. For each package you get its trade, a scope summary, "
    "and a deterministic coverage signal (register firms, assessable subcontractors, whether "
    "the pool is thin, and our in-house history). Recommend a route per package with a "
    "one-sentence rationale grounded in that signal. You RECOMMEND only — a human decides. "
    'Return JSON: {"suggestions": [{"package_key": <string>, "recommended_route": '
    '"self_perform" | "sublet", "rationale": <string>}]} — one entry per package.'
)


def _prompt(packages: list[dict]) -> str:
    lines = []
    for p in packages:
        s = p.get("signals", {})
        lines.append(
            f"- package_key={p['package_key']} trade={p.get('trade', '')} | "
            f"firms={s.get('trade_firm_count')} assessable={s.get('assessable_firm_count')} "
            f"thin_pool={s.get('thin_pool')} in_house_history={s.get('in_house_history')} | "
            f"scope: {(p.get('scope_summary') or '')[:200]}"
        )
    return "Packages:\n" + "\n".join(lines) + "\n\nRecommend a route per package."


def fallback_route(signal: dict) -> tuple[str, str]:
    """A deterministic route + rationale from the Layer-1 signal alone (no LLM). Always
    returns a valid route, so a recommendation always exists."""
    thin = bool(signal.get("thin_pool"))
    assessable = int(signal.get("assessable_firm_count") or 0)
    firms = int(signal.get("trade_firm_count") or 0)
    in_house = int(signal.get("in_house_history") or 0)
    if in_house > 0 and not thin:
        return SELF_PERFORM, f"Strong in-house history ({in_house} prior project(s)) and a broad pool — self-perform is viable."
    if thin and assessable >= 1:
        return SUBLET, f"Specialist trade with a thin in-house pool but {assessable} assessable subcontractor(s) — sublet."
    if assessable >= 2:
        return SUBLET, f"{assessable} assessable subcontractors available — sublet for competitive tension."
    if assessable == 0 and firms == 0:
        return SELF_PERFORM, "No subcontractor pool for this trade — self-perform."
    return SUBLET, f"{assessable} assessable subcontractor(s) available — sublet."


def recommend_routes(
    packages: list[dict], *, demo_fixture: Optional[str] = None, client: Optional[LLMClient] = None,
) -> list[dict]:
    """Return ``packages`` each augmented with ``recommended_route``, ``rationale``, and
    ``source`` (``route-suggest`` when the model covered it, else ``fallback``)."""
    client = client or LLMClient()
    index: dict[str, tuple[str, str]] = {}
    if demo_fixture or not demo_mode():
        try:
            drafted = client.complete_json(
                system=_SYSTEM, user=_prompt(packages), target_model=RouteSuggestionSet,
                demo_fixture=demo_fixture, purpose="route-suggest",
            )
            index = {
                s.package_key: (s.recommended_route, s.rationale)
                for s in drafted.suggestions if s.recommended_route in ROUTES
            }
        except (RuntimeError, FileNotFoundError, ValidationError, ValueError):
            index = {}

    out: list[dict] = []
    for p in packages:
        hit = index.get(p["package_key"])
        if hit:
            route, rationale, source = hit[0], hit[1], "route-suggest"
        else:
            route, rationale = fallback_route(p.get("signals", {}))
            source = "fallback"
        out.append({**p, "recommended_route": route, "rationale": rationale, "source": source})
    return out
