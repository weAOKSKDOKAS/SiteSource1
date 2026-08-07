"""A working directory for a live tender's real files (Phase A).

The demo carries document *labels* (``schedule_of_rates.pdf`` is a name, not a file).
The live engine, once ``DEMO_MODE`` is off, receives real uploads and must be able to
attach the relevant originals to each subcontractor's email. This module gives those
files a deterministic home on disk, keyed by a slug of the tender's project name, so a
later stage (dispatch, the mailer) can find them again without threading bytes through
every typed handoff.

Nothing here touches the network. The root defaults to
``backend/fixtures/out/workspace`` and can be overridden with ``SITESOURCE_WORKDIR``
(so a deployment can point it at a real volume). The slug is a pure function of the
project name — no timestamps, no randomness — so the same tender always resolves to
the same directory and the paths are reproducible.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "out" / "workspace"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
# A Hong Kong contract number: a letter prefix then 2–3 slash-separated numeric groups,
# e.g. "GE/2026/14", "HY/2020/09". Preferred as the slug — short, human, and stable.
_CONTRACT_RE = re.compile(r"[A-Za-z]{1,5}(?:\s*/\s*\d{1,4}){2,3}")
# The same contract number embedded in free DOCUMENT text — stricter than `_CONTRACT_RE` (which
# slugs an already-short project name): the middle group must be a 4-digit YEAR (19xx/20xx), so a
# clause reference like "PS/7/34" or a bare date buried in a spec is not mistaken for a contract.
_DOC_CONTRACT_RE = re.compile(r"[A-Za-z]{1,4}\s*/\s*(?:19|20)\d{2}\s*/\s*\d{1,3}\b")
_SLUG_MAX = 40  # keep slugs short so nested artifact paths stay well under Windows' 259-char limit
# A value already in canonical slug form: lowercase alphanumerics joined by single hyphens. The
# length bound is `_SLUG_MAX` plus a `-` and the 8-hex digest, which is the longest this function
# ever produces — anything longer is a name that has not been slugged yet.
_ALREADY_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def name_has_contract_number(project_name: str) -> bool:
    """Whether ``project_name`` already embeds a contract number ``tender_slug`` would key off."""
    return bool(_CONTRACT_RE.search(project_name or ""))


def contract_number_in_text(text: str) -> str:
    """The first Hong Kong contract number found in a block of document text, normalised to its
    canonical ``GE/2026/14`` form (whitespace around the slashes dropped, prefix upper-cased), or
    ``""`` when none is present. Pure and deterministic — a regex read of the cached document text,
    no model — used at ingest to anchor a tender's identity on its contract number."""
    match = _DOC_CONTRACT_RE.search(text or "")
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(0)).upper()


def anchor_name_on_contract(project_name: str, document_text: str) -> str:
    """Return ``project_name`` guaranteed to carry a contract number ``tender_slug`` keys off, so a
    tender's on-disk identity and its ``[SiteSource Ref: …]`` slug are the stable ``ge-2026-14``.

    If the name already embeds a contract number it is returned unchanged; else, if a contract
    number is found in ``document_text``, it is prepended (``"Contract No. GE/2026/14 — {name}"``, or
    just ``"Contract No. GE/2026/14"`` when the name is empty); else the name is returned unchanged.
    Pure and deterministic. The caller applies it only to NEW ingests, so existing slugs/refs — which
    store their own full name — are untouched."""
    if name_has_contract_number(project_name):
        return project_name
    contract = contract_number_in_text(document_text)
    if not contract:
        return project_name
    base = (project_name or "").strip()
    return f"Contract No. {contract} — {base}" if base else f"Contract No. {contract}"


def tender_slug(project_name: str) -> str:
    """A filesystem-safe, deterministic, **short** id for a tender from its project name.

    A full contract title runs to 150+ chars, which overran Windows' path limit for the
    nested per-firm SoR sheet (Excel refused to open it) and bloated the ``[SiteSource
    Ref: …]`` email subject. So: prefer an embedded contract number (``GE/2026/14`` →
    ``ge-2026-14``); otherwise slugify and, if still long, truncate to ~40 chars plus a
    short stable hash of the full name so distinct long titles never collide. Pure
    function of the name — no timestamp, no randomness — so a ref always round-trips.
    """
    name = (project_name or "").strip()
    # IDEMPOTENCE. `tender_slug(tender_slug(x))` MUST equal `tender_slug(x)`, and on the
    # truncate-and-hash branch it did not: the hash is taken over the INPUT, so slugging an
    # already-slugged name hashes the slug and yields a different directory every time —
    #
    #   'Ground Investigation Works for … (Phase 2)' -> 'ground-investigation-works-for-developme-ccd1cccd'
    #                                                -> 'ground-investigation-works-for-developme-dc2fbca2'
    #                                                -> 'ground-investigation-works-for-developme-eb58083d'
    #
    # A run_ref IS a slug, and every caller that resolves an id before addressing a directory slugs
    # it once more — so registering a tender FLIPPED its workspace, and two of the operator's stray
    # directories are the same tender slugged a different number of times. Recognising a value that
    # is already in canonical form and returning it unchanged closes that: the function becomes a
    # projection, and a slug is a fixed point of it.
    if _ALREADY_SLUG.match(name) and len(name) <= _SLUG_MAX + 9:
        return name
    match = _CONTRACT_RE.search(name)
    if match:
        contract = _SLUG_STRIP.sub("-", match.group(0).lower()).strip("-")
        if contract:
            return contract
    slug = _SLUG_STRIP.sub("-", name.lower()).strip("-")
    if not slug:
        return "tender"
    if len(slug) <= _SLUG_MAX:
        return slug
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]  # stable across processes
    return f"{slug[:_SLUG_MAX].rstrip('-')}-{digest}"


def _safe_name(filename: str) -> str:
    """Reduce an uploaded filename to a safe basename (no path traversal)."""
    base = Path(filename or "upload").name
    base = base.replace("\x00", "")
    return base or "upload"


class UnsafeUploadPath(ValueError):
    """A relative path that would escape the tender's own folder.

    Raised rather than sanitised. A ``..`` segment or a drive letter arriving from a browser is not
    a typo somebody made — quietly rewriting it to something harmless would hide an attempt to write
    outside the workspace, and the app has no business being discreet about that.
    """


def safe_relative_path(relative_path: str) -> Path:
    """Validate a browser-supplied relative path and return it as a ``Path``.

    Uploading a folder means the client tells the server where each file sat in the tree, and a path
    that comes from a client is input, not fact. Anything absolute, drive-lettered, or containing
    ``..`` is refused; separators are normalised so Windows and POSIX clients agree; each segment is
    reduced to a safe name so a component cannot smuggle a separator through.
    """
    raw = (relative_path or "").replace("\\", "/").replace("\x00", "").strip()
    if not raw:
        raise UnsafeUploadPath("an uploaded file arrived with no path at all")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise UnsafeUploadPath(
            f"{relative_path!r} is an absolute path. Uploaded files are stored relative to the "
            f"tender's own folder, so only a relative path can be honoured.")

    parts = [segment for segment in raw.split("/") if segment not in ("", ".")]
    if any(segment == ".." for segment in parts):
        raise UnsafeUploadPath(
            f"{relative_path!r} climbs above the tender folder. Refused rather than trimmed — a "
            f"path that tries to escape is worth seeing, not quietly fixing.")
    if not parts:
        raise UnsafeUploadPath(f"{relative_path!r} names no file")

    cleaned = [_safe_name(segment) for segment in parts]
    return Path(*cleaned)


def _alias_connections() -> list:
    """Every database the alias registry might live in, in the order worth trying.

    Normally one: with ``SITESOURCE_DB`` set — live, and in every test — procurement and client_boq
    open the SAME file, so the first succeeds and the second is never reached.

    They diverge in DEMO with no ``SITESOURCE_DB``, where client_boq deliberately opens a gitignored
    scratch database so the committed ``sitesource.db`` is never written (trap 3b). The bridge
    registers aliases through THAT connection, so a resolver that only knew about procurement's
    would find nothing and quietly fall back to slugging a display name — the defect this whole
    resolution exists to close, reappearing in exactly the mode that is hardest to notice.

    Ordered procurement-first so the common path costs one open. The client_boq import is lazy and
    inside the list, so `pipeline` still does not import it at module scope.
    """
    def _procurement():
        from db.store import get_connection

        return get_connection()

    def _client_boq():
        from client_boq import store as cb_store

        return cb_store.get_conn()

    return [_procurement, _client_boq]


class Workspace:
    """Deterministic on-disk storage for one tender's originals and artifacts."""

    def __init__(self, root: Path | str | None = None) -> None:
        env = os.getenv("SITESOURCE_WORKDIR", "").strip()
        self.root = Path(root) if root is not None else (Path(env) if env else _DEFAULT_ROOT)
        self._refs: dict[str, Optional[str]] = {}   # per-instance resolution cache

    # -- identity -----------------------------------------------------------
    def resolve_ref(self, tender_id: str) -> Optional[str]:
        """The ``run_ref`` this string addresses, or ``None`` when it addresses no known tender.

        A tender is addressed by its ``run_ref`` and by nothing else — but the callers that reach a
        workspace hold whatever string they have: the bridge holds the ``set_id``, client_boq's
        ingest holds the set's display NAME, `/ingest-upload` holds the project title read off the
        documents, and one archive upload held a FILENAME. Slugging each of them produced a
        different directory, and one tender ended up with five.

        Resolved HERE, and not only at the API boundary, because several of those writers are not
        callers this can change: `client_boq/ingest/run.py` saves its uploads under the set's name
        and `bridge/archive.py` extracts under the same, so a boundary-only fix would leave the
        originals in one directory and the index in another. One lookup inside the one class every
        path goes through fixes all of them at once.

        STRICTLY READ-ONLY and cached per instance. It never creates a table and never writes a
        row: this runs against whatever database is open, including the committed demo one, and
        `CREATE TABLE IF NOT EXISTS` on that file is a documented way to damage it.
        """
        key = (tender_id or "").strip()
        if not key:
            return None
        if key in self._refs:
            return self._refs[key]
        ref: Optional[str] = None
        for open_conn in _alias_connections():
            try:
                from db import project as uproject

                conn = open_conn()
                try:
                    ref = uproject.resolve_ref(conn, key)
                finally:
                    conn.close()
            except Exception:  # noqa: BLE001 — no database is not a reason to fail a path lookup
                ref = None
            if ref:
                break
        self._refs[key] = ref
        return ref

    # -- directories --------------------------------------------------------
    def tender_dir(self, tender_id: str) -> Path:
        """This tender's directory — by ``run_ref`` where one is registered, never by a display
        string. An UNREGISTERED string still gets its own directory (that is the pure procurement
        path, where the name IS the identity, and every existing run depends on it) — but it is
        logged, so a new name-derived directory is never minted in silence. See
        :meth:`resolve_ref`."""
        ref = self.resolve_ref(tender_id)
        if ref is None:
            slug = tender_slug(tender_id)
            if not (self.root / slug).exists():
                _log.info(
                    "workspace: %r is not registered to any tender — addressing a new directory %r. "
                    "If this tender already exists under another name, that name needs registering "
                    "(db.project.register_aliases) or its artifacts will be split across two.",
                    tender_id, slug)
            return self.root / slug
        return self.root / tender_slug(ref)

    def docs_dir(self, tender_id: str, *, create: bool = False) -> Path:
        path = self.tender_dir(tender_id) / "docs"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def artifacts_dir(self, tender_id: str, *, create: bool = False) -> Path:
        path = self.tender_dir(tender_id) / "artifacts"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    # -- files --------------------------------------------------------------
    def save_upload(self, tender_id: str, filename: str, data: bytes) -> Path:
        """Persist an uploaded original and return its path.

        Flattens to a basename. Correct for a binder upload, where filenames are already distinct —
        and lossy for a folder, where two subfolders may each hold a ``BOQ.pdf``. Use
        :meth:`save_upload_at` when the tree matters.
        """
        path = self.docs_dir(tender_id, create=True) / _safe_name(filename)
        path.write_bytes(data)
        return path

    def save_upload_at(self, tender_id: str, relative_path: str, data: bytes) -> Path:
        """Persist an uploaded original **keeping its folder tree**, and return its path.

        The reason this exists: ``save_upload`` reduces every file to a basename, so
        ``TA #1/BQ/BQ.pdf`` and ``TA #2/BQ/BQ.pdf`` both become ``docs/BQ.pdf`` and the second
        silently overwrites the first. On a tender package that is a lost document — the addendum's
        bill replacing the original with no trace that either existed.
        """
        target = self.docs_dir(tender_id, create=True) / safe_relative_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def doc_path(self, tender_id: str, filename: str) -> Path:
        """Where an original *would* live (may or may not exist yet)."""
        return self.docs_dir(tender_id) / _safe_name(filename)

    def sor_sheet_path(self, tender_id: str, trade: str) -> Path:
        """Where this trade's generated Schedule-of-Rates sheet lives."""
        return self.artifacts_dir(tender_id, create=True) / f"SoR_{tender_slug(trade)}.xlsx"

    def doc_index_path(self, tender_id: str, *, create: bool = False) -> Path:
        """Where this run's per-document structural index (doc_index.json) lives."""
        return self.artifacts_dir(tender_id, create=create) / "doc_index.json"

    def scope_path(self, tender_id: str, *, create: bool = False) -> Path:
        """Where this run's canonical scope split (scope.json — the ``ScopePackages`` the ingest
        produced) lives, so the inbound-reply loop can route returned lines to their true SoR
        section by matching item identity instead of trusting the enquiry's trade."""
        return self.artifacts_dir(tender_id, create=create) / "scope.json"

    def firm_attachment_path(self, tender_id: str, firm_id: str, filename: str) -> Path:
        """Where an assembled per-firm attachment (a sliced/whole PDF) is materialised."""
        safe_firm = _SLUG_STRIP.sub("-", (firm_id or "firm").lower()).strip("-") or "firm"
        out = self.artifacts_dir(tender_id, create=True) / "attachments" / safe_firm
        out.mkdir(parents=True, exist_ok=True)
        return out / _safe_name(filename)
