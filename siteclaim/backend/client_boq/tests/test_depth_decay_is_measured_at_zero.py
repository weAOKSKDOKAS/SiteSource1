"""Depth decay: measured at zero, scoped per hole, and the rock band is the driver instead.

THE RULING, from real as-built data rather than an assumption:

* within a hole the rate does NOT fall with depth — 205 drilling-days band 4.42 / 5.32 / 3.41
  m/day at 0-20 / 20-40 / 40 m+, so the middle band is 20% FASTER than the surface;
* per hole, across the 21 holes with five or more drilling days, the depth-to-log-rate correlation
  averages +0.11 and is positive in 13 of them;
* the 40 m+ dip is rock, not depth: over 95 holes corr(rate, rock%) = -0.428 against
  corr(rate, depth) = +0.196, and holding rock constant leaves depth POSITIVE.

So the old -5%/20 m default had the wrong sign, and `groups.py` compounded it over the group's
POOLED total rather than down each hole — 0.95^(600/20) is 21% of the surface rate. Both halves are
fixed here, and both are pinned: the default is 0.0, and a decay somebody asks for deliberately
resets at every hole.
"""

import math

import pytest

from client_boq.boq import empirical
from client_boq.boq.duration import simulate
from client_boq.boq.groups import HoleGroup, HoleShape, band_calibration, summarise
from client_boq.boq.outputs import NORM_INDEX, OutputBook, apply_to_group
from client_boq.boq.schedule import Station, StationSchedule

BOOK_SOIL, BOOK_ROCK = 20.0, 10.0


def _group(soil_m: float, rock_m: float, holes: int, *, rigs: int = 1,
           decay: float = 0.0) -> HoleGroup:
    """A group of ``holes`` identical holes summing to the totals given."""
    return HoleGroup(
        label="G", stations=[f"S{n}" for n in range(holes)], access_class="A", rigs=rigs,
        soil_output=BOOK_SOIL, rock_output=BOOK_ROCK, decay=decay,
        soil_m=soil_m, rock_m=rock_m,
        shapes=[HoleShape(station=f"S{n}", soil_m=soil_m / holes, rock_m=rock_m / holes)
                for n in range(holes)])


# -- the default is zero, everywhere it defaults ------------------------------------------------
class TestZeroIsTheDefault:
    def test_simulate_defaults_to_no_decay(self):
        import inspect
        assert inspect.signature(simulate).parameters["decay"].default == 0.0

    def test_a_fresh_group_defaults_to_no_decay(self):
        assert HoleGroup().decay == 0.0

    def test_the_output_book_norm_defaults_to_no_decay(self):
        assert NORM_INDEX["decay_pct"].default == 0.0
        assert OutputBook().decay == 0.0
        filled, _ = apply_to_group(HoleGroup(label="g"), OutputBook())
        assert filled.decay == 0.0

    def test_at_zero_the_rate_does_not_move_with_depth(self):
        """The claim itself: the hundredth metre is drilled at the same rate as the first."""
        shallow = simulate(20.0, 0.0, soil_output=BOOK_SOIL, rock_output=BOOK_ROCK)
        deep = simulate(200.0, 0.0, soil_output=BOOK_SOIL, rock_output=BOOK_ROCK)
        assert shallow.soil_days == pytest.approx(20.0 / BOOK_SOIL)
        assert deep.soil_days == pytest.approx(200.0 / BOOK_SOIL)
        assert deep.soil_days == pytest.approx(shallow.soil_days * 10), "strictly proportional"
        assert {d.soil_rate for d in deep.days if d.soil_rate > 0} == {BOOK_SOIL}


# -- the scope fix: a group is holes, not one long hole ------------------------------------------
class TestDecayIsPerHole:
    def test_three_fifty_metre_holes_are_not_one_hundred_and_fifty_metre_hole(self):
        """The exact ratio, pinned. Three 50 m holes at 5%/20 m take 7.7368 soil-days; a single
        150 m hole takes 8.7030 — 12.49% more, purely from a depth the rig never reached."""
        per_hole = _group(150.0, 0.0, holes=3, decay=0.05).duration()
        one_hole = _group(150.0, 0.0, holes=1, decay=0.05).duration()

        assert per_hole.soil_days == pytest.approx(7.7368, abs=0.0005)
        assert one_hole.soil_days == pytest.approx(8.7030, abs=0.0005)
        assert one_hole.soil_days / per_hole.soil_days == pytest.approx(1.1249, abs=0.0005)

    def test_the_group_no_longer_pools_its_depth_across_the_rigs_either(self):
        """The old form drilled `group_total / rigs` as one continuous hole. With the same metres
        spread over real holes the answer stops depending on how deep the pooled share happened to
        be."""
        spread_out = _group(600.0, 0.0, holes=12, rigs=1, decay=0.05).duration()
        pooled = simulate(600.0, 0.0, soil_output=BOOK_SOIL, rock_output=BOOK_ROCK, decay=0.05)
        assert spread_out.total_days < pooled.total_days / 2

    def test_at_zero_decay_per_hole_and_pooled_agree_exactly(self):
        """The reason this shape is safe to adopt: at the default it changes nothing at all."""
        for holes in (1, 3, 12, 91):
            group = _group(600.0, 200.0, holes=holes)
            duration = group.duration()
            assert duration.soil_days == pytest.approx(600.0 / BOOK_SOIL)
            assert duration.rock_days_actual == pytest.approx(200.0 / BOOK_ROCK)

    def test_more_rigs_still_mean_fewer_days(self):
        """The behaviour that had to survive the rewrite."""
        one = _group(600.0, 200.0, holes=12, rigs=1).duration()
        two = _group(600.0, 200.0, holes=12, rigs=2).duration()
        four = _group(600.0, 200.0, holes=12, rigs=4).duration()
        assert one.total_days > two.total_days > four.total_days
        assert two.soil_days == pytest.approx(one.soil_days / 2)
        assert four.soil_days == pytest.approx(one.soil_days / 4)

    def test_the_shapes_come_from_the_schedule_not_from_an_average(self):
        schedule = StationSchedule(stations=[
            Station(station="A", soil_m=10.0, rock_m=0.0),
            Station(station="B", soil_m=90.0, rock_m=10.0),
        ])
        group = summarise(HoleGroup(label="G", stations=["A", "B"]), schedule)
        assert [(s.station, s.soil_m, s.rock_m) for s in group.shapes] == [
            ("A", 10.0, 0.0), ("B", 90.0, 10.0)]
        assert group.soil_m == 100.0 and group.rock_m == 10.0

    def test_a_group_with_no_shapes_falls_back_to_its_hole_count_not_to_one_hole(self):
        bare = HoleGroup(label="G", stations=["a", "b", "c"], soil_m=150.0,
                         soil_output=BOOK_SOIL, rock_output=BOOK_ROCK, decay=0.05)
        assert len(bare.hole_shapes()) == 3
        assert bare.duration().soil_days == pytest.approx(7.7368, abs=0.0005)


# -- the inflation the old shape produced is gone -------------------------------------------------
class TestTheSixHundredMetreGroup:
    """The probed case. A 600 m group is 12 holes of 50 m, one rig, book outputs."""

    def test_the_duration_is_the_honest_thirty_days(self):
        assert _group(600.0, 0.0, holes=12, rigs=1).duration().total_days == 30

    def test_the_old_pooled_form_inflated_it_to_sixty_nine(self):
        """What the code used to do, computed here so the size of the error is on the record."""
        old = simulate(600.0, 0.0, soil_output=BOOK_SOIL, rock_output=BOOK_ROCK, decay=0.05)
        assert old.total_days == 69
        assert old.total_days / 30 == pytest.approx(2.3, abs=0.01)

    def test_even_a_deliberate_five_percent_no_longer_inflates_it(self):
        """Ask for padding and you get padding — 3.6% on this group, not 130%, because the decay
        is now bounded by how deep a hole actually goes."""
        padded = _group(600.0, 0.0, holes=12, rigs=1, decay=0.05).duration()
        assert padded.total_days == 31
        assert padded.soil_days / 30.0 < 1.05

    def test_every_group_priced_rate_moves_with_the_days(self):
        """A rate is cost ÷ days. The point of the fix, stated as the thing it changes."""
        fixed = _group(600.0, 0.0, holes=12, rigs=1).duration()
        old = simulate(600.0, 0.0, soil_output=BOOK_SOIL, rock_output=BOOK_ROCK, decay=0.05)
        assert 600.0 / fixed.total_days == pytest.approx(20.0)
        assert 600.0 / old.total_days == pytest.approx(8.7, abs=0.05)


# -- the rock band is what drives the group now ---------------------------------------------------
class TestTheBandDrivesTheGroup:
    def test_the_group_selects_its_band_from_its_own_rock_fraction(self):
        soft = band_calibration(_group(900.0, 100.0, holes=20))      # 10% rock
        hard = band_calibration(_group(300.0, 700.0, holes=20))      # 70% rock
        assert soft.rock_fraction == pytest.approx(0.10)
        assert hard.rock_fraction == pytest.approx(0.70)
        assert soft.band_label == "under 15% rock" and soft.band_rate == 3.39
        assert hard.band_label == "over 60% rock" and hard.band_rate == 1.82
        assert soft.expected_work_days < hard.expected_work_days, "rock is slower, and it says so"

    def test_the_banded_table_feeds_it_and_not_a_decay_curve(self):
        """Two groups of identical metres and identical outputs, differing only in rock fraction,
        must get different expected durations. Under the old shape nothing about rock reached the
        group path at all — only depth did, through the decay curve."""
        soft = band_calibration(_group(900.0, 100.0, holes=20))
        hard = band_calibration(_group(300.0, 700.0, holes=20))
        assert soft.expected_work_days / hard.expected_work_days == pytest.approx(
            hard.band_rate / soft.band_rate)

    def test_a_group_below_the_lowest_band_is_told_so_rather_than_priced_anyway(self):
        table = empirical.BandTable(bands=[
            empirical.Band(label="15% to 35% rock", lower=0.15, rate=3.69, holes=32)])
        out = band_calibration(_group(1000.0, 0.0, holes=20), bands=table)
        assert out.band_label == "" and out.problems
        assert "nothing to say" in out.problems[0]

    def test_the_divergence_compares_like_with_like(self):
        """The band rate includes per-hole set-up; the outputs do not. Set-up is added explicitly
        before the two are compared, so the number is a real disagreement rather than a definition
        gap."""
        group = _group(600.0, 200.0, holes=12)
        without = band_calibration(group, setup_days_per_hole=0.0)
        with_setup = band_calibration(group, setup_days_per_hole=4.73)
        assert with_setup.simulated_work_days > without.simulated_work_days
        assert with_setup.simulated_work_days - without.simulated_work_days == pytest.approx(
            12 * 4.73)
        assert "set-up" in with_setup.note


# -- the two calibration tables, and why one of them is not the default ---------------------------
class TestBothTablesAreOnTheRecord:
    def test_the_as_built_measurement_is_recorded_with_its_source(self):
        rates = {b.label: b.rate for b in empirical.AS_BUILT_BANDS.bands}
        assert rates == {"under 15% rock": 4.22, "15% to 35% rock": 4.32,
                         "35% to 60% rock": 3.85, "over 60% rock": 2.23}
        assert {b.holes for b in empirical.AS_BUILT_BANDS.bands} == {12, 37, 23}
        assert sum(b.holes for b in empirical.AS_BUILT_BANDS.bands) == 95
        assert "Lok Ma Chau" in empirical.AS_BUILT_SOURCE
        assert "Kwun Tong North" in empirical.AS_BUILT_SOURCE

    def test_the_defaults_were_not_silently_replaced(self):
        assert [b.rate for b in empirical.DEFAULT_BANDS.sorted_bands()] == [3.39, 3.69, 2.64, 1.82]

    def test_the_reconciliation_is_computed_from_the_corpus_and_shows_why(self):
        """The arithmetic that settles it, recomputed rather than asserted from memory: a band rate
        is a DIVISOR, so `metres / rate` has to come back to the day count actually worked."""
        recon = empirical.reconciliation()
        assert recon["corpus_work_days"] == 1260
        assert recon["pooled_rate"] == pytest.approx(2.771, abs=0.001)

        by_name = {t["name"]: t for t in recon["tables"]}
        assert by_name["current default"]["error_against_actual"] == pytest.approx(-0.047, abs=0.002)
        assert by_name["as-built measurement"]["error_against_actual"] == pytest.approx(
            -0.249, abs=0.002)
        assert abs(by_name["as-built measurement"]["error_against_actual"]) > 5 * abs(
            by_name["current default"]["error_against_actual"])
        assert "not on the same definition" in recon["verdict"]

    def test_the_daily_log_evidence_is_on_the_record(self):
        bands = {b["band"]: b["m_per_day"] for b in empirical.DAILY_RATE_BY_DEPTH}
        assert bands["20 to 40 m"] > bands["0 to 20 m"], "the middle band is FASTER"
        assert empirical.DEPTH_RATE_CORRELATION["mean"] > 0
        assert empirical.DEPTH_RATE_CORRELATION["positive"] > (
            empirical.DEPTH_RATE_CORRELATION["holes"] / 2)
        assert empirical.RATE_DRIVERS["rock_fraction"] < 0 < empirical.RATE_DRIVERS["depth"]
        assert abs(empirical.RATE_DRIVERS["rock_fraction"]) > empirical.RATE_DRIVERS["depth"]
        assert empirical.RATE_DRIVERS["drilling_days_measured"] == 205


class TestTheRegisterCarriesBoth:
    def test_both_tables_and_the_decay_ruling_reach_the_assumptions_register(self):
        from client_boq.boq import assumptions as assum
        from client_boq.boq.buildup import build, build_spread
        from client_boq.boq.model import default_model
        from client_boq.boq.programme import Quantities, derive

        model = default_model()
        programme = derive(Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0), model)
        spread = build_spread(programme, model)
        register = assum.build(programme, model, build(programme, model, spread), spread)
        rows = {r.key: r for r in register.rows}

        default_row = rows["bands_current_default"]
        as_built_row = rows["bands_as-built_measurement"]
        assert default_row.source == assum.SOURCE_EMPIRICAL
        assert as_built_row.source == assum.SOURCE_EMPIRICAL
        assert "IN FORCE." in default_row.basis
        assert "RECORDED, not in force." in as_built_row.basis
        assert "4.22" in as_built_row.value and "3.39" in default_row.value
        assert "Lok Ma Chau" in as_built_row.basis, "the source is named, not implied"
        assert default_row.confidence == assum.CONFIDENCE_HIGH
        assert as_built_row.confidence == assum.CONFIDENCE_LOW, "25% off the real day count"

        decay_row = rows["depth_decay"]
        assert decay_row.value.startswith("0%")
        assert "205 real drilling-days" in decay_row.basis
        assert "counts it twice" in decay_row.basis
