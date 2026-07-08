"""The tender workspace — deterministic, path-safe on-disk storage (Phase A)."""

from pipeline import reply_loop
from pipeline.workspace import (
    Workspace,
    anchor_name_on_contract,
    contract_number_in_text,
    name_has_contract_number,
    tender_slug,
)


def test_tender_slug_is_deterministic_and_safe():
    assert tender_slug("Kwun Tong Commercial Tower — Cat-A") == "kwun-tong-commercial-tower-cat-a"
    assert tender_slug("") == "tender"
    assert tender_slug("A/B\\C") == "a-b-c"
    # pure function of the name — same input, same slug, no timestamp/randomness
    assert tender_slug("Proj X") == tender_slug("Proj X")


def test_tender_slug_prefers_an_embedded_contract_number():
    # The real GE/2026/14 title ran to 150+ chars; the contract number is the slug.
    assert tender_slug("Contract No. GE/2026/14 — Ground Investigation Works for Foo District") == "ge-2026-14"
    assert tender_slug("HY/2020/09 Widening of Trunk Road") == "hy-2020-09"


def test_tender_slug_is_bounded_and_collision_resistant_for_long_titles():
    long_a = "Provision of Term Consultancy Services for Landscape and Tree Works across the New Territories East District Alpha"
    long_b = long_a[:-5] + "Bravo"  # shares the truncation prefix, differs only in the tail
    slug_a, slug_b = tender_slug(long_a), tender_slug(long_b)
    assert len(slug_a) <= 40 + 9  # ~40 chars + "-" + 8-char hash
    assert slug_a != slug_b       # the stable hash of the full name keeps them distinct
    assert tender_slug(long_a) == slug_a  # deterministic


def test_ref_round_trips_through_the_short_slug(tmp_path):
    # Dispatch records a ref off the contract-number slug; inbound resolves the same ref.
    ws = Workspace(root=tmp_path)
    project = "Contract No. GE/2026/14 — Ground Investigation Works for the Whole District"
    ref = reply_loop.make_ref(project, "castco-b6e5", "ground_investigation")
    assert ref == "ge-2026-14.castco-b6e5.ground_investigation"  # short subject-safe ref
    reply_loop.record_dispatch(ws, ref, project, "castco-b6e5", "ground_investigation")
    resolved = reply_loop.resolve_ref(ws, ref)
    assert resolved == {"tender_id": project, "firm_id": "castco-b6e5", "trade": "ground_investigation"}


# -- RT2-C5: anchor the tender identity on the contract number from the documents ----------
def test_contract_number_is_read_from_document_text_and_normalised():
    body = "FORM OF TENDER\nContract No.  GE / 2026 / 14\nGround Investigation for the District"
    assert contract_number_in_text(body) == "GE/2026/14"          # spacing dropped, prefix upper
    assert contract_number_in_text("Widening works, tender HY/2020/09 refers") == "HY/2020/09"
    assert contract_number_in_text("no contract number anywhere here") == ""


def test_contract_scan_ignores_clause_refs_and_bare_dates():
    # A clause reference "PS/7/34" (no 4-digit year) and a bare date must NOT read as a contract.
    assert contract_number_in_text("see Clause PS/7/34 for standpipes") == ""
    assert contract_number_in_text("issued 2026/07/14 for tender") == ""


def test_name_has_contract_number_detects_an_embedded_ref():
    assert name_has_contract_number("Contract No. GE/2026/14 — Ground Investigation")
    assert not name_has_contract_number("Ground Investigation Works for Foo District")


def test_anchor_prepends_the_contract_number_when_the_name_dropped_it():
    # The extracted title omitted the contract number, but a document carries it -> the finalised
    # name embeds it, so tender_slug is the stable ge-2026-14 rather than a name hash.
    docs = "FORM OF TENDER — Contract No. GE/2026/14"
    anchored = anchor_name_on_contract("Ground Investigation Works for Foo District", docs)
    assert anchored == "Contract No. GE/2026/14 — Ground Investigation Works for Foo District"
    assert tender_slug(anchored) == "ge-2026-14"
    # an empty name (form left at its default) -> just the contract number
    assert anchor_name_on_contract("", docs) == "Contract No. GE/2026/14"
    assert tender_slug(anchor_name_on_contract("", docs)) == "ge-2026-14"


def test_anchor_leaves_a_name_that_already_has_a_contract_number_untouched():
    name = "Contract No. HY/2020/09 — Road Widening"
    # even if the documents mention a DIFFERENT number, an explicit name wins (no double-prepend)
    assert anchor_name_on_contract(name, "elsewhere GE/2026/14 is cited") == name


def test_anchor_is_a_noop_when_no_contract_number_is_present_anywhere():
    assert anchor_name_on_contract("Landscape Term Contract", "no numbers in the docs") == "Landscape Term Contract"


def test_save_and_resolve_upload(tmp_path):
    ws = Workspace(root=tmp_path)
    saved = ws.save_upload("Proj X", "../../etc/passwd", b"data")  # traversal stripped to basename
    assert saved.name == "passwd"
    assert saved.read_bytes() == b"data"
    assert ws.doc_path("Proj X", "passwd").is_file()


def test_sor_sheet_path_lives_under_artifacts(tmp_path):
    ws = Workspace(root=tmp_path)
    path = ws.sor_sheet_path("Proj X", "electrical")
    assert path.name == "SoR_electrical.xlsx"
    assert path.parent.name == "artifacts"
