"""The chain closes: bill item → the cost its rate is made of → the clause that obliges it.

WHY THIS EXISTS. Under General Preambles ¶2 a rate is deemed to include everything the specification
names for its item, and *"any item missed out from the item coverage shall not be measured"* — the
work is still owed and cannot be claimed. So an obligation nobody priced is not saved, it is given
away for the life of the contract. That is why 122 coverage heads across nine bills were
transcribed, each carrying the clause that produced it.

**And nothing in the costing engine read any of it.** The engine priced quantities; the checklist
sat beside it, ticked by a human, connected to nothing. A tick said *"my build-up carries this
head"* and there was no way to check it — `client_boq_coverage_ticks` was keyed
`(set_id, rev, full_ref, head_key)` with a boolean and an actor, and `CostLine` had no field a head
key could go in.

One additive column turns the belief into a LINK, and a link is checkable against the cost the
item's rate is actually made of — `ItemMapping.basis_key`, which is the live engine's own answer to
"where does this rate's money come from". Four states follow, and the two that matter are the two
nothing else could see:

* **claimed against a cost this rate does not draw on** — the head is ticked, so every other reading
  calls it covered; the rate is priced, so every other reading calls it priced. The obligation is
  real and the money is somewhere else.
* **unaccounted** — nobody said this rate carries it. Visible, never assumed included.

Nothing here ticks or unticks anything. It reads what a person recorded and says what that recording
is worth.
"""

from __future__ import annotations

import pytest

from client_boq.boq import coverage as boq_coverage
from client_boq.boq.coverage import (
    ACCOUNTED_BY_COST,
    ASSERTED_ONLY,
    COST_NOT_IN_RATE,
    UNACCOUNTED,
    CoverageEntry,
    ItemCoverage,
    account_for_cost,
)

#: What a build-up looks like from the outside: the bases a tender's cost is made of.
BASES = {
    "soil_drilling": "Drilling, material other than rock",
    "rock_drilling": "Drilling, rock",
    "rig_moves": "Moving and setting up rigs",
    "site_team": "The site team",
}


def _entry(key: str, *, ticked=False, basis="") -> CoverageEntry:
    return CoverageEntry(key=key, label=f"head {key}", clause_ref=f"SMM S02 ¶2.13({key})",
                         ticked=ticked, basis_key=basis)


def _coverage(*entries: CoverageEntry) -> ItemCoverage:
    return ItemCoverage(full_ref="2.4", description="Drilling in material other than rock",
                        entries=list(entries))


class TestTheFourStates:

    def test_a_head_carried_by_a_cost_the_rate_draws_on(self):
        item = account_for_cost(_coverage(_entry("a", ticked=True, basis="soil_drilling")),
                                bases=BASES, drawn_on={"soil_drilling"})
        entry = item.entries[0]
        assert entry.accounting == ACCOUNTED_BY_COST
        assert entry.basis_label == "Drilling, material other than rock"
        assert item.accounted_by_cost() == [entry]

    def test_a_tick_with_no_cost_named_is_still_only_somebody_s_word(self):
        """Exactly what a tick was before the column existed, and it must keep saying so rather
        than being quietly promoted."""
        item = account_for_cost(_coverage(_entry("a", ticked=True)),
                                bases=BASES, drawn_on={"soil_drilling"})
        assert item.entries[0].accounting == ASSERTED_ONLY
        assert item.asserted_only() and not item.accounted_by_cost()

    def test_a_head_claimed_against_a_cost_this_rate_does_not_draw_on(self):
        """THE FIND. The head is ticked, so every other reading here calls it covered. The rate is
        priced, so every other reading calls it priced. The money is somewhere else."""
        item = account_for_cost(_coverage(_entry("a", ticked=True, basis="rock_drilling")),
                                bases=BASES, drawn_on={"soil_drilling"})
        assert item.entries[0].accounting == COST_NOT_IN_RATE
        assert item.cost_not_in_rate() == item.entries
        assert item.entries[0].covered(), "still ticked — that is what makes it invisible"

    def test_a_head_nobody_has_claimed(self):
        item = account_for_cost(_coverage(_entry("a")), bases=BASES, drawn_on={"soil_drilling"})
        assert item.entries[0].accounting == UNACCOUNTED
        assert item.unaccounted() == item.entries

    def test_the_verdict_is_empty_until_the_rule_has_run(self):
        """A verdict nobody computed must not read as one that came out clean."""
        assert _coverage(_entry("a", ticked=True)).entries[0].accounting == ""


class TestWhatItSays:

    @pytest.fixture
    def mixed(self):
        return account_for_cost(
            _coverage(
                _entry("a", ticked=True, basis="soil_drilling"),
                _entry("b", ticked=True),
                _entry("c", ticked=True, basis="rock_drilling"),
                _entry("d"),
            ),
            bases=BASES, drawn_on={"soil_drilling", "site_team"})

    def test_the_summary_counts_all_four(self, mixed):
        summary = mixed.accounting_summary()
        assert "4 heads" in summary
        assert "1 carried by a named cost" in summary
        assert "1 asserted without one" in summary
        assert "1 claimed against a cost NOT in this rate" in summary
        assert "1 accounted for by nobody" in summary

    def test_the_problems_put_the_worst_first(self, mixed):
        problems = mixed.accounting_problems()
        assert len(problems) == 2
        assert "does not draw on" in problems[0]
        assert "Drilling, rock" in problems[0], "the cost is named in words, not as a key"
        assert "nobody has said this rate carries it" in problems[1]

    def test_the_unaccounted_sentence_names_the_clause_that_costs_money(self, mixed):
        assert "General Preambles ¶6" in mixed.accounting_problems()[1]

    def test_a_fully_accounted_item_has_no_problems(self):
        item = account_for_cost(
            _coverage(_entry("a", ticked=True, basis="soil_drilling"),
                      _entry("b", ticked=True, basis="site_team")),
            bases=BASES, drawn_on={"soil_drilling", "site_team"})
        assert item.accounting_problems() == []
        assert item.accounting_summary() == "2 heads · 2 carried by a named cost"


class TestAbsenceNeverReadsAsHealth:
    """The recurring failure this codebase is built against, applied to its newest surface."""

    def test_an_item_with_no_heads_says_there_is_nothing_to_account_for(self):
        empty = account_for_cost(_coverage(), bases=BASES, drawn_on={"soil_drilling"})
        assert "nothing to account for" in empty.accounting_summary()
        assert "carried by a named cost" not in empty.accounting_summary()

    def test_an_item_with_no_transcribed_list_says_that_instead(self):
        item = ItemCoverage(full_ref="9.1", no_list_for_section="9")
        assert "no item-coverage list transcribed" in item.accounting_summary()

    def test_an_unrun_check_does_not_read_as_a_clean_one(self):
        item = _coverage(_entry("a", ticked=True, basis="soil_drilling"))
        assert "has not been checked" in item.accounting_summary()

    def test_a_rate_that_draws_on_nothing_accounts_for_nothing(self):
        """An item with no cost basis at all — every ticked head is then claimed against a cost
        that is not in the rate, because there is no rate."""
        item = account_for_cost(_coverage(_entry("a", ticked=True, basis="soil_drilling")),
                                bases=BASES, drawn_on=set())
        assert item.entries[0].accounting == COST_NOT_IN_RATE


class TestItDecidesNothing:

    def test_it_never_ticks_or_unticks(self):
        before = _coverage(_entry("a"), _entry("b", ticked=True, basis="soil_drilling"))
        ticks = [(e.key, e.ticked, e.ticked_by, e.basis_key) for e in before.entries]
        account_for_cost(before, bases=BASES, drawn_on={"soil_drilling"})
        assert [(e.key, e.ticked, e.ticked_by, e.basis_key) for e in before.entries] == ticks

    def test_an_unknown_basis_key_still_gets_a_verdict(self):
        """A basis renamed or deleted between the tick and the read. The claim is against a cost
        the rate does not draw on, which is true and is the safe reading."""
        item = account_for_cost(_coverage(_entry("a", ticked=True, basis="a_basis_that_went_away")),
                                bases=BASES, drawn_on={"soil_drilling"})
        assert item.entries[0].accounting == COST_NOT_IN_RATE
        assert item.entries[0].basis_label == "", "no label to give — the key stands in"
        assert "a_basis_that_went_away" in item.accounting_problems()[0]


class TestTheStoreCarriesTheLink:

    @pytest.fixture
    def conn(self):
        from client_boq import store

        connection = store.get_conn()
        yield connection
        connection.close()

    def test_a_tick_remembers_the_cost_it_named(self, conn):
        from client_boq import store

        store.save_coverage_tick(conn, "t", 0, "2.4", "smm.s02.2.13.e", True, "SW",
                                 "soil_drilling")
        mark = store.load_coverage_ticks(conn, "t", 0)["2.4"]["smm.s02.2.13.e"]
        assert mark["ticked"] is True and mark["basis_key"] == "soil_drilling"
        assert mark["ticked_by"] == "SW"

    def test_a_tick_with_no_cost_is_still_a_tick(self, conn):
        from client_boq import store

        store.save_coverage_tick(conn, "t", 0, "2.4", "smm.s02.2.13.f", True, "SW")
        mark = store.load_coverage_ticks(conn, "t", 0)["2.4"]["smm.s02.2.13.f"]
        assert mark["ticked"] is True and mark["basis_key"] == ""

    def test_unticking_clears_the_cost_with_the_name(self, conn):
        """The link was part of the claim. A withdrawn claim must not leave its evidence behind
        looking live."""
        from client_boq import store

        store.save_coverage_tick(conn, "t", 0, "2.4", "smm.s02.2.13.e", True, "SW",
                                 "soil_drilling")
        store.save_coverage_tick(conn, "t", 0, "2.4", "smm.s02.2.13.e", False, "SW")
        mark = store.load_coverage_ticks(conn, "t", 0)["2.4"]["smm.s02.2.13.e"]
        assert mark["ticked"] is False
        assert mark["basis_key"] == "" and mark["ticked_by"] == ""

    def test_a_reticked_head_can_name_a_different_cost(self, conn):
        from client_boq import store

        store.save_coverage_tick(conn, "t", 0, "2.4", "smm.s02.2.13.e", True, "SW", "rig_moves")
        store.save_coverage_tick(conn, "t", 0, "2.4", "smm.s02.2.13.e", True, "SW",
                                 "soil_drilling")
        mark = store.load_coverage_ticks(conn, "t", 0)["2.4"]["smm.s02.2.13.e"]
        assert mark["basis_key"] == "soil_drilling"

    def test_the_link_reaches_the_entry(self, conn):
        """`coverage_for` must carry it through, or the classification has nothing to classify."""
        from client_boq.models import BillItem

        item = BillItem(bill_no="2", item_ref="2.13", full_ref="2.13",
                        description="Rotary drilling in material other than rock")
        ticks = {"smm.s02.2.13.e": {"ticked": True, "ticked_by": "SW", "ticked_at": None,
                                    "basis_key": "soil_drilling"}}
        coverage = boq_coverage.coverage_for(item, ticks=ticks)
        linked = [e for e in coverage.entries if e.basis_key]
        assert linked and linked[0].basis_key == "soil_drilling"


class TestTheColumnIsAdditive:

    def test_a_database_created_before_the_column_gains_it(self, tmp_path):
        """No migration framework here, so additive columns are applied by shape. A tick written
        before the column existed must read back as "asserted, no cost named" rather than as NULL."""
        import sqlite3

        from client_boq import models

        db = tmp_path / "old.db"
        old = sqlite3.connect(str(db))
        old.execute("""
            CREATE TABLE client_boq_coverage_ticks (
                set_id TEXT NOT NULL, rev INTEGER NOT NULL, full_ref TEXT NOT NULL,
                head_key TEXT NOT NULL, ticked INTEGER NOT NULL DEFAULT 0,
                ticked_by TEXT NOT NULL DEFAULT '', ticked_at TEXT,
                PRIMARY KEY (set_id, rev, full_ref, head_key))
        """)
        old.execute("INSERT INTO client_boq_coverage_ticks VALUES ('t', 0, '2.4', 'h', 1, 'SW', "
                    "'2026-01-01T00:00:00+00:00')")
        old.commit()
        old.close()

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        models.init_tables(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(client_boq_coverage_ticks)")}
        assert "basis_key" in columns
        row = conn.execute("SELECT basis_key, ticked FROM client_boq_coverage_ticks").fetchone()
        assert row["basis_key"] == "" and row["ticked"] == 1
        conn.close()

    def test_applying_it_twice_is_a_no_op(self, tmp_path):
        import sqlite3

        from client_boq import models

        db = tmp_path / "twice.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        models.init_tables(conn)
        models.init_tables(conn)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(client_boq_coverage_ticks)")]
        assert columns.count("basis_key") == 1
        conn.close()
