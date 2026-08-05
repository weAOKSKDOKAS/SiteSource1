"""The output book: what your company knows, and how a tender is allowed to disagree with it.

The rule these defend: **an inherited number and a chosen number are different claims, and the app
must never lose track of which it is holding.**

That distinction is the whole reason the book exists as a separate thing from a tender. *20 m a day
in soil* is what the company stands behind; *9 m a day on that hill* is what one estimator decided
about one group of holes. Both are legitimate, they are frequently the same digits, and a screen
that cannot tell them apart is a screen nobody should price from — which is why
:func:`client_boq.boq.outputs.resolve` is the only place the answer is worked out, and why a group
records overriding as an **act** rather than letting it be inferred from a value.

The other rule here is quieter and bites harder: **the book's defaults are the engine's own
constants, imported and never retyped.** A book that reads 33% while :mod:`client_boq.boq.resources`
prices at 30% is a bug invisible from either file on its own, so the drift test below is the only
thing standing between the two.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq import store
from client_boq.boq import duration as duration_mod
from client_boq.boq import outputs as outputs_mod
from client_boq.boq import resources as resources_mod
from client_boq.boq.groups import HoleGroup
from client_boq.boq.outputs import (
    NORM_INDEX,
    NORMS,
    SOURCE_BOOK,
    SOURCE_MISSING,
    SOURCE_YOURS,
    OutputBook,
    apply_to_group,
    default_book,
    resolve,
)

BASE = "/client-boq"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


class TestTheDefaultsAreTheEnginesOwn:
    """A norm that has drifted from the constant it mirrors is the one bug nobody would find by
    reading either file. These are the only thing that catches it."""

    @pytest.mark.parametrize("key, constant", [
        ("mob_days", resources_mod.DEFAULT_MOB_DAYS),
        ("markup_pct", resources_mod.DEFAULT_MARKUP_PCT),
    ])
    def test_a_default_matches_the_module_that_prices_from_it(self, key, constant):
        assert NORM_INDEX[key].default == constant

    def test_the_decay_norm_names_the_band_the_simulation_actually_uses(self):
        assert f"{duration_mod.DEPTH_BAND_M:g} m" in NORM_INDEX["decay_pct"].label

    def test_every_norm_is_declared_once_and_lands_in_a_real_block(self):
        assert len(NORM_INDEX) == len(NORMS), "two norms share a key"
        assert {n.block for n in NORMS} <= set(outputs_mod.BLOCK_ORDER)
        assert set(outputs_mod.BLOCK_TITLE) == set(outputs_mod.BLOCK_ORDER)


class TestTheBook:
    def test_an_unset_norm_falls_back_to_its_default_rather_than_zero(self):
        assert OutputBook().get("soil_output") == 20.0

    def test_a_norm_the_book_never_heard_of_is_none_not_zero(self):
        # 0.0 is a claim ("holes do not slow down"); None is the absence of one. A caller has to be
        # able to tell those apart or MISSING silently becomes a price.
        assert OutputBook().get("helicopter_hours") is None

    def test_a_stored_zero_survives_as_a_zero(self):
        assert OutputBook(values={"decay_pct": 0.0}).get("decay_pct") == 0.0

    def test_decay_is_said_as_a_percentage_and_read_as_a_fraction(self):
        # Stored the way it is spoken, converted in exactly one place, so no caller has to remember.
        assert OutputBook(values={"decay_pct": 5.0}).decay == 0.05

    def test_the_shipped_book_declares_every_norm(self):
        assert set(default_book().values) == set(NORM_INDEX)


class TestResolve:
    def test_an_untouched_norm_comes_back_as_the_books(self):
        settled = resolve(default_book(), {}, keys=["soil_output"])["soil_output"]
        assert settled.source == SOURCE_BOOK and settled.value == 20.0

    def test_a_typed_norm_comes_back_as_yours_and_still_carries_the_books(self):
        settled = resolve(default_book(), {"soil_output": 9.0}, keys=["soil_output"])["soil_output"]
        assert settled.source == SOURCE_YOURS and settled.value == 9.0
        assert settled.book_value == 20.0, "the chip has to be able to say ⟨BOOK 20⟩ beside your 9"
        assert settled.overridden

    def test_typing_the_books_own_number_is_still_yours(self):
        # A number somebody chose is a different claim from one they inherited, even when the digits
        # match — and only the person who chose it can be asked why.
        settled = resolve(default_book(), {"soil_output": 20.0}, keys=["soil_output"])["soil_output"]
        assert settled.source == SOURCE_YOURS

    def test_a_norm_nobody_declared_is_flagged_missing_and_priced_at_nothing(self):
        settled = resolve(default_book(), {}, keys=["helicopter_hours"])["helicopter_hours"]
        assert settled.source == SOURCE_MISSING and settled.value == 0.0
        assert settled.book_value is None

    def test_a_resolution_carries_the_label_and_unit_so_a_screen_needs_no_second_lookup(self):
        settled = resolve(default_book(), {}, keys=["soil_output"])["soil_output"]
        assert settled.label == "Drilling, soil" and settled.unit == "m/day"

    def test_resolving_everything_covers_the_whole_book_plus_anything_typed(self):
        settled = resolve(default_book(), {"helicopter_hours": 3.0})
        assert set(settled) == {*NORM_INDEX, "helicopter_hours"}


class TestInheritingIntoAGroup:
    """The group's defaults are a trap: ``decay`` is 0.05 whether or not anybody chose it."""

    def test_a_group_nobody_touched_inherits_everything_and_says_so(self):
        group = HoleGroup(label="Roadside", stations=["a"])
        filled, sources = apply_to_group(group, default_book())
        assert filled.soil_output == 20.0 and filled.rock_output == 10.0
        assert filled.decay == 0.05
        assert {s.source for s in sources.values()} == {SOURCE_BOOK}

    def test_decay_is_book_even_though_the_field_already_held_the_same_number(self):
        # The value cannot distinguish these two, so the recorded act has to.
        untouched = HoleGroup(label="g", decay=0.05)
        chosen = HoleGroup(label="g", decay=0.05, overrides=["decay"])
        assert apply_to_group(untouched, default_book())[1]["decay"].source == SOURCE_BOOK
        assert apply_to_group(chosen, default_book())[1]["decay"].source == SOURCE_YOURS

    def test_an_overridden_output_wins_and_is_marked_yours(self):
        group = HoleGroup(label="Hillside", soil_output=9.0, overrides=["soil_output"])
        filled, sources = apply_to_group(group, default_book())
        assert filled.soil_output == 9.0
        assert sources["soil_output"].source == SOURCE_YOURS
        assert sources["rock_output"].source == SOURCE_BOOK, "one override does not orphan the rest"

    def test_an_overridden_decay_survives_the_percent_round_trip(self):
        group = HoleGroup(label="Hillside", decay=0.06, overrides=["decay"])
        filled, sources = apply_to_group(group, default_book())
        assert filled.decay == pytest.approx(0.06)
        assert sources["decay"].value == pytest.approx(6.0), "the chip shows percent, not 0.06"

    def test_inheriting_makes_an_untouched_group_priceable(self):
        # `ready()` reads 0.0 as "not yet decided", which is right on the Site screen and useless to
        # the engine. Inheritance is what closes that gap without anybody typing a number.
        group = HoleGroup(label="g", stations=["a"], access_class="A", soil_m=100.0, rock_m=20.0)
        assert "soil output (m/day)" in group.ready()
        assert apply_to_group(group, default_book())[0].ready() == []

    def test_the_source_map_is_keyed_by_the_field_the_screen_shows(self):
        _, sources = apply_to_group(HoleGroup(label="g"), default_book())
        assert set(sources) == {"soil_output", "rock_output", "decay"}


class TestPersistence:
    def test_a_saved_norm_comes_back_and_the_rest_still_default(self):
        conn = store.get_conn()
        try:
            store.save_output_norm(conn, "soil_output", 18.0, unit="m/day", actor="SW")
            book = store.load_output_book(conn)
            assert book.get("soil_output") == 18.0
            assert book.get("rock_output") == 10.0
            assert store.output_norm_meta(conn)["soil_output"]["updated_by"] == "SW"
        finally:
            conn.close()

    def test_an_empty_table_is_a_book_of_defaults_not_a_book_of_zeroes(self):
        conn = store.get_conn()
        try:
            assert store.load_output_book(conn).markup_pct == resources_mod.DEFAULT_MARKUP_PCT
        finally:
            conn.close()


class TestTheHttpSurface:
    def test_the_book_arrives_in_blocks_ready_to_render(self, client):
        body = client.get(f"{BASE}/library/outputs").json()
        assert [b["id"] for b in body["blocks"]] == list(outputs_mod.BLOCK_ORDER)
        assert body["count"] == len(NORMS)
        rows = {row["key"]: row for block in body["blocks"] for row in block["rows"]}
        assert rows["soil_output"]["value"] == 20.0
        assert rows["soil_output"]["unit"] == "m/day"
        assert rows["mob_days"]["note"], "the ⌞ line explains why the number is what it is"

    def test_an_untouched_norm_does_not_claim_to_be_somebodys_decision(self, client):
        body = client.get(f"{BASE}/library/outputs").json()
        rows = {row["key"]: row for block in body["blocks"] for row in block["rows"]}
        assert rows["soil_output"]["source"] == "seed" and rows["soil_output"]["updated_by"] == ""

    def test_setting_a_norm_stamps_who(self, client):
        saved = client.post(f"{BASE}/library/outputs/soil_output", json={"value": 9.0},
                            headers={"X-CBOQ-Actor": "SW"})
        assert saved.status_code == 200 and saved.json()["value"] == 9.0

        body = client.get(f"{BASE}/library/outputs").json()
        rows = {row["key"]: row for block in body["blocks"] for row in block["rows"]}
        assert rows["soil_output"]["source"] == "you"
        assert rows["soil_output"]["updated_by"] == "SW"
        assert rows["soil_output"]["default"] == 20.0, "the shipped number stays visible"

    def test_a_norm_the_engine_never_reads_is_refused_and_the_real_ones_named(self, client):
        response = client.post(f"{BASE}/library/outputs/vibes", json={"value": 1.0})
        assert response.status_code == 404
        assert "soil_output" in response.json()["detail"]

    def test_a_norm_with_no_number_is_refused_rather_than_becoming_zero(self, client):
        response = client.post(f"{BASE}/library/outputs/soil_output", json={})
        assert response.status_code == 422
        assert "Drilling, soil" in response.json()["detail"]

    def test_forgetting_your_value_puts_the_shipped_default_back(self, client):
        client.post(f"{BASE}/library/outputs/markup_pct", json={"value": 15.0})
        assert client.delete(f"{BASE}/library/outputs/markup_pct").json()["value"] == \
            resources_mod.DEFAULT_MARKUP_PCT
        body = client.get(f"{BASE}/library/outputs").json()
        rows = {row["key"]: row for block in body["blocks"] for row in block["rows"]}
        assert rows["markup_pct"]["source"] == "seed"
