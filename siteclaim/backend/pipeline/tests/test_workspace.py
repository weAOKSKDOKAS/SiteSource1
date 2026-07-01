"""The tender workspace — deterministic, path-safe on-disk storage (Phase A)."""

from pipeline.workspace import Workspace, tender_slug


def test_tender_slug_is_deterministic_and_safe():
    assert tender_slug("Kwun Tong Commercial Tower — Cat-A") == "kwun-tong-commercial-tower-cat-a"
    assert tender_slug("") == "tender"
    assert tender_slug("A/B\\C") == "a-b-c"
    # pure function of the name — same input, same slug, no timestamp/randomness
    assert tender_slug("Proj X") == tender_slug("Proj X")


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
