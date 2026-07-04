"""The tender workspace — deterministic, path-safe on-disk storage (Phase A)."""

from pipeline import reply_loop
from pipeline.workspace import Workspace, tender_slug


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
