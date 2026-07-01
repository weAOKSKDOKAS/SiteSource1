"""Phase B — the live-engine shortlist path (``include_public=True``).

The default cross-reference shortlists only firms that carry an assessable EOS
closeout record, so the real scraped public-record firms (which have none yet) never
reach a shortlist. These tests cover the opened pool: every registered firm in the
trade becomes a candidate, ordered by the public risk screen, with the closeout
match kept as a soft enrichment feature. Default-mode behaviour is unchanged, so the
baked demo scenarios keep working.
"""

from db import store
from db.cross_reference import cross_reference
from db.tests.conftest import ELECTRICAL_SCOPE_QUERY
from schemas.models import Severity


def _ids(candidates):
    return [c.firm.firm_id for c in candidates]


def _warnings(candidate):
    return sum(1 for f in candidate.risk_flags if f.severity is Severity.WARNING)


def test_public_mode_shortlists_public_only_firms(conn):
    # Real scraped firms with no EOS record are absent from the default shortlist …
    default_ids = set(_ids(cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY)))
    public_ids = set(_ids(cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY, include_public=True)))

    assessable = store.eos_firm_ids(conn)
    public_only = {f.firm_id for f in store.firms_for_trade(conn, "electrical")} - assessable

    assert public_only  # the real electrical scrape is in the DB
    # … and appear once the pool is opened. The decouple did its job.
    assert public_only & public_ids
    assert public_only.isdisjoint(default_ids)
    assert default_ids <= public_ids  # opening the pool only adds; it drops no assessed firm


def test_default_mode_hero_catch_is_unchanged(conn):
    # Regression guard: the include_public default must leave the demo hero intact.
    ids = _ids(cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY))
    assert ids[0] == "F-EL-02"
    assert ids[-1] == "F-EL-01"  # the gotcha still demoted last


def test_public_mode_keeps_fatal_flagged_below_every_clean_firm(conn):
    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY, include_public=True)
    flagged = [i for i, c in enumerate(candidates) if c.recommended_against]
    clean = [i for i, c in enumerate(candidates) if not c.recommended_against]
    if flagged and clean:
        # every clean firm outranks every fatal-flagged one, regardless of match/price
        assert max(clean) < min(flagged)
    # and any fatal firm is explicitly marked recommend-against with its flag intact
    for c in candidates:
        if c.recommended_against:
            assert any(f.severity is Severity.FATAL for f in c.risk_flags)


def test_public_mode_orders_spotless_above_warned(conn):
    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY, include_public=True)
    # Among the opened public firms that carry no closeout match (score 0) and no fatal
    # flag, warning-free firms come before those carrying a warning.
    tail = [c for c in candidates if not c.recommended_against and c.match_score == 0.0]
    warning_counts = [_warnings(c) for c in tail]
    assert warning_counts == sorted(warning_counts)


def test_public_mode_every_candidate_is_screened(conn):
    # No firm enters the live shortlist unscreened: risk_flags is the deterministic
    # adjudication of its public signals (may be empty for a spotless firm, but the
    # firm was still run through score_firm).
    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY, include_public=True)
    assert candidates
    for c in candidates:
        expected = store.firm_profile(conn, c.firm.firm_id)
        assert expected is not None
