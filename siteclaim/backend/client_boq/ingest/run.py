"""INGEST orchestration — the two halves of the front door, separated by the manifest gate.

``run_inspect``  upload -> save originals -> inspect (Det) -> plan (AI) -> persist a draft
                 manifest. Stops there. Nothing is cut yet.
        [ HUMAN GATE: the operator edits and approves the manifest ]
``run_split``    approved manifest -> cut the pages (Det) -> interpret each part (AI) ->
                 persist parts, part PDFs and context cards.

Splitting the run in two at the gate is the point. The manifest is cheap to produce and
cheap to re-cut, so a wrong boundary costs one edit and zero model calls — where a wrong
boundary discovered after the review would cost the whole review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from client_boq import models, store
from client_boq.ingest import folder, pdfops, s01_plan_split, s02_interpret, s03_map_changes
from client_boq.models import PartSpec, SplitManifest
from pipeline.workspace import Workspace, tender_slug

Progress = Optional[Callable[[str], None]]
DEFAULT_SET_NAME = "Client document set"
BASE_DOC_ID = "doc-0"  # the original upload; every part's Rev 0 belongs to it


def _note(progress: Progress, stage: str) -> None:
    if progress is not None:
        progress(stage)


def _is_pdf(filename: str, content_type: Optional[str]) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    return ct.endswith("/pdf") or (filename or "").lower().endswith(".pdf")


def _page_count(data: bytes) -> int:
    import fitz  # PyMuPDF — lazy

    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return len(doc)
    except Exception:  # noqa: BLE001 — an unreadable file is still one part, not a crash
        return 0


def run_inspect(
    uploads: list[tuple[str, Optional[str], bytes]],
    project_name: str = "",
    *,
    progress_cb: Progress = None,
) -> SplitManifest:
    """Inspect the upload and produce a DRAFT manifest for the human gate.

    The binder is the PDF with the most pages; any other uploaded file becomes a part in its
    own right (a tender often arrives as one big volume plus a handful of loose annexes).
    """
    if not uploads:
        raise ValueError("No files were uploaded.")

    _note(progress_cb, "reading")
    pdfs = [(name, ct, data) for name, ct, data in uploads if _is_pdf(name, ct) and data]
    if not pdfs:
        raise ValueError("Upload at least one PDF. The ingest splits PDF tender documents.")

    ws = Workspace()
    name = (project_name or DEFAULT_SET_NAME).strip() or DEFAULT_SET_NAME
    set_id = tender_slug(name)
    for filename, _ct, data in uploads:
        ws.save_upload(name, filename or "document", data)

    counted = [(fn, ct, data, _page_count(data)) for fn, ct, data in pdfs]
    counted.sort(key=lambda row: row[3], reverse=True)
    binder_name, _binder_ct, binder_data, binder_pages = counted[0]

    _note(progress_cb, "inspecting")
    report = pdfops.inspect(binder_data, binder_name)

    _note(progress_cb, "planning")
    manifest = s01_plan_split.plan_split(report, set_id=set_id)
    for part in manifest.parts:
        part.source_doc = binder_name

    # Every other uploaded file joins the set as a single whole-file part.
    extras = counted[1:]
    for offset, (filename, _ct, _data, pages) in enumerate(extras, start=1):
        manifest.parts.append(PartSpec(
            n=len(manifest.parts) + 1,
            abbr=pdfops.abbreviate(filename)[:4],
            slug=pdfops.slugify(filename.rsplit(".", 1)[0]),
            title=filename,
            start=1, end=max(1, pages),
            source_doc=filename,
        ))
    if extras:
        manifest.tier_reason += (
            f" | {len(extras)} further uploaded file(s) added as whole-file parts"
        )

    _note(progress_cb, "saving")
    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=set_id, name=name, slug=set_id, status="inspected")
        store.save_manifest(conn, manifest)
    finally:
        conn.close()
    store.save_manifest_artifact(ws, name, manifest)
    return manifest


def run_folder_inspect(
    uploads: list[tuple[str, Optional[str], bytes]],
    project_name: str = "",
    *,
    progress_cb: Progress = None,
) -> folder.FolderPlan:
    """Ingest an already-organised folder. No inspection, no planning, no gate.

    The counterpart to :func:`run_inspect`. Where that one has a binder to take apart, this has a
    tree somebody already sorted — so each file becomes its own part, the paths are kept, and the
    manifest arrives approved with a record saying it was automatic.

    Non-PDFs do not vanish: a workbook that parses as a bill is offered to the bill importer, and
    everything else is listed as held.
    """
    if not uploads:
        raise ValueError("No files were uploaded.")

    _note(progress_cb, "reading")
    ws = Workspace()
    name = (project_name or DEFAULT_SET_NAME).strip() or DEFAULT_SET_NAME
    set_id = tender_slug(name)

    # Keep the tree. `save_upload` would flatten every path to a basename, and two subfolders each
    # holding a BQ.pdf would silently become one file.
    parcels: list[folder.FolderUpload] = []
    for relative_path, content_type, data in uploads:
        if not data:
            continue
        ws.save_upload_at(name, relative_path, data)
        parcels.append(folder.FolderUpload(
            relative_path=relative_path, content_type=content_type or "", data=data))

    _note(progress_cb, "listing")
    plan = folder.plan_folder(parcels, set_id=set_id, page_count=_page_count)

    _note(progress_cb, "saving")
    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=set_id, name=name, slug=set_id, status="inspected")
        store.save_manifest(conn, plan.manifest)
        # The gate is passed here rather than by a person. `save_manifest` deliberately preserves
        # the stored approval flag, so it takes an explicit call to set it.
        if plan.manifest.approved:
            store.approve_manifest(conn, set_id, True)
    finally:
        conn.close()
    store.save_manifest_artifact(ws, name, plan.manifest)
    return plan


def run_split(set_id: str, *, progress_cb: Progress = None) -> list[PartSpec]:
    """Cut the approved manifest into parts and interpret each one.

    The cut itself costs no model calls, so re-splitting after a manifest edit is free. Each
    part is then interpreted independently; a part that cannot be read is recorded as an
    honest "not read" card rather than failing the set.
    """
    conn = store.get_conn()
    try:
        manifest = store.load_manifest(conn, set_id)
        row = conn.execute(
            "SELECT name FROM client_boq_document_sets WHERE set_id = ?", (set_id,)
        ).fetchone()
    finally:
        conn.close()
    if manifest is None:
        raise ValueError(f"No split manifest for set {set_id!r}; run the ingest first.")
    if not manifest.approved:
        raise ValueError(f"The split manifest for set {set_id!r} is not approved yet.")

    name = (row["name"] if row else "") or DEFAULT_SET_NAME
    ws = Workspace()
    docs = ws.docs_dir(name)
    out_root = store.parts_dir(ws, name)

    sources: dict[str, bytes] = {}

    def source_bytes(filename: str) -> bytes:
        if filename not in sources:
            # A folder ingest stores originals under their own subfolders, so `filename` may be a
            # relative path rather than a bare name. `docs / path` handles both.
            path = docs / filename
            sources[filename] = path.read_bytes() if path.is_file() else b""
        return sources[filename]

    _note(progress_cb, "splitting")
    pdf_paths: dict[str, str] = {}
    cut: list[tuple[PartSpec, bytes]] = []
    planned = len(manifest.parts)
    for index, part in enumerate(manifest.parts, start=1):
        # A folder set can be two hundred files, and one unchanging "splitting" for the whole loop
        # is indistinguishable from a hang. Counted, like the interpreting pass below.
        if planned > 1:
            _note(progress_cb, f"splitting {index}/{planned}")
        origin = part.source_doc or manifest.source_doc
        data = source_bytes(origin)
        if not data:
            cut.append((part, b""))
            continue
        # A part that spans the whole of its own file is COPIED, not cut. Slicing it would
        # re-encode an untouched PDF through PyMuPDF for no reason — losing byte-identity with the
        # original, and any structure PyMuPDF does not carry across. `apply_document` has always
        # done it this way for a replacement document; this is the same rule applied earlier.
        if part.start == 1 and part.end >= _page_count(data):
            part_bytes = data
        else:
            part_bytes = pdfops.slice_pdf(data, part.start, part.end)
        folder = out_root / f"{part.n:02d}_{(part.abbr or part.slug or 'part').upper()}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{manifest.prefix or 'part'}-{part.n:02d}-{part.slug}.pdf"
        target.write_bytes(part_bytes)
        pdf_paths[part.part_id] = str(target)
        cut.append((part, part_bytes))

    conn = store.get_conn()
    try:
        # The original upload is document 0 of the set's history, and Rev 0 of every part belongs
        # to it. Recording it here (rather than at upload) keeps the timeline anchored to what was
        # actually cut. Re-splitting after a manifest edit rewrites Rev 0 in place: a manifest edit
        # is a better reading of the same document, not a new document.
        store.upsert_document(
            conn, set_id, doc_id=BASE_DOC_ID, filename=manifest.source_doc,
            kind=models.DOC_BASE, ref="As issued",
        )
        store.save_parts(conn, set_id, manifest.parts, pdf_paths, doc_id=BASE_DOC_ID, rev=0)
    finally:
        conn.close()

    _note(progress_cb, "interpreting")
    total = len(cut)
    for index, (part, part_bytes) in enumerate(cut, start=1):
        _note(progress_cb, f"interpreting {index}/{total}")
        context = s02_interpret.interpret_part(
            part, part_bytes, source_doc=part.source_doc or manifest.source_doc,
        )
        conn = store.get_conn()
        try:
            store.save_part_context(conn, set_id, part.part_id, context)
        finally:
            conn.close()
        path = pdf_paths.get(part.part_id)
        if path:
            card = s02_interpret.card_markdown(
                part, context, part.source_doc or manifest.source_doc
            )
            (out_root.joinpath(
                f"{part.n:02d}_{(part.abbr or part.slug or 'part').upper()}"
            ) / "context.md").write_text(card, encoding="utf-8")

    _note(progress_cb, "ingested")
    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=set_id, name=name, slug=set_id, status="ingested")
    finally:
        conn.close()
    return manifest.parts


def run_reinterpret(set_id: str, part_id: str) -> models.PartContext:
    """Re-read ONE part and rewrite its context card. The manifest screen's ``⟳`` control.

    Worth having as its own entry point rather than telling someone to re-split: interpretation
    is where the vision fallback lives, so this is the retry for a scan that came back unread —
    a transient vision failure, or a part whose OCR is worth a second attempt. Re-splitting to
    get it would re-interpret all twelve parts to fix one.

    Only the context is rewritten. The page bounds, the cut PDF and the revision are untouched,
    because none of them is what failed.
    """
    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()

    match = next(((spec, path) for spec, path, _ctx in rows if spec.part_id == part_id), None)
    if match is None:
        raise ValueError(f"No part {part_id!r} in set {set_id!r}.")
    spec, path = match
    if not path or not Path(path).exists():
        raise ValueError(f"Part {part_id!r} has no cut PDF on disk; re-split the set first.")

    data = Path(path).read_bytes()
    context = s02_interpret.interpret_part(spec, data, source_doc=spec.source_doc)

    conn = store.get_conn()
    try:
        # No explicit rev: the store defaults to the operative one, which is the revision
        # `load_parts` just handed us. Passing spec.rev would be a second opinion about which
        # revision is current, and the derived one is the authority.
        store.save_part_context(conn, set_id, part_id, context)
    finally:
        conn.close()

    # Keep the card on disk in step with the stored context, or the downloaded ZIP would carry
    # the stale reading of a part the app now shows as read.
    card = Path(path).with_name("context.md")
    try:
        card.write_text(s02_interpret.card_markdown(spec, context, spec.source_doc),
                        encoding="utf-8")
    except OSError:
        pass  # the stored context is the source of truth; the card is a convenience copy
    return context


def _looks_like_letter(filename: str, ref: str) -> bool:
    """Whether an uploaded file is the addendum's covering letter rather than a replacement.

    Matched on the addendum's own naming ("Tender Addendum No.1.pdf" in the real package). A
    wrong guess here is cheap: the letter is only used to extract the advisory change table, and
    a misidentified file simply appears as an unmatched replacement at the gate.
    """
    name = (filename or "").lower()
    if "addendum" in name or "addenda" in name:
        return True
    tag = (ref or "").lower().replace(" ", "")
    return bool(tag) and tag in name.replace(" ", "")


def receive_document(
    set_id: str,
    uploads: list[tuple[str, Optional[str], bytes]],
    *,
    kind: str = models.DOC_ADDENDUM,
    ref: str = "",
    progress_cb: Progress = None,
) -> dict:
    """Take in an addendum, a correction, or a clarification, and PROPOSE what it changes.

    Commits nothing. Every revision it would create waits behind the change-mapping gate, for the
    same reason the split waits behind the manifest gate: superseding the wrong document is a
    quiet, expensive mistake, and a person can spot it in seconds.

    A clarification is recorded and stops there — both reference tenders state clarifications are
    expressly non-contractual, and the system should not quietly disagree with the contract.
    """
    if kind not in models.DOC_KINDS:
        raise ValueError(f"Unknown document kind {kind!r}; expected one of {models.DOC_KINDS}.")
    if not uploads:
        raise ValueError("No files were uploaded.")

    conn = store.get_conn()
    try:
        record = store.load_set(conn, set_id)
        parts = [spec for spec, _path, _ctx in store.load_parts(conn, set_id)]
    finally:
        conn.close()
    if record is None:
        raise ValueError(f"No document set {set_id!r}; ingest the base tender first.")
    if not parts:
        raise ValueError(f"Set {set_id!r} has no split parts yet; approve and split it first.")

    _note(progress_cb, "reading")
    ws = Workspace()
    name = record["name"]
    for filename, _ct, data in uploads:
        ws.save_upload(name, filename or "document", data)

    pdfs = [(fn or "document", data) for fn, ct, data in uploads if _is_pdf(fn, ct) and data]
    letter = next((item for item in pdfs if _looks_like_letter(item[0], ref)), None)
    replacements = [item for item in pdfs if item is not letter]

    conn = store.get_conn()
    try:
        doc_id = f"doc-{len(store.list_documents(conn, set_id))}"
        seq = store.upsert_document(
            conn, set_id, doc_id=doc_id,
            filename=(letter[0] if letter else (replacements[0][0] if replacements else "")),
            kind=kind, ref=ref,
        )
    finally:
        conn.close()

    if kind == models.DOC_CLARIFICATION:
        # Recorded, summarised, and deliberately inert: it bumps no revision.
        return {
            "set_id": set_id, "doc_id": doc_id, "kind": kind, "ref": ref, "seq": seq,
            "changes": [], "mappings": [], "notes": (
                "Clarifications are expressly non-contractual and change no document. "
                "Recorded for reference only."
            ),
            "requires_gate": False,
        }

    _note(progress_cb, "mapping")
    plan = s03_map_changes.plan_addendum(parts, letter, replacements, ref=ref)

    conn = store.get_conn()
    try:
        conn.execute("DELETE FROM client_boq_changes WHERE set_id = ? AND doc_id = ?",
                     (set_id, doc_id))
        for index, entry in enumerate(plan.changes, start=1):
            conn.execute(
                "INSERT INTO client_boq_changes (set_id, change_id, doc_id, part_id, kind, pages, "
                "description) VALUES (?, ?, ?, '', ?, ?, ?)",
                (set_id, f"{doc_id}-c{index:02d}", doc_id, models.CHANGE_REPLACE_PAGES,
                 f"{entry.document} {entry.pages}".strip(), entry.description),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "set_id": set_id, "doc_id": doc_id, "kind": kind, "ref": plan.ref or ref, "seq": seq,
        "letter": letter[0] if letter else "",
        "changes": [entry.model_dump() for entry in plan.changes],
        "mappings": [mapping.model_dump() for mapping in plan.mappings],
        "unmatched": [m.filename for m in plan.mappings if not m.part_id],
        "notes": plan.notes,
        "advisory": (
            "The change table is the addendum's own summary and may be neither exhaustive nor "
            "accurate. The replacement pages are the authority — check them before approving."
        ),
        "requires_gate": True,
    }


def apply_document(set_id: str, doc_id: str, mappings: list[tuple[str, str]],
                   *, progress_cb: Progress = None) -> list[PartSpec]:
    """Commit an approved mapping: cut each replacement in as a NEW revision of its part.

    Nothing is overwritten. Rev 0 survives Rev 1, so the history stays readable and a superseded
    revision can still be opened and compared. Only the parts named in ``mappings`` move; every
    other part keeps the revision it already had, which is why an addendum touching 9 documents
    out of 165 costs 9 revisions rather than a whole second copy of the tender.
    """
    conn = store.get_conn()
    try:
        record = store.load_set(conn, set_id)
        document = next(
            (d for d in store.list_documents(conn, set_id) if d["doc_id"] == doc_id), None
        )
        held = {spec.part_id: spec for spec, _p, _c in store.load_parts(conn, set_id)}
    finally:
        conn.close()
    if record is None or document is None:
        raise ValueError(f"No document {doc_id!r} on set {set_id!r}.")

    ws = Workspace()
    name = record["name"]
    docs = ws.docs_dir(name)
    out_root = store.parts_dir(ws, name)

    _note(progress_cb, "revising")
    applied: list[PartSpec] = []
    for filename, part_id in mappings:
        spec = held.get(part_id)
        source = docs / filename
        if spec is None or not source.is_file():
            continue
        data = source.read_bytes()
        pages = _page_count(data)

        conn = store.get_conn()
        try:
            revisions = store.load_part_revisions(conn, set_id, part_id)
        finally:
            conn.close()
        rev = max((r["rev"] for r in revisions), default=0) + 1

        # A replacement document IS the part now: it stands alone, so the new revision spans the
        # whole file rather than a page range of the original binder.
        revised = spec.model_copy(update={
            "start": 1, "end": max(1, pages), "source_doc": filename, "rev": rev,
        })
        pdfops.mark_scanned([revised], _scanned_pages(data))

        folder = out_root / f"{revised.n:02d}_{(revised.abbr or revised.slug or 'part').upper()}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"rev{rev}-{revised.slug}.pdf"
        target.write_bytes(data)

        conn = store.get_conn()
        try:
            store.save_parts(conn, set_id, [revised], {revised.part_id: str(target)},
                             doc_id=doc_id, rev=rev)
            conn.execute(
                "UPDATE client_boq_changes SET part_id = ? WHERE set_id = ? AND doc_id = ? "
                "AND part_id = '' AND description LIKE ?",
                (part_id, set_id, doc_id, f"%{revised.title[:20]}%"),
            )
            conn.commit()
        finally:
            conn.close()

        _note(progress_cb, f"interpreting {revised.part_id}")
        context = s02_interpret.interpret_part(revised, data, source_doc=filename)
        conn = store.get_conn()
        try:
            store.save_part_context(conn, set_id, revised.part_id, context, rev=rev)
        finally:
            conn.close()
        (folder / f"rev{rev}-context.md").write_text(
            s02_interpret.card_markdown(revised, context, filename), encoding="utf-8"
        )
        applied.append(revised)

    _note(progress_cb, "reopening")
    revised_ids = [p.part_id for p in applied]
    reopened = store.reopen_verdicts_for_parts(set_id, revised_ids)

    # A question about a clause the client has since rewritten has been answered, whether or not
    # anyone wrote back. Leaving it open would have us chasing a reply that is not coming, and
    # would hold a stale item in the count the freeze gate reads.
    conn = store.get_conn()
    try:
        overtaken = store.overtake_rfis_for_parts(
            conn, set_id, revised_ids, document["ref"] or document["filename"] or doc_id,
        )
    finally:
        conn.close()

    _note(progress_cb, "revised")
    return applied, reopened, overtaken


def _scanned_pages(data: bytes) -> list[int]:
    """Which pages of a standalone document carry no text layer."""
    report = pdfops.inspect(data, "replacement.pdf")
    return report.scanned_pages


def split_readme(manifest: SplitManifest) -> str:
    """The split's own README — the part table, page arithmetic, and coverage.

    Ships inside the download archive so the folder is readable without the app, the same way
    the prototype's split output was.
    """
    covered = sum(p.page_count() for p in manifest.parts
                  if not p.source_doc or p.source_doc == manifest.source_doc)
    lines = [
        f"# Split of {manifest.source_doc}",
        "",
        f"{manifest.pages} pages, cut into {len(manifest.parts)} parts. "
        f"Pages are physical and 1-based.",
        f"Coverage: {covered} of {manifest.pages} pages.",
        f"Confidence tier {manifest.tier}: {manifest.tier_reason}",
        "",
        "| NN | Abbr | Part | Pages | Category | Read |",
        "|---|---|---|---|---|---|",
    ]
    for part in manifest.parts:
        lines.append(
            f"| {part.n:02d} | {part.abbr} | {part.title} | {part.start}-{part.end} "
            f"| {part.category} | {'scan' if part.scanned else 'text'} |"
        )
    return "\n".join(lines) + "\n"
