"""`tender_slug(tender_slug(x))` must equal `tender_slug(x)`, and it did not.

On the truncate-and-hash branch the digest is taken over the INPUT, so slugging an already-slugged
name hashes the slug:

    'Ground Investigation Works for … (Phase 2)' -> 'ground-investigation-works-for-developme-ccd1cccd'
                                                 -> 'ground-investigation-works-for-developme-dc2fbca2'
                                                 -> 'ground-investigation-works-for-developme-eb58083d'

A `run_ref` IS a slug, and `Workspace.tender_dir` slugs whatever it is given. So the moment the id
resolved through the registry, the directory MOVED — a tender written before registration and read
after it addressed two different places, which is the very class the registry exists to close. Two
of the operator's stray directories are the same tender slugged a different number of times.

The fix makes the function a projection: a value already in canonical slug form is a fixed point.
Everything else is unchanged — the contract-number branch, the plain slugify, the hash for genuinely
long names, and every pinned example in `test_workspace.py`.
"""

import pytest

from pipeline.workspace import Workspace, tender_slug

LONG = "Ground Investigation Works for Development of San Tin Technopole (Phase 2)"
NAMES = [
    LONG,
    "Contract No. GE/2026/14 — Ground Investigation Works for Foo District",
    "Kwun Tong Commercial Tower — Cat-A",
    "HY/2020/09 Widening of Trunk Road",
    "Contract No. ND/2025/04",
    "nd-2025-04-san-tin-technopole",
    "A/B\\C",
    "",
    "   ",
    "x",
    "I-ND_2025_04_BQ-0.pdf",
    "San Tin Technopole (Phase 2) — Ground Investigation, Environmental Boreholes and Testing",
]


@pytest.mark.parametrize("name", NAMES)
def test_slugging_a_slug_changes_nothing(name):
    once = tender_slug(name)
    assert tender_slug(once) == once
    assert tender_slug(tender_slug(once)) == once, "and stays fixed however often it is applied"


@pytest.mark.parametrize("name", NAMES)
def test_the_directory_does_not_move_when_the_id_is_already_resolved(name):
    """The concrete consequence. `tender_dir` slugs what it is given, and a resolved `run_ref` is
    already a slug — so a non-idempotent slug moved the tender's whole workspace."""
    ws = Workspace(root="/tmp/does-not-need-to-exist")
    assert ws.tender_dir(name) == ws.tender_dir(tender_slug(name))


def test_the_hash_branch_is_where_it_broke():
    """Named, so the fix is not mistaken for a coincidence: only names too long to slug plainly
    reach the digest, and only they were unstable."""
    once = tender_slug(LONG)
    assert len(once) > 40 and once.count("-") >= 4
    assert once.endswith("-ccd1cccd"), "the digest is over the ORIGINAL name, and stays that way"
    assert tender_slug(once) == once


def test_a_long_name_still_gets_a_short_hashed_slug():
    """The behaviour the hash branch exists for is untouched: distinct long titles never collide."""
    a = tender_slug(LONG)
    b = tender_slug(LONG.replace("Phase 2", "Phase 3"))
    assert a != b and len(a) <= 49 and len(b) <= 49


@pytest.mark.parametrize("name,expected", [
    ("Kwun Tong Commercial Tower — Cat-A", "kwun-tong-commercial-tower-cat-a"),
    ("", "tender"),
    ("A/B\\C", "a-b-c"),
    ("Contract No. GE/2026/14 — Ground Investigation Works for Foo District", "ge-2026-14"),
    ("HY/2020/09 Widening of Trunk Road", "hy-2020-09"),
])
def test_every_pinned_example_is_unchanged(name, expected):
    """The same assertions `test_workspace.py` makes, restated here so a future change to the
    short-circuit cannot quietly move them."""
    assert tender_slug(name) == expected


def test_a_contract_number_still_wins_over_the_short_circuit():
    """`ge-2026-14` is slug-shaped AND a contract number. It must keep resolving to itself either
    way — but a NAME carrying a contract number must still collapse onto it."""
    assert tender_slug("ge-2026-14") == "ge-2026-14"
    assert tender_slug("Contract No. GE/2026/14") == "ge-2026-14"


def test_a_long_lowercase_hyphenated_name_is_still_hashed():
    """The short-circuit is bounded by length, so a genuinely long name that happens to be
    slug-shaped is not mistaken for an already-slugged one."""
    long_shaped = "-".join(["segment"] * 12)
    assert len(long_shaped) > 49
    assert tender_slug(long_shaped) != long_shaped
    assert tender_slug(tender_slug(long_shaped)) == tender_slug(long_shaped)
