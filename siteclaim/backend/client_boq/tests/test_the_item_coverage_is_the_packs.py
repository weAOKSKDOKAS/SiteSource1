"""The item coverage carries THIS contract's clause letters, and says what it cannot see.

DEFECT A. The first transcription of Bill No.2 lettered the ¶2.13 heads (a)–(h) in reading order.
The pack does not letter them that way. Verbatim from `SMM_S02` Particular Preambles:

    Delete paragraph 2.13(d) and substitute: (d) taking readings, measurements and observations,
    and recording and supplying the logs and other records of each drillhole, borehole or probehole
    to the Project Manager.

    Add the following to paragraph 2.13: (e) stabilising the hole; (f) reaming of casing;
    (g) disposal of surplus material; (h) drilling using 4C-MLC core barrel as required;
    (i) taking and submitting small disturbed samples to the Project Manager; (j) providing,
    maintaining and removing temporary traffic arrangement in accordance with PS Clauses 1.14–1.15.

So what was carried as (a) is really (e), (b) is (f), (c) is (g), (d) is (i), the three
readings/logging heads are all the substituted (d), and (h) is really (j). The CONTENT was right;
every REFERENCE was wrong. That matters exactly as much as `coverage.py`'s own docstring says it
does — "a wrong transcription shows up the moment somebody clicks through to the page" only works
if the reference points at the right sub-clause.

THREE DECISIONS TAKEN HERE, each pinned below:

**The substituted 2.13(d) is three heads, not one.** The estimator TICKS these, and "have I priced
the logging?" and "have I priced supplying the logs?" are two questions with two answers. One tick
would settle both on the strength of whichever the reader happened to be thinking about. All three
carry the same `clause_ref`, so clicking any of them lands on the right sub-clause.

**"Casing" is kept and marked base-SMM.** The old head read "Casing, and reaming of casing"; only
"reaming of casing" appears in an amendment. Deleting the casing half would delete a real cost on
the strength of a document nobody here has read. It stays, with `provenance=FROM_BASE_SMM` and a
stated reason its words cannot be checked.

**The keys move to a new namespace rather than being migrated.** Old and new key spaces OVERLAP
WITH DIFFERENT MEANINGS: old `smm.2.13.e` was "Taking readings", new `smm.s02.2.13.e` is
"Stabilising the hole". A rename-in-place would therefore land a tick given for one head onto a
different head — the one thing that must never happen. Moving namespace makes every stale tick fail
to match anything, so it comes back as an honest untick; and `ItemCoverage.orphan_ticks` NAMES it,
because a tick that silently stops counting is a loss dressed as a clean migration.
"""

from __future__ import annotations

from client_boq.boq.coverage import (
    BASE_SMM_UNVERIFIABLE,
    FROM_AMENDMENT,
    FROM_BASE_SMM,
    PARTIAL_BY_CONSTRUCTION,
    SECTION_COVERAGE,
    coverage_for,
    heads_for,
)
from client_boq.models import BillItem


def _item(full_ref: str = "2.4", *, bill_no: str = "2", description: str = "Drilling") -> BillItem:
    return BillItem(bill_no=bill_no, full_ref=full_ref, description=description, unit="m",
                    qty=100.0, row=1)


def _keys(item: BillItem) -> set[str]:
    return {head.key for head in heads_for(item)}


def _by_key(item: BillItem) -> dict:
    return {head.key: head for head in heads_for(item)}


class TestTheLettersAreThePacks:
    def test_the_substituted_clause_d_covers_the_readings_and_the_logs(self):
        heads = _by_key(_item())
        for suffix in ("readings", "recording", "supplying"):
            head = heads[f"smm.s02.2.13.d.{suffix}"]
            assert head.clause_ref == "SMM S02 ¶2.13(d)", "one clause, three ticks"

    def test_the_added_clauses_land_on_the_letters_the_pack_gives_them(self):
        heads = _by_key(_item())
        assert heads["smm.s02.2.13.e"].label == "Stabilising the hole"
        assert heads["smm.s02.2.13.f"].label == "Reaming of casing"
        assert heads["smm.s02.2.13.g"].label == "Disposal of surplus material"
        assert heads["smm.s02.2.13.i"].label.startswith("Taking and submitting small disturbed")
        assert heads["smm.s02.2.13.j"].label.startswith("Providing, maintaining and removing")

    def test_every_clause_ref_agrees_with_its_key(self):
        """The whole point of the fix: click through and land on the right sub-clause."""
        for head in heads_for(_item()):
            if not head.key.startswith("smm.s02.2.13.") or ".base." in head.key:
                continue
            letter = head.key.removeprefix("smm.s02.2.13.").split(".")[0]
            assert f"¶2.13({letter})" in head.clause_ref, head.key

    def test_the_old_letters_are_gone_from_the_list_entirely(self):
        stale = {f"smm.2.13.{letter}" for letter in "abcdefgh"} | {"smm.2.08.h"}
        assert not (stale & _keys(_item("2.2b")))

    def test_the_traffic_arrangement_head_cites_the_ps_clause_the_pack_names(self):
        head = _by_key(_item())["smm.s02.2.13.j"]
        assert head.cites == "1.14", "PS Clauses 1.14 to 1.15"
        assert "PS 1.14" in head.clause_ref


class TestTheGapThePackCannotClose:
    def test_casing_is_kept_and_marked_base_smm_rather_than_deleted(self):
        """Only 'reaming of casing' is in an amendment. Deleting the casing half would delete a
        real cost on the strength of a document nobody here has read."""
        head = _by_key(_item())["smm.s02.2.13.base.casing"]
        assert head.label == "Casing"
        assert head.provenance == FROM_BASE_SMM
        assert "base SMM" in head.clause_ref

    def test_a_base_smm_head_says_its_words_cannot_be_checked(self):
        entry = next(e for e in coverage_for(_item()).entries
                     if e.key == "smm.s02.2.13.base.casing")
        assert entry.provenance == FROM_BASE_SMM
        assert entry.unverifiable == BASE_SMM_UNVERIFIABLE
        assert "NOT in this tender pack" in entry.unverifiable

    def test_an_amendment_head_claims_no_such_caveat(self):
        entry = next(e for e in coverage_for(_item()).entries if e.key == "smm.s02.2.13.e")
        assert entry.provenance == FROM_AMENDMENT and entry.unverifiable == ""

    def test_the_bill_two_list_declares_itself_partial(self):
        assert SECTION_COVERAGE["2"].partial == PARTIAL_BY_CONSTRUCTION
        assert SECTION_COVERAGE["2"].smm_clause == "SMM S02 ¶2.13"

    def test_an_item_carries_the_partial_reason_so_a_tidy_list_cannot_pass_for_a_whole_one(self):
        coverage = coverage_for(_item())
        assert coverage.partial and "AMENDMENTS" in coverage.partial[0]
        assert "SMM S02 ¶2.13" in coverage.partial[0]

    def test_all_covered_never_stands_alone(self):
        ticks = {head.key: {"ticked": True, "ticked_by": "SW"} for head in heads_for(_item())}
        summary = coverage_for(_item(), ticks=ticks).summary()
        assert "all covered" in summary and summary.endswith("LIST IS PARTIAL")


class TestATickNeverLandsWhereItWasNotGiven:
    def test_a_tick_on_an_old_key_is_not_applied_to_the_head_that_now_owns_that_letter(self):
        """THE FAILURE THE NAMESPACE MOVE PREVENTS. Old `smm.2.13.e` meant "Taking readings"; the
        letter (e) now belongs to "Stabilising the hole". A rename-in-place would have silently
        moved that tick onto a head it was never given for."""
        stale = {"smm.2.13.e": {"ticked": True, "ticked_by": "SW"}}
        coverage = coverage_for(_item(), ticks=stale)

        assert all(not entry.ticked for entry in coverage.entries), "nothing inherited it"
        stabilising = next(e for e in coverage.entries if e.key == "smm.s02.2.13.e")
        assert not stabilising.ticked and stabilising.ticked_by == ""

    def test_the_lost_tick_is_named_rather_than_vanishing(self):
        stale = {"smm.2.13.a": {"ticked": True, "ticked_by": "SW"},
                 "smm.2.13.h": {"ticked": True, "ticked_by": "SW"}}
        coverage = coverage_for(_item(), ticks=stale)

        assert len(coverage.orphan_ticks) == 2
        assert any("'smm.2.13.a'" in note for note in coverage.orphan_ticks)
        assert all("NOT been applied" in note for note in coverage.orphan_ticks)
        assert all("back to being a question" in note for note in coverage.orphan_ticks)

    def test_an_untick_recorded_against_a_dead_key_is_not_reported_as_a_loss(self):
        """Only a TICK is a loss. A recorded `ticked: False` was never carrying anything."""
        coverage = coverage_for(_item(), ticks={"smm.2.13.a": {"ticked": False}})
        assert coverage.orphan_ticks == []

    def test_a_live_tick_is_not_reported_as_an_orphan(self):
        coverage = coverage_for(_item(), ticks={"smm.s02.2.13.e": {"ticked": True}})
        assert coverage.orphan_ticks == []
        assert next(e for e in coverage.entries if e.key == "smm.s02.2.13.e").ticked

    def test_the_bill_level_head_is_not_mistaken_for_an_orphan(self):
        coverage = coverage_for(_item(), ticks={"preambles.deemed": {"ticked": True}})
        assert coverage.orphan_ticks == []

    def test_the_whole_bill_summary_counts_the_orphans(self):
        from client_boq.boq.coverage import bill_summary
        from client_boq.models import ClientBill

        bill = ClientBill(items=[_item("2.4"), _item("2.5")])
        out = bill_summary(bill, ticks={"2.4": {"smm.2.13.a": {"ticked": True}}})
        assert out["orphan_ticks"] == 1
        assert out["partial"] == 2, "both items' lists are the amendments only"


class TestDefectBTheHeadsThatWereMissingEntirely:
    def test_the_4c_mlc_core_barrel_is_on_the_drilling_checklist(self):
        """A real cost inside the drilling rate that was on no checklist at all — and Particular
        Preamble ¶12/¶4A means it cannot be claimed later."""
        head = _by_key(_item("2.4"))["smm.s02.2.13.h"]
        assert head.label == "Drilling using 4C-MLC core barrel as required"
        assert head.clause_ref == "SMM S02 ¶2.13(h)"

    def test_establishing_a_rig_carries_the_permits_and_the_government_land_application(self):
        keys = _keys(_item("2.1", description="Establishment of rigs"))
        assert "smm.s02.2.07.d" in keys, "road excavation permits"
        assert "smm.s02.2.07.e" in keys, "acceptance for GI works on Government land"
        assert "smm.s02.2.07.f" in keys, "temporary traffic arrangement"

    def test_moving_a_rig_carries_the_setting_out_and_the_scaffolding(self):
        keys = _keys(_item("2.2", description="Moving rigs"))
        assert "smm.s02.2.08.f" in keys and "smm.s02.2.08.h" in keys

    def test_standing_time_carries_its_own_traffic_head(self):
        assert "smm.s02.2.09.c" in _keys(_item("2.3", description="Standing time for rigs"))

    def test_the_setting_up_family_never_reaches_a_drilling_metre(self):
        """The reason these are per item: a permit application is a cost of establishing a rig, not
        a cost of every metre drilled. Attaching them bill-wide would charge it inside the metre
        rate AND again on the establishment item."""
        keys = _keys(_item("2.4", description="Drilling, vertically downwards"))
        for stray in ("smm.s02.2.07.d", "smm.s02.2.07.e", "smm.s02.2.08.f", "smm.s02.2.08.h",
                      "smm.s02.2.09.c"):
            assert stray not in keys

    def test_a_bill_three_rig_move_is_reached_by_title_since_its_refs_are_unknown(self):
        """Bill 3's BQ references were not transcribed, so it is reached by what its items are
        CALLED rather than by references invented here."""
        keys = _keys(_item("3.2", bill_no="3", description="Moving rigs between stations"))
        assert "smm.s02.2.08.h" in keys

    def test_an_item_reached_by_both_routes_carries_each_head_once(self):
        """2.2 arrives by reference AND by title. Two entries with one key would render the head
        twice and let a single tick appear to settle both."""
        heads = heads_for(_item("2.2", description="Moving rigs"))
        keys = [head.key for head in heads]
        assert len(keys) == len(set(keys))
        assert keys.count("smm.s02.2.08.h") == 1
