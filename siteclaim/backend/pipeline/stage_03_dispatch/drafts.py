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
from pathlib import Path
from typing import Callable, Optional

from pipeline.stage_01_ingest.doc_index import load_doc_index
from pipeline.stage_03_dispatch.relevant_docs import (
    PRICED_RETURN,
    PlanAttachment,
    SectionPlan,
    resolve_section_plan,
    slice_pdf,
)
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


# The workbook the firm actually fills in, sent BESIDE the sliced bill rather than instead of it.
#
# Proven on the real pack: the sliced PDF arrives correctly and is the right document to READ — it
# is the bill as issued, with its own item numbers and quantities. It is the wrong document to
# PRICE. A print PDF has no form fields, so the operator "filled it in" in a viewer, nothing was
# written to the file, and the return came back with Quantity and Unit intact and Rate and Amount
# entirely empty. The engine read it correctly: 27 line items, no rates, scope gap (unpriced). A
# subcontractor will hit exactly this.
#
# So the enquiry carries both, and each is flagged for what it is. `PRICED_RETURN` stays on the
# slice, unchanged — the human gate protects it, and the return-format rules keyed on it do not
# move.
PRICING_WORKBOOK = "pricing_workbook"


def _pricing_workbook_attachment(
    priced_return, sor_sheet_name: str, sheet_path,
) -> Optional[PlanAttachment]:
    """The .xlsx to price, beside a slice. ``None`` when there is no second file to send.

    Two cases return ``None``, and both are "there is nothing to add here":

    * the priced return is ALREADY ``mode="generated"`` — that IS this workbook, reached because
      there was no bill PDF to slice, and attaching it twice would ask a firm to price the same
      file under two names;
    * the sheet has not been generated. `generate_sor_sheet` writes it from the package's own
      ``sor_items``, and both endpoints that matter do so before planning — `/dispatch/drafts`
      through `build_dispatch`, `/dispatch/plan` directly. A plan must never promise a file that
      does not exist: this is a derived artifact we own, so its absence means "not generated",
      never "missing", and planning it anyway would put a name on the gate that the assembler
      would then skip.
    """
    if priced_return.mode == "generated" or not sheet_path.is_file():
        return None
    # Named off the slice so the pair sorts together and reads as a pair —
    # `SoR_ground_investigation_Section_2.pdf` beside `SoR_ground_investigation_Section_2_to_price.xlsx`.
    stem = (priced_return.out_filename or priced_return.source_doc or "SoR").rsplit(".", 1)[0]
    return PlanAttachment(
        source_doc=sor_sheet_name, out_filename=f"{stem}_to_price.xlsx", mode="generated",
        flags=[PRICING_WORKBOOK],
        reason=("The sheet to PRICE and return — same items, descriptions, quantities and units as "
                "the bill extract beside it. A PDF has no fields to type in and comes back blank; "
                "this workbook is read back deterministically, with no interpretation."),
    )


def plan_for_firms(
    scope: Optional[ScopePackages], approvals: dict[str, list[str]], *, tender_id: str,
    workspace: Optional[Workspace] = None,
) -> dict[str, SectionPlan]:
    """The relevant-document plan per dispatched section (keyed by package_key). Firms in the
    same section share the doc plan; the SoR sheet is per-section. Reads the run's persisted
    doc_index — empty (DEMO / no upload) yields a plan with just the SoR sheet.

    Where the priced return is a SLICE, the pricing workbook is added beside it — see
    :data:`PRICING_WORKBOOK`. Added HERE rather than in ``relevant_docs`` so the one function both
    the gate preview (``/dispatch/plan``) and the draft assembly (``/dispatch/drafts``) call is the
    one place it is decided: the operator sees exactly what the firm will receive.
    """
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
        sheet_path = ws.sor_sheet_path(tender_id, package_key)
        sheet_name = sheet_path.name
        plan = resolve_section_plan(
            package_key=package_key, trade=base_trade(package_key),
            section_title=(pkg.scope_summary if pkg else ""), section=suffix, sections=unit_sections,
            items=items, doc_index=doc_index,
            sor_sheet_name=sheet_name,
            page_texts_of=page_texts_of,
        )
        priced = next((a for a in plan.attachments if PRICED_RETURN in a.flags), None)
        book = (_pricing_workbook_attachment(priced, sheet_name, sheet_path)
                if priced is not None else None)
        if book is not None:
            # Directly after the slice: the two belong together, and an operator reading the gate
            # top to bottom meets "the bill extract" and "the sheet to price" in that order.
            at = plan.attachments.index(priced) + 1
            plan = plan.model_copy(update={
                "attachments": plan.attachments[:at] + [book] + plan.attachments[at:]})
        plans[package_key] = plan
    return plans


def _attachment_bytes(att, ws: Workspace, tender_id: str, package_key: str,
                      sources: Optional[dict] = None) -> Optional[bytes]:
    """The bytes for one planned attachment (SoR sheet / whole original / sliced PDF), or None
    if the source file is not present.

    ``sources`` maps an indexed ``filename`` to the ``source_path`` recorded with it, and is tried
    FIRST. ``/ingest-upload`` records none — it saves each original to ``docs/<filename>`` and
    indexes it under that same name, so the ``doc_path`` lookup below has always found it. The
    bridge cannot: it indexes a client_boq PART under the part's TITLE, and no file called
    "Schedule of Rates" has ever existed in ``docs/``. That lookup returned None for every
    attachment, every one was skipped, and the drafts went out empty.
    """
    if att.mode == "generated":
        path = ws.sor_sheet_path(tender_id, package_key)
        return path.read_bytes() if path.is_file() else None
    recorded = (sources or {}).get(att.source_doc, "")
    path = Path(recorded) if recorded else ws.doc_path(tender_id, att.source_doc)
    if not path.is_file():
        return None
    data = path.read_bytes()
    return slice_pdf(data, att.pages) if att.mode == "sliced" else data


def assemble_firm_attachments(
    plan: SectionPlan, ws: Workspace, tender_id: str, package_key: str,
    *, on_note: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """Materialise a section's plan into ``[{filename, mime, content_b64}]`` — ONLY the planned
    relevant-only files, each base64-encoded. Missing sources are skipped (never fabricated).

    The source of each file is resolved from the doc index's ``source_path`` where one was
    recorded, falling back to ``docs/<filename>``. Skipping stays the behaviour for a source that
    genuinely is not there — but it is now REPORTED through ``on_note``. Silence is why an empty
    draft could ship while the preview, which reads the index and never touches disk, showed the
    full set.
    """
    sources = {e.filename: e.source_path for e in load_doc_index(ws, tender_id) if e.source_path}
    out: list[dict] = []
    for att in plan.attachments:
        data = _attachment_bytes(att, ws, tender_id, package_key, sources)
        if data is None:
            if on_note:
                on_note(
                    f"{att.source_doc!r} is on the plan for {package_key!r} but its source file "
                    "was not found, so it is NOT attached to this enquiry"
                )
            continue
        emit_name = att.out_filename or att.source_doc  # the SoR slice is sent under its friendly name
        out.append({
            "filename": emit_name,
            "mime": mimetypes.guess_type(emit_name)[0] or "application/octet-stream",
            "content_b64": base64.b64encode(data).decode("ascii"),
        })
    return out


def create_gmail_drafts(
    drafts: list[dict], *, service=None,
    on_created: Optional[Callable[[dict], None]] = None,
) -> tuple[list[str], list[dict]]:
    """One Gmail DRAFT per assembled enquiry — ``(drafted firm ids, failed [{firm_id, reason}])``.

    ``on_created`` is called once per successful draft with
    ``{firm_id, message_id, ref, to}`` — the OUTBOUND LEDGER's raw material. Every dispatched RFQ
    is addressed to the operator during live testing, so it lands in the mailbox the poller watches
    carrying the ref tag and the blank SoR, indistinguishable from a genuine reply by query alone.
    The MESSAGE id is the explicit identity that makes it distinguishable, and this is the only
    moment it is in hand.

    A callback rather than a third return value on purpose: the return shape is what four existing
    tests and the route both unpack, and widening it would break them to carry a fact only one
    caller wants.

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
            _draft_id, message_id = gmail_client.create_draft_ids(
                to, d.get("subject", ""), d.get("body", ""), attachments, service=svc,
                # Stamps X-SiteSource-Outbound. The message id ledger cannot survive the send
                # (Gmail replaces the id), so the header is what actually identifies our own RFQ
                # when it lands back in the watched mailbox.
                ref=d.get("ref", ""))
            drafted.append(firm_id)
            if on_created is not None:
                on_created({"firm_id": firm_id, "message_id": message_id,
                            "ref": d.get("ref", ""), "to": to})
        except gmail_client.GmailUnavailable as exc:
            failed.append({"firm_id": firm_id, "reason": str(exc)})
    return drafted, failed
