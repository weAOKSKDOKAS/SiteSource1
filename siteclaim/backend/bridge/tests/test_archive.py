"""A whole tender pack, as one archive, at constant memory.

Built against the shape measured on CEDD ND/2025/04 (`OneDrive_2026-07-21.zip`): 232.3 MB, 441
entries, 206 content files (203 PDFs + 3 XLSX), 201 `.p7s` signatures, seventeen top-level folders —
37 distinct directories once the nesting is counted — and filenames carrying a document code and a
revision.

**Everything below is a FIXTURE, and its counts are its own.** The real pack is not in the repo and
is not reproduced here: these archives are a dozen members, not 441, so a count asserted in this file
is a fact about the fixture and never evidence about the tender. What IS carried over from the real
pack is its SHAPE — a folder tree, mixed PDFs and one workbook, signature files, a wrapper directory,
folders nested three deep, and a filename that carries a revision beside one that does not — because
shape is the thing the code has to get right and the thing a small archive can hold honestly.

The load-bearing assertion is the memory one, and it is MEASURED rather than asserted in prose: an
archive that gets ten times bigger must not make the process ten times bigger.
"""

import io
import json
import tracemalloc
import zipfile
from pathlib import Path

import pytest

from bridge import archive


# ---------------------------------------------------------------------------
# A synthetic pack of the same shape
# ---------------------------------------------------------------------------
def _pdf_bytes(pages: int = 1) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((60, 80), f"page {i + 1}", fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def _make_pack(path: Path, *, filler_mb: int = 0) -> Path:
    """The ND shape in miniature. `filler_mb` grows ONE member without changing the structure, so
    the memory test can scale the archive while holding everything else constant."""
    two_page = _pdf_bytes(2)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:   # STORED: PDFs do not compress
        zf.writestr("BQ/E-ND_2025_04-BQ-1.xlsx", b"PK\x03\x04 pretend workbook")
        zf.writestr("BQ/E-ND_2025_04_BQ-0.pdf", two_page)
        zf.writestr("BQ/E-ND_2025_04_BQ-0.pdf.p7s", b"\x30\x82 signature" * 100)
        zf.writestr("DRG/GA-01.pdf", two_page)
        zf.writestr("DRG/GA-01.pdf.p7s", b"\x30\x82 signature" * 100)
        zf.writestr("S/PS-S07.pdf", two_page)
        zf.writestr("SI/borehole-log.pdf", two_page)
        zf.writestr("TA #1/BQ/E-ND_2025_04-BQ-1.pdf", two_page)
        zf.writestr("TC No. 1 & 2/cover.pdf", two_page)
        zf.writestr("GP&PP/preambles.pdf", two_page)
        zf.writestr("Covers/log.txt", b"not content")
        zf.writestr("__MACOSX/._junk", b"not content")
        zf.writestr("Unmapped Folder/mystery.pdf", two_page)
        if filler_mb:
            zf.writestr("DRG/big.pdf", b"\0" * (filler_mb * 1024 * 1024))
    return path


@pytest.fixture
def pack(tmp_path):
    return _make_pack(tmp_path / "pack.zip")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "work"))
    from pipeline.workspace import Workspace

    return Workspace()


# ---------------------------------------------------------------------------
# PHASE 1 — receive without materialising
# ---------------------------------------------------------------------------
def test_peak_memory_does_not_scale_with_archive_size(tmp_path, workspace):
    """MEASURED. A 1 MB filler and a 24 MB filler through the same code: if anything held the
    archive, the second would cost ~23 MB more than the first."""
    def peak_for(mb: int) -> int:
        pack_path = _make_pack(tmp_path / f"p{mb}.zip", filler_mb=mb)
        report = archive.read_tree(pack_path)
        tracemalloc.start()
        archive.extract(report, workspace, f"tender-{mb}")
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        return peak

    small, large = peak_for(1), peak_for(24)
    # 23 MB more content through the same path. Allow generous slack for interpreter noise, but
    # nothing like the difference in size — a materialising implementation fails this by an order
    # of magnitude.
    assert large < small + 8 * 1024 * 1024, f"peak grew {(large - small) / 1e6:.1f} MB"
    assert large < 16 * 1024 * 1024, f"peak {large / 1e6:.1f} MB is not one-chunk behaviour"


def test_the_upload_streams_rather_than_reading(tmp_path, workspace):
    """`stream_to` must never ask for the whole thing. A source that refuses an unbounded read is
    the only way to prove it from outside."""
    class ChunkOnly(io.RawIOBase):
        def __init__(self, data: bytes):
            self.buf = io.BytesIO(data)

        def read(self, size=-1):
            if size is None or size < 0:
                raise AssertionError("read() with no size — that materialises the whole upload")
            return self.buf.read(size)

    written = archive.stream_to(ChunkOnly(b"x" * (3 << 20)), tmp_path / "out.bin")
    assert written == 3 << 20


def test_an_oversized_archive_is_refused_before_extraction(pack, monkeypatch):
    monkeypatch.setenv("SITESOURCE_ARCHIVE_MAX_BYTES", "1000")
    report = archive.read_tree(pack)
    with pytest.raises(ValueError, match="over the"):
        archive.check_size(report)


def test_the_ceiling_is_read_from_the_central_directory_not_from_disk(tmp_path, monkeypatch):
    """The zip-bomb guard: a member claiming to expand hugely is refused having decompressed
    nothing, because `file_size` comes from the directory."""
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BQ/huge.pdf", b"\0" * (40 * 1024 * 1024))   # compresses to almost nothing
    assert bomb.stat().st_size < 100_000                          # tiny on disk
    monkeypatch.setenv("SITESOURCE_ARCHIVE_MAX_BYTES", str(10 * 1024 * 1024))
    with pytest.raises(ValueError, match="over the"):
        archive.check_size(archive.read_tree(bomb))


def test_a_file_that_is_not_a_zip_is_refused_clearly(tmp_path):
    (tmp_path / "nope.zip").write_bytes(b"this is not a zip")
    with pytest.raises(ValueError, match="not a readable ZIP"):
        archive.read_tree(tmp_path / "nope.zip")


# ---------------------------------------------------------------------------
# PHASE 2 — the tree becomes the manifest
# ---------------------------------------------------------------------------
def test_signature_files_are_never_content(pack):
    report = archive.read_tree(pack)
    assert len(report.signatures) == 2
    assert all(not m.filename.endswith(".p7s") for m in report.content)


def test_signature_files_are_never_opened(pack, workspace, monkeypatch):
    """201 of them and 96 MB in the real pack. Recorded as provenance, never read."""
    opened: list[str] = []
    real = zipfile.ZipFile.open

    def spy(self, name, *a, **kw):
        opened.append(name.filename if hasattr(name, "filename") else str(name))
        return real(self, name, *a, **kw)

    monkeypatch.setattr(zipfile.ZipFile, "open", spy)
    archive.extract(archive.read_tree(pack), workspace, "t")
    assert opened and not any(n.endswith(".p7s") for n in opened)


def test_packaging_is_skipped_by_name_before_any_io(pack):
    names = {m.filename for m in archive.read_tree(pack).content}
    assert not any("log.txt" in n or "__MACOSX" in n for n in names)


def test_categories_derive_from_folders(pack):
    manifest = archive.plan_manifest(
        archive.read_tree(pack), set_id="nd-2025-04", source_name="pack.zip")
    by_title = {p.title: p.category for p in manifest.parts}
    assert by_title["BQ/E-ND_2025_04_BQ-0.pdf"] == "pricing"
    assert by_title["DRG/GA-01.pdf"] == "drawings"
    assert by_title["S/PS-S07.pdf"] == "specifications"
    assert by_title["SI/borehole-log.pdf"] == "site-information"
    assert by_title["GP&PP/preambles.pdf"] == "specifications"
    assert by_title["TC No. 1 & 2/cover.pdf"] == "tender-conditions"


def test_an_unmapped_folder_is_other_never_a_guess(pack):
    manifest = archive.plan_manifest(
        archive.read_tree(pack), set_id="s", source_name="pack.zip")
    mystery = next(p for p in manifest.parts if p.title.startswith("Unmapped"))
    assert mystery.category == "other"


def test_a_numbered_addendum_folder_needs_no_entry_per_issue(pack):
    assert archive.category_for("TA #1/BQ/x.pdf") == archive.category_for("TA #2/BQ/x.pdf")


# ---------------------------------------------------------------------------
# The standard Hong Kong government tender codes, pinned one per line
# ---------------------------------------------------------------------------
# These recur on every pack from these departments, so each is worth getting right ONCE rather than
# re-derived per tender — and four were wrong on the first pass. A wrong category here is not a
# cosmetic mislabel: `PartSpec.category` is what `effective_category` falls back to when a part has
# no context card, so it is what reaches the review's skip-list. Filed as `admin-forms`, 127 pages of
# amended NEC conditions would have been skipped as a probity declaration.
_STANDARD_CODES = {
    # code        expected category        what the abbreviation stands for
    "ACC":       ("contract-conditions",   "Additional Conditions of Contract"),
    "AoA":       ("contract-conditions",   "Articles of Agreement"),
    "GCT":       ("tender-conditions",     "General Conditions of Tender"),
    "SCT":       ("tender-conditions",     "Special Conditions of Tender"),
    "GP&PP":     ("specifications",        "General and Particular Preambles"),
    "BQ":        ("pricing",               "Bills of Quantities"),
    "DRG":       ("drawings",              "Drawings"),
    "SI":        ("site-information",      "Site Information"),
    "FoT":       ("bid-forms",             "Form of Tender"),
    "NTT":       ("tender-instructions",   "Notice to Tenderers"),
    "CDP1":      ("contract-data",         "Contract Data part 1"),
    "CDP2":      ("contract-data",         "Contract Data part 2"),
    "TC No. 1 & 2": ("tender-conditions",  "Technical Circulars"),
}


@pytest.mark.parametrize("code", sorted(_STANDARD_CODES))
def test_a_standard_tender_code_maps_to_its_real_category(code):
    expected, meaning = _STANDARD_CODES[code]
    got = archive.category_for(f"{code}/doc.pdf")
    assert got == expected, f"{code} is {meaning} — expected {expected!r}, got {got!r}"


def test_the_four_corrected_codes_reach_the_manifest_end_to_end(tmp_path):
    """Through `read_tree` and `plan_manifest`, not just `category_for` — the four that were wrong
    were wrong in the manifest a person approves, which is the only place it matters."""
    p = tmp_path / "codes.zip"
    with zipfile.ZipFile(p, "w") as zf:
        for member in ("ACC/additional-conditions.pdf", "AoA/articles.pdf",
                       "GCT/general-conditions-of-tender.pdf", "SCT/special-conditions.pdf",
                       "GP&PP/preambles.pdf"):
            zf.writestr(member, _pdf_bytes())
    manifest = archive.plan_manifest(
        archive.read_tree(p), set_id="s", source_name="codes.zip")
    assert {x.title: x.category for x in manifest.parts} == {
        # The document the departure register exists to read. Was `admin-forms`.
        "ACC/additional-conditions.pdf": "contract-conditions",
        # The executed contract instrument, not a form a bidder fills in. Was `bid-forms`.
        "AoA/articles.pdf": "contract-conditions",
        # Conditions of TENDER govern the process and expire at award. Were `contract-conditions`,
        # which put terms that die at award beside terms that bind for the whole job.
        "GCT/general-conditions-of-tender.pdf": "tender-conditions",
        "SCT/special-conditions.pdf": "tender-conditions",
        # The Standard Method of Measurement rules — what a rate must include. Was
        # `safety-requirements`, a guess from the ampersand.
        "GP&PP/preambles.pdf": "specifications",
    }


def test_sct_is_not_read_as_the_specification_folder():
    """`S/` is the Particular Specification tree and `_category_key` falls back to a leading
    alphabetic token, so a bare prefix rule would resolve `SCT` at `S`. The exact key must win —
    otherwise Special Conditions of Tender are filed as specification and read as scope."""
    assert archive.category_for("S/PS-S07.pdf") == "specifications"
    assert archive.category_for("SCT/x.pdf") == "tender-conditions"
    assert archive.category_for("SI/x.pdf") == "site-information"


def test_every_mapped_category_is_a_real_part_category():
    """A typo here would not raise — `category_for` checks membership and silently returns `other`,
    so a mistyped value degrades to the unknown bucket with no error anywhere. Caught at the table."""
    from client_boq.models import PART_CATEGORIES

    bad = {k: v for k, v in archive._FOLDER_CATEGORY.items() if v not in PART_CATEGORIES}
    assert bad == {}


def test_revisions_parse_where_the_convention_matches_and_are_absent_where_it_does_not():
    assert archive.parse_revision("BQ/E-ND_2025_04-BQ-1.xlsx") == 1
    assert archive.parse_revision("TA #2/BQ/E-ND_2025_04-BQ-2.xlsx") == 2
    # 165 of 206 matched in the real pack — a majority, not an authority.
    assert archive.parse_revision("Covers/cover page.pdf") is None
    assert archive.parse_revision("DRG/GA-01.pdf") is None


def test_the_manifest_is_tier_whole_and_names_the_tree(pack):
    manifest = archive.plan_manifest(
        archive.read_tree(pack), set_id="s", source_name="pack.zip")
    from client_boq.models import TIER_WHOLE

    assert manifest.tier == TIER_WHOLE
    assert "folder tree" in manifest.tier_reason
    assert "DRG/" in manifest.tier_reason
    assert "signature file(s) were present" in manifest.tier_reason


def test_the_manifest_carries_per_part_source_and_none_of_its_own(pack):
    """The shape `run_inspect` already emits for non-binder uploads, and the shape `run_split`
    already resolves with `part.source_doc or manifest.source_doc`."""
    manifest = archive.plan_manifest(
        archive.read_tree(pack), set_id="s", source_name="pack.zip")
    assert manifest.source_doc == ""
    assert all(p.source_doc for p in manifest.parts)


def test_a_tree_manifest_passes_validate_untouched(pack):
    """`pdfops.validate` measures only parts belonging to the BINDER, and a tree manifest has
    none — so the coverage rules written for a single binder neither fire nor need widening."""
    from client_boq.ingest import pdfops

    manifest = archive.plan_manifest(
        archive.read_tree(pack), set_id="s", source_name="pack.zip")
    assert pdfops.validate(manifest, 0) == ([], [])


# ---------------------------------------------------------------------------
# Flattening — the finding that nearly cost a drawing
# ---------------------------------------------------------------------------
def test_the_folder_survives_into_the_stored_name():
    assert archive.flatten("DRG/a.pdf") == "DRG__a.pdf"
    assert archive.flatten("SI/a.pdf") == "SI__a.pdf"
    assert archive.flatten("TA #1/BQ/x.xlsx") == "TA #1__BQ__x.xlsx"


def test_two_folders_with_the_same_basename_do_not_collide(tmp_path, workspace):
    """`_safe_name` is `Path(name).name`, so without flattening both of these become `a.pdf` in one
    flat `docs/` directory and the second silently overwrites the first."""
    p = tmp_path / "clash.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("DRG/a.pdf", _pdf_bytes())
        zf.writestr("SI/a.pdf", _pdf_bytes())
    written = archive.extract(archive.read_tree(p), workspace, "t")
    assert set(written) == {"DRG__a.pdf", "SI__a.pdf"}
    assert len({Path(v).name for v in written.values()}) == 2      # two real files on disk


def test_the_operator_sees_the_archive_path_not_the_flattened_one(pack):
    """The on-disk name is an implementation detail. The person is looking for the document they
    know by its place in the pack."""
    manifest = archive.plan_manifest(
        archive.read_tree(pack), set_id="s", source_name="pack.zip")
    drawing = next(p for p in manifest.parts if p.source_doc == "DRG__GA-01.pdf")
    assert drawing.title == "DRG/GA-01.pdf"


def test_a_flattening_collision_fails_loudly_rather_than_overwriting():
    with pytest.raises(ValueError, match="silently overwrite"):
        archive.assert_unique(["S/PS/x.pdf", "S__PS/x.pdf"])


def test_uniqueness_holds_for_the_real_shape(pack):
    archive.assert_unique([m.filename for m in archive.read_tree(pack).content])   # no raise


# ---------------------------------------------------------------------------
# The 203-row gate
# ---------------------------------------------------------------------------
def test_the_proposal_is_grouped_by_folder_with_counts(pack):
    """A person approving a tender pack is checking the SHAPE — not auditing 203 filenames."""
    groups = archive.folder_summary(archive.read_tree(pack))
    by_folder = {g["folder"]: g for g in groups}
    assert by_folder["BQ"]["files"] == 2
    assert by_folder["BQ"]["category"] == "pricing"
    assert by_folder["DRG"]["files"] == 1
    assert all("names" in g for g in groups)          # expandable where they doubt it


# ---------------------------------------------------------------------------
# PHASE 3 — extraction, and the set that results
# ---------------------------------------------------------------------------
def test_every_content_member_lands_on_disk_and_no_signature_does(pack, workspace):
    report = archive.read_tree(pack)
    written = archive.extract(report, workspace, "t")
    # Derived from the report rather than hardcoded: a count typed by hand is a count that
    # disagrees with the fixture the moment the fixture grows.
    assert len(written) == len(report.content) == 9
    assert not any(k.endswith(".p7s") for k in written)
    assert all(Path(v).is_file() for v in written.values())


def test_a_workbook_keeps_its_real_extension(pack, workspace):
    """`slice_pdf` degrades to returning its input, so a workbook cut as a part would land as a
    `.pdf` containing xlsx bytes. A lie on disk is worse than a refusal."""
    written = archive.extract(archive.read_tree(pack), workspace, "t")
    book = written["BQ__E-ND_2025_04-BQ-1.xlsx"]
    assert book.endswith(".xlsx")
    assert Path(book).read_bytes().startswith(b"PK\x03\x04")


def test_the_workbook_note_names_the_reader_it_actually_needs():
    """`scanned` is overloaded — elsewhere it means "needs vision OCR". Nobody should end up
    pointing OCR at a spreadsheet."""
    assert "workbook, not a scan" in archive.WORKBOOK_NOTE
    assert "Excel reader" in archive.WORKBOOK_NOTE
    assert archive.is_workbook("BQ__x.xlsx") and not archive.is_workbook("DRG__x.pdf")


# ---------------------------------------------------------------------------
# End to end, through the endpoints and the gate
# ---------------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "work"))
    from fastapi.testclient import TestClient
    import api

    return TestClient(api.app)


def _upload(client, pack: Path, name="ND 2025 04"):
    with open(pack, "rb") as fh:
        return client.post(
            "/bridge/archive/upload",
            files={"file": ("pack.zip", fh, "application/zip")},
            data={"project_name": name},
        )


def test_upload_proposes_a_manifest_and_extracts_nothing(client, pack, tmp_path):
    body = _upload(client, pack).json()
    assert body["set_id"] == "nd-2025-04"
    assert body["content_files"] == 9 and body["signature_files"] == 2
    assert body["manifest_approved"] is False
    docs = tmp_path / "work" / "ND 2025 04" / "docs"
    assert not docs.exists() or not list(docs.glob("*.pdf"))     # nothing extracted yet


def test_the_gate_is_the_same_gate_a_single_document_passes(client, pack):
    set_id = _upload(client, pack).json()["set_id"]
    # Refused until approved — and the message says a pack passes the same gate.
    blocked = client.post("/bridge/archive/extract", json={"set_id": set_id})
    assert blocked.status_code == 409
    assert "same gate" in blocked.json()["detail"]

    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    assert client.post("/bridge/archive/extract", json={"set_id": set_id}).status_code == 200


def test_an_oversized_upload_is_refused_and_leaves_nothing_behind(client, pack, monkeypatch, tmp_path):
    monkeypatch.setenv("SITESOURCE_ARCHIVE_MAX_BYTES", "1000")
    resp = _upload(client, pack)
    assert resp.status_code == 400 and "over the" in resp.json()["detail"]
    assert not (tmp_path / "work" / "ND 2025 04" / "artifacts" / "archive.zip").exists()


def test_extracting_an_unknown_set_404s(client):
    assert client.post("/bridge/archive/extract", json={"set_id": "nope"}).status_code == 404


def test_the_resulting_set_reads_like_any_other(client, pack):
    """`store.load_parts` is what every consumer uses. A pack-created set must be indistinguishable
    from one created by the normal path."""
    from client_boq import jobs, store
    from bridge.archive_job import run_archive_extract_job

    set_id = _upload(client, pack).json()["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    job_id = jobs.JOBS.create("archive")
    run_archive_extract_job(job_id, set_id, "ND 2025 04")           # inline: no pool, no waiting
    assert jobs.JOBS.get(job_id).status == "done", jobs.JOBS.get(job_id).error

    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()
    assert len(rows) == 9
    by_title = {spec.title: (spec, path, ctx) for spec, path, ctx in rows}
    assert by_title["DRG/GA-01.pdf"][0].category == "drawings"
    assert by_title["BQ/E-ND_2025_04_BQ-0.pdf"][0].end == 2          # page count, from extraction
    # The workbook: recorded, not cut, flagged, and with no pdf path pretending otherwise.
    book = by_title["BQ/E-ND_2025_04-BQ-1.xlsx"][0]
    assert book.scanned is True
    assert by_title["BQ/E-ND_2025_04-BQ-1.xlsx"][1] == ""


def test_the_workbook_reason_reaches_the_person(client, pack):
    from client_boq import jobs
    from bridge.archive_job import run_archive_extract_job

    set_id = _upload(client, pack).json()["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    job_id = jobs.JOBS.create("archive")
    run_archive_extract_job(job_id, set_id, "ND 2025 04")
    said = " ".join(jobs.JOBS.get(job_id).warnings)
    assert "workbook, not a scan" in said and "Excel reader" in said


def test_the_archive_job_reports_its_stages_like_every_other(client, pack):
    """The longest-running operation in the product must not be the one thing the strip cannot
    describe. One entry in `_WORKFLOW_STAGES`, and it reports position like the rest."""
    from client_boq import jobs
    from bridge.archive_job import run_archive_extract_job
    from client_boq.router import _WORKFLOW_STAGES

    assert _WORKFLOW_STAGES["archive"] == ["reading", "extracting", "recording", "ingested"]
    set_id = _upload(client, pack).json()["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    job_id = jobs.JOBS.create("archive")
    run_archive_extract_job(job_id, set_id, "ND 2025 04")
    job = jobs.JOBS.get(job_id)
    assert (job.done, job.total) == (9, 9)


def test_a_cancelled_extraction_stops_and_is_not_an_error(client, pack):
    from client_boq import jobs
    from bridge.archive_job import run_archive_extract_job

    set_id = _upload(client, pack).json()["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    job_id = jobs.JOBS.create("archive")
    jobs.JOBS.cancel(job_id)                       # cancelled while queued
    run_archive_extract_job(job_id, set_id, "ND 2025 04")
    job = jobs.JOBS.get(job_id)
    assert job.status == "cancelled" and job.error == ""


# ---------------------------------------------------------------------------
# The wrapper directory — the bug that disabled every category on the real pack
# ---------------------------------------------------------------------------
WRAPPER = "ND202504 Contract Dcos"


def _wrapped_pack(path: Path, *, root: str = WRAPPER, levels: int = 1) -> Path:
    """A FIXTURE carrying the wrapped shape — eight members, where the real pack has 206.

    What it reproduces is the arrangement, not the size: one wrapper directory over the whole tree,
    which is how Windows, OneDrive and most zip tools package a folder and therefore the common case
    rather than an edge one; and a specification branch nested three deep, because the real tree's 37
    directories include `S/PS/PS7` and the folder match cannot assume a single level.
    """
    prefix = "/".join([root] * levels)
    two_page = _pdf_bytes(2)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for member in (
            "BQ/E-ND_2025_04_BQ-0.xlsx",
            "BQ/E-ND_2025_04_BQ-0.pdf",
            "DRG/GA-01.pdf",
            "GP&PP/preambles.pdf",
            "S/PS/PS7/ps7.pdf",
            "S/PS/PS31/ps31.pdf",
            "SI/borehole-log.pdf",
            "TA #1/BQ/E-ND_2025_04-BQ-1.xlsx",
        ):
            zf.writestr(f"{prefix}/{member}", two_page)
        zf.writestr(f"{prefix}/BQ/E-ND_2025_04_BQ-0.pdf.p7s", b"\x30\x82 sig" * 50)
    return path


def test_a_single_wrapper_directory_is_stripped(tmp_path):
    """`ND202504 Contract Dcos/BQ/...` — the folder derivation took the first segment, got the
    wrapper every time, and reported ONE folder with all 206 files categorised `other`."""
    report = archive.read_tree(_wrapped_pack(tmp_path / "w.zip"))
    assert report.root_levels == 1
    assert WRAPPER not in " ".join(report.folders)
    assert set(report.folders) == {"BQ", "DRG", "GP&PP", "S/PS/PS7", "S/PS/PS31", "SI", "TA #1/BQ"}


def test_categories_survive_the_wrapper(tmp_path):
    """The whole consequence of the bug: with the wrapper in place every one of these was
    `other`."""
    report = archive.read_tree(_wrapped_pack(tmp_path / "w.zip"))
    manifest = archive.plan_manifest(report, set_id="s", source_name="w.zip")
    by_title = {p.title: p.category for p in manifest.parts}
    assert by_title["BQ/E-ND_2025_04_BQ-0.pdf"] == "pricing"
    assert by_title["DRG/GA-01.pdf"] == "drawings"
    assert by_title["SI/borehole-log.pdf"] == "site-information"
    assert by_title["GP&PP/preambles.pdf"] == "specifications"
    assert not any(c == "other" for c in by_title.values())


def test_two_wrappers_are_both_stripped(tmp_path):
    """This archive had one. A folder zipped inside a folder gives two, and the strip loops."""
    report = archive.read_tree(_wrapped_pack(tmp_path / "w2.zip", levels=2))
    assert report.root_levels == 2
    assert "BQ" in report.folders


def test_a_pack_with_no_wrapper_is_untouched(pack):
    report = archive.read_tree(pack)
    assert report.root_levels == 0
    assert "BQ" in report.folders


def test_a_wrapper_is_never_stripped_down_to_a_bare_filename(tmp_path):
    """`wrapper/BQ/x.pdf` alone shares BOTH segments. Stripping twice would take the file's own
    folder — the structure — rather than the packaging, and lose the only category signal there is."""
    p = tmp_path / "one.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("wrapper/BQ/x.pdf", _pdf_bytes())
    report = archive.read_tree(p)
    assert report.root_levels == 1
    assert report.folders == ["BQ"]
    assert archive.category_for(report.rel_of(report.content[0])) == "pricing"


def test_a_file_at_the_root_means_nothing_wraps_everything(tmp_path):
    p = tmp_path / "mixed.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("readme.pdf", _pdf_bytes())
        zf.writestr("BQ/x.pdf", _pdf_bytes())
    report = archive.read_tree(p)
    assert report.root_levels == 0
    assert set(report.folders) == {"(root)", "BQ"}


def test_the_strip_ignores_packaging_when_deciding(tmp_path):
    """A stray `__MACOSX/` sibling would otherwise look like a second top-level folder and stop the
    strip that every real pack needs."""
    p = tmp_path / "mac.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(f"{WRAPPER}/BQ/x.pdf", _pdf_bytes())
        zf.writestr(f"{WRAPPER}/DRG/y.pdf", _pdf_bytes())
        zf.writestr("__MACOSX/._junk", b"not content")
    report = archive.read_tree(p)
    assert report.root_levels == 1
    assert set(report.folders) == {"BQ", "DRG"}


def test_the_reason_says_the_wrapper_was_packaging(tmp_path):
    report = archive.read_tree(_wrapped_pack(tmp_path / "w.zip"))
    manifest = archive.plan_manifest(report, set_id="s", source_name="w.zip")
    assert "One leading directory was packaging" in manifest.tier_reason


# -- folder matching cannot assume a single level -------------------------------------------------
def test_a_nested_specification_section_resolves(tmp_path):
    """`S/PS/PS7` is three deep. `PS7` itself is unmapped and it resolves at `PS`."""
    report = archive.read_tree(_wrapped_pack(tmp_path / "w.zip"))
    manifest = archive.plan_manifest(report, set_id="s", source_name="w.zip")
    by_title = {p.title: p.category for p in manifest.parts}
    assert by_title["S/PS/PS7/ps7.pdf"] == "specifications"
    assert by_title["S/PS/PS31/ps31.pdf"] == "specifications"


def test_the_category_is_read_deepest_first(tmp_path):
    """`TA #1/BQ/...` is a BILL that arrived with addendum 1. Reading only the outermost folder
    would call it `other` and the bill proposal would miss it entirely."""
    report = archive.read_tree(_wrapped_pack(tmp_path / "w.zip"))
    manifest = archive.plan_manifest(report, set_id="s", source_name="w.zip")
    addendum = next(p for p in manifest.parts if p.title.startswith("TA #1/"))
    assert addendum.category == "pricing"
    assert archive.category_for("TA #2/DRG/x.pdf") == "drawings"


def test_folders_are_reported_at_their_full_depth(tmp_path):
    """A person recognises `S/PS/PS7`, not `S`. Counted that way the real tree has 37 directories
    under its seventeen top-level folders; this fixture has seven, and asserts the depth rule."""
    report = archive.read_tree(_wrapped_pack(tmp_path / "w.zip"))
    groups = {g["folder"]: g for g in archive.folder_summary(report)}
    assert "S/PS/PS7" in groups and "S/PS/PS31" in groups
    assert groups["S/PS/PS7"]["category"] == "specifications"
    assert groups["TA #1/BQ"]["category"] == "pricing"


# -- the collision guard, actually exercised ------------------------------------------------------
def test_two_folders_holding_the_same_basename_survive_end_to_end(tmp_path, workspace):
    """Basenames happened to be unique in the real pack, so the flattening was never proven there.
    `_safe_name` is `Path(name).name`: without flattening both of these become `a.pdf` in one flat
    `docs/` directory and the second silently overwrites the first."""
    p = tmp_path / "clash.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(f"{WRAPPER}/DRG/GA-01.pdf", _pdf_bytes(2))
        zf.writestr(f"{WRAPPER}/SI/GA-01.pdf", _pdf_bytes(3))
        zf.writestr(f"{WRAPPER}/S/PS/PS7/GA-01.pdf", _pdf_bytes(4))

    report = archive.read_tree(p)
    manifest = archive.plan_manifest(report, set_id="s", source_name="clash.zip")
    # Three parts, three distinct stored names, three distinct titles.
    assert sorted(x.source_doc for x in manifest.parts) == [
        "DRG__GA-01.pdf", "SI__GA-01.pdf", "S__PS__PS7__GA-01.pdf",
    ]
    assert len({x.title for x in manifest.parts}) == 3
    assert {x.category for x in manifest.parts} == {"drawings", "site-information", "specifications"}

    written = archive.extract(report, workspace, "clash")
    assert len(written) == 3
    # Three real files on disk, each with its own bytes — not one file written three times.
    sizes = {Path(v).stat().st_size for v in written.values()}
    assert len(sizes) == 3


def test_the_flattening_uses_the_stripped_path_not_the_wrapper(tmp_path):
    """The wrapper must not bloat every stored filename — it is packaging, and it is identical on
    every one of them, so it distinguishes nothing."""
    report = archive.read_tree(_wrapped_pack(tmp_path / "w.zip"))
    manifest = archive.plan_manifest(report, set_id="s", source_name="w.zip")
    assert all(WRAPPER not in x.source_doc for x in manifest.parts)
    assert "DRG__GA-01.pdf" in {x.source_doc for x in manifest.parts}
