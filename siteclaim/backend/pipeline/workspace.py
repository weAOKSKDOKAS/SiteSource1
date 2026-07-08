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
import os
import re
from pathlib import Path

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


class Workspace:
    """Deterministic on-disk storage for one tender's originals and artifacts."""

    def __init__(self, root: Path | str | None = None) -> None:
        env = os.getenv("SITESOURCE_WORKDIR", "").strip()
        self.root = Path(root) if root is not None else (Path(env) if env else _DEFAULT_ROOT)

    # -- directories --------------------------------------------------------
    def tender_dir(self, tender_id: str) -> Path:
        return self.root / tender_slug(tender_id)

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
        """Persist an uploaded original and return its path."""
        path = self.docs_dir(tender_id, create=True) / _safe_name(filename)
        path.write_bytes(data)
        return path

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
