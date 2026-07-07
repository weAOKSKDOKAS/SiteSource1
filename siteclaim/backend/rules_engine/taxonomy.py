"""Deterministic trade-taxonomy validation (Layer 1).

The canonical trade keys are read **from** ``references/rubrics/trade_taxonomy.md``
at import, so the rubric is the single source of truth: add a trade there and the
validator follows with no code change. The LLM may phrase a trade richly; this
module normalises every ``TradeWorkPackage.trade`` to a canonical key. A trade that
maps to nothing is **surfaced as unmapped, never silently dropped** (the rubric's
rule), so a human can reconcile it.
"""

from __future__ import annotations

import re
from pathlib import Path

from schemas.models import ScopePackages, TradeWorkPackage

_RUBRIC_PATH = Path(__file__).resolve().parents[1] / "references" / "rubrics" / "trade_taxonomy.md"

# Fallback if the rubric file is ever unreadable (keeps the package importable).
_FALLBACK_KEYS = {
    "foundation_substructure", "structural", "reinforced_concrete", "electrical",
    "mechanical_plumbing", "fire_services", "joinery_fitting_out", "builders_work",
    "external_works",
}

_ROW_RE = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*([^|]+?)\s*\|")


def _load_canonical() -> tuple[frozenset[str], dict[str, str]]:
    """Return (canonical keys, label->key map) parsed from the rubric table."""
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

# Near-synonyms the model is likely to emit -> canonical key. Matched in two passes
# (see ``normalize``): short abbreviations (``em``/``lv``/``rc``/``me``/``mep``) match a
# WHOLE whitespace token only, so they cannot fire inside an unrelated word (``demolition``,
# ``valve``, ``commercial``); longer needles keep the substring match, in insertion order.
_SYNONYMS: dict[str, str] = {
    "electric": "electrical", "e&m": "electrical", "em": "electrical", "lv": "electrical",
    "mechanicalplumbing": "mechanical_plumbing", "mechanical": "mechanical_plumbing",
    "m&e": "mechanical_plumbing", "mep": "mechanical_plumbing", "hvac": "mechanical_plumbing",
    "plumb": "mechanical_plumbing", "drainage": "mechanical_plumbing", "pipework": "mechanical_plumbing",
    "fire": "fire_services", "sprinkler": "fire_services",
    "joinery": "joinery_fitting_out", "fitout": "joinery_fitting_out", "fittingout": "joinery_fitting_out",
    "interior": "joinery_fitting_out", "partition": "joinery_fitting_out",
    "concrete": "reinforced_concrete", "rc": "reinforced_concrete", "formwork": "reinforced_concrete",
    "rebar": "reinforced_concrete",
    "structural": "structural", "steel": "structural",
    "foundation": "foundation_substructure", "substructure": "foundation_substructure",
    "piling": "foundation_substructure", "pile": "foundation_substructure",
    "builderswork": "builders_work", "bwic": "builders_work",
    "external": "external_works", "landscap": "external_works", "roadworks": "external_works",
    # Ground investigation (v2) — listed AFTER foundation/piling so a bored-pile scope
    # still resolves to foundation_substructure; a pure GI/drilling scope lands here.
    "groundinvestigation": "ground_investigation", "siteinvestigation": "ground_investigation",
    "gifieldwork": "ground_investigation", "geotechnical": "ground_investigation",
    "drilling": "ground_investigation",
}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# Partition the synonyms once by squashed length. Short forms (<= 3 chars: em, lv, rc, me,
# mep — and the "&" forms e&m/m&e that squash to em/me) are abbreviation-matched against whole
# tokens; longer forms keep the substring match. Insertion order is preserved in both lists,
# so foundation/piling/pile still resolve before the ground_investigation synonyms.
def _partition_synonyms() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    abbrev: list[tuple[str, str]] = []
    substring: list[tuple[str, str]] = []
    for needle, key in _SYNONYMS.items():
        squashed_needle = _squash(needle)
        if not squashed_needle:
            continue
        (abbrev if len(squashed_needle) <= 3 else substring).append((squashed_needle, key))
    return abbrev, substring


_ABBREV_SYNONYMS, _SUBSTRING_SYNONYMS = _partition_synonyms()


def base_trade(package_key: str) -> str:
    """The canonical trade behind a routing package_key. A section sub-package is keyed
    ``trade:SECTION`` (Prompt 2) — its DB reads (shortlist, historical band) run against the
    parent trade. A bare trade (every demo package) is returned unchanged."""
    return (package_key or "").split(":", 1)[0]


# The GI specialty sub-trades and their parent. A Ground Investigation section shortlists against
# its own specialty pool (field_testing / field_installations / geophysical_survey), widening to
# the parent ``ground_investigation`` when the specialist pool is too thin to compete. Kept explicit
# and small — a canonical key not listed here is its own parent.
_SPECIALTY_PARENTS: dict[str, str] = {
    "field_testing": "ground_investigation",
    "field_installations": "ground_investigation",
    "geophysical_survey": "ground_investigation",
}


def parent_trade(trade: str) -> str:
    """The parent canonical trade of a specialty sub-trade (``field_testing`` ->
    ``ground_investigation``), or the trade itself when it has no parent. Deterministic."""
    return _SPECIALTY_PARENTS.get(trade, trade)


def normalize(trade: str) -> str | None:
    """Map a free-form trade name to a canonical key, or None if unmapped."""
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
    # Abbreviation pass — whole-token match only. "E&M"/"LV switchgear"/"RC works" map, but
    # "em"/"lv"/"rc" never fire inside an unrelated word (demolition, valve, commercial).
    tokens = {_squash(tok) for tok in raw.split()} - {""}
    for needle, key in _ABBREV_SYNONYMS:
        if needle in tokens:
            return key
    # Substring pass — long synonyms only, in insertion order (foundation/piling/pile before
    # the ground_investigation synonyms).
    for needle, key in _SUBSTRING_SYNONYMS:
        if needle in squashed:
            return key
    return None


def validate_scope(scope: ScopePackages) -> tuple[ScopePackages, list[str]]:
    """Normalise every package's trade to a canonical key.

    Returns the normalised :class:`ScopePackages` and the list of original trade
    names that could not be mapped (kept in the output unchanged, never dropped).
    """
    packages: list[TradeWorkPackage] = []
    unmapped: list[str] = []
    for pkg in scope.packages:
        canonical = normalize(pkg.trade)
        if canonical is None:
            unmapped.append(pkg.trade)
            packages.append(pkg)
        else:
            packages.append(pkg.model_copy(update={"trade": canonical}))
    return ScopePackages(project_name=scope.project_name, packages=packages), unmapped
