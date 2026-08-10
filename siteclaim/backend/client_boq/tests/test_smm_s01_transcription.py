"""SMM S01 is transcribed, and the transcription is honest about what it could not read.

THE LINE THIS FILE DEFENDS. A transcription is only worth having if you can tell, from the
transcription itself, what is missing from it. Three ways that goes wrong, one class of test each:

**A silent drop.** 264 printed bullets go in; 264 heads, two fragments and one NOT-USED marker come
out. The arithmetic closes on the source's own count, so a bullet cannot go missing without the sum
saying so.

**A quiet completion.** Three sub-heads stop mid-sentence in the pack and two "clauses" are only the
tail of an amendment whose substituted text never extracted. Every one of them is easy to finish
from knowledge of what such a clause usually says, and finishing any of them would put words in the
contract's mouth. They are kept exactly as they break.

**A partial list wearing the clothes of a whole one.** ¶1.06 prints (c), (f), (h)–(p), (w). The
missing letters are base SMM 1992 sub-heads — real, binding, and not in this pack. `BASE_SMM_GAPS`
DERIVES that from the letters rather than asserting it, and derives INTERIOR gaps only, because a
clause running (a)–(e) with no holes proves nothing about whether the base carries an (f).
"""

from __future__ import annotations

import re

import pytest

from client_boq.boq import smm_s01
from client_boq.boq.heads import FROM_AMENDMENT

ALL_HEADS = [head for heads in smm_s01.CLAUSES.values() for head in heads]


class TestTheArithmeticClosesOnTheSource:
    def test_every_printed_bullet_is_accounted_for(self):
        """264 in the pack, 264 out — after the one split and the three that are not heads.

        This is the test that makes a silent drop impossible. Rewriting a clause and losing a
        sub-head changes this sum, and the sum is the source document's own published count.
        """
        heads = len(ALL_HEADS)
        recovered_by_split = sum(len(row["split_into"]) - 1 for row in smm_s01.RUN_ON_SPLIT)
        not_a_head = len(smm_s01.FRAGMENTS) + len([n for n in smm_s01.NOT_USED if n["letter"]])
        assert heads - recovered_by_split + not_a_head == 264

    def test_forty_clauses_carry_heads_and_two_are_only_fragments(self):
        assert len(smm_s01.CLAUSES) == 40
        assert len(smm_s01.FRAGMENTS) == 2, "¶1.17 and ¶1.19 — 42 clauses in the pack"
        assert not ({f["clause"] for f in smm_s01.FRAGMENTS} & set(smm_s01.CLAUSES))

    def test_no_clause_is_transcribed_empty(self):
        """An empty list would read as "this clause demands nothing", which is never true."""
        assert not [clause for clause, heads in smm_s01.CLAUSES.items() if not heads]

    def test_every_key_is_unique_and_names_its_clause_and_letter(self):
        keys = [head.key for head in ALL_HEADS]
        assert len(keys) == len(set(keys))
        for clause, heads in smm_s01.CLAUSES.items():
            for head in heads:
                assert head.key.startswith(f"smm.s01.{clause}."), head.key

    def test_every_clause_ref_agrees_with_its_key(self):
        """Click through and land on the right sub-clause — the whole point of a reference."""
        for head in ALL_HEADS:
            clause, letter = head.key.removeprefix("smm.s01.").rsplit(".", 1)
            assert head.clause_ref.startswith(f"SMM S01 ¶{clause}({letter})"), head.key


class TestNothingIsCompletedForThePack:
    def test_the_three_truncated_sub_heads_are_named_and_left_broken(self):
        broken = {(row["clause"], row["letter"]) for row in smm_s01.TRUNCATED}
        assert broken == {("1.96", "d"), ("1.112", "s"), ("1.156", "c")}

    def test_a_truncated_head_still_ends_where_the_pack_stopped(self):
        head = smm_s01.CLAUSES["1.156"][2]
        assert head.label.endswith("for complying with"), (
            "the pack does not say what is to be complied with, and neither does this")

    def test_the_colon_that_introduces_a_list_the_pack_never_printed_survives(self):
        head = next(h for h in smm_s01.CLAUSES["1.112"] if h.key.endswith(".s"))
        assert head.label.endswith("the followings:")

    def test_the_two_fragments_produce_no_heads_at_all(self):
        """"(i) and substitute : Unit 1.17" is the tail of an instruction, not item coverage. A
        head invented from it would be pure fabrication with a real clause number on it."""
        for fragment in smm_s01.FRAGMENTS:
            assert fragment["clause"] not in smm_s01.CLAUSES
            assert "did not extract" in fragment["reading"]

    def test_not_used_is_recorded_and_is_never_a_tickable_head(self):
        """A checklist line an estimator must tick to reach "all covered" is an obligation, and the
        pack says there is none at ¶1.14(o)."""
        assert ("1.14", "o") in {(n["clause"], n["letter"]) for n in smm_s01.NOT_USED}
        assert "smm.s01.1.14.o" not in {head.key for head in ALL_HEADS}
        assert not [h for h in ALL_HEADS if h.label.strip().upper() == "NOT USED"]

    def test_the_packs_own_misspelling_is_left_alone(self):
        """"accpetance", twice. Correcting it would make this file stop matching the document it
        claims to transcribe — and the next reader could not tell which of the two was true."""
        misspelt = [h.key for h in ALL_HEADS if "accpetance" in h.label]
        assert sorted(misspelt) == ["smm.s01.1.77.b", "smm.s01.1.85.b"]

    def test_the_second_k_of_clause_106_is_named_rather_than_written(self):
        """The pack prints TWO sub-heads lettered (k) and only one was transcribed. The other is a
        known gap with a known letter, which is a thing to say out loud, not to round off."""
        assert smm_s01.SECOND_K["letter"] == "k"
        assert "office assistants" in smm_s01.SECOND_K["missing"]
        assert len([h for h in smm_s01.CLAUSES["1.06"] if h.key.endswith(".k")]) == 1


class TestTheBleedIsCutAndTheCutIsRecorded:
    def test_no_label_carries_the_next_sections_heading(self):
        """¶1.76(d) is "reinstatement of the Site". Left as extracted it would have read as though
        it covered ¶1.77's separately-measured smoke screens."""
        assert smm_s01.CLAUSES["1.76"][-1].label == "Reinstatement of the Site"
        for head in ALL_HEADS:
            assert "Item coverage" not in head.label, head.key
            assert not re.search(r"\b1\.\d+ The item", head.label), head.key

    def test_every_cut_is_recorded_with_what_was_removed(self):
        assert len(smm_s01.TRIMMED_BLEED) == 26
        for row in smm_s01.TRIMMED_BLEED:
            assert row["trimmed"].strip()
            assert row["clause"] in smm_s01.CLAUSES

    def test_a_cut_that_does_not_match_the_text_raises_rather_than_guessing(self):
        """The literal is verbatim including the bleed, so the file diffs against the source. A
        mistyped cut must fail loudly here, not leave the wrong half on somebody's checklist."""
        with pytest.raises(ValueError, match="is not how the text ends"):
            smm_s01._head("1.05", "z", "some text. A HEADING", bleed="A DIFFERENT HEADING")

    def test_the_run_on_sub_heads_are_split_out_as_the_pack_letters_them(self):
        """¶1.14(z) arrived as one bullet carrying four sub-heads, each printed with its own
        reference. Three real obligations would have hidden inside a head about street lighting."""
        letters = [h.key.rsplit(".", 1)[-1] for h in smm_s01.CLAUSES["1.14"]]
        assert letters[-4:] == ["z", "aa", "ab", "ac"]
        assert smm_s01.CLAUSES["1.14"][-4].label == "Provision of temporary street lighting"
        assert smm_s01.CLAUSES["1.14"][-1].label.startswith("All other works")

    def test_trailing_list_punctuation_is_dropped_but_nothing_else_is(self):
        head = next(h for h in smm_s01.CLAUSES["1.104"] if h.key.endswith(".i"))
        assert head.label.endswith("nearby construction works"), "the '; and' is typesetting"
        assert not [h for h in ALL_HEADS if h.label.endswith((".", "; and"))]


class TestTheGapTheLetteringProves:
    def test_the_holes_in_clause_106_are_derived_not_asserted(self):
        assert smm_s01.BASE_SMM_GAPS["1.06"] == list("abdeg") + list("qrstuv")

    def test_a_contiguous_clause_claims_no_gap(self):
        """¶1.40 runs (a)–(f) unbroken. That proves nothing about whether the base carries a (g),
        so nothing is claimed — the general partial caveat says the honest thing instead."""
        for clause in ("1.05", "1.40", "1.45", "1.104", "1.151"):
            assert clause not in smm_s01.BASE_SMM_GAPS

    def test_only_ten_of_the_forty_clauses_have_provable_holes(self):
        assert set(smm_s01.BASE_SMM_GAPS) == {"1.06", "1.07", "1.11", "1.14", "1.15",
                                              "1.22", "1.23", "1.28", "1.32", "1.37"}

    def test_a_not_used_letter_is_not_a_hole(self):
        """¶1.14(o) is printed. Its letter is spoken for, so no base sub-head can sit there."""
        assert "o" not in smm_s01.BASE_SMM_GAPS["1.14"]
        assert "w" in smm_s01.BASE_SMM_GAPS["1.14"], "but (w) really is missing"

    def test_the_double_letters_are_ordered_after_z(self):
        """¶1.14 runs past (z) into (aa)–(ac), so the gap walk has to letter the way clauses do."""
        assert smm_s01._ordinal("z") == 26 and smm_s01._ordinal("aa") == 27
        assert smm_s01._letter(27) == "aa" and smm_s01._letter(29) == "ac"
        assert max(smm_s01.BASE_SMM_GAPS["1.14"], key=smm_s01._ordinal) == "w"


class TestTheCitationsPointSomewhereOrNowhere:
    def test_every_head_naming_a_ps_clause_cites_it(self):
        """A reference that says "PS 1.49" and cites nothing is a page somebody hunts for by hand."""
        for head in ALL_HEADS:
            if re.search(r"PS \d", head.clause_ref):
                assert head.cites, f"{head.key} names a PS clause and cites nothing"

    def test_a_whole_section_is_cited_only_where_the_number_cannot_collide(self):
        """`DocumentMap.resolve` falls back to a prefix match, so "25" reaches 25.xx and nothing
        else — but a bare "1" would also reach 10.xx, 11.xx and 12.xx. "PS Section 1" is therefore
        left uncited: a `▸ show me` that lands on the wrong page is worse than one that admits it
        cannot say."""
        for head in ALL_HEADS:
            if "PS Section 1" in head.clause_ref:
                assert head.cites == "", head.key
            if "PS Section 25" in head.clause_ref:
                assert head.cites == "25", head.key

    def test_a_head_citing_conditions_outside_the_specification_claims_no_page(self):
        """¶1.18 cites the NEC conditions and ¶1.22(g) a CEDD standard drawing. Neither is in the
        specification index, so neither pretends to resolve."""
        for key in ("smm.s01.1.18.a", "smm.s01.1.22.g"):
            head = next(h for h in ALL_HEADS if h.key == key)
            assert head.cites == ""

    def test_the_first_clause_of_a_range_is_the_one_cited(self):
        head = next(h for h in smm_s01.CLAUSES["1.14"] if h.key.endswith(".s"))
        assert head.cites == "1.14" and "PS 1.14–1.15" in head.clause_ref

    def test_an_appendix_is_cited_in_the_form_the_index_lists_it(self):
        head = smm_s01.CLAUSES["1.06"][0]
        assert head.cites == "Appendix 1.12"

    def test_every_head_arrives_from_the_amendment_and_unticked(self):
        """These are the pack's own words — none of them come from the base SMM, and a transcribed
        head is still a question for a person, never an answer."""
        for head in ALL_HEADS:
            assert head.provenance == FROM_AMENDMENT
            assert head.authored_by == "rule"


class TestWhatTheModuleWillNotDo:
    def test_it_refuses_a_clause_it_does_not_have(self):
        """A typo that silently produced "no coverage" is the failure this package is built on."""
        with pytest.raises(KeyError, match="not transcribed"):
            smm_s01.heads_for_clauses("1.05", "1.99")

    def test_a_range_comes_back_in_the_order_the_pack_prints_it(self):
        heads = smm_s01.heads_for_clauses("1.109", "1.110", "1.111")
        assert len(heads) == 9 + 7 + 4
        assert heads[0].key == "smm.s01.1.109.a" and heads[-1].key == "smm.s01.1.111.d"

    def test_the_clauses_no_bill_item_claims_are_named_not_attached(self):
        """Six clauses this pack amends have no BQ item in the Bill 1 mapping. Hanging them on a
        plausible-looking item would be worse than leaving them unasked — the mapping was read off
        the real BQ pages and this list was not."""
        assert set(smm_s01.UNMAPPED) == {"1.86", "1.91", "1.96", "1.112", "1.133", "1.156"}
        for clause in smm_s01.UNMAPPED:
            assert smm_s01.CLAUSES[clause], "transcribed and available, just not attached"

    def test_the_monitoring_clauses_declare_that_their_mapping_is_unsettled(self):
        assert set(smm_s01.MAPPING_UNVERIFIED) == {"1.45", "1.46", "1.47"}
        for reason in smm_s01.MAPPING_UNVERIFIED.values():
            assert "MONITORING" in reason
