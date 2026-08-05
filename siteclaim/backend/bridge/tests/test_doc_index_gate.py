"""The dispatch gate states the index it is about to draft from — and the slice is proven end to end.

The last live failure was not a bug in any component. The split ran under one tender slug and the
drafts were assembled under another, so `load_doc_index` returned `[]`, `relevant_docs` took its
`if not sr_entries` fallback, and the enquiry carried a 7 KB generated workbook where a sliced bill
belonged. Everything behaved as designed; the only symptom was the attachment, after it was sent.

Two halves here:

* the STATE the gate shows — exists / built when / how many documents / stale — with the slug named
  in every warning, because a warning that says "no index" without saying which tender it looked
  under sends the reader to the same dead end the original failure did;
* the CHAIN, run for real: split writes the index, and the dispatch preview built from the SAME
  slug comes back with a sliced Schedule of Rates and a sliced Particular Specification.

**These are FIXTURES, not the real pack.** The pdfs below are written by pymupdf a few lines at a
time, modelling a bill with section headers and a specification with numbered clauses. The 232 MB
CEDD tender is not in this repository and no live run against it happens here.
"""

import pytest
from fastapi.testclient import TestClient

from bridge import parts as parts_mod
from schemas.models import ScopePackages, SorItem, TradeWorkPackage


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


@pytest.fixture
def make_pdf(tmp_path):
    def _make(name: str, pages: list[str]) -> str:
        import fitz

        doc = fitz.open()
        for body in pages:
            page = doc.new_page()
            y = 70
            for line in body.splitlines():
                page.insert_text((55, y), line, fontsize=10)
                y += 14
        path = tmp_path / name
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make


BILL_PAGES = [
    "SECTION G : DRILLING AND SAMPLING\n"
    "G1   Cable percussion borehole      m    120   Clause Ref: PS 3.1\n"
    "G2   Rotary core drilling           m     80   Clause Ref: PS 3.4",
    "SECTION H : INSTRUMENTATION\n"
    "H1   Standpipe piezometer          nr     12   Clause Ref: PS 3.9\n"
    "H2   Vibrating wire piezometer     nr      8",
]
# The section header on page 1 is load-bearing, not decoration: with no declared section
# `_accept_clause_id` rejects a bare `3.1` as marker noise, and the clause index comes back empty.
# A real CEDD Particular Specification opens exactly this way.
SPEC_PAGES = [
    "SECTION 3 : GROUND INVESTIGATION\n"
    "3.1  Cable percussion boring shall be carried out in accordance\n"
    "     with the General Specification.\n"
    "3.4  Rotary core drilling shall recover not less than 95%.",
    "3.9  Standpipe piezometers shall be installed in accordance with\n"
    "     the manufacturer's instructions and tested on completion.",
]


@pytest.fixture
def a_split_set(make_set, part_spec, make_pdf, tmp_path, monkeypatch):
    """A set whose bill and specification are real pdfs, ready to split."""
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    specs = [
        part_spec(1, "SR", "Schedule of Rates", "pricing", end=2),
        part_spec(2, "PS", "Particular Specification", "specifications", end=2),
        part_spec(3, "DR", "Drawings", "drawings", end=1),
    ]
    paths = {
        specs[0].part_id: make_pdf("bill.pdf", BILL_PAGES),
        specs[1].part_id: make_pdf("spec.pdf", SPEC_PAGES),
        specs[2].part_id: make_pdf("drawings.pdf", ["GENERAL ARRANGEMENT"]),
    }
    make_set("gi-2026-09", "Contract No. GI/2026/09", specs, pdf_paths=paths)
    parts_mod.confirm_bill_parts("gi-2026-09", [specs[0].part_id])
    return "gi-2026-09"


class StubClient:
    """Layer 2, scripted: the two sections the bill declares, with their Clause Refs."""

    def complete_json(self, *, system, user, target_model, **_kw):
        return ScopePackages(project_name="GI/2026/09", packages=[TradeWorkPackage(
            trade="ground_investigation", scope_summary="Ground investigation",
            sor_items=[
                SorItem(item_ref="G1", description="Cable percussion borehole", unit="m", qty=120.0,
                        section="G", clause_refs=["PS 3.1"]),
                SorItem(item_ref="G2", description="Rotary core drilling", unit="m", qty=80.0,
                        section="G", clause_refs=["PS 3.4"]),
                SorItem(item_ref="H1", description="Standpipe piezometer", unit="nr", qty=12.0,
                        section="H", clause_refs=["PS 3.9"]),
            ],
        )])


def _dispatched_scope(scope_json: dict) -> dict:
    """The split's scope as the DISPATCH step sends it — one package per routable unit.

    `route_units` produces `trade:SECTION` keys and `Sourcing.tsx` rebuilds each package with
    `trade: p.package_key`. That re-key is load-bearing and easy to lose: `plan_for_firms` looks
    the package up BY the approval key, so a scope still keyed on the parent trade finds nothing,
    contributes no items, no clause refs — and every document falls back to whole or generated.
    """
    from pipeline.routing.split import route_units

    scope = ScopePackages.model_validate(scope_json)
    units = route_units(scope, split_keys={p.trade for p in scope.packages})
    return ScopePackages(
        project_name=scope.project_name,
        packages=[u["package"].model_copy(update={"trade": u["package_key"]}) for u in units],
    ).model_dump()


# -- the state the gate shows ---------------------------------------------------------------------
def test_before_any_split_the_gate_says_there_is_no_index(client, a_split_set):
    body = client.get(f"/bridge/{a_split_set}/doc-index").json()

    assert body["exists"] is False and body["documents"] == 0
    assert body["built_at"] is None
    assert a_split_set in body["warning"]                 # the SLUG is named, not just "no index"
    assert "generated pricing sheet" in body["warning"]   # and what it will cost


def test_a_set_that_does_not_exist_answers_rather_than_404s(client):
    body = client.get("/bridge/never-heard-of-it/doc-index").json()
    assert body["exists"] is False and body["warning"]


def test_after_the_split_it_states_when_and_over_how_many(client, a_split_set, monkeypatch):
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    client.post(f"/bridge/{a_split_set}/scope")

    body = client.get(f"/bridge/{a_split_set}/doc-index").json()
    assert body["exists"] is True
    assert body["built_at"] and body["built_at"].endswith("+00:00")
    assert body["documents"] == 2                          # the bill and the spec
    assert body["kinds"]["schedule_of_rates"] == 1
    assert body["sor_sections"] == ["G", "H"]
    assert body["warning"] == ""                           # nothing to warn about
    assert body["stale"] is False


def test_a_drawing_is_not_counted_as_a_missing_document(client, a_split_set, monkeypatch):
    """`_NEVER_INDEXED` skips drawings, so the denominator must skip them too — or a healthy
    index would report itself stale on every pack that contains a drawing."""
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    client.post(f"/bridge/{a_split_set}/scope")

    body = client.get(f"/bridge/{a_split_set}/doc-index").json()
    assert body["indexable_parts"] == 2 and body["stale"] is False


def test_a_document_added_after_the_split_reads_as_stale(
    client, a_split_set, make_set, part_spec, make_pdf, monkeypatch,
):
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    client.post(f"/bridge/{a_split_set}/scope")

    # An addendum arrives after the index was built.
    from client_boq import store as cb_store
    from bridge.identity import bridge_conn

    conn = bridge_conn()
    try:
        added = part_spec(4, "AD", "Addendum No. 1", "correspondence", end=1)
        # A NEW document, so a higher rev — `save_parts` at rev 0 is a re-cut and would drop every
        # part not in the list, which is the opposite of an addendum.
        cb_store.upsert_document(conn, a_split_set, doc_id="doc-1", filename="addendum.pdf",
                                 kind="addendum", ref="Addendum No. 1")
        cb_store.save_parts(conn, a_split_set, [added],
                            {added.part_id: make_pdf("addendum.pdf", ["ADDENDUM NO. 1"])},
                            doc_id="doc-1", rev=1)
    finally:
        conn.close()

    body = client.get(f"/bridge/{a_split_set}/doc-index").json()
    assert body["stale"] is True
    assert "cannot be sliced or attached until the split is re-run" in body["warning"]
    assert a_split_set in body["warning"]


def test_the_slug_it_looked_under_is_always_reported(client, a_split_set):
    # The whole failure was a slug mismatch. The answer names the slug whether or not it found one.
    assert client.get(f"/bridge/{a_split_set}/doc-index").json()["tender_slug"] == a_split_set


# -- the chain, end to end -------------------------------------------------------------------------
def test_split_then_dispatch_preview_carries_a_sliced_sor_and_a_sliced_spec(
    client, a_split_set, monkeypatch,
):
    """The proof the brief asks for, on a fixture: one slug, split then preview, and the list.

    Nothing is stubbed between the two calls — the split writes a real `doc_index.json` and the
    preview reads that file back off disk under the same slug.
    """
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    split = client.post(f"/bridge/{a_split_set}/scope").json()

    plans = client.post("/dispatch/plan", json={
        "scope": _dispatched_scope(split["scope"]),
        "approvals": {"ground_investigation:G": ["F001"]},
        "project_name": a_split_set,
    }).json()

    attachments = {a["source_doc"]: a for p in plans for a in p["attachments"]}
    modes = {name: a["mode"] for name, a in attachments.items()}

    # The Schedule of Rates, SLICED to section G's own page — not the generated sheet, and not
    # the whole bill: page 2 is section H, which this unit is not pricing.
    assert modes["Schedule of Rates"] == "sliced"
    assert attachments["Schedule of Rates"]["pages"] == [1]
    assert "priced_return" in attachments["Schedule of Rates"]["flags"]
    assert "substituted_priced_return" not in attachments["Schedule of Rates"]["flags"]

    # The Particular Specification, SLICED to the clauses section G's items cite (PS 3.1 / 3.4).
    assert modes["Particular Specification"] == "sliced"
    assert attachments["Particular Specification"]["pages"]      # a real page range, not whole-file

    # And the drawing is not in the enquiry at all — it was never indexed.
    assert "Drawings" not in modes


def test_the_same_split_under_a_different_slug_produces_the_silent_substitution(
    client, a_split_set, monkeypatch,
):
    """The original failure, reproduced as a test so the warning above has something to be about.

    Same scope, same approvals, one character different in the tender id — and the priced return
    silently becomes the generated sheet. This is what the gate now refuses to let happen quietly.
    """
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    split = client.post(f"/bridge/{a_split_set}/scope").json()

    plans = client.post("/dispatch/plan", json={
        "scope": _dispatched_scope(split["scope"]),
        "approvals": {"ground_investigation:G": ["F001"]},
        "project_name": "gi-2026-09-draft",          # the wrong slug
    }).json()

    attachments = [a for p in plans for a in p["attachments"]]
    assert [a["mode"] for a in attachments] == ["generated"]
    assert "substituted_priced_return" in attachments[0]["flags"]
    # ...and the gate would have said so first.
    assert client.get("/bridge/gi-2026-09-draft/doc-index").json()["exists"] is False
