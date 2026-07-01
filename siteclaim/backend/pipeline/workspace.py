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

import os
import re
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "out" / "workspace"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def tender_slug(project_name: str) -> str:
    """A filesystem-safe, deterministic id for a tender from its project name."""
    slug = _SLUG_STRIP.sub("-", (project_name or "").strip().lower()).strip("-")
    return slug or "tender"


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
