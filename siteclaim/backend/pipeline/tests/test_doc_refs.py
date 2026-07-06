"""Reference extraction from SoR item text (relevant-doc assembler, RD1)."""

from pipeline.stage_03_dispatch.doc_refs import (
    clause_of,
    extract_refs,
    refs_for_items,
    section_refs,
    spec_section_of,
)
from schemas.models import SorItem


def test_extracts_every_reference_kind_from_one_item():
    text = ("Rotary drilling to PS 28.2.07 and PS 1.13.1, per GS 25.01, preamble PB/B11, "
            "as Standard Drawing C1012B and Sketch S3, see Appendix 7.4.1.")
    refs = extract_refs(text)
    assert refs["ps"] == ["PS 28.2.07", "PS 1.13.1"]
    assert refs["gs"] == ["GS 25.01"]
    assert refs["pb"] == ["PB/B11"]
    assert refs["standard_drawing"] == ["Standard Drawing C1012B"]
    assert refs["sketch"] == ["Sketch S3"]
    assert refs["appendix"] == ["Appendix 7.4.1"]


def test_distinct_and_tolerant_of_spacing_and_case():
    refs = extract_refs("ps 7.1 PS 7.1 again, PB / c2, appendix 7")
    assert refs["ps"] == ["PS 7.1"]  # de-duplicated, spacing/case normalised
    assert refs["pb"] == ["PB/C2"]
    assert refs["appendix"] == ["Appendix 7"]


def test_no_false_positive_inside_words():
    assert extract_refs("GPS survey and maps of the site") == {}  # PS not fired inside GPS/maps


def test_section_rollup_groups_by_item_section():
    items = [
        SorItem(item_ref="E10", description="Drilling per PS 7.13.1 and Appendix 7.4", section="E"),
        SorItem(item_ref="E11", description="More drilling per PS 7.14", section="E"),
        SorItem(item_ref="J1", description="Survey per GS 25.01", section="J"),
    ]
    by_sec = section_refs(items)
    assert by_sec["E"]["ps"] == ["PS 7.13.1", "PS 7.14"]
    assert by_sec["E"]["appendix"] == ["Appendix 7.4"]
    assert by_sec["J"]["gs"] == ["GS 25.01"]
    assert refs_for_items(items)["ps"] == ["PS 7.13.1", "PS 7.14"]


def test_spec_section_and_clause_helpers():
    assert spec_section_of("PS 28.2.07") == "28" and clause_of("PS 28.2.07") == "28.2.07"
    assert spec_section_of("Appendix 7.4.1") == "7" and clause_of("Appendix 7.4.1") == "7.4.1"
