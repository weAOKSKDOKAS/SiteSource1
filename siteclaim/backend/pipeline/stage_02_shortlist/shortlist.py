"""Stage 02 — shortlist: ScopePackages + the database -> ShortlistSet.

For each trade in the scope this calls :func:`db.cross_reference.cross_reference`
to get :class:`Candidate` objects — firms that do the trade, scored by the semantic
relevance of their closeout history to the package's ``scope_summary``, each
carrying cited evidence and the risk flags adjudicated by ``rules_engine``. Ranking
(``rules_engine.ranking``) then demotes any firm with a fatal flag below every clean
firm, regardless of how well it matches.

This is **pure Layer 1 over the database** — the LLM is not asked to rank or to
invent a flag, so the shortlist is deterministic and reproduces identically on every
run. The database is already offline, so DEMO_MODE needs no LLM call and no fixture
here; ``demo_fixture`` is accepted only to keep the stage signatures uniform.

This stage carries the demo hero: for the electrical trade the cheapest, strongest-
matching firm (``F-EL-01``) surfaces but is demoted and marked
``recommended_against`` by its fatal winding-up flag, with the clean runner-up
(``F-EL-02``) on top and all evidence attached and citable.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from db import store
from db.cross_reference import cross_reference
from rules_engine.taxonomy import base_trade, parent_trade, section_specialty
from schemas.models import ScopePackages, ShortlistSet, TradeWorkPackage


def _section_specialty_for(pkg: TradeWorkPackage) -> Optional[str]:
    """The GI specialty pool this package's section shortlists against, or ``None`` to keep the
    parent trade. Prefers the specialty annotated at ingest (a single-section package's
    ``section_trade``); else the section's own TITLE. Only a real specialty whose parent is this
    package's trade is used — so a non-GI package (electrical, mechanical) never leaves its own
    pool.

    **THE ITEM SAMPLE DOES NOT CHOOSE THE POOL.** This matched over `pkg.scope_summary`, and for a
    routed sub-package that string is `_summary`'s RENDERING — `Section 2 — DRILLING (28 items):`
    followed by the first four item descriptions. So a single description mentioning "geophysical"
    among 28 rotary-drilling items moved the whole section to the geophysical pool, and which four
    descriptions were sampled is decided by document order. A sample is evidence for a reader,
    never a signal: the title is what names the section.
    """
    from pipeline.routing.split import summary_heading

    parent = base_trade(pkg.trade)
    sole = pkg.sections[0] if len(pkg.sections) == 1 else None
    stored = sole.section_trade if sole else ""
    # A declared title first; otherwise the summary's HEADING (a whole-trade package's summary is
    # an LLM sentence with no rendering to strip, and `summary_heading` returns it unchanged).
    from_title = (section_specialty(sole.title) if sole and sole.title else None)
    cand = stored or from_title or section_specialty(summary_heading(pkg.scope_summary or "")) or ""
    return cand if (cand and cand != parent and parent_trade(cand) == parent) else None


def shortlist(
    scope: ScopePackages,
    demo_fixture: Optional[str] = None,  # noqa: ARG001 — deterministic over the offline DB
    *,
    conn: Optional[sqlite3.Connection] = None,
    include_public: bool = False,
    k: Optional[int] = None,
) -> ShortlistSet:
    """Return ranked candidates per trade for ``scope``.

    Pass ``conn`` to read a specific database (tests use a temp seed); otherwise the
    packaged ``sitesource.db`` is opened and closed here. ``include_public=True``
    opens the shortlist to the full screened public-record pool (the live-engine
    path); the default keeps the assessed-firm behaviour the demo scenarios rely on.
    ``k`` caps each trade's ranked list (a broad public trade can hold 20+ firms —
    nobody dispatches to all of them); ``None`` returns every candidate, as before.
    """
    own_conn = conn is None
    conn = conn or store.get_connection()
    try:
        # Keyed by package_key (pkg.trade holds it for a section sub-package). The DB read runs
        # against the parent trade, but a GI section shortlists against its own specialty pool
        # (field_testing / field_installations / geophysical_survey) with the parent as the
        # thin-pool fallback — so G, H and J no longer draw the identical coarse GI list.
        per_trade = {
            pkg.trade: cross_reference(
                conn, base_trade(pkg.trade), pkg.scope_summary, k=k,
                include_public=include_public, specialty=_section_specialty_for(pkg),
            )
            for pkg in scope.packages
        }
    finally:
        if own_conn:
            conn.close()
    return ShortlistSet(per_trade=per_trade)
