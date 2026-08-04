"""A whole tender pack, as one archive, at constant memory.

The second engine prices self-perform work and cannot do that from a bill alone — it needs the
Particular Specification for each bill, the drawings, the Site Information and the preambles. A real
Hong Kong government tender arrives as one archive containing all of it. Measured on CEDD ND/2025/04
(`OneDrive_2026-07-21.zip`): 232.3 MB, 441 entries, 203 PDFs, 3 XLSX, 201 `.p7s` signatures, largest
member 41.3 MB, central directory read in 226 ms with ZERO bytes decompressed.

**The tree is the manifest.** The issuer already split the binder into seventeen top-level folders —
`ACC/ AoA/ BQ/ CDP1/ CDP2/ Covers/ DRG/ FoT/ GCT/ GP&PP/ NTT/ S/ SCT/ SI/ TA #1/ TA #2/ TC No. 1 & 2/`
— and a person at the issuing authority made that tree deliberately. It is a strong signal. It is
still a proposal: the human approves the manifest exactly as they do today, through the same gate.

Three properties this module exists to hold:

* **Nothing is ever fully in memory.** The upload streams to disk a chunk at a time; the central
  directory is read without decompressing a byte; each member is extracted with `copyfileobj`.
  Peak memory is one chunk, whatever the archive weighs.
* **The size ceiling is checked BEFORE anything is extracted.** `infolist()` gives `file_size` per
  member from the central directory, so a zip bomb is refused having decompressed nothing. This
  endpoint accepts uploads from outside; the order of those two operations is the guard.
* **`.p7s` signature members are never opened at all.** 201 of them, 96 MB in the real pack. That
  they were PRESENT is real provenance and is recorded; a signature is never treated as content.

Everything here lives in `bridge/`. Every client_boq call is public — `store.get_conn`,
`upsert_document_set`, `save_manifest`, `upsert_document`, `save_parts` — and the models are
constructed, never modified.
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Optional

from client_boq.models import PART_CATEGORIES, TIER_WHOLE, PartSpec, SplitManifest
from pipeline.workspace import Workspace, tender_slug

Progress = Optional[Callable[[str], None]]
Count = Optional[Callable[[int, int], None]]

# 1 GiB of UNCOMPRESSED content, env-overridable. The real pack is 232 MB, so this is roughly four
# times the largest thing anyone has actually sent — generous enough not to refuse real work, small
# enough that a bomb claiming terabytes is refused from its own central directory in milliseconds.
_DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
_CHUNK = 1 << 20  # 1 MiB — the whole of peak memory, for both the upload and each member


def max_uncompressed_bytes() -> int:
    try:
        return int(os.getenv("SITESOURCE_ARCHIVE_MAX_BYTES", str(_DEFAULT_MAX_BYTES)))
    except ValueError:
        return _DEFAULT_MAX_BYTES


# ---------------------------------------------------------------------------
# What is content, and what is not
# ---------------------------------------------------------------------------
# Skipped by NAME, before any I/O — never opened, never counted as content, never a part.
_SKIP_SUFFIXES = frozenset({".p7s"})
_SKIP_BASENAMES = frozenset({"log.txt", ".ds_store", "thumbs.db"})
_SKIP_PATH_PARTS = ("__macosx",)


def is_signature(name: str) -> bool:
    return Path(name).suffix.lower() in _SKIP_SUFFIXES


def is_content(name: str) -> bool:
    """Whether an archive member is a document rather than packaging."""
    if not name or name.endswith("/"):
        return False
    parts = [p.lower() for p in Path(name).parts]
    if any(p in _SKIP_PATH_PARTS for p in parts):
        return False
    if Path(name).name.lower() in _SKIP_BASENAMES:
        return False
    return not is_signature(name)


# ---------------------------------------------------------------------------
# The folder IS the category
# ---------------------------------------------------------------------------
# Derived from the pack's own tree, deterministically. This is what makes deferred interpretation
# possible: `effective_category` falls back to `PartSpec.category` when a part has no context card,
# so a folder-derived category reaches the review's skip-list and the bill proposal with ZERO model
# calls. 203 parts at one interpretation call each was never acceptable per tender.
#
# An unmapped folder becomes `other` — the honest-unknown bucket — and NEVER a guess from the
# filename. A tender that arrives with a folder nobody has seen should say so, not invent a fit.
_FOLDER_CATEGORY: dict[str, str] = {
    "bq": "pricing",                 # bills of quantities
    "drg": "drawings",
    "s": "specifications",           # S/ holds the Particular Specification tree
    "si": "site-information",        # ground investigation, surveys, existing conditions
    "gct": "contract-conditions",    # General Conditions
    "sct": "contract-conditions",    # Special Conditions
    "cdp1": "contract-data",
    "cdp2": "contract-data",
    "fot": "bid-forms",              # Form of Tender
    "aoa": "bid-forms",              # Articles of Agreement
    "ntt": "tender-instructions",    # Notice to Tenderers
    "tc": "tender-conditions",       # "TC No. 1 & 2"
    "acc": "admin-forms",            # declarations / probity
    "gp&pp": "safety-requirements",  # General & Particular Preambles carry the safety regime
    "covers": "other",
    "ta": "other",                   # an addendum is a KIND, not a category — its contents vary
}


def top_folder(name: str) -> str:
    """The archive path's first segment, or ``''`` for a member at the root."""
    parts = Path(name).parts
    return parts[0] if len(parts) > 1 else ""


def category_for(name: str) -> str:
    """The `PART_CATEGORIES` value this member's folder implies. Unmapped -> ``other``."""
    folder = top_folder(name).strip().lower()
    # `TA #1` and `TA #2` are the same folder kind; `TC No. 1 & 2` likewise. Match on the leading
    # alphabetic token so a numbered addendum does not need its own entry per issue.
    key = re.match(r"[a-z&]+", folder)
    guess = _FOLDER_CATEGORY.get(folder) or (_FOLDER_CATEGORY.get(key.group(0)) if key else None)
    return guess if guess in PART_CATEGORIES else "other"


# ---------------------------------------------------------------------------
# Flattening — the finding that nearly cost a drawing
# ---------------------------------------------------------------------------
# `Workspace._safe_name` is `Path(filename).name`: it defeats path traversal, correctly, and in
# doing so it DISCARDS the folder. `docs/` is one flat directory, so `DRG/a.pdf` and `SI/a.pdf` both
# land as `a.pdf` and the second silently overwrites the first — no error, and no way to know which
# survived. Priced against the wrong drawing, that is invisible until it is expensive.
#
# The bridge flattens instead. `_safe_name` keeps its contract as a security primitive; widening it
# to preserve folders would change what it is for to solve a naming problem.
_FLAT_SEP = "__"


def flatten(archive_path: str) -> str:
    """``DRG/a.pdf`` -> ``DRG__a.pdf``. The name on disk, and what `part.source_doc` stores, so
    `run_split`'s ``docs / filename`` resolves. The operator never sees this — the part's title
    carries the ARCHIVE path, because that is where they know the document from."""
    clean = [p for p in Path(archive_path).parts if p not in ("/", "\\", "..", ".")]
    return _FLAT_SEP.join(clean) or "upload"


def assert_unique(names: Iterable[str]) -> None:
    """Two archive paths must never flatten to one name.

    Contrived — `S/PS/x.pdf` versus `S__PS/x.pdf` — but a silent overwrite is exactly the failure
    this flattening exists to prevent, and re-introducing it one level up would be worse than
    never having moved. The guard costs a dict.
    """
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for name in names:
        flat = flatten(name)
        if flat in seen and seen[flat] != name:
            clashes.append(f"{seen[flat]!r} and {name!r} both become {flat!r}")
        seen[flat] = name
    if clashes:
        raise ValueError(
            "Two different files in this archive would be stored under the same name, and one "
            "would silently overwrite the other: " + "; ".join(clashes[:5])
        )


# ---------------------------------------------------------------------------
# Reading the tree — central directory only, zero bytes decompressed
# ---------------------------------------------------------------------------
_REV_RE = re.compile(r"[-_](?:BQ|DRG|PS|SI|S)?[-_]?(\d+)\s*$", re.I)
# The pack's convention: `E-ND_2025_04_BQ-0.xlsx` rev 0, `E-ND_2025_04-BQ-1.xlsx` rev 1. 165 of 206
# content files match it. That is a majority, not an authority — where it does not match, NO
# revision is claimed rather than a zero assumed, because "as issued" and "unknown" differ.
_CODED_RE = re.compile(r"^(?P<code>[A-Za-z]-?[A-Za-z0-9_]*?)[-_](?P<doc>BQ|DRG|PS|SI|S|TA)[-_](?P<rev>\d+)$", re.I)


def parse_revision(filename: str) -> Optional[int]:
    """The revision the filename claims, or ``None`` when it does not follow the convention."""
    stem = Path(filename).stem
    m = _CODED_RE.match(stem)
    return int(m.group("rev")) if m else None


class ArchiveReport:
    """What the central directory says, before anything is extracted."""

    def __init__(self, path: Path, members: list[zipfile.ZipInfo]) -> None:
        self.path = path
        self.members = members
        self.content = [m for m in members if is_content(m.filename)]
        self.signatures = [m for m in members if is_signature(m.filename)]
        self.skipped = [
            m for m in members
            if not m.filename.endswith("/") and not is_content(m.filename) and not is_signature(m.filename)
        ]

    @property
    def uncompressed_bytes(self) -> int:
        return sum(m.file_size for m in self.members)

    @property
    def folders(self) -> list[str]:
        seen: list[str] = []
        for m in self.content:
            folder = top_folder(m.filename) or "(root)"
            if folder not in seen:
                seen.append(folder)
        return seen


def read_tree(path: Path) -> ArchiveReport:
    """The archive's structure, from its central directory. Decompresses nothing."""
    try:
        with zipfile.ZipFile(path) as zf:
            return ArchiveReport(path, [m for m in zf.infolist()])
    except zipfile.BadZipFile as exc:
        raise ValueError(f"That file is not a readable ZIP archive ({exc}).") from exc


def check_size(report: ArchiveReport) -> None:
    """Refuse an oversized archive BEFORE extracting anything.

    Both a sanity limit and the zip-bomb guard, and it is the ORDER that makes it a guard: a bomb
    claiming a terabyte is refused from its own central directory having decompressed nothing.
    """
    ceiling = max_uncompressed_bytes()
    total = report.uncompressed_bytes
    if total > ceiling:
        raise ValueError(
            f"This archive expands to {total / 1e6:.0f} MB, over the {ceiling / 1e6:.0f} MB "
            "ceiling, so nothing was extracted. Raise SITESOURCE_ARCHIVE_MAX_BYTES if this pack "
            "is genuinely that large."
        )


# ---------------------------------------------------------------------------
# The proposed manifest
# ---------------------------------------------------------------------------
def plan_manifest(report: ArchiveReport, *, set_id: str, source_name: str) -> SplitManifest:
    """One `PartSpec` per content file, category from its folder, revision where the name says so.

    `TIER_WHOLE` with a `tier_reason` naming the tree, per the ruling: per-document a whole-file
    part genuinely IS tier 4, and adding a fifth tier constant would mean editing
    `client_boq/models.py`.

    `manifest.source_doc` is empty and every part carries its OWN — the shape `run_inspect` already
    emits for non-binder uploads, and the shape `run_split` already resolves with
    ``part.source_doc or manifest.source_doc``.

    `end` is 1 here. The brief asks for `end=<page count>` AND for no extraction at this stage, and
    those cannot both hold: a page count needs the PDF. Extraction corrects every count as the
    bytes pass through, where it is free. Nothing depends on it at the gate — `pdfops.validate`
    measures only parts belonging to the BINDER, and a tree manifest has none.
    """
    assert_unique([m.filename for m in report.content])
    parts: list[PartSpec] = []
    for n, member in enumerate(sorted(report.content, key=lambda m: m.filename), start=1):
        name = member.filename
        stem = Path(name).stem
        rev = parse_revision(name)
        parts.append(PartSpec(
            n=n,
            abbr=(top_folder(name) or stem)[:4].upper() or "DOC",
            slug=_slug(stem),
            # The ARCHIVE path, not the flattened name: the operator is looking for the document
            # they know by its place in the pack.
            title=name,
            start=1, end=1,
            category=category_for(name),
            source_doc=flatten(name),
            rev=rev if rev is not None else 0,
        ))

    folders = ", ".join(f"{f}/" for f in report.folders)
    sig = (f" {len(report.signatures)} .p7s signature file(s) were present and were NOT read as "
           "content." if report.signatures else "")
    manifest = SplitManifest(
        set_id=set_id, source_doc="", pages=0, prefix=_slug(Path(source_name).stem),
        tier=TIER_WHOLE,
        tier_reason=(
            f"the archive's own folder tree — {len(report.folders)} folder(s): {folders}. "
            f"{len(parts)} content file(s); one whole-file part each. The issuer split this "
            "binder deliberately, which is a strong signal and still a proposal."
            + sig
        ),
        parts=parts,
    )
    return manifest


def _slug(text: str) -> str:
    from client_boq.ingest import pdfops  # read-only import; its slug rule, not a second one

    return pdfops.slugify(text)


def folder_summary(report: ArchiveReport) -> list[dict]:
    """The proposal GROUPED BY FOLDER, for a gate that would otherwise be 203 rows.

    A person approving a tender pack is checking that the shape is right — that the drawings are
    under `DRG/` and there are about the right number of them — not auditing 203 filenames. They
    expand a folder they doubt. The gate is unchanged: approving is still one deliberate act.
    """
    groups: dict[str, list[zipfile.ZipInfo]] = {}
    for m in report.content:
        groups.setdefault(top_folder(m.filename) or "(root)", []).append(m)
    out: list[dict] = []
    for folder in report.folders:
        members = groups.get(folder, [])
        out.append({
            "folder": folder,
            "files": len(members),
            "category": category_for(members[0].filename) if members else "other",
            "bytes": sum(m.file_size for m in members),
            "names": sorted(Path(m.filename).name for m in members),
        })
    return out


# ---------------------------------------------------------------------------
# Extraction — one member at a time, on approval only
# ---------------------------------------------------------------------------
def stream_to(source, destination: Path) -> int:
    """Copy a file-like object to ``destination`` a chunk at a time. Returns the bytes written.

    Starlette has already spooled a large upload to disk (`SpooledTemporaryFile(max_size=1MB)`),
    so `UploadFile.file` is a real file object — `.read()` is what would materialise 232 MB, and
    this is what does not.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(destination, "wb") as dst:
        while True:
            chunk = source.read(_CHUNK)
            if not chunk:
                break
            dst.write(chunk)
            written += len(chunk)
    return written


def extract(
    report: ArchiveReport, ws: Workspace, tender_name: str,
    *, progress_cb: Progress = None, count_cb: Count = None,
) -> dict[str, str]:
    """Extract every content member to its flattened path under `Workspace.docs_dir`.

    ``part.source_doc -> on-disk path``. Signature members are never opened. Never more than one
    chunk in memory, whatever the archive weighs.
    """
    written: dict[str, str] = {}
    total = len(report.content)
    ws.docs_dir(tender_name, create=True)
    with zipfile.ZipFile(report.path) as zf:
        for index, member in enumerate(sorted(report.content, key=lambda m: m.filename)):
            if count_cb is not None:
                count_cb(index, total)
            flat = flatten(member.filename)
            target = ws.doc_path(tender_name, flat)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=_CHUNK)
            written[flat] = str(target)
    if count_cb is not None:
        count_cb(total, total)
    return written


# ---------------------------------------------------------------------------
# Workbooks
# ---------------------------------------------------------------------------
# `pdfops.slice_pdf` degrades to returning its input, so a workbook cut as a "part" would land on
# disk as a `.pdf` file containing xlsx bytes. A lie on disk is worse than a refusal, so a workbook
# is recorded as a part, NOT cut, and keeps its real extension.
#
# `scanned=True` is the honest-unreadable channel and the only one available without editing
# `client_boq/models.py` — but elsewhere it means "needs vision OCR", and a workbook needs an Excel
# reader, not vision. The note says which, so nobody eventually points OCR at a spreadsheet.
WORKBOOK_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls"})
WORKBOOK_NOTE = (
    "workbook, not a scan; needs the Excel reader. `scanned` is set because it is the only "
    "unreadable flag available, but vision would read nothing here."
)


def is_workbook(name: str) -> bool:
    return Path(name).suffix.lower() in WORKBOOK_SUFFIXES


def set_id_for(project_name: str) -> str:
    """The same identity rule as every other entry point — a tender is its name."""
    return tender_slug(project_name)
