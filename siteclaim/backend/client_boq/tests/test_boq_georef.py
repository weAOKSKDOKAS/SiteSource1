"""Putting ninety-one holes on five drawing sheets, by arithmetic.

The rule these defend: **a station is placed by a ruler or it is not placed at all.**

The screen this feeds — Site › Holes — turns "hunt across five 1:2000 sheets" into ninety-one small
pictures, and its entire value rests on each picture being of the right place. A tile that is thirty
metres out does not look broken; it looks like a slightly different bit of hillside, and somebody
classes a hole from it. So this module refuses in every case where it cannot be certain: too few
control points, marks that do not span the page, a scale that disagrees between the axes, a station
that falls off the sheet. None of those is approximated and none is clamped.

The geometry is the reference contract's: HK1980 grid coordinates from GI/210, on a sheet whose
printed grid crosses give two known points.
"""

from __future__ import annotations

import pytest

from client_boq.boq.georef import (
    DEFAULT_WINDOW_M,
    GridMark,
    SheetRegistration,
    crops_for,
    plot,
    sheet_for,
)
from client_boq.boq.schedule import Station, StationSchedule

# A sheet spanning 1,000 m across and 1,000 m down, with marks at the 10% and 90% grid crosses —
# which is how a real one is registered: read two printed intersections, not the paper corners.
SHEET = SheetRegistration(
    sheet="60740338/GI/201", part_id="09-DRG", page=3,
    marks=[
        GridMark(easting=825_000.0, northing=839_000.0, x=0.1, y=0.1, label="825000E 839000N"),
        GridMark(easting=825_800.0, northing=838_200.0, x=0.9, y=0.9, label="825800E 838200N"),
    ],
)


def _station(name, e, n):
    return Station(station=name, easting=e, northing=n, soil_m=30.0, length_m=30.0)


@pytest.fixture
def schedule():
    return StationSchedule(
        set_id="t", source_sheet="60740338/GI/210",
        stations=[
            _station("CE19-ABH02", 825_100.0, 838_900.0),   # comfortably on the sheet
            _station("CE19-ABH19", 826_337.69, 839_177.88),  # east of it: another sheet
            Station(station="CE19-ABH99", soil_m=30.0, length_m=30.0),  # no coordinates at all
        ],
    )


class TestTheRegistration:
    def test_two_marks_span_the_page_and_give_its_scale(self):
        across, down = SHEET.metres_per_page()
        assert across == pytest.approx(1000.0) and down == pytest.approx(1000.0)

    def test_a_mark_lands_back_on_itself(self):
        # The only round trip that matters: the arithmetic has to reproduce its own inputs.
        for mark in SHEET.marks:
            x, y = SHEET.locate(mark.easting, mark.northing)
            assert (x, y) == pytest.approx((mark.x, mark.y))

    def test_north_is_up_the_page(self):
        # Page y grows downward and northing grows upward; getting this backwards mirrors the whole
        # sheet, which is the one error that still produces a plausible-looking picture.
        higher = SHEET.locate(825_400.0, 838_900.0)
        lower = SHEET.locate(825_400.0, 838_500.0)
        assert higher[1] < lower[1]

    def test_east_is_across_the_page(self):
        assert SHEET.locate(825_100.0, 838_600.0)[0] < SHEET.locate(825_700.0, 838_600.0)[0]

    def test_one_mark_is_not_enough_and_says_so(self):
        lonely = SheetRegistration(sheet="GI/201", marks=[SHEET.marks[0]])
        assert not lonely.usable()
        assert "needs two grid marks" in lonely.problems()[0]

    def test_two_marks_on_the_same_grid_line_cannot_locate_anything(self):
        flat = SheetRegistration(sheet="GI/201", marks=[
            GridMark(easting=825_000.0, northing=839_000.0, x=0.1, y=0.5),
            GridMark(easting=825_800.0, northing=839_000.0, x=0.9, y=0.5),
        ])
        assert any("northing" in p for p in flat.problems())

    def test_a_scale_that_disagrees_between_the_axes_names_both_numbers(self):
        # A drawing is isotropic. If it reads 1,000 m across and 500 m down, somebody mistyped a
        # coordinate — and averaging that away places every station slightly wrong, forever.
        skewed = SheetRegistration(sheet="GI/201", marks=[
            GridMark(easting=825_000.0, northing=839_000.0, x=0.1, y=0.1),
            GridMark(easting=825_800.0, northing=838_600.0, x=0.9, y=0.9),
        ])
        problem = " ".join(skewed.problems())
        assert "1000.0 m across" in problem and "500.0 m down" in problem
        assert "mistyped" in problem

    def test_a_small_scale_disagreement_is_tolerated_because_paper_is_not_perfect(self):
        near = SheetRegistration(sheet="GI/201", marks=[
            GridMark(easting=825_000.0, northing=839_000.0, x=0.1, y=0.1),
            GridMark(easting=825_800.0, northing=838_192.0, x=0.9, y=0.9),   # 1% out
        ])
        assert near.usable()

    def test_an_unlocated_sheet_refuses_to_place_anything(self):
        with pytest.raises(ValueError, match="is not located"):
            SheetRegistration(sheet="GI/201").locate(825_100.0, 838_900.0)

    def test_a_registration_starts_unconfirmed(self):
        # Two typed numbers are a proposal until somebody has looked at the sheet beside them.
        assert SHEET.confirmed_by == ""


class TestPlacingStations:
    def test_a_station_on_the_sheet_is_marked_so(self):
        placed = SHEET.place("CE19-ABH02", 825_100.0, 838_900.0)
        assert placed.on_sheet
        assert (placed.x, placed.y) == pytest.approx((0.2, 0.2))

    def test_a_station_beyond_the_page_is_reported_not_clamped(self):
        # It is on another sheet. Pinning it to the edge would caption a picture of the wrong place
        # with the right station name.
        placed = SHEET.place("CE19-ABH19", 826_337.69, 839_177.88)
        assert not placed.on_sheet and placed.x > 1.0

    def test_plotting_the_schedule_separates_the_two(self, schedule):
        result = plot(schedule, SHEET)
        assert [p.station for p in result.on_sheet()] == ["CE19-ABH02"]
        assert result.elsewhere() == ["CE19-ABH19"]

    def test_a_station_with_no_coordinates_is_named_rather_than_placed_at_the_origin(self, schedule):
        result = plot(schedule, SHEET)
        assert "CE19-ABH99" in " ".join(result.problems)
        assert all(p.station != "CE19-ABH99" for p in result.placed)

    def test_plotting_against_a_broken_registration_returns_the_reason_not_a_guess(self, schedule):
        result = plot(schedule, SheetRegistration(sheet="GI/201"))
        assert result.placed == [] and "needs two grid marks" in result.problems[0]


class TestTheCropAScreenRenders:
    def test_a_window_is_centred_on_the_station_and_the_right_size(self):
        box = SHEET.crop(825_400.0, 838_600.0, window_m=100.0)
        assert (box.centre_x, box.centre_y) == pytest.approx((0.5, 0.5))
        # 100 m of a 1,000 m page is a tenth of it, both ways.
        assert (box.x1 - box.x0) == pytest.approx(0.1)
        assert (box.y1 - box.y0) == pytest.approx(0.1)
        assert not box.clipped

    def test_a_station_near_the_edge_produces_a_clipped_box_and_admits_it(self):
        # 20 m inside the page edge, with a 100 m window: half the tile is off the paper. The mark
        # at 825,000E sits at x = 0.1, so the page starts 100 m west of it.
        box = SHEET.crop(824_920.0, 839_080.0, window_m=100.0)
        assert box.clipped, "the window runs off the page and the tile has to know"
        assert box.x0 < 0.0 and box.y0 < 0.0

    def test_the_default_window_carries_enough_ground_to_judge_access_by(self):
        assert DEFAULT_WINDOW_M == 100.0

    def test_crops_cover_every_station_that_lands_and_no_others(self, schedule):
        crops = crops_for(schedule, SHEET)
        assert set(crops) == {"CE19-ABH02"}, "off-sheet and unlocated stations get no tile"

    def test_an_unlocated_sheet_yields_no_crops_rather_than_wrong_ones(self, schedule):
        assert crops_for(schedule, SheetRegistration(sheet="GI/201")) == {}


class TestChoosingBetweenSheets:
    """The site plan is five sheets and a station is on exactly one of them."""

    EAST = SheetRegistration(sheet="GI/202", marks=[
        GridMark(easting=826_000.0, northing=839_400.0, x=0.1, y=0.1),
        GridMark(easting=826_800.0, northing=838_600.0, x=0.9, y=0.9),
    ])

    def test_the_sheet_a_point_falls_on_is_returned(self):
        found = sheet_for(826_337.69, 839_177.88, [SHEET, self.EAST])
        assert found is not None and found.sheet == "GI/202"

    def test_a_point_on_no_sheet_is_none_rather_than_the_nearest(self):
        # A station on no sheet means a wrong coordinate or a missing drawing. Both are worth
        # knowing; a nearest-match hides both.
        assert sheet_for(999_999.0, 999_999.0, [SHEET, self.EAST]) is None

    def test_a_broken_registration_is_skipped_not_matched(self):
        assert sheet_for(825_100.0, 838_900.0, [SheetRegistration(sheet="bad"), SHEET]).sheet == \
            "60740338/GI/201"
