"""The recurring failure of this codebase, swept and pinned.

An empty list, a zero, a `None` or a swallowed exception rendered as *fine*. It is one defect class
wearing many faces, and it has cost this product four separate findings:

* `if schedule is not None:` guarded the app's only hard stop, so the net could not fire in exactly
  the case it was written for.
* `⚠ N HOLES UNASSIGNED` computed over an empty list and read 0.
* `unpriced == []` and `placeholders == []` were both true while HK$3,038,117 of direct cost reached
  no rate — they answer *is every BILL line priced?*, and a basis nothing claims is not a bill line.
* An item with zero transcribed coverage heads reported "all covered".

These tests pin the sweep that followed. Each one is a state that used to be indistinguishable from
health and now has to say what it is.
"""

from __future__ import annotations

import pytest

from client_boq.boq.conservation import Conservation


class TestAnEngineThatComputedNothingIsNotAConservedOne:
    """`Conservation.clean()` returned True on an empty basis list — difference 0.00, nothing
    miscounted. This module exists to catch cost that goes missing, and it reported perfection on a
    model that had computed no cost at all."""

    def test_no_bases_is_not_clean(self):
        assert Conservation().clean() is False

    def test_the_headline_says_what_actually_happened(self):
        headline = Conservation().headline()
        assert "produced no bases at all" in headline
        assert "not a clean bill" in headline
        assert "balances" not in headline, "the reassuring sentence must not appear"

    def test_a_real_basis_that_balances_is_still_clean(self):
        """The line the guard must not cross: a genuine, balanced model still reports conservation."""
        from client_boq.boq.conservation import BasisRecovery

        balanced = Conservation(
            direct_cost=1000.0, recovered=1000.0,
            bases=[BasisRecovery(key="soil", label="Drilling, soil", direct_cost=1000.0,
                                 divisor=100.0, claimed_by=["2.4"], claimed_qty=100.0,
                                 recovered=1000.0)])
        assert balanced.clean() is True
        assert "recovered exactly once" in balanced.headline()


class TestTheConservationVerdictHasThreeStates:
    """The sentence is non-empty on GOOD news too, so a caller that branches on it being non-empty
    prints a red alarm over "every basis balances" — and one that branches on it being EMPTY reads
    "we do not know" as "it is fine"."""

    def test_a_check_that_could_not_run_is_neither_clean_nor_dirty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
        from client_boq.router import conservation_state

        state = conservation_state("a-tender-that-was-never-priced")
        assert state["checked"] is False
        assert state["clean"] is None, "None is 'we do not know'; False would be a verdict"
        assert state["not_checked_because"], "silence would read as a clean check"

    def test_the_state_names_this_defect_class_in_its_own_words(self):
        """Kept because the reason is the load-bearing part: a later edit that returns `{}` on
        failure would pass every other assertion here."""
        from client_boq.router import conservation_state

        assert "absence reading as health" in (conservation_state.__doc__ or "")


class TestASweepNobodyRanIsNotASettledOne:
    """`UnbilledSweep.settled()` was `not outstanding()`, and an empty cost list has nothing
    outstanding. The sweep is hand-typed and never seeded from the build-up, so an empty sweep is
    the NORMAL state — "nobody has looked" was reading as "looked and clean" on every tender."""

    def test_an_empty_sweep_is_not_settled(self):
        from client_boq.boq.unbilled import UnbilledSweep

        assert UnbilledSweep().settled() is False

    def test_it_says_why(self):
        from client_boq.boq.unbilled import UnbilledSweep

        assert "nobody has listed" in UnbilledSweep().not_settled_because()

    def test_a_swept_and_routed_sweep_is_settled(self):
        from client_boq.boq.unbilled import ROUTE_ACCEPT, UnbilledCost, UnbilledSweep

        swept = UnbilledSweep(costs=[UnbilledCost(
            key="uniform", label="Site uniform", amount=120_000.0, route=ROUTE_ACCEPT,
            # An accepted risk with no reason is itself outstanding, by the module's own rule:
            # "a risk somebody took deliberately and one nobody noticed look identical six months
            # later". So the reason is part of what makes this sweep genuinely settled.
            reason="PP 11 says there is no separate payment; carried in the rates",
            decided_by="SW")])
        assert swept.settled() is True
        assert swept.not_settled_because() == ""


class TestARegisterNobodyReviewedIsNotAClearedOne:
    """`assumptions.Register.gate()` returned CLEARED on an empty row list, and
    `summary()` read "0 assumptions · all reviewed" — printed on the workbook and rendered in the
    OK colour on the costing screen."""

    def test_an_empty_register_is_not_cleared(self):
        from client_boq.boq.assumptions import Register

        assert Register().gate() != "CLEARED"

    def test_the_summary_does_not_say_all_reviewed(self):
        from client_boq.boq.assumptions import Register

        summary = Register().summary()
        assert "all reviewed" not in summary
        assert "no assumptions were recorded" in summary
