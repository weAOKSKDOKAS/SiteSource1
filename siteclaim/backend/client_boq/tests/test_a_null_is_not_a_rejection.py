"""An explicit ``null`` from a model means "there is none", not "throw the answer away".

WHAT HAPPENED, twice, on the same live sheet. GI/210's borehole table has no TERMINATION
REQUIREMENT column — that column is on GI/310 only — so the reader correctly returned
``"termination": null``. The field was a plain ``str``; pydantic validates a payload as ONE object;
and rejecting that one key discarded **forty-seven correctly-read boreholes and twenty-one trial
pits**, complete with the ground levels, rockheads and soil/rock splits the model had plainly read.
Two slices of four died that way while the other two died of something else entirely.

`RawStation` was fixed field by field. This is the same defect swept across the module, because the
sweep found it on fourteen more types — and the worst of them is `DepartureProposal`, the review's
main output, where `extracted_value` and `cited_text` are exactly the shape: a criterion the
contract does not address has no value to extract and nothing to quote.

WHY A DEFAULT WAS NEVER THE FIX. ``field: str = ""`` makes the key safe to OMIT and does nothing
when the key is present holding null — and the key present holding null is what a model actually
produces when you ask it for something the document has no answer for. The tolerance has to be
about the VALUE.

AND WHY IT STOPS AT TEXT. Six numeric and boolean fields still reject a null on purpose. Turning
`PartSpec.start` into 0 invents page 0; turning `PartSpec.scanned` into False asserts that a page
nobody checked has a text layer. A blank that every consumer already reads as "there is none" is
tolerable; a blank that would be a claim is not.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from client_boq import models
from client_boq.boq import ask as boq_ask
from client_boq.boq import conditions as boq_conditions


class TestTheDefectThatWasMeasured:
    def test_a_departure_with_nothing_to_quote_survives(self):
        """The review's main output, and the one that would have cost the most."""
        parsed = models.DepartureProposalSet.model_validate({"departures": [
            {"clause_id": "GCC-12", "criterion_id": "cri-01",
             "extracted_value": None, "cited_text": None,
             "amendment_proposal": None, "rationale": "no threshold stated",
             "proposed_position": None},
        ]})
        assert len(parsed.departures) == 1
        row = parsed.departures[0]
        assert row.clause_id == "GCC-12" and row.criterion_id == "cri-01"
        assert row.extracted_value == "" and row.cited_text == ""

    def test_one_null_row_no_longer_takes_its_siblings_with_it(self):
        """The actual arithmetic of the live failure: 1 bad field, N rows lost."""
        rows = [{"clause_id": f"C{n}", "cited_text": f"quote {n}"} for n in range(20)]
        rows.append({"clause_id": "C20", "cited_text": None})
        parsed = models.DepartureProposalSet.model_validate({"departures": rows})
        assert len(parsed.departures) == 21
        assert [r.clause_id for r in parsed.departures][:3] == ["C0", "C1", "C2"]
        assert parsed.departures[-1].cited_text == ""

    def test_a_clause_with_no_printed_reference_survives(self):
        """A preamble paragraph has no clause ref. It is still a clause."""
        parsed = models.ParsedDocumentSet.model_validate({
            "set_id": "t", "clauses": [
                {"clause_id": "c1", "ref": None, "heading": None, "text": "The Contractor shall…",
                 "source_doc": None, "part_id": None}]})
        assert parsed.clauses[0].text.startswith("The Contractor")
        assert parsed.clauses[0].ref == "" and parsed.clauses[0].source_doc == ""

    def test_a_finding_with_no_citable_clause_survives(self):
        for target, key in ((models.ProgramFindingSet, "findings"),
                            (models.ScopeAlignmentSet, "findings")):
            parsed = target.model_validate({key: [
                {"kind": "gap", "description": "nothing in the pack fixes this",
                 "contract_ref": None, "cited_text": None}]})
            assert getattr(parsed, key)[0].description
            assert getattr(parsed, key)[0].contract_ref == ""


class TestAListNullMeansNone:
    def test_a_null_list_becomes_an_empty_one(self):
        """A model answering "there are no exclusions" writes null, not []."""
        draft = models.LetterDraft.model_validate(
            {"intro": "We are pleased…", "inclusions": ["a"], "exclusions": None,
             "additional_conditions": None})
        assert draft.exclusions == [] and draft.additional_conditions == []
        assert draft.inclusions == ["a"]

    def test_the_context_card_survives_a_null_everywhere(self):
        card = models.PartContext.model_validate({
            "part_id": "p1", "title": None, "summary": None, "key_points": None,
            "obligations": None, "commercial_flags": None, "feeds": None,
            "strategy_flags": None, "notes": None})
        assert card.part_id == "p1"
        assert card.key_points == [] and card.strategy_flags == []
        assert card.title == "" and card.summary == ""


class TestItStopsWhereABlankWouldBeAClaim:
    """The deliberate limit. These six must keep failing, and the reason is not tidiness."""

    def test_a_part_with_no_start_page_is_still_refused(self):
        with pytest.raises(ValidationError):
            models.PartSpec.model_validate({"n": 1, "abbr": "acc", "start": None, "end": 12})

    def test_a_part_that_nobody_checked_is_not_declared_unscanned(self):
        """`scanned` is a measurement from `pdfops`. False would assert a text layer nobody saw."""
        with pytest.raises(ValidationError):
            models.PartSpec.model_validate({"n": 1, "start": 1, "end": 2, "scanned": None})

    def test_readability_is_a_measurement_and_not_the_models_to_blank(self):
        with pytest.raises(ValidationError):
            models.PartContext.model_validate({"part_id": "p1", "readable": None})

    def test_an_absent_key_still_falls_back_to_the_default(self):
        """The coercion must not have quietly changed what omitting a key does."""
        assert models.PartSpec.model_validate({"n": 1, "start": 1, "end": 2}).scanned is False
        assert models.PartContext.model_validate({"part_id": "p"}).readable is True


class TestEveryModelFacingTypeIsCovered:
    """The sweep itself, as a test — so a new AI-facing type cannot be added without meeting it."""

    TYPES = [
        models.AddendumPlan, models.ContextSummary, models.DepartureProposalSet,
        models.LetterDraft, models.ParsedDocumentSet, models.PartContext, models.PlannedSplit,
        models.ProgramFindingSet, models.RFILetterDraft, models.ScopeAlignmentSet,
        models.ScopeReviewResult, boq_ask.RawAnswer, boq_conditions.RawConditionMapping,
    ]

    #: Named one by one rather than matched by type, so adding a numeric field to a model-facing
    #: type is a deliberate act with a line in this list rather than a silent exemption.
    ALLOWED_TO_REFUSE = {
        ("PartSpec", "n"), ("PartSpec", "start"), ("PartSpec", "end"), ("PartSpec", "rev"),
        ("PartSpec", "scanned"), ("PartContext", "readable"),
    }

    def _walk(self, model, seen):
        import typing

        if model in seen:
            return []
        seen.add(model)
        out = []
        for name, info in model.model_fields.items():
            try:
                model.model_validate({name: None})
            except Exception:  # noqa: BLE001 — collecting, not asserting
                out.append((model.__name__, name))
            for arg in (typing.get_args(info.annotation) or (info.annotation,)):
                if isinstance(arg, type) and issubclass(arg, models.BaseModel):
                    out += self._walk(arg, seen)
        return out

    def test_no_text_or_list_field_anywhere_rejects_a_null(self):
        seen: set = set()
        refusing = []
        for target in self.TYPES:
            refusing += self._walk(target, seen)
        unexpected = sorted(set(refusing) - self.ALLOWED_TO_REFUSE)
        assert not unexpected, (
            "these fields discard a whole payload when a model says 'there is none': "
            + ", ".join(f"{cls}.{field}" for cls, field in unexpected))

    def test_the_allowed_list_is_not_stale(self):
        """A permitted exemption that no longer refuses is an exemption nobody needs."""
        seen: set = set()
        refusing = set()
        for target in self.TYPES:
            refusing |= set(self._walk(target, seen))
        assert self.ALLOWED_TO_REFUSE <= refusing, (
            "these are listed as deliberately strict but now accept a null: "
            + ", ".join(f"{c}.{f}" for c, f in sorted(self.ALLOWED_TO_REFUSE - refusing)))
