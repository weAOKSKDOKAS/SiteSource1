"""Relevant-only attachment assembly + the Gmail draft hand-off (direct API, no n8n).

The outbound draft path: build each approved firm's relevant-only attachment set (sliced /
whole PDFs + the priced-return sheet) from its per-section plan, and create ONE Gmail DRAFT per
firm via :mod:`pipeline.gmail_client` — the human gate holds (the operator reviews and sends
from Gmail; nothing is auto-sent). The n8n webhook transport this replaced
(``N8N_DRAFTS_WEBHOOK``) failed whenever n8n was down and 500'd the whole dispatch; a Gmail
failure here is returned as data (``failed`` with a per-firm reason), never raised — the
enquiries are already prepared in the outbox and can be drafted again. Sync; the only network
is the Gmail API on the live confirm path.
"""

from __future__ import annotations

import base64
import mimetypes
from typing import Optional

from pipeline.stage_01_ingest.doc_index import load_doc_index
from pipeline.stage_03_dispatch.relevant_docs import SectionPlan, resolve_section_plan, slice_pdf
from pipeline.workspace import Workspace
from rules_engine.taxonomy import base_trade
from schemas.models import ScopePackages


def _page_texts_reader(ws: Workspace, tender_id: str) -> "callable":
    """A ``filename -> cached OCR page texts`` reader for the directed clause search: reads the
    original from the workspace and serves its page text from the OCR spine's content-addressed cache
    (populated at ingest), so re-reading needs no live engine. A read never fails the plan — a missing
    file or an unreachable engine yields ``[]`` (the whole-file fallback remains)."""
    from pipeline import ocr

    def _get(filename: str) -> list[str]:
        path = ws.doc_path(tender_id, filename)
        if not path.is_file():
            return []
        try:
            return ocr.page_texts(path.read_bytes())
        except Exception:  # noqa: BLE001 — cached text read is best-effort; whole-file is the fallback
            return []

    return _get


def plan_for_firms(
    scope: Optional[ScopePackages], approvals: dict[str, list[str]], *, tender_id: str,
    workspace: Optional[Workspace] = None,
) -> dict[str, SectionPlan]:
    """The relevant-document plan per dispatched section (keyed by package_key). Firms in the
    same section share the doc plan; the SoR sheet is per-section. Reads the run's persisted
    doc_index — empty (DEMO / no upload) yields a plan with just the SoR sheet."""
    ws = workspace or Workspace()
    doc_index = load_doc_index(ws, tender_id)
    page_texts_of = _page_texts_reader(ws, tender_id)  # shared cache across this run's sections
    pkg_by_key = {p.trade: p for p in (scope.packages if scope else [])}
    plans: dict[str, SectionPlan] = {}
    for package_key in approvals:
        pkg = pkg_by_key.get(package_key)
        items = pkg.sor_items if pkg else []
        suffix = package_key.split(":", 1)[1] if ":" in package_key else ""
        # A split unit carries its section in the ``:SECTION`` suffix; a suffix-less single/specialty
        # package (e.g. ``field_installations``) has none, so derive its section(s) from its items —
        # otherwise the SoR would be sent WHOLE for want of a section to slice on.
        unit_sections = (
            [suffix] if suffix
            else list(dict.fromkeys(s for it in items if (s := (it.section or "").strip().upper())))
        )
        plans[package_key] = resolve_section_plan(
            package_key=package_key, trade=base_trade(package_key),
            section_title=(pkg.scope_summary if pkg else ""), section=suffix, sections=unit_sections,
            items=items, doc_index=doc_index,
            sor_sheet_name=ws.sor_sheet_path(tender_id, package_key).name,
            page_texts_of=page_texts_of,
        )
    return plans


def _attachment_bytes(att, ws: Workspace, tender_id: str, package_key: str) -> Optional[bytes]:
    """The bytes for one planned attachment (SoR sheet / whole original / sliced PDF), or None
    if the source file is not present in the workspace."""
    if att.mode == "generated":
        path = ws.sor_sheet_path(tender_id, package_key)
        return path.read_bytes() if path.is_file() else None
    path = ws.doc_path(tender_id, att.source_doc)
    if not path.is_file():
        return None
    data = path.read_bytes()
    return slice_pdf(data, att.pages) if att.mode == "sliced" else data


def assemble_firm_attachments(
    plan: SectionPlan, ws: Workspace, tender_id: str, package_key: str,
) -> list[dict]:
    """Materialise a section's plan into ``[{filename, mime, content_b64}]`` — ONLY the planned
    relevant-only files, each base64-encoded. Missing sources are skipped (never fabricated)."""
    out: list[dict] = []
    for att in plan.attachments:
        data = _attachment_bytes(att, ws, tender_id, package_key)
        if data is None:
            continue
        emit_name = att.out_filename or att.source_doc  # the SoR slice is sent under its friendly name
        out.append({
            "filename": emit_name,
            "mime": mimetypes.guess_type(emit_name)[0] or "application/octet-stream",
            "content_b64": base64.b64encode(data).decode("ascii"),
        })
    return out


def create_gmail_drafts(drafts: list[dict], *, service=None) -> tuple[list[str], list[dict]]:
    """One Gmail DRAFT per assembled enquiry — ``(drafted firm ids, failed [{firm_id, reason}])``.

    NEVER raises: the enquiries are already prepared in the outbox before drafting, so a Gmail
    failure (no credential, expired token, API error, offline) must not fail the dispatch — it
    comes back as data with an actionable per-firm reason, and the operator can draft again. A
    firm with no contact email is reported in ``failed`` too (never a silent empty To). Drafts
    only, never a send — the human gate holds. ``service`` injects a stub in tests."""
    from pipeline import gmail_client  # lazy: DEMO/tests never import the Google SDK path

    if not drafts:
        return [], []
    svc = service
    if svc is None:
        try:
            svc = gmail_client.build_service()
        except gmail_client.GmailUnavailable as exc:
            return [], [{"firm_id": d.get("firm_id", ""), "reason": str(exc)} for d in drafts]
    drafted: list[str] = []
    failed: list[dict] = []
    for d in drafts:
        firm_id = d.get("firm_id", "")
        to = (d.get("to") or "").strip()
        if not to:
            failed.append({"firm_id": firm_id,
                           "reason": "no contact email on file — add one in the address book (GET /contacts)"})
            continue
        attachments = [(a["filename"], base64.b64decode(a["content_b64"])) for a in d.get("attachments", [])]
        try:
            gmail_client.create_draft(to, d.get("subject", ""), d.get("body", ""), attachments, service=svc)
            drafted.append(firm_id)
        except gmail_client.GmailUnavailable as exc:
            failed.append({"firm_id": firm_id, "reason": str(exc)})
    return drafted, failed
