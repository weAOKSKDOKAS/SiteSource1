"""INGEST — the other front door: a folder that is already organised.

Bucket: **Deterministic**. No model call at all. There is nothing to plan.

WHY THIS IS A SEPARATE MODULE
-----------------------------
The binder path is *inspect → plan → approve → cut*. This one is *list → interpret*. They share a
destination (a ``SplitManifest`` of ``PartSpec``) and almost nothing else, so folding them together
would put an ``if layout == …`` at every stage of ``run.py`` and make each one harder to read than
both are apart.

A tender package normally arrives as a folder — ``ND202504 Contract Dcos / TA #2 / BQ / bill.xlsx``
and forty siblings. Somebody has already done the splitting, and the client's own tree is a statement
about what belongs with what. Re-splitting it would be work done twice and worse: the app would
discard a real organisation in favour of an inferred one.

THREE RULES
-----------
**The path is the identity.** A part's title is its relative path, and parts sort by path, so the
Documents screen reads like the folder that was uploaded. That also means two files called ``BQ.pdf``
in different subfolders are two parts rather than one overwriting the other — see
:func:`pipeline.workspace.save_upload_at`, which is where that used to go wrong.

**Nothing is split.** Each part spans its own whole file (``start=1``, ``end=<its pages>``), and
``run_split`` copies rather than slices for exactly that shape.

**A file may be un-read, but never un-mentioned.** Ingest is PDF-only, and today a ``.xlsx`` is
written to disk and then vanishes from the manifest. Here a workbook that parses as a bill of
quantities is routed to the bill importer, and everything else comes back as a :class:`HeldFile` —
listed, counted, and honest about not being interpreted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from client_boq import models
from client_boq.ingest import pdfops
from client_boq.models import PartSpec, SplitManifest

# The document set arrived already organised, so there was no split to plan and none to approve.
TIER_FOLDER = 5

APPROVAL_NOTE = (
    "approved automatically: the folder was already organised, so there were no page ranges to "
    "confirm. Nobody reviewed this."
)
TIER_REASON = (
    "uploaded as an organised folder — each file is its own part and nothing was split"
)
HELD_NOTE = "held, not read — nothing in the app interprets this format"

_WORKBOOK_SUFFIXES = {".xlsx", ".xlsm"}

# A detached digital signature is not an unread document — it is evidence that the file beside it is
# authentic. On the reference package there are 201 of them, one per PDF, and listing those as
# "held, not read" is both wrong and loud enough to bury the handful that genuinely are.
_SIGNATURE_SUFFIXES = {".p7s", ".p7m", ".sig", ".asc"}


class FolderUpload(BaseModel):
    """One file as the browser sent it, with the place it sat in the tree."""

    relative_path: str
    content_type: str = ""
    data: bytes = b""

    @property
    def name(self) -> str:
        return Path(self.relative_path.replace("\\", "/")).name

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()

    @property
    def folder(self) -> str:
        parent = Path(self.relative_path.replace("\\", "/")).parent
        return "" if str(parent) in (".", "") else str(parent)


class HeldFile(BaseModel):
    """A file that arrived and is stored, but that nothing in the app reads."""

    relative_path: str
    suffix: str = ""
    bytes: int = 0
    note: str = HELD_NOTE


class BillCandidate(BaseModel):
    """A workbook that parses as a bill of quantities."""

    relative_path: str
    items: int = 0
    priceable: int = 0
    notes: list[str] = Field(default_factory=list)


class FolderPlan(BaseModel):
    """Everything the folder produced: the parts, the bills, and what was merely kept."""

    manifest: SplitManifest = Field(default_factory=SplitManifest)
    bills: list[BillCandidate] = Field(default_factory=list)
    held: list[HeldFile] = Field(default_factory=list)
    signed: int = 0                 # files that arrived with a detached digital signature
    problems: list[str] = Field(default_factory=list)

    @property
    def pdf_count(self) -> int:
        return len(self.manifest.parts)

    def page_total(self) -> int:
        return sum(part.page_count() for part in self.manifest.parts)

    def summary(self) -> str:
        """What the Documents screen says instead of a coverage bar."""
        bits = [f"{self.pdf_count} file{'' if self.pdf_count == 1 else 's'}",
                f"{self.page_total():,} pages"]
        if self.bills:
            bits.append(f"{len(self.bills)} bill of quantities"
                        if len(self.bills) == 1 else f"{len(self.bills)} bills of quantities")
        if self.signed:
            bits.append(f"{self.signed} digitally signed")
        if self.held:
            bits.append(f"{len(self.held)} held, not read")
        return " · ".join(bits)


def is_pdf(upload: FolderUpload) -> bool:
    ct = (upload.content_type or "").split(";")[0].strip().lower()
    return ct.endswith("/pdf") or upload.suffix == ".pdf"


def plan_folder(uploads: list[FolderUpload], set_id: str = "",
                page_count=None) -> FolderPlan:
    """Turn an organised folder into a manifest. Deterministic; no model call.

    ``page_count`` is injected so the planner can be unit-tested without PyMuPDF; production passes
    the real counter.
    """
    counter = page_count or _page_count
    plan = FolderPlan()
    if not uploads:
        plan.problems.append("the folder was empty")
        return plan

    pdfs = sorted((u for u in uploads if is_pdf(u)), key=lambda u: u.relative_path.lower())
    others = [u for u in uploads if not is_pdf(u)]

    parts: list[PartSpec] = []
    for n, upload in enumerate(pdfs, start=1):
        pages = counter(upload.data)
        parts.append(PartSpec(
            n=n,
            abbr=_abbr(upload),
            slug=pdfops.slugify(_slug_source(upload)),
            title=upload.relative_path,
            category=_category(upload),
            start=1,
            end=max(1, pages),
            # The part IS this file. `run_split` copies rather than slices for this shape, and
            # `pdfops.validate` skips it because it belongs to no binder.
            source_doc=upload.relative_path,
        ))

    plan.manifest = SplitManifest(
        set_id=set_id,
        # No binder. Claiming one is what makes the coverage bar report "0 of N pages" for a set
        # where every page is accounted for — there is simply no single document to account against.
        source_doc="",
        pages=0,
        prefix=pdfops.slugify(set_id or "part"),
        tier=TIER_FOLDER,
        tier_reason=TIER_REASON,
        parts=parts,
        # Your call: no gate for a folder. Recorded as automatic rather than shown as a verdict —
        # the flag unlocks every later step, so it has to be set, but nobody looked and the record
        # says so.
        approved=True,
    )

    documents = {u.relative_path for u in uploads}
    for upload in others:
        if upload.suffix in _SIGNATURE_SUFFIXES and _signs_something(upload, documents):
            # Counted, not listed. It is proof about a file that IS here, not a file nobody read.
            plan.signed += 1
            continue
        if upload.suffix in _WORKBOOK_SUFFIXES:
            candidate = _as_bill(upload)
            if candidate is not None:
                plan.bills.append(candidate)
                continue
        plan.held.append(HeldFile(relative_path=upload.relative_path, suffix=upload.suffix,
                                  bytes=len(upload.data)))

    if not parts:
        plan.problems.append(
            "no PDFs in the folder, so there are no parts to interpret — everything is held")
    if len(plan.bills) > 1:
        plan.problems.append(
            f"{len(plan.bills)} workbooks parse as a bill of quantities "
            f"({', '.join(b.relative_path for b in plan.bills)}). Which one is operative is a "
            f"decision, so none was imported — pick one on the Price step.")
    return plan


def _signs_something(upload: FolderUpload, documents: set[str]) -> bool:
    """Whether this is a detached signature for a file that is also in the upload.

    ``I-ND_2025_04-ACC-0.pdf.p7s`` signs ``I-ND_2025_04-ACC-0.pdf``. A ``.p7s`` whose subject is
    NOT in the folder is a different thing — a signature for something missing — so it stays on the
    held list where somebody can notice it.
    """
    subject = upload.relative_path[: -len(upload.suffix)]
    return bool(subject) and subject in documents


def _abbr(upload: FolderUpload) -> str:
    """The short tag on the part, and the ``NN_ABBR`` folder it is written into.

    The containing subfolder, verbatim — ``ACC``, ``BQ``, ``CDP1``, ``PS25``. That is the client's
    own label for what the file is, and on a tender package it is already an abbreviation.

    Two things this deliberately does not do. It does not use the filename: on the reference package
    every file is called ``I-ND_2025_04-…``, so initials give ``IN20`` for all 203 and every folder
    on disk reads ``NN_IN20``. And it does not take *initials of the folder* either — ``ACC`` is one
    word, so that yields ``A``, which is worse than useless because ``ACC`` and ``AoA`` collide.
    """
    folder = Path(upload.relative_path.replace("\\", "/")).parent.name
    tag = re.sub(r"[^A-Za-z0-9]+", "", folder).upper()[:4]
    return tag or pdfops.abbreviate(Path(upload.name).stem)[:4] or "PART"


def _slug_source(upload: FolderUpload) -> str:
    """Slug from the folder plus the filename, so two `BQ.pdf` in different folders differ.

    A slug collision does not merely look untidy: `part_id` is built from it, and two parts sharing
    one id would have the second overwrite the first in the parts table.
    """
    folder = upload.folder.replace("/", " ")
    stem = Path(upload.name).stem
    return f"{folder} {stem}".strip() if folder else stem


# Folder names a tender package actually uses, and the category each implies. Deliberately a short
# list of strong signals: "other" is an honest answer and a wrong category is worse than none,
# because downstream prompts address the category rather than the title.
_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    ("drawing", "drawings"), ("drg", "drawings"),
    ("/bq", "pricing"), ("bill of quantities", "pricing"), ("boq", "pricing"),
    ("specification", "specifications"), ("/ps", "specifications"),
    ("conditions of tender", "tender-instructions"),
    ("instructions to tender", "tender-instructions"),
    ("contract data", "contract-data"),
    ("conditions of contract", "contract-conditions"),
    ("safety", "safety-requirements"),
    ("ground investigation", "site-information"),
)


def _category(upload: FolderUpload) -> str:
    """Propose a category from the path. The Documents screen can change it."""
    text = f"/{upload.relative_path.lower().replace(chr(92), '/')}"
    for needle, category in _CATEGORY_HINTS:
        if needle in text:
            return category if category in models.PART_CATEGORIES else "other"
    return "other"


def _as_bill(upload: FolderUpload) -> Optional[BillCandidate]:
    """Whether this workbook reads as a bill of quantities — by trying, not by guessing at a name.

    A filename is a weak signal (the reference corpus has ``E-ND_2025_04-BQ-2.xlsx`` and also a
    ``Summary.xlsx`` that is not a bill). The reader either finds priceable items or it does not.
    """
    import tempfile

    try:
        from client_boq.boq import reader as boq_reader
    except Exception:  # noqa: BLE001 — openpyxl absent is not a reason to lose the file
        return None

    # `read_workbook` takes a path, so the bytes need a home for the length of the read.
    temp: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=upload.suffix, delete=False) as handle:
            handle.write(upload.data)
            temp = Path(handle.name)
        bill = boq_reader.read_workbook(temp)
    except Exception:  # noqa: BLE001 — an unreadable workbook is simply held, never a crash
        return None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)

    priceable = [i for i in bill.items if not i.is_parent and not i.pre_priced]
    if not priceable:
        return None
    return BillCandidate(relative_path=upload.relative_path, items=len(bill.items),
                         priceable=len(priceable), notes=list(bill.notes[:4]))


def _page_count(data: bytes) -> int:
    import fitz  # PyMuPDF — lazy

    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return len(doc)
    except Exception:  # noqa: BLE001 — an unreadable file is still one part, not a crash
        return 0
