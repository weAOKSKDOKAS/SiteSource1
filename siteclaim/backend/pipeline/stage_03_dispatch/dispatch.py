"""Stage 03 — dispatch: ShortlistSet + human approvals -> DispatchSet.

Layer 4 gate: ``approvals`` maps each trade to the list of ``firm_id``s the human
approved, and only those firms (that are actually on the shortlist) get a bundle.

For each approved firm a :class:`DispatchBundle` is assembled with:

* ``bundle_doc_refs`` — **only that trade's documents** (the trade scope/SoR package
  and that trade's SoR item refs), so an electrical firm receives the electrical
  scope, not the whole tender. This split is deterministic Layer 1.
* ``email_subject`` / ``email_body`` — composed by **Layer 2** (``complete_json``),
  professional and specific to the trade and project. In DEMO_MODE the email bodies
  are read from a baked ``DispatchSet`` fixture; if a firm is approved that the
  fixture does not cover, a deterministic offline template is used, so the stage
  never needs the network.

Nothing is actually sent — :func:`db.outbox.send_mock` writes "sent" bundles to a
mock outbox JSON file and flips their status to ``sent_mock``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from pipeline.concurrency import run_calls
from pipeline.llm_client import LLMClient, demo_mode
from pipeline.reply_loop import make_ref, record_dispatch, subject_with_ref
from pipeline.stage_03_dispatch.attachments import build_attachments
from pipeline.workspace import Workspace
from schemas.models import (
    BundleAttachment,
    DispatchBundle,
    DispatchSet,
    DispatchStatus,
    ScopePackages,
    ShortlistSet,
    TenderPackage,
)

_EMAIL_SYSTEM = (
    "You write concise, professional sub-contract enquiry (RFQ) emails for a Hong "
    "Kong main contractor's buying team. For each firm, compose an email_subject and "
    "email_body inviting them to price ONLY their trade's package on the named "
    "project, referencing the enclosed trade scope and Schedule of Rates and asking "
    "for a priced return by the tender date. Be specific to the trade and project. "
    "Do not quote prices or make commitments.\n\n"
    "Return ONE JSON object with a `bundles` array — never a bare top-level array. "
    'The exact shape is: {"bundles": [{"firm_id": <string>, "firm_name": <string>, '
    '"trade": <string>, "email_subject": <string>, "email_body": <string>}]} — one '
    "entry per firm. The top level is an object with a `bundles` key, not a list."
)


def _trade_label(trade: str) -> str:
    return trade.replace("_", " ").title()


def _bundle_docs(trade: str, scope: Optional[ScopePackages]) -> list[str]:
    """Only this trade's documents — never another trade's, never the whole tender."""
    refs = [f"{trade} — scope & SoR package"]
    if scope is not None:
        pkg = next((p for p in scope.packages if p.trade == trade), None)
        if pkg is not None:
            refs += [f"SoR {item.item_ref}" for item in pkg.sor_items]
    return refs


def _template_email(firm_name: str, trade: str, project_name: str) -> tuple[str, str]:
    """A deterministic, offline fallback RFQ email (no LLM, no network)."""
    label = _trade_label(trade)
    subject = f"RFQ — {label} package — {project_name}"
    body = (
        f"Dear {firm_name},\n\n"
        f"We are inviting selected specialists to price the {label} package for "
        f"{project_name}. Please find enclosed the {label.lower()} scope summary and the "
        f"relevant Schedule of Rates for your trade only.\n\n"
        "We would be grateful for your priced return, with any qualifications or "
        "exclusions clearly stated, by the tender date. Please direct any queries to "
        "the buying team.\n\n"
        "Kind regards,\nBuying Team"
    )
    return subject, body


_COMPOSE_BATCH_SIZE = 6  # bundles per compose call — bounded so the JSON response never truncates


def _compose_batch(
    batch: list[tuple[str, str, str, list[str]]],
    project_name: str,
    demo_fixture: Optional[str],
    client: LLMClient,
) -> dict[tuple[str, str], tuple[str, str]]:
    """Compose one bounded batch. Returns {} on any failure so the batch's firms fall back
    to the deterministic template — a bad or truncated response never fails dispatch."""
    try:
        drafted = client.complete_json(
            system=_EMAIL_SYSTEM,
            user=_compose_prompt(batch, project_name),
            target_model=DispatchSet,
            demo_fixture=demo_fixture,
        )
    except (RuntimeError, FileNotFoundError, ValidationError, ValueError):
        return {}
    return {(b.trade, b.firm_id): (b.email_subject, b.email_body) for b in drafted.bundles}


def _compose_emails(
    scaffold: list[tuple[str, str, str, list[str]]],
    project_name: str,
    demo_fixture: Optional[str],
    client: LLMClient,
) -> dict[tuple[str, str], tuple[str, str]]:
    """Return {(trade, firm_id): (subject, body)} — baked in DEMO_MODE, composed live.

    Composition runs in bounded batches (<=6 bundles per call): asking the model for all of
    a big tender's bundles in one JSON is the same output-size failure that truncated ingest
    and reply parsing. Batches are independent (run concurrently, order-preserved); a batch
    that fails leaves its firms to the deterministic template, so dispatch never fails on
    compose."""
    index: dict[tuple[str, str], tuple[str, str]] = {}
    # Layer 2: DEMO reads the baked DispatchSet fixture; live composes via the model.
    if demo_fixture or not demo_mode():
        batches = [scaffold[i:i + _COMPOSE_BATCH_SIZE] for i in range(0, len(scaffold), _COMPOSE_BATCH_SIZE)]
        for partial in run_calls(lambda b: _compose_batch(b, project_name, demo_fixture, client), batches):
            index.update(partial)
    # Any firm not covered by the model/fixture falls back to a deterministic template.
    return {
        (trade, fid): index.get((trade, fid)) or _template_email(name, trade, project_name)
        for (trade, fid, name, _docs) in scaffold
    }


def _compose_prompt(scaffold: list[tuple[str, str, str, list[str]]], project_name: str) -> str:
    lines = "\n".join(f"- {name} ({fid}) — trade: {trade}" for (trade, fid, name, _d) in scaffold)
    return f"Project: {project_name}\nCompose one RFQ email per firm:\n{lines}"


def build_dispatch(
    shortlist: ShortlistSet,
    approvals: dict[str, list[str]],
    demo_fixture: Optional[str] = None,
    *,
    scope: Optional[ScopePackages] = None,
    project_name: str = "",
    tender: Optional[TenderPackage] = None,
    tender_id: str = "",
    workspace: Optional[Workspace] = None,
    client: Optional[LLMClient] = None,
) -> DispatchSet:
    """Assemble approved bundles. Only approved, shortlisted firms appear; each
    bundle carries only its trade's documents and a composed email; status is set
    to ``approved`` (past the Layer 4 gate).

    ``bundle_doc_refs`` stays the human-readable label list. When ``tender``/
    ``workspace`` are given, ``attachments`` are the routed real files (general docs +
    this trade's docs + the generated SoR sheet) for the live send path (§5)."""
    client = client or LLMClient()
    tender_id = tender_id or project_name

    # Deterministic scaffold: which firms (approved AND shortlisted), which trade docs.
    scaffold: list[tuple[str, str, str, list[str]]] = []
    for trade, firm_ids in approvals.items():
        shortlisted = {c.firm.firm_id: c for c in shortlist.per_trade.get(trade, [])}
        for fid in firm_ids:
            cand = shortlisted.get(fid)
            if cand is None:
                continue  # approved a firm that is not on the shortlist -> skip
            scaffold.append((trade, fid, cand.firm.name, _bundle_docs(trade, scope)))

    emails = _compose_emails(scaffold, project_name, demo_fixture, client)

    # Attachments are per-trade: assemble once per trade (the SoR sheet is generated
    # once), then shared by every firm approved for that trade.
    attachments_by_trade: dict[str, list[BundleAttachment]] = {}
    for trade in {t for (t, _f, _n, _d) in scaffold}:
        attachments_by_trade[trade] = build_attachments(
            trade, scope, tender, project_name=project_name, tender_id=tender_id, workspace=workspace
        )

    # A stable correlation ref goes in every subject so an inbound reply resolves
    # deterministically; the mapping is recorded to the registry on the live path.
    bundles: list[DispatchBundle] = []
    for (trade, fid, name, docs) in scaffold:
        ref = make_ref(tender_id, fid, trade)
        if workspace is not None:
            record_dispatch(workspace, ref, tender_id, fid, trade)
        subject, body = emails[(trade, fid)]
        bundles.append(DispatchBundle(
            firm_id=fid,
            firm_name=name,
            trade=trade,
            bundle_doc_refs=docs,
            attachments=attachments_by_trade.get(trade, []),
            email_subject=subject_with_ref(subject, ref),
            email_body=body,
            status=DispatchStatus.APPROVED,
        ))
    return DispatchSet(bundles=bundles)
