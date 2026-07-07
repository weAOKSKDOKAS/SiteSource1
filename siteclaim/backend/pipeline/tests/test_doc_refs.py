"""Reference extraction from SoR item text (relevant-doc assembler, RD1)."""

from pipeline.stage_03_dispatch.doc_refs import (
    base_clause,
    clause_of,
    extract_refs,
    parse_clause_refs,
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


# -- Assembler v2: clause-ref parsing (GS / PS with suffixes / MM PB) -------
def test_parse_clause_ref_column_captures_gs_ps_and_pb():
    refs = parse_clause_refs("GS 7.34 / PS 7.34A / PB 71 / PS 7.37A / PS 7.41.(4)S")
    assert refs["gs"] == ["GS 7.34"]
    assert refs["ps"] == ["PS 7.34A", "PS 7.37A", "PS 7.41.(4)S"]  # letter / bracket / S suffixes kept
    assert refs["pb"] == ["PB 71"]                                  # MM preamble clause, number form


def test_clause_of_keeps_suffix_and_base_clause_strips_it():
    assert clause_of("PS 7.34A") == "7.34A" and base_clause("7.34A") == "7.34"
    assert clause_of("PS 7.41.(4)S") == "7.41.(4)S" and base_clause("7.41.(4)S") == "7.41"
    assert clause_of("PS 28.2.07") == "28.2.07" and base_clause("28.2.07") == "28.2.07"  # plain unchanged


def test_clause_of_keeps_a_dotless_bracket_suffix():
    # Real specs write the bracketed sub-index with OR without the separating dot; both must be
    # kept whole so an index key built from ``7.72(6)S`` matches the reference ``PS 7.72(6)S``.
    assert clause_of("PS 7.72(6)S") == "7.72(6)S" and base_clause("7.72(6)S") == "7.72"
    assert extract_refs("priced to PS 7.72(6)S")["ps"] == ["PS 7.72(6)S"]  # suffix not truncated to 7.72


def test_pb_number_form_and_preamble_form_both_parse():
    assert extract_refs("measured per PB 71")["pb"] == ["PB 71"]     # MM clause
    assert extract_refs("preamble PB/B11 and PB / c2")["pb"] == ["PB/B11", "PB/C2"]  # doc preambles


def test_refs_are_read_from_the_item_clause_ref_column():
    # The Clause Ref column is the primary source; description is only a backstop.
    item = SorItem(item_ref="I3", description="Rotary drilling in rock", section="I",
                   clause_refs=["GS 7.34", "PS 7.34A", "PS 7.37A", "PB 71"])
    refs = refs_for_items([item])
    assert refs["ps"] == ["PS 7.34A", "PS 7.37A"] and refs["gs"] == ["GS 7.34"] and refs["pb"] == ["PB 71"]
    by_sec = section_refs([item])
    assert by_sec["I"]["ps"] == ["PS 7.34A", "PS 7.37A"]
