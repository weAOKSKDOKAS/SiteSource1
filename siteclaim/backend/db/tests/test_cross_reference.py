"""The hero: the cross-reference demotes the cheapest, best-matching electrical
firm because the database carries a fatal winding-up petition against it."""

from db import store
from db.cross_reference import SECTION_CAP, cross_reference
from db.tests.conftest import ELECTRICAL_SCOPE_QUERY
from schemas.models import Severity


def _ids(candidates):
    return [c.firm.firm_id for c in candidates]


def test_shortlist_puts_clean_runner_up_on_top(conn):
    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY)
    ids = _ids(candidates)
    # the clean runner-up wins; the gotcha is present but last among electrical firms
    assert ids[0] == "F-EL-02"
    assert "F-EL-01" in ids
    assert ids.index("F-EL-01") > ids.index("F-EL-02")


def test_gotcha_demoted_below_weaker_but_clean_matches(conn):
    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY)
    gotcha = next(c for c in candidates if c.firm.firm_id == "F-EL-01")
    # it is a strong semantic match, yet it sinks to the very bottom …
    assert gotcha.match_score > 0.4
    assert candidates[-1].firm.firm_id == "F-EL-01"
    # … and clean firms with a *weaker* match are ranked above it: the fatal flag,
    # not the score, drove the demotion.
    above = candidates[: candidates.index(gotcha)]
    assert any(c.match_score < gotcha.match_score for c in above)


def test_gotcha_carries_fatal_winding_up_with_evidence(conn):
    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY)
    gotcha = next(c for c in candidates if c.firm.firm_id == "F-EL-01")
    fatal = [f for f in gotcha.risk_flags if f.severity is Severity.FATAL]
    rule_refs = {f.rule_ref for f in fatal}
    assert "risk.winding_up" in rule_refs
    assert "risk.safety_prosecutions" in rule_refs
    winding = next(f for f in fatal if f.rule_ref == "risk.winding_up")
    assert winding.evidence and winding.evidence[0].reference == "CR:HCCW-215/2026"


def test_electrical_shortlist_is_capped_and_keeps_the_demoted_gotcha(conn):
    # The shortlist now surfaces the genuine register pool too, so it is capped to a
    # readable size — but the recommend-against gotcha is always kept, demoted last,
    # never capped away, and the clean demo firms remain present.
    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY)
    ids = set(_ids(candidates))
    assert {"F-EL-01", "F-EL-02", "F-EL-03", "F-EL-04"} <= ids
    assert candidates[-1].firm.firm_id == "F-EL-01"  # the flagged firm is present, just demoted last
    clean = [c for c in candidates if not c.recommended_against]
    assert len(clean) <= SECTION_CAP
    # far more electrical firms are now shortlistable than are shown — the cap is real
    assert len(store.shortlistable_firms_for_trade(conn, "electrical")) > len(candidates)


def test_trade_matched_register_firms_now_surface_capped_and_ranked(conn):
    # The opened gate: a trade-matched firm on the real CIC register is shortlistable
    # even with no held closeout and no award — the genuine pool surfaces (previously
    # it was hidden behind the closeout/award gate).
    register = store.register_firm_ids(conn)
    order = [c.firm.firm_id for c in cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY)]
    assert any(fid in register for fid in order)  # real register firms now appear
    # yet the hero still reads correctly: clean runner-up on top, gotcha demoted last,
    # and the curated/assessed demo firms sit above the register-only pool.
    assert order[0] == "F-EL-02"
    assert order[-1] == "F-EL-01"
    register_in_card = [fid for fid in order if fid in register]
    demo_in_card = [fid for fid in order if fid.startswith("F-EL-")]
    assert max(order.index(fid) for fid in demo_in_card if fid != "F-EL-01") < min(
        order.index(fid) for fid in register_in_card
    )
    # a firm that does not do the trade is never surfaced under it
    non_electrical = next(f.firm_id for f in store.all_firms(conn) if "electrical" not in f.trades)
    assert non_electrical not in set(order)
