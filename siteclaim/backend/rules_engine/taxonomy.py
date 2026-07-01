"""Deterministic work-package taxonomy validation (Layer 1).

The canonical keys are read **from** ``references/rubrics/trade_taxonomy.md`` at
import, so the rubric is the single source of truth across tender domains: a
building/fit-out tender splits by trade (electrical, M&P, fire services); a civil or
ground-investigation tender splits by work section (drilling, sampling, field
testing, field installations, drainage works). This module normalises each
``TradeWorkPackage.trade`` to a canonical key where a known label or synonym matches.

The taxonomy is **advisory, not a whitelist**: a tender may legitimately use a work
package outside the list. An unmatched package is **not** an error and **not**
dropped — it is kept under a slugified form of the tender's own label (a valid
work-package key for any tender type) and surfaced for human review.
"""

from __future__ import annotations

import re
from pathlib import Path

from schemas.models import ScopePackages, TradeWorkPackage

_RUBRIC_PATH = Path(__file__).resolve().parents[1] / "references" / "rubrics" / "trade_taxonomy.md"

# Fallback if the rubric file is ever unreadable (keeps the package importable).
_FALLBACK_KEYS = {
    # building / fit-out
    "foundation_substructure", "structural", "reinforced_concrete", "electrical",
    "mechanical_plumbing", "fire_services", "joinery_fitting_out", "builders_work",
    "external_works",
    # civil / ground investigation
    "ground_investigation", "drilling", "sampling", "field_testing",
    "field_installations", "instrumentation", "drainage_works", "slope_works",
    "site_formation", "roadworks",
}

_ROW_RE = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*([^|]+?)\s*\|")


def _load_canonical() -> tuple[frozenset[str], dict[str, str]]:
    """Return (canonical keys, label->key map) parsed from the rubric tables."""
    keys: set[str] = set()
    labels: dict[str, str] = {}
    try:
        for line in _RUBRIC_PATH.read_text(encoding="utf-8").splitlines():
            match = _ROW_RE.match(line)
            if match:
                key, label = match.group(1), match.group(2)
                keys.add(key)
                labels[label.strip().lower()] = key
    except OSError:
        pass
    if not keys:
        keys = set(_FALLBACK_KEYS)
    return frozenset(keys), labels


CANONICAL_TRADES, _LABELS = _load_canonical()

# Near-synonyms the model is likely to emit -> canonical key. Matched as substrings
# against a normalised (lowercased, separators stripped) form of the work-package
# name. NOTE: "drainage" no longer maps to mechanical_plumbing — a civil drainage
# scope must not be mis-tagged as building M&P (building drainage arrives as part of
# the "mechanical & plumbing" trade label, which still maps via "mechanical").
_SYNONYMS: dict[str, str] = {
    # building / fit-out
    "electric": "electrical", "e&m": "electrical", "em": "electrical", "lv": "electrical",
    "mechanicalplumbing": "mechanical_plumbing", "mechanical": "mechanical_plumbing",
    "m&e": "mechanical_plumbing", "mep": "mechanical_plumbing", "hvac": "mechanical_plumbing",
    "plumb": "mechanical_plumbing", "pipework": "mechanical_plumbing",
    "fire": "fire_services", "sprinkler": "fire_services",
    "joinery": "joinery_fitting_out", "fitout": "joinery_fitting_out", "fittingout": "joinery_fitting_out",
    "interior": "joinery_fitting_out", "partition": "joinery_fitting_out",
    "concrete": "reinforced_concrete", "rc": "reinforced_concrete", "formwork": "reinforced_concrete",
    "rebar": "reinforced_concrete",
    "structural": "structural", "steel": "structural",
    "foundation": "foundation_substructure", "substructure": "foundation_substructure",
    "piling": "foundation_substructure", "pile": "foundation_substructure",
    "builderswork": "builders_work", "bwic": "builders_work",
    "external": "external_works", "landscap": "external_works",
    # civil / ground investigation
    "groundinvestigation": "ground_investigation",
    "borehole": "drilling", "drill": "drilling",
    "sampl": "sampling",
    "fieldtest": "field_testing", "permeability": "field_testing",
    "piezometer": "field_installations", "standpipe": "field_installations",
    "slope": "slope_works",
    "siteformation": "site_formation",
    "roadwork": "roadworks",
}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _slugify(label: str) -> str:
    """A valid work-package key from any label: lowercase, non-alphanumeric -> '_'."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def normalize(trade: str) -> str | None:
    """Map a free-form work-package name to a canonical key, or None if unknown."""
    raw = trade.strip().lower()
    squashed = _squash(raw)
    if squashed in {_squash(k) for k in CANONICAL_TRADES}:
        # exact canonical key (allowing spacing/punctuation differences)
        for key in CANONICAL_TRADES:
            if _squash(key) == squashed:
                return key
    if raw in _LABELS:  # exact rubric label, e.g. "mechanical & plumbing"
        return _LABELS[raw]
    for label, key in _LABELS.items():  # label match ignoring punctuation
        if _squash(label) == squashed:
            return key
    for needle, key in _SYNONYMS.items():  # near-synonym substring
        if needle in squashed:
            return key
    return None


def validate_scope(scope: ScopePackages) -> tuple[ScopePackages, list[str]]:
    """Normalise every package's work-package key.

    A known label is mapped to its canonical key. A package with **no** canonical
    match is kept under a slugified form of its own label (a valid key — the pipeline
    runs cleanly on any tender type); its original label is returned in the second
    value **for transparency, not as an error**.
    """
    packages: list[TradeWorkPackage] = []
    unmapped: list[str] = []
    for pkg in scope.packages:
        canonical = normalize(pkg.trade)
        if canonical is not None:
            packages.append(pkg.model_copy(update={"trade": canonical}))
        else:
            key = _slugify(pkg.trade) or "work_section"
            unmapped.append(pkg.trade)
            packages.append(pkg.model_copy(update={"trade": key}))
    return ScopePackages(project_name=scope.project_name, packages=packages), unmapped
