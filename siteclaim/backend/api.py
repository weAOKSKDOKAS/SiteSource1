"""SiteSource HTTP API — thin driver over the five-stage pipeline.

One POST per stage, plus the Excel download and the demo loaders. The chassis
pattern is preserved: ``.env`` is auto-loaded before anything reads env, DEMO_MODE
is respected end-to-end (the routes call the same stage functions the offline runner
does), CORS is permissive for local dev, and ``/health`` reports ``demo_mode``.

Phase A live-engine routes sit alongside the demo ones: ``/ingest-upload`` reads a
real tender and persists the originals; ``/dispatch`` can route real attachments and
send real email (gated — see ``mailer``); ``/level-upload`` catches a subcontractor's
returned Schedule of Rates; ``/contacts`` exposes the address book.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # before anything reads env

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from pipeline.documents import extract_document, to_images  # noqa: E402
from pipeline.llm_client import demo_mode  # noqa: E402
from pipeline.stage_01_ingest.classify import classify_documents  # noqa: E402
from pipeline.stage_01_ingest.ingest import ingest_tender  # noqa: E402
from pipeline.stage_02_shortlist.shortlist import shortlist  # noqa: E402
from pipeline.stage_03_dispatch.dispatch import build_dispatch  # noqa: E402
from pipeline.stage_03_dispatch.mailer import send_bundles  # noqa: E402
from pipeline.stage_04_level.export_xlsx import OUT_PATH, export_leveling_xlsx  # noqa: E402
from pipeline.stage_04_level.level import level_bids, load_demo_replies, merge_replies, parse_bid_reply  # noqa: E402
from pipeline.stage_04_level.reply_xlsx import is_xlsx_upload, parse_sor_xlsx  # noqa: E402
from pipeline.stage_05_recommend.recommend import recommend  # noqa: E402
from pipeline.workspace import Workspace, tender_slug  # noqa: E402
from pipeline import reply_loop  # noqa: E402
from pipeline.benchmark import actuals_xlsx, matcher, tender_snapshot  # noqa: E402
from pipeline.benchmark.eos_reason import EOS_REASON_FIXTURE, extract_reason_candidates  # noqa: E402
from pipeline.routing.recommend import ROUTE_SUGGESTIONS_FIXTURE, recommend_routes  # noqa: E402
from pipeline.routing.signal import package_signal  # noqa: E402
from db import benchmark as bench, estimate as est, project as uproject, refresh, routing, store  # noqa: E402
from schemas.routing import (  # noqa: E402
    ROUTES,
    SUBLET,
    SELF_PERFORM,
    AnalyzeRequest,
    ConfirmRoutesRequest,
    RouteDecisionResult,
    RoutePackage,
    RouteProposal,
)
from schemas.benchmark import (  # noqa: E402
    ActualItem,
    ActualsUploadResponse,
    BenchmarkSummary,
    ConfirmMatchesRequest,
    MatchPair,
    MatchProposal,
    Project,
    ProjectCreate,
    ProjectEOS,
    ProjectUpdate,
    ReasonCandidate,
    ReasonCode,
    ReasonRequest,
    TenderItem,
    TenderUploadResponse,
    VarianceReasonSuggestions,
    VarianceRecord,
)
from schemas.estimate import (  # noqa: E402
    EstimateCheckRequest,
    EstimateCheckResult,
    EstimateDraftResult,
    EstimateFinding,
    EstimateItem,
    EstimateItemsRequest,
    EstimateItemUpdate,
    EstimateProject,
    EstimateProjectCreate,
    EstimateProjectUpdate,
    FromPackageRequest,
    LetterOfOffer,
    RatePrecedent,
    RateSuggestions,
    ToBenchmarkResult,
)
from pipeline.estimate.checks import ESTIMATE_CHECK_FIXTURE, check_estimate  # noqa: E402
from pipeline.estimate.draft import ESTIMATE_DRAFT_FIXTURE, draft_estimate  # noqa: E402
from pipeline.estimate.letter import LETTER_FIXTURE, draft_letter  # noqa: E402
from pipeline.estimate.rates import suggest_rates  # noqa: E402
from schemas.project import DashboardPackage, ProjectDashboard, ProjectSummary  # noqa: E402
from schemas.models import (  # noqa: E402
    BidReply,
    Contact,
    DispatchSet,
    DocType,
    FirmProfile,
    FirmsPage,
    LevelledBid,
    Recommendation,
    ScopePackages,
    ShortlistSet,
    TenderDocument,
    TenderPackage,
)

# Canonical demo fixtures (only consulted when DEMO_MODE is on).
SCOPE_FIXTURE = "cases/clean/scope_packages.json"
DISPATCH_FIXTURE = "cases/clean/dispatch.json"
REPLIES_FIXTURE = "cases/messy/bid_replies.json"
RATIONALE_FIXTURE = "cases/clean/recommendation_rationale.json"
INBOUND_REPLY_FIXTURE = "cases/inbound/reply.json"          # DEMO parse of an inbound reply
INBOUND_FALLBACK_FIXTURE = "cases/inbound/fallback_match.json"  # DEMO AI fallback verdict

app = FastAPI(
    title="SiteSource API",
    version="0.3.0",
    description="AI subcontractor-sourcing and bid-leveling platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict[str, object]:
    """Liveness probe; reports whether the server is offline (DEMO_MODE)."""
    return {"status": "ok", "demo_mode": demo_mode()}


@app.get("/coverage")
def coverage() -> dict:
    """Database-coverage figures (read live from the DB) for the screening line:
    total firms, firms carrying public flags, flags by type, distinct trades, and
    how many carry an assessable closeout record."""
    conn = store.get_connection()
    try:
        return store.coverage(conn)
    finally:
        conn.close()


@app.get("/contacts", response_model=list[Contact])
def contacts() -> list[Contact]:
    """The subcontractor address book (Phase A) — where each trade's RFQ is sent."""
    conn = store.get_connection()
    try:
        return store.all_contacts(conn)
    finally:
        conn.close()


_FIRMS_PAGE_SIZES = {10, 25, 50, 100}


@app.get("/firms", response_model=FirmsPage)
def get_firms(q: str = "", trade: str = "", limit: int = 25, offset: int = 0) -> FirmsPage:
    """Browse the proprietary firm database — the **real-provenance register firms only** (the
    same 140/46 population ``/coverage`` counts). Illustrative demo firms and partner-archive
    firms never appear. Optional name substring ``q`` and canonical ``trade`` filter; paginated
    (``limit`` in {10,25,50,100}, default 25). Pure DB read — offline, no LLM."""
    lim = limit if limit in _FIRMS_PAGE_SIZES else 25
    off = max(0, offset)
    conn = store.get_connection()
    try:
        items, total = store.firms_page(conn, q=q, trade=trade, limit=lim, offset=off)
    finally:
        conn.close()
    return FirmsPage(items=items, total=total, limit=lim, offset=off)


@app.get("/firms/{firm_id}", response_model=FirmProfile)
def get_firm(firm_id: str) -> FirmProfile:
    """The full fused profile for one firm (registration, trades, closeout, public flags with
    their issuing source/reference, award history). 404 if unknown."""
    conn = store.get_connection()
    try:
        firm = store.firm_profile(conn, firm_id)
    finally:
        conn.close()
    if firm is None:
        raise HTTPException(status_code=404, detail=f"No firm {firm_id}.")
    return firm


# ---------------------------------------------------------------------------
# Refresh — semi-automated public-data ingest with a human-confirm gate (Phase C)
# ---------------------------------------------------------------------------
class PublicFlagIn(BaseModel):
    signal_type: str
    label: str
    date: str | None = None
    source: str | None = None
    reference: str | None = None


class PublicRecordIn(BaseModel):
    model_config = {"extra": "ignore"}  # tolerate scrape-only keys (confidence, sources_used, …)
    firm_id: str
    name_en: str | None = None
    name_zh: str | None = None
    registered_grade: str | None = None
    value_band: str | None = None
    registers: list[str] = Field(default_factory=list)
    trades: list[str] = Field(default_factory=list)
    public_flags: list[PublicFlagIn] = Field(default_factory=list)
    award_history: list[dict] = Field(default_factory=list)


class StageRequest(BaseModel):
    records: list[PublicRecordIn] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    batch_id: str | None = None
    firm_ids: list[str] | None = None


def _refresh_write_guard() -> None:
    if demo_mode():
        raise HTTPException(status_code=409, detail="Refresh is disabled in DEMO_MODE.")


def _require_live_target(conn) -> None:
    """Refresh writes only ever land in a clean live-profile database — never the
    committed demo/pitch DB. Guarding by the target's profile (not just the DEMO_MODE
    flag) means a live run that forgets to set SITESOURCE_DB cannot mutate the demo DB."""
    if store._meta(conn, "profile", "demo") != "live":
        raise HTTPException(
            status_code=409,
            detail="Refresh applies only to a live-profile database; point SITESOURCE_DB at sitesource_live.db.",
        )


@app.post("/refresh/stage")
def post_refresh_stage(req: StageRequest) -> dict:
    """Stage new public records/flags for human review (nothing lands until confirmed)."""
    _refresh_write_guard()
    conn = store.get_connection()
    try:
        _require_live_target(conn)
        return refresh.stage_records(conn, [r.model_dump() for r in req.records])
    finally:
        conn.close()


@app.get("/refresh/pending")
def get_refresh_pending() -> list[dict]:
    """What is waiting for a human to confirm or reject."""
    conn = store.get_connection()
    try:
        return refresh.list_pending(conn)
    finally:
        conn.close()


@app.post("/refresh/confirm")
def post_refresh_confirm(req: ConfirmRequest) -> dict:
    """Apply staged records/flags into the live database (the human gate)."""
    _refresh_write_guard()
    conn = store.get_connection()
    try:
        _require_live_target(conn)
        return refresh.confirm_pending(conn, batch_id=req.batch_id, firm_ids=req.firm_ids)
    finally:
        conn.close()


@app.post("/refresh/reject")
def post_refresh_reject(req: ConfirmRequest) -> dict:
    """Reject staged records/flags (kept as an audit trail, never applied)."""
    _refresh_write_guard()
    conn = store.get_connection()
    try:
        _require_live_target(conn)
        return refresh.reject_pending(conn, batch_id=req.batch_id, firm_ids=req.firm_ids)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Demo loaders — the seeded tender and replies the wizard starts from
# ---------------------------------------------------------------------------
def _demo_tender() -> TenderPackage:
    docs = [
        TenderDocument(doc_type=DocType.METHOD_OF_MEASUREMENT, filename="method_of_measurement.pdf"),
        TenderDocument(doc_type=DocType.PARTICULAR_SPECIFICATION, filename="particular_specification.pdf"),
        TenderDocument(doc_type=DocType.TENDER_ADDENDUM, filename="tender_addendum.pdf"),
        TenderDocument(doc_type=DocType.SCHEDULE_OF_RATES, filename="schedule_of_rates.pdf"),
    ]
    return TenderPackage(
        project_name="Kwun Tong Commercial Tower — Category-A Office Fit-out",
        description="Cat-A office fit-out across 12 floors.",
        documents=docs,
    )


# Three deterministic demo scenarios — same tender + seeded DB, different bid
# replies (and focus trade), each isolating one catch. All reproduce identically.
_DEMO_CASES = {
    # The golden walkthrough — the whole product in one confirm-routing. The Kwun Tong
    # 4-package tender routes TWO trades to SUBLET (electrical + mechanical & plumbing —
    # priced replies below, with the risk catch in the mechanical section) and TWO to
    # SELF-PERFORM (fire services + joinery — their routed estimates open with baked rate
    # precedent from the demo benchmark corpus). It reuses the verified two-trade sublet
    # bundle (two sections, the flagged-cheapest mechanical bidder) for the sourcing half,
    # so the golden path needs no separate reply fixture; the self-perform half is the
    # seeded corpus (db/golden_demo.py).
    "golden": {
        "name": "Golden — the full walkthrough",
        "blurb": "Full walkthrough — two trades sourced, two self-performed. Route electrical and mechanical & plumbing to sublet for two leveling sections and two awards (the cheapest mechanical bidder carries an unpaid adjudication — recommended against despite price); route fire services and joinery to self-perform and price each line against live rate precedent from the benchmark corpus.",
        "hero_trade": "electrical",
        "replies_fixture": "cases/scenarios/two_trade_replies.json",
        "rationale_fixture": "cases/scenarios/two_trade_rationale_electrical.json",
        "rationale_fixtures": {
            "electrical": "cases/scenarios/two_trade_rationale_electrical.json",
            "mechanical_plumbing": "cases/scenarios/two_trade_rationale_mechanical.json",
        },
    },
    "hero": {
        "name": "Hero — the cheapest bidder, flagged",
        "blurb": "Electrical: the cheapest, best-matching bidder looks clean on the bid sheet but carries an active winding-up petition and two safety prosecutions — recommended against despite the lowest price.",
        "hero_trade": "electrical",
        "replies_fixture": "cases/scenarios/hero_replies.json",
        "rationale_fixture": "cases/scenarios/hero_rationale.json",
    },
    "messy": {
        "name": "Messy — leveling changes the ranking",
        "blurb": "Electrical: a reply hides an understated line, an unpriced provisional sum, and an exclusion; leveling corrects the total so the cheapest clean bid changes.",
        "hero_trade": "electrical",
        "replies_fixture": REPLIES_FIXTURE,
        "rationale_fixture": RATIONALE_FIXTURE,
    },
    # Per-section flow (Prompt 1): priced replies for TWO trades, so routing both to
    # sublet yields two leveling sections and two awards — and the risk catch fires in
    # the second section too (the cheapest mechanical bidder carries an unpaid
    # adjudication, a fatal flag).
    "two_trade": {
        "name": "Two-trade — electrical + mechanical sourced",
        "blurb": "Route electrical AND mechanical & plumbing to sublet: two leveling sections and two risk-adjusted awards. The cheapest mechanical bidder carries an unpaid adjudication — recommended against despite price.",
        "hero_trade": "electrical",
        "replies_fixture": "cases/scenarios/two_trade_replies.json",
        "rationale_fixture": "cases/scenarios/two_trade_rationale_electrical.json",
        "rationale_fixtures": {
            "electrical": "cases/scenarios/two_trade_rationale_electrical.json",
            "mechanical_plumbing": "cases/scenarios/two_trade_rationale_mechanical.json",
        },
    },
}


class DemoCaseSummary(BaseModel):
    id: str
    name: str
    hero_trade: str
    blurb: str


class DemoCase(DemoCaseSummary):
    tender: TenderPackage
    replies: list[BidReply]
    rationale_fixture: str
    # Per-trade rationale fixtures for the per-section recommend path. Single-trade
    # scenarios carry {hero_trade: rationale_fixture}; a multi-trade scenario names one
    # fixture per sourced trade. A trade with no entry narrates via the offline template.
    rationale_fixtures: dict[str, str] = Field(default_factory=dict)


@app.get("/demo/cases", response_model=list[DemoCaseSummary])
def demo_cases() -> list[DemoCaseSummary]:
    return [
        DemoCaseSummary(id=cid, name=m["name"], hero_trade=m["hero_trade"], blurb=m["blurb"])
        for cid, m in _DEMO_CASES.items()
    ]


@app.get("/demo/{case_id}", response_model=DemoCase)
def demo_case(case_id: str) -> DemoCase:
    m = _DEMO_CASES.get(case_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"Unknown demo case {case_id!r}.")
    return DemoCase(
        id=case_id,
        name=m["name"],
        hero_trade=m["hero_trade"],
        blurb=m["blurb"],
        tender=_demo_tender(),
        replies=load_demo_replies(m["replies_fixture"]),
        rationale_fixture=m["rationale_fixture"],
        rationale_fixtures=m.get("rationale_fixtures") or {m["hero_trade"]: m["rationale_fixture"]},
    )


# ---------------------------------------------------------------------------
# Stage 01 — ingest
# ---------------------------------------------------------------------------
class IngestRequest(BaseModel):
    tender: TenderPackage
    demo_fixture: str | None = SCOPE_FIXTURE


class IngestUploadResponse(BaseModel):
    """The scope split plus the trade-tagged tender, so the client can hand the tagged
    tender to ``/dispatch`` for per-trade document routing. ``tender_slug`` is the
    server-derived slug the client uses to poll ``/tender/{slug}/replies`` (so it never
    re-implements the slug logic)."""

    scope: ScopePackages
    tender: TenderPackage
    tender_slug: str = ""


@app.post("/ingest", response_model=ScopePackages)
def post_ingest(req: IngestRequest) -> ScopePackages:
    return ingest_tender(req.tender, demo_fixture=req.demo_fixture)


DEFAULT_UPLOAD_PROJECT_NAME = "Uploaded tender"  # the /ingest-upload form default


@app.post("/ingest-upload", response_model=IngestUploadResponse)
def post_ingest_upload(
    files: list[UploadFile] = File(...),
    project_name: str = Form(DEFAULT_UPLOAD_PROJECT_NAME),
) -> IngestUploadResponse:
    """Ingest live tender documents (PDF/image) and return the scope split plus the
    trade-tagged tender. In DEMO_MODE the upload is accepted but the baked scope fixture
    is returned and the tender is left untagged (no model, no network). Live, each
    original is persisted to the tender workspace so dispatch can attach the real files;
    the pages are rasterised for the vision model; and each document is classified by
    trade (Layer 2) so its ``trades`` route the right whole originals at dispatch.

    The tender's final name is decided once, after the split: an explicit form
    ``project_name`` always wins, but when the operator left the default the real
    contract name the split extracts (``scope.project_name``) is adopted — and the
    originals are saved only then, so the workspace slug, the ref registry (keyed off
    this name at dispatch), and the returned scope/tender all agree on one name.

    Sync handler: FastAPI runs it in a threadpool, so the blocking pymupdf render and the
    sequential LLM calls below never stall the event loop (``/health`` keeps answering
    during a long ingest)."""
    tender = TenderPackage(
        project_name=project_name,
        documents=[TenderDocument(doc_type=DocType.SCHEDULE_OF_RATES, filename=f.filename or "upload") for f in files],
    )
    if demo_mode():
        return IngestUploadResponse(
            scope=ingest_tender(tender, demo_fixture=SCOPE_FIXTURE), tender=tender,
            tender_slug=tender_slug(project_name),
        )

    workspace = Workspace()
    originals: list[tuple[str, bytes]] = []  # saved late — under the final name (below)
    per_doc_images: list[list[str]] = []    # first pages for classification — scanned docs only
    doc_texts: list[str] = []               # extracted text layer, per document (index-aligned)
    doc_page_images: list[list[str]] = []   # scanned-page renders, per document
    for upload in files:
        data = upload.file.read()
        originals.append((upload.filename or "upload", data))
        try:
            # Text-first: extract each page's text layer, rendering a page to an image only
            # when it is scanned.
            text, page_images = extract_document(data, upload.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        doc_texts.append(text)
        doc_page_images.append(page_images)
        # Classification is text-first too: a doc with a text layer is classified from its
        # text (no render); only a scanned doc needs pages, and we reuse the ones already
        # rendered above rather than rasterising again.
        per_doc_images.append([] if text.strip() else page_images[:2])

    # Classify each document FIRST (kind + trade routing) so item extraction can be gated
    # to the Schedule(s) of Rates: a Method of Measurement lists item-like rows that are
    # NOT priceable, and extracting over every document's text yielded phantom sor_items
    # live. Only schedule_of_rates text/images feed the priced-item split; every other
    # document informs the trade split as bounded context but never produces a line item.
    tagged = classify_documents(tender, per_doc_images, per_doc_text=doc_texts)
    sor_text_parts: list[str] = []
    context_parts: list[str] = []
    scope_images: list[str] = []
    for doc, text, page_images in zip(tagged.documents, doc_texts, doc_page_images):
        label = doc.filename or "document"
        if doc.doc_type == DocType.SCHEDULE_OF_RATES:
            if text.strip():
                sor_text_parts.append(f"=== {label} ===\n{text}")
            scope_images += page_images  # scanned SoR pages carry priced rows -> vision
        elif text.strip():
            context_parts.append(f"=== {label} ===\n{text}")
    scope = ingest_tender(
        tender, images=scope_images,
        doc_text="\n\n".join(sor_text_parts), context_text="\n\n".join(context_parts),
    )

    # Adopt the extracted contract name when the form was left at its default (the split
    # reads the real name off the documents, e.g. "Contract No. GE/2026/14 — ..."); an
    # explicit operator value is kept. Either way scope, tender, and the saved originals
    # carry the SAME final name, so dispatch attaches from — and the ref registry keys
    # off — the same workspace slug.
    extracted = scope.project_name.strip()
    final_name = project_name
    if project_name == DEFAULT_UPLOAD_PROJECT_NAME and extracted and extracted != DEFAULT_UPLOAD_PROJECT_NAME:
        final_name = extracted
    for filename, data in originals:
        workspace.save_upload(final_name, filename, data)

    scope = scope.model_copy(update={"project_name": final_name})
    tagged = tagged.model_copy(update={"project_name": final_name})
    return IngestUploadResponse(scope=scope, tender=tagged, tender_slug=tender_slug(final_name))


# ---------------------------------------------------------------------------
# Stage 02 — shortlist
# ---------------------------------------------------------------------------
class ShortlistRequest(BaseModel):
    scope: ScopePackages
    include_public: bool = False  # live engine sets True; demo/default stays assessed-firm
    k: int | None = None  # cap per trade's ranked list; None (demo/default) returns all


@app.post("/shortlist", response_model=ShortlistSet)
def post_shortlist(req: ShortlistRequest) -> ShortlistSet:
    return shortlist(req.scope, include_public=req.include_public, k=req.k)


# ---------------------------------------------------------------------------
# Stage 03 — dispatch
# ---------------------------------------------------------------------------
class DraftOverride(BaseModel):
    """A human-edited enquiry draft for one (trade, firm). The approve-before-send gate
    lets the person edit the composed subject/body; the outbox (and, later, the real
    send) carries EXACTLY the edited text. An empty field keeps the composed value."""

    trade: str
    firm_id: str
    subject: str = ""
    body: str = ""


class DispatchRequest(BaseModel):
    shortlist: ShortlistSet
    approvals: dict[str, list[str]] = Field(default_factory=dict)
    scope: ScopePackages | None = None
    tender: TenderPackage | None = None  # live: routes real attachments by document
    project_name: str = ""
    send: bool = False
    dry_run: bool = False  # force the mock outbox even when SMTP is configured
    demo_fixture: str | None = DISPATCH_FIXTURE
    draft_overrides: list[DraftOverride] = Field(default_factory=list)


def _apply_draft_overrides(dispatch: DispatchSet, overrides: list[DraftOverride]) -> DispatchSet:
    """Replace composed subject/body with the human's edits, matched by (trade, firm)."""
    if not overrides:
        return dispatch
    by_key = {(o.trade, o.firm_id): o for o in overrides}
    bundles = []
    for bundle in dispatch.bundles:
        edit = by_key.get((bundle.trade, bundle.firm_id))
        if edit is not None:
            bundle = bundle.model_copy(update={
                "email_subject": edit.subject or bundle.email_subject,
                "email_body": edit.body or bundle.email_body,
            })
        bundles.append(bundle)
    return DispatchSet(bundles=bundles)


@app.post("/dispatch", response_model=DispatchSet)
def post_dispatch(req: DispatchRequest) -> DispatchSet:
    # Live runs get a workspace so the SoR sheets are generated and real originals
    # (persisted at ingest-upload) are attached; the demo describes bundles only.
    workspace = None if demo_mode() else Workspace()
    dispatch = build_dispatch(
        req.shortlist, req.approvals, demo_fixture=req.demo_fixture,
        scope=req.scope, project_name=req.project_name,
        tender=req.tender, tender_id=req.project_name, workspace=workspace,
    )
    dispatch = _apply_draft_overrides(dispatch, req.draft_overrides)
    return send_bundles(dispatch, dry_run=req.dry_run) if req.send else dispatch


# ---------------------------------------------------------------------------
# Stage 04 — level (+ Excel export)
# ---------------------------------------------------------------------------
class LevelRequest(BaseModel):
    replies: list[BidReply] = Field(default_factory=list)
    scope: ScopePackages | None = None
    demo_fixture: str | None = REPLIES_FIXTURE


@app.post("/level", response_model=list[LevelledBid])
def post_level(req: LevelRequest) -> list[LevelledBid]:
    # The empty-set fixture fallback is a DEMO convenience only — on a live run an empty
    # replies set must never fabricate the scenario bids (no demo leak into a live run).
    replies = req.replies or (load_demo_replies(req.demo_fixture) if demo_mode() else [])
    levelled = level_bids(replies, req.scope)
    export_leveling_xlsx(levelled, replies, path=OUT_PATH,
                         project_name=req.scope.project_name if req.scope else "")
    return levelled


class LevelSection(BaseModel):
    """One sublet trade's leveling — that trade's bids only, never mixed."""

    trade: str
    levelled: list[LevelledBid] = Field(default_factory=list)


class LevelAllResponse(BaseModel):
    sections: list[LevelSection] = Field(default_factory=list)


@app.post("/level-all", response_model=LevelAllResponse)
def post_level_all(req: LevelRequest) -> LevelAllResponse:
    """Per-section leveling: group the replies by their ``trade`` and level each trade
    only against its own bids (the peer item reference never crosses trades). Returns one
    section per trade, in first-seen reply order, and refreshes the downloadable Excel as
    a multi-sheet workbook (one sheet per trade). Sync handler — pure Layer-1 math."""
    # The empty-set fixture fallback is a DEMO convenience only — a live run with zero
    # replies renders the awaiting state and must never receive the scenario bids.
    replies = req.replies or (load_demo_replies(req.demo_fixture) if demo_mode() else [])
    trades: list[str] = []
    for reply in replies:
        if reply.trade not in trades:
            trades.append(reply.trade)
    sections = [
        LevelSection(trade=trade, levelled=level_bids([r for r in replies if r.trade == trade], req.scope))
        for trade in trades
    ]
    flat = [b for s in sections for b in s.levelled]
    export_leveling_xlsx(flat, replies, path=OUT_PATH,
                         project_name=req.scope.project_name if req.scope else "")
    return LevelAllResponse(sections=sections)


def _read_reply_uploads(files: list[UploadFile]) -> tuple[list[BidReply], list[str]]:
    """Split reply uploads into deterministically-parsed SoR sheets and rasterised pages.

    An xlsx reply is our own dispatched SoR sheet returned with the Rate column filled —
    we authored the format, so it parses with openpyxl and NO model call
    (``parse_sor_xlsx``). PDFs and images keep the existing vision/text parse path.

    Sync (called from sync route handlers): reads the spooled upload directly so the
    blocking render/parse below runs in FastAPI's threadpool, not on the event loop."""
    sheets: list[BidReply] = []
    images: list[str] = []
    for upload in files:
        data = upload.file.read()
        try:
            if is_xlsx_upload(upload.filename, upload.content_type):
                sheets.append(parse_sor_xlsx(data))
            else:
                images += to_images(data, upload.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sheets, images


def _parse_reply(
    sheets: list[BidReply], images: list[str], *, firm_id: str, trade: str,
    demo_fixture: str | None = None,
) -> BidReply:
    """One BidReply from the uploads. Sheets are already parsed (deterministic); the
    model is consulted only when there are pages for it to read (or for the DEMO
    fixture). Identity is forced by ``merge_replies`` — the ref/form stays
    authoritative on every path."""
    if sheets and not images:
        return merge_replies(sheets, firm_id, trade)  # pure xlsx reply -> no LLM at all
    parsed = parse_bid_reply(firm_id=firm_id, trade=trade, images=images, demo_fixture=demo_fixture)
    return merge_replies(sheets + [parsed], firm_id, trade) if sheets else parsed


@app.post("/level-upload", response_model=list[LevelledBid])
def post_level_upload(
    files: list[UploadFile] = File(...),
    firm_id: str = Form(...),
    trade: str = Form(...),
) -> list[LevelledBid]:
    """Inbound channel (Phase A): the operator drops a subcontractor's returned
    Schedule of Rates here. In DEMO_MODE the baked levelled comparison is returned;
    live, an xlsx (our returned SoR sheet) is parsed deterministically and a PDF/image
    is parsed by Layer 2; Layer 1 levels the result.

    Sync handler (threadpool): the blocking parse/level below never stalls the loop."""
    if demo_mode():
        levelled = level_bids([], demo_fixture=REPLIES_FIXTURE)
        export_leveling_xlsx(levelled, load_demo_replies(REPLIES_FIXTURE), path=OUT_PATH)
        return levelled

    sheets, images = _read_reply_uploads(files)
    reply = _parse_reply(sheets, images, firm_id=firm_id, trade=trade)
    levelled = level_bids([reply])
    export_leveling_xlsx(levelled, [reply], path=OUT_PATH)
    return levelled


class InboundReplyResponse(BaseModel):
    """The outcome of an inbound reply: matched onto a tender's growing comparison, or
    unmatched (needs manual assignment). ``comparison`` is the re-leveled set of every
    reply received for the tender so far."""

    status: str  # "matched" | "unmatched"
    detail: str = ""
    tender_id: str = ""
    firm_id: str = ""
    trade: str = ""
    reply_count: int = 0
    comparison: list[LevelledBid] = Field(default_factory=list)


@app.post("/inbound-reply", response_model=InboundReplyResponse)
def post_inbound_reply(
    files: list[UploadFile] = File(...),
    ref: str = Form(""),
) -> InboundReplyResponse:
    """Close the reply loop (Phase A): n8n posts a subcontractor's reply attachment plus
    the correlation ref it read from the subject. The ref resolves the reply to its
    tender/firm/trade deterministically (AI matching is only a fallback for a ref-less
    reply); the reply is parsed, accumulated onto that tender, re-leveled, and the
    comparison xlsx regenerated with the existing leveling/export code. This fills the
    comparison only — a human still awards.

    Sync handler (threadpool): the blocking parse/level below never stalls the loop."""
    workspace = Workspace()

    # Read the attachment on the live path: an xlsx (our returned SoR sheet) parses
    # deterministically, a PDF/image is rasterised for parse + fallback; DEMO uses fixtures.
    sheets: list[BidReply] = []
    images: list[str] = []
    if not demo_mode():
        sheets, images = _read_reply_uploads(files)

    resolved = reply_loop.resolve_ref(workspace, ref)  # primary: deterministic
    if resolved is None:  # secondary: best-effort AI, only for a ref-less reply
        resolved = reply_loop.fallback_match(
            images, workspace, demo_fixture=INBOUND_FALLBACK_FIXTURE if demo_mode() else None
        )
    if resolved is None:
        return InboundReplyResponse(status="unmatched", detail="unmatched — needs manual assignment")

    tender_id, firm_id, trade = resolved["tender_id"], resolved["firm_id"], resolved["trade"]
    parsed = _parse_reply(
        sheets, images, firm_id=firm_id, trade=trade,
        demo_fixture=INBOUND_REPLY_FIXTURE if demo_mode() else None,
    )
    # The ref is authoritative for identity; the parse supplies the priced content.
    reply = parsed.model_copy(update={"firm_id": firm_id, "trade": trade})

    replies = reply_loop.accumulate_reply(workspace, tender_id, reply)
    levelled = level_bids(replies)
    export_leveling_xlsx(levelled, replies, path=reply_loop.comparison_path(workspace, tender_id), project_name=tender_id)
    export_leveling_xlsx(levelled, replies, path=OUT_PATH, project_name=tender_id)  # refresh the /leveling.xlsx download
    return InboundReplyResponse(
        status="matched", tender_id=tender_id, firm_id=firm_id, trade=trade,
        reply_count=len(replies), comparison=levelled,
    )


@app.get("/leveling.xlsx")
def get_leveling_xlsx() -> FileResponse:
    if not OUT_PATH.is_file():
        replies = load_demo_replies(REPLIES_FIXTURE)
        export_leveling_xlsx(level_bids(replies), replies, path=OUT_PATH)
    return FileResponse(
        OUT_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="leveling.xlsx",
    )


# ---------------------------------------------------------------------------
# Reply visibility — which replies have landed for a tender (Phase A operator view)
# ---------------------------------------------------------------------------
class TenderReplyInfo(BaseModel):
    firm_id: str
    trade: str
    line_items: int
    claimed_total: float | None = None


class TenderRepliesResponse(BaseModel):
    """The accumulator/registry state for one tender: who has replied (with item counts),
    when the latest reply landed, who is still outstanding, and whether the comparison
    xlsx is ready to download."""

    tender_slug: str
    reply_count: int
    last_received: str | None = None
    replies: list[TenderReplyInfo] = Field(default_factory=list)
    outstanding: list[dict] = Field(default_factory=list)  # dispatched, not yet replied
    comparison_available: bool = False


@app.get("/tender/{slug}/replies", response_model=TenderRepliesResponse)
def get_tender_replies(slug: str) -> TenderRepliesResponse:
    """Which replies have accumulated for a tender (keyed by slug). Read-only; the
    frontend refreshes it manually (no polling loop). The path param is re-slugified so
    either the slug or a slash-free tender name resolves to the same tender."""
    workspace = Workspace()
    canonical = tender_slug(slug)
    replies = reply_loop.tender_replies(workspace, canonical)
    replied = {(r.firm_id, r.trade) for r in replies}
    outstanding = [
        {"firm_id": d["firm_id"], "trade": d["trade"]}
        for d in reply_loop.outstanding_dispatches(workspace)
        if tender_slug(d["tender_id"]) == canonical and (d["firm_id"], d["trade"]) not in replied
    ]
    return TenderRepliesResponse(
        tender_slug=canonical,
        reply_count=len(replies),
        last_received=reply_loop.replies_last_received(workspace, canonical),
        replies=[
            TenderReplyInfo(firm_id=r.firm_id, trade=r.trade, line_items=len(r.line_items), claimed_total=r.claimed_total)
            for r in replies
        ],
        outstanding=outstanding,
        comparison_available=reply_loop.comparison_file(workspace, canonical).is_file(),
    )


@app.get("/tender/{slug}/comparison.xlsx")
def get_tender_comparison(slug: str) -> FileResponse:
    """Download this tender's accumulating leveled comparison xlsx (404 until a reply lands)."""
    comp = reply_loop.comparison_file(Workspace(), tender_slug(slug))
    if not comp.is_file():
        raise HTTPException(status_code=404, detail="No comparison for this tender yet.")
    return FileResponse(
        comp,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"comparison-{tender_slug(slug)}.xlsx",
    )


# ---------------------------------------------------------------------------
# Stage 05 — recommend
# ---------------------------------------------------------------------------
class RecommendRequest(BaseModel):
    levelled: list[LevelledBid]
    trade: str
    demo_fixture: str | None = RATIONALE_FIXTURE


@app.post("/recommend", response_model=Recommendation)
def post_recommend(req: RecommendRequest) -> Recommendation:
    return recommend(req.levelled, req.trade, demo_fixture=req.demo_fixture)


class RecommendSection(BaseModel):
    """One sublet trade's risk-adjusted recommendation (its own award downstream)."""

    trade: str
    recommendation: Recommendation


class RecommendAllRequest(BaseModel):
    levelled: list[LevelledBid] = Field(default_factory=list)
    # trade -> rationale fixture (DEMO). A trade with no entry narrates via the offline
    # deterministic template — Layer 2 only ever narrates; the ranking is Layer 1's.
    demo_fixtures: dict[str, str] = Field(default_factory=dict)


class RecommendAllResponse(BaseModel):
    sections: list[RecommendSection] = Field(default_factory=list)


@app.post("/recommend-all", response_model=RecommendAllResponse)
def post_recommend_all(req: RecommendAllRequest) -> RecommendAllResponse:
    """Per-section recommend: one risk-adjusted recommendation per trade present in the
    levelled set (``recommend`` already filters to the trade's own bids). The award for
    each stays a human decision recorded by the UI. Sync handler."""
    trades: list[str] = []
    for bid in req.levelled:
        if bid.trade not in trades:
            trades.append(bid.trade)
    return RecommendAllResponse(
        sections=[
            RecommendSection(
                trade=trade,
                recommendation=recommend(req.levelled, trade, demo_fixture=req.demo_fixtures.get(trade)),
            )
            for trade in trades
        ]
    )


# ===========================================================================
# Benchmark estimator (Phase B1 — the variance spine)
#
# Projects capture the priced tender (tender_items) vs the actual outturn
# (actual_items), item-matched behind a human confirm gate into variance_records.
# Cost data is local SQLite only. Writes target the active DB (SITESOURCE_DB or the
# packaged demo DB) — benchmark CRUD is NOT gated to the live profile (unlike
# /refresh), because the pitch flow must work in demo too; the demo/live separation
# is by projects.provenance ('demo' seeded, 'live' operator-created), and
# /benchmark/summary counts only 'live'. See docs/PRODUCT_ARCHITECTURE_benchmark_estimator.md.
# ===========================================================================
def _require_project(conn, project_id: int) -> dict:
    project = bench.get_project(conn, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No benchmark project {project_id}.")
    return project


@app.post("/benchmark/projects", response_model=Project)
def post_benchmark_project(req: ProjectCreate) -> Project:
    conn = store.get_connection()
    try:
        return Project(**bench.create_project(
            conn, name=req.name, trade=req.trade, client=req.client,
            contract_ref=req.contract_ref, notes=req.notes, source="manual",
        ))
    finally:
        conn.close()


@app.get("/benchmark/projects", response_model=list[Project])
def get_benchmark_projects() -> list[Project]:
    conn = store.get_connection()
    try:
        return [Project(**p) for p in bench.list_projects(conn)]
    finally:
        conn.close()


@app.get("/benchmark/projects/{project_id}", response_model=Project)
def get_benchmark_project(project_id: int) -> Project:
    conn = store.get_connection()
    try:
        return Project(**_require_project(conn, project_id))
    finally:
        conn.close()


@app.patch("/benchmark/projects/{project_id}", response_model=Project)
def patch_benchmark_project(project_id: int, req: ProjectUpdate) -> Project:
    """Update project fields; ``status='closed'`` closes it (stamps closed_at)."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        try:
            updated = bench.update_project(conn, project_id, req.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Project(**updated)
    finally:
        conn.close()


@app.post("/benchmark/{project_id}/tender-upload", response_model=TenderUploadResponse)
def post_benchmark_tender_upload(
    project_id: int,
    files: list[UploadFile] = File(...),
    source_doc: str = Form(""),
) -> TenderUploadResponse:
    """Capture the old priced tender. xlsx (our SoR-sheet layout) parses deterministically
    with openpyxl (rates kept, qty optional); a PDF/image is parsed by the chunked reply
    parser on the live engine (in DEMO_MODE a PDF is rejected — upload the xlsx)."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        items: list[dict] = []
        source = "tender-upload"
        for upload in files:
            data = upload.file.read()
            try:
                if is_xlsx_upload(upload.filename, upload.content_type):
                    items += tender_snapshot.tender_items_from_xlsx(data)
                    source = "tender-xlsx"
                elif demo_mode():
                    raise HTTPException(
                        status_code=400,
                        detail="PDF tender parsing runs on the live engine — upload the SoR-sheet xlsx in DEMO.",
                    )
                else:
                    items += tender_snapshot.tender_items_from_document(data, upload.content_type)
                    source = "tender-pdf"
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        written = bench.replace_tender_items(conn, project_id, items, source=source, source_doc=source_doc)
        return TenderUploadResponse(
            project_id=project_id, source=source, item_count=len(written),
            items=[TenderItem(**it) for it in written],
        )
    finally:
        conn.close()


@app.post("/benchmark/{project_id}/link-scope", response_model=TenderUploadResponse)
def post_benchmark_link_scope(project_id: int, scope: ScopePackages) -> TenderUploadResponse:
    """The compounding loop (§10): capture a tender already run through the sourcing
    pipeline (its ScopePackages) into this project's tender snapshot. Scope items are
    unpriced (rate stays null) — the item_refs seed later matching."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        items = tender_snapshot.tender_items_from_scope(scope)
        written = bench.replace_tender_items(conn, project_id, items, source="pipeline-link", source_doc=scope.project_name)
        return TenderUploadResponse(
            project_id=project_id, source="pipeline-link", item_count=len(written),
            items=[TenderItem(**it) for it in written],
        )
    finally:
        conn.close()


_ACTUALS_PDF_TRUTHY = {"1", "true", "yes", "on"}


def _actuals_pdf_enabled() -> bool:
    """PDF actuals parsing (the chunked LLM fallback) is opt-in — default off, so cost
    data stays deterministic and local unless the operator turns it on."""
    return os.getenv("ACTUALS_PDF_PARSE", "").strip().lower() in _ACTUALS_PDF_TRUTHY


def _eos_pdf_enabled() -> bool:
    """PDF EOS-narrative extraction is opt-in — default off (mirrors ACTUALS_PDF_PARSE).
    The narrative can always be pasted as text; a PDF is only read when explicitly enabled,
    keeping the cost-data-never-leaves posture intact (EOS supplies reasons, not numbers)."""
    return os.getenv("EOS_PDF_PARSE", "").strip().lower() in _ACTUALS_PDF_TRUTHY


@app.get("/benchmark/actuals-template.xlsx")
def get_actuals_template(project: int) -> FileResponse:
    """Download the Final Account template for a project, pre-filled with its tender item
    refs/descriptions so the operator only types the actual numbers."""
    conn = store.get_connection()
    try:
        proj = _require_project(conn, project)
        items = bench.tender_items(conn, project)
    finally:
        conn.close()
    out = Workspace().artifacts_dir(f"benchmark-{project}", create=True) / "actuals-template.xlsx"
    actuals_xlsx.build_actuals_template(proj["name"], items, out)
    return FileResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"actuals-template-{project}.xlsx",
    )


@app.post("/benchmark/{project_id}/actuals-upload", response_model=ActualsUploadResponse)
def post_actuals_upload(
    project_id: int,
    files: list[UploadFile] = File(...),
    source_doc: str = Form(""),
) -> ActualsUploadResponse:
    """Capture the actual outturn. xlsx (the Final Account template) parses
    deterministically with openpyxl — granularity detected per row (item vs section-totals
    vs project-total), tolerant of blank cells and typed-in numbers. A wrong-layout
    workbook returns a clean 400. A PDF is rejected unless ``ACTUALS_PDF_PARSE=true`` (and
    then only on the live engine), keeping cost data deterministic and local by default."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        items: list[dict] = []
        source = "actuals-xlsx"
        for upload in files:
            data = upload.file.read()
            try:
                if is_xlsx_upload(upload.filename, upload.content_type):
                    items += actuals_xlsx.parse_actuals_xlsx(data)
                elif not _actuals_pdf_enabled():
                    raise HTTPException(
                        status_code=400,
                        detail="PDF actuals parsing is off. Use the Final Account xlsx template, "
                        "or set ACTUALS_PDF_PARSE=true to enable the LLM parse fallback.",
                    )
                elif demo_mode():
                    raise HTTPException(
                        status_code=400,
                        detail="PDF actuals parsing runs on the live engine — upload the xlsx template in DEMO.",
                    )
                else:
                    text, images = extract_document(data, upload.content_type)
                    reply = parse_bid_reply(firm_id="", trade="", images=images, doc_text=text)
                    items += [{
                        "item_ref": li.item_ref, "description": li.description or "", "unit": li.unit or "",
                        "qty": li.qty, "rate": li.rate, "amount": li.amount, "section": "", "granularity": "item",
                    } for li in reply.line_items]
                    source = "actuals-pdf"
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        written = bench.replace_actual_items(conn, project_id, items, source=source, source_doc=source_doc)
        granularities = sorted({it["granularity"] for it in written})
        return ActualsUploadResponse(
            project_id=project_id, source=source, item_count=len(written),
            granularities=granularities, items=[ActualItem(**it) for it in written],
        )
    finally:
        conn.close()


# -- EOS narrative (Phase 2) — the field account behind the variances -----------------
@app.post("/benchmark/{project_id}/eos-upload", response_model=ProjectEOS)
def post_eos_upload(
    project_id: int,
    files: list[UploadFile] = File(default=[]),
    narrative: str = Form(""),
    summary: str = Form(""),
    source_doc: str = Form(""),
) -> ProjectEOS:
    """Attach the project's End-of-Site (EOS) narrative — the field account of WHY prices
    moved between tender and outturn. Narrative-only: it supplies reasons, never numbers, so
    the cost-data posture is untouched. Paste the narrative as text (the default, deterministic,
    offline path), or upload the EOS PDF when ``EOS_PDF_PARSE=true`` (its text layer is
    extracted deterministically; images are noted, not parsed for figures). One report per
    project — a re-upload replaces. The reason is still written only by the human confirm gate."""
    conn = store.get_connection()
    try:
        project = _require_project(conn, project_id)
        text = (narrative or "").strip()
        has_images = False
        doc = source_doc.strip()
        for upload in files:
            data = upload.file.read()
            if not data:
                continue
            if not _eos_pdf_enabled():
                raise HTTPException(
                    status_code=400,
                    detail="EOS file parsing is off. Paste the narrative text, or set "
                    "EOS_PDF_PARSE=true to extract the EOS PDF's text layer.",
                )
            if demo_mode():
                raise HTTPException(
                    status_code=400,
                    detail="EOS PDF extraction runs on the live engine — paste the narrative text in DEMO.",
                )
            try:
                extracted, images = extract_document(data, upload.content_type)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            text = (text + "\n\n" + extracted).strip() if text else extracted.strip()
            has_images = has_images or bool(images)
            doc = doc or (upload.filename or "")
        if not text:
            raise HTTPException(
                status_code=400,
                detail="No EOS narrative provided. Paste the narrative text or upload the EOS PDF "
                "(with EOS_PDF_PARSE=true).",
            )
        # An EOS on a demo project stays 'demo' so the fictional narrative never reads as live.
        stored = bench.attach_eos(
            conn, project_id, narrative=text, summary=summary.strip(),
            source_doc=doc, has_images=has_images, provenance=project["provenance"],
        )
        return ProjectEOS(**stored)
    finally:
        conn.close()


@app.get("/benchmark/{project_id}/eos", response_model=Optional[ProjectEOS])
def get_eos(project_id: int) -> Optional[ProjectEOS]:
    """The project's attached EOS narrative, or null when none is attached."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        stored = bench.get_eos(conn, project_id)
        return ProjectEOS(**stored) if stored else None
    finally:
        conn.close()


# -- Matching, the confirm gate, variance table, reasons, summary --------------------
def _variance_response(records: list[dict]) -> list[VarianceRecord]:
    """Attach the deterministic reason hint (never written without the human's code)."""
    return [VarianceRecord(**{**r, "suggested_reason": matcher.suggest_reason(r)}) for r in records]


@app.get("/benchmark/reason-codes", response_model=list[ReasonCode])
def get_reason_codes() -> list[ReasonCode]:
    conn = store.get_connection()
    try:
        return [ReasonCode(**c) for c in bench.all_reason_codes(conn)]
    finally:
        conn.close()


@app.get("/benchmark/summary", response_model=BenchmarkSummary)
def get_benchmark_summary() -> BenchmarkSummary:
    """Coverage across the LIVE profile only — demo-provenance projects never count."""
    conn = store.get_connection()
    try:
        return BenchmarkSummary(**bench.summary(conn))
    finally:
        conn.close()


@app.get("/benchmark/{project_id}/matches", response_model=MatchProposal)
def get_benchmark_matches(project_id: int) -> MatchProposal:
    """The tiered match proposal (Tier 1 exact ref, Tier 2 embedding, Tier 3 unmatched).
    Read-only — nothing is written until the confirm gate."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        pairs = matcher.match(bench.tender_items(conn, project_id), bench.actual_items(conn, project_id))
    finally:
        conn.close()

    def to_pair(p: dict) -> MatchPair:
        return MatchPair(
            tier=p["tier"], similarity=p["similarity"],
            tender=TenderItem(**p["tender"]) if p["tender"] else None,
            actual=ActualItem(**p["actual"]) if p["actual"] else None,
        )

    return MatchProposal(
        project_id=project_id,
        tier1=[to_pair(p) for p in pairs if p["tier"] == 1],
        tier2=[to_pair(p) for p in pairs if p["tier"] == 2],
        tier3=[to_pair(p) for p in pairs if p["tier"] == 3],
    )


@app.post("/benchmark/{project_id}/matches/confirm", response_model=list[VarianceRecord])
def post_confirm_matches(project_id: int, req: ConfirmMatchesRequest) -> list[VarianceRecord]:
    """The Layer-4 confirm gate — the ONLY writer of variance_records. Confirm-all for
    Tier 1 or individual confirm/repair for Tier 2/3 (the frontend sends the chosen pairs).
    Each confirmed pair's rate-primary variance is computed and upserted."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        try:
            records = bench.confirm_matches(
                conn, project_id, [c.model_dump() for c in req.confirm], confirmed_by=req.confirmed_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _variance_response(records)
    finally:
        conn.close()


@app.get("/benchmark/{project_id}/variance", response_model=list[VarianceRecord])
def get_benchmark_variance(project_id: int) -> list[VarianceRecord]:
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        return _variance_response(bench.variance_records(conn, project_id))
    finally:
        conn.close()


@app.get("/benchmark/{project_id}/variance/reason-suggestions", response_model=VarianceReasonSuggestions)
def get_variance_reason_suggestions(project_id: int) -> VarianceReasonSuggestions:
    """EOS-derived reason candidates per variance record (Phase 2, Layer-2 suggestion only).

    Reads the project's attached EOS narrative and its variance table, and returns one
    candidate reason code + supporting narrative snippet per line the report explains. The
    reason POST below stays the SOLE writer — this endpoint never mutates a record. Empty
    (``eos_attached=false``) when no EOS narrative is attached: the honest empty state.
    DEMO reads the baked candidate fixture; no network. Sync ``def`` (an LLM read in live)."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        eos = bench.get_eos(conn, project_id)
        records = bench.variance_records(conn, project_id)
    finally:
        conn.close()
    narrative = (eos or {}).get("narrative", "").strip()
    if not narrative:
        return VarianceReasonSuggestions(project_id=project_id, eos_attached=bool(eos), candidates=[])
    candidates = extract_reason_candidates(
        narrative, records, demo_fixture=EOS_REASON_FIXTURE if demo_mode() else None,
    )
    return VarianceReasonSuggestions(
        project_id=project_id, eos_attached=True,
        candidates=[ReasonCandidate(**c) for c in candidates],
    )


@app.post("/benchmark/{project_id}/variance/{record_id}/reason", response_model=VarianceRecord)
def post_variance_reason(project_id: int, record_id: int, req: ReasonRequest) -> VarianceRecord:
    """Set a variance record's reason — the human's code (validated against the ten-code
    vocabulary) is required. The candidate may come from the EOS narrative
    (``/variance/reason-suggestions``) or a deterministic hint, with its snippet passed as the
    note; either way this write is the SOLE writer and requires the human's confirmed code."""
    conn = store.get_connection()
    try:
        _require_project(conn, project_id)
        try:
            updated = bench.set_reason(
                conn, project_id, record_id, reason_code=req.reason_code, note=req.note, tagged_by=req.tagged_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail=f"No variance record {record_id} in project {project_id}.")
        return _variance_response([updated])[0]
    finally:
        conn.close()


# ===========================================================================
# Routing gate (Phase 1) — self-perform (left) vs sublet (right), per package.
#
# After ingest splits the tender, /route/analyze computes the Layer-1 coverage
# signal per package and drafts an AI recommendation (suggestion only, with a
# deterministic fallback), persisting the proposal with chosen_route null.
# /route/confirm is the Layer-4 gate — the only writer of chosen_route — and
# returns the sublet packages (for the existing shortlist path) and the
# self-perform packages (for the Phase-3 estimator).
# ===========================================================================
@app.post("/route/analyze", response_model=RouteProposal)
def post_route_analyze(req: AnalyzeRequest) -> RouteProposal:
    """Recommend a route per package (advisory) and persist the proposal."""
    run_ref = req.run_ref.strip() or tender_slug(req.scope.project_name)

    conn = store.get_connection()
    try:
        packages = [
            {
                "package_key": pkg.trade, "trade": pkg.trade, "scope_summary": pkg.scope_summary,
                "signals": package_signal(conn, pkg.trade, pkg.scope_summary),
            }
            for pkg in req.scope.packages
        ]
    finally:
        conn.close()

    recommended = recommend_routes(
        packages, demo_fixture=ROUTE_SUGGESTIONS_FIXTURE if demo_mode() else None,
    )

    conn = store.get_connection()
    try:
        saved = routing.write_proposal(conn, run_ref, recommended)
        # Record the run as a unified project (Phase 4) — the identity that carries this
        # tender through the tracks. Thin umbrella, no cost data.
        uproject.get_or_create(conn, run_ref, name=req.scope.project_name,
                               provenance=("demo" if demo_mode() else "live"))
    finally:
        conn.close()
    return RouteProposal(run_ref=run_ref, packages=[RoutePackage(**r) for r in saved])


@app.post("/route/confirm", response_model=RouteDecisionResult)
def post_route_confirm(req: ConfirmRoutesRequest) -> RouteDecisionResult:
    """The Layer-4 gate: record the human's route decisions (the sole writer of chosen_route)
    and return the sublet / self-perform splits. Auto-link on route (P4b): when the scope is
    supplied, each self-perform package seeds its estimate (idempotent) and the run is recorded
    as a unified project — so confirming lands the person in the right track (sourcing) or the
    left track (estimator) per package."""
    for d in req.decisions:
        if d.chosen_route not in ROUTES:
            raise HTTPException(status_code=400, detail=f"unknown route {d.chosen_route!r} (use one of {ROUTES})")
    conn = store.get_connection()
    try:
        saved = routing.confirm_decisions(
            conn, req.run_ref, {d.package_key: d.chosen_route for d in req.decisions}, decided_by=req.decided_by,
        )
        packages = [RoutePackage(**r) for r in saved]
        self_perform = [p.package_key for p in packages if p.chosen_route == SELF_PERFORM]
        sublet = [p.package_key for p in packages if p.chosen_route == SUBLET]
        estimate_ids: dict[str, int] = {}
        if req.scope is not None:
            uproject.get_or_create(conn, req.run_ref, name=req.scope.project_name,
                                   provenance=("demo" if demo_mode() else "live"))
            pkg_by_trade = {p.trade: p for p in req.scope.packages}
            for key in self_perform:
                pkg = pkg_by_trade.get(key)
                if pkg is not None:
                    estimate_ids[key] = _seed_estimate(conn, pkg, run_ref=req.run_ref, project_name=req.scope.project_name)["id"]
    finally:
        conn.close()
    return RouteDecisionResult(
        run_ref=req.run_ref, packages=packages, sublet_packages=sublet,
        self_perform_packages=self_perform, estimate_ids=estimate_ids,
    )


# ===========================================================================
# Estimator (Phase 3) — the LEFT track. Our own priced tender for a self-perform
# package. A DRAFT surface, separate from the confirmed benchmark corpus; the human
# prices every line and owns the offer. Seeded from a routed self-perform package
# (/estimate/from-package) or opened manually. One endpoint per step — no monolith.
# ===========================================================================
def _require_estimate(conn, estimate_id: int) -> dict:
    project = est.get_project(conn, estimate_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No estimate {estimate_id}.")
    return project


@app.post("/estimate/projects", response_model=EstimateProject)
def post_estimate_project(req: EstimateProjectCreate) -> EstimateProject:
    conn = store.get_connection()
    try:
        return EstimateProject(**est.create_project(
            conn, name=req.name, trade=req.trade, client=req.client,
            contract_ref=req.contract_ref, notes=req.notes, source="manual",
        ))
    finally:
        conn.close()


@app.get("/estimate/projects", response_model=list[EstimateProject])
def get_estimate_projects() -> list[EstimateProject]:
    conn = store.get_connection()
    try:
        return [EstimateProject(**p) for p in est.list_projects(conn)]
    finally:
        conn.close()


@app.get("/estimate/projects/{estimate_id}", response_model=EstimateProject)
def get_estimate_project(estimate_id: int) -> EstimateProject:
    conn = store.get_connection()
    try:
        return EstimateProject(**_require_estimate(conn, estimate_id))
    finally:
        conn.close()


@app.patch("/estimate/projects/{estimate_id}", response_model=EstimateProject)
def patch_estimate_project(estimate_id: int, req: EstimateProjectUpdate) -> EstimateProject:
    """Update estimate fields; ``status='closed'`` closes it (stamps closed_at)."""
    conn = store.get_connection()
    try:
        _require_estimate(conn, estimate_id)
        try:
            updated = est.update_project(conn, estimate_id, req.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return EstimateProject(**updated)
    finally:
        conn.close()


def _seed_estimate(conn, pkg, *, run_ref: str = "", project_name: str = "", client: str = "", contract_ref: str = "") -> dict:
    """Seed (or return the existing) estimate for a self-perform package — its SoR items
    become the initial unpriced lines. Idempotent per (run_ref, package_key); the trade is
    canonicalised against the taxonomy (Layer 1). Shared by /estimate/from-package and the
    route-confirm auto-link (P4b)."""
    from rules_engine.taxonomy import normalize as normalize_trade  # Layer 1; local import keeps the graph flat

    trade = normalize_trade(pkg.trade) or pkg.trade
    existing = est.find_by_route(conn, run_ref, pkg.trade) if run_ref else None
    if existing is not None:
        return existing
    name = (f"{project_name} — {trade}" if project_name else trade).strip(" —") or trade or "Estimate"
    project = est.create_project(
        conn, name=name, trade=trade, client=client, contract_ref=contract_ref,
        source=("routing" if run_ref else "from-package"), run_ref=run_ref, package_key=pkg.trade,
        scope_of_works=pkg.scope_summary or "",
    )
    items = [{
        "item_ref": it.item_ref, "description": it.description or "", "unit": it.unit or "",
        "qty": it.qty, "rate": None, "section": trade,
    } for it in pkg.sor_items]
    if items:
        est.replace_items(conn, project["id"], items, source="scope-link")
    return est.get_project(conn, project["id"])


@app.post("/estimate/from-package", response_model=EstimateProject)
def post_estimate_from_package(req: FromPackageRequest) -> EstimateProject:
    """Seed an estimate from a routed self-perform package (or any TradeWorkPackage). The
    package's SoR items become the initial (unpriced) estimate lines — the human prices.
    Idempotent per (run_ref, package_key): a routed package opens one estimate, not a new one
    per click."""
    conn = store.get_connection()
    try:
        return EstimateProject(**_seed_estimate(
            conn, req.package, run_ref=req.run_ref, project_name=req.project_name,
            client=req.client, contract_ref=req.contract_ref,
        ))
    finally:
        conn.close()


@app.post("/estimate/{estimate_id}/draft", response_model=EstimateDraftResult)
def post_estimate_draft(estimate_id: int) -> EstimateDraftResult:
    """Draft the scope-of-works + a candidate item skeleton (Layer-2 assist, purpose
    ``estimate-draft``) from the estimate's trade + scope + current items. Refreshes the
    scope narrative and adds any commonly-needed items not already present — unpriced and
    unquantified (the person prices and quantifies). Never invents a quantity or a rate.
    DEMO reads the baked fixture; a deterministic fallback keeps the scope from the summary.
    Sync ``def`` (an LLM read in live)."""
    conn = store.get_connection()
    try:
        project = _require_estimate(conn, estimate_id)
        existing_refs = [i["item_ref"] for i in est.items_for(conn, estimate_id)]
        draft = draft_estimate(
            project["trade"], project["scope_of_works"], existing_refs,
            demo_fixture=ESTIMATE_DRAFT_FIXTURE if demo_mode() else None,
        )
        est.update_project(conn, estimate_id, {"scope_of_works": draft["scope_of_works"]})
        if draft["additional_items"]:
            est.add_items(conn, estimate_id, [{
                "item_ref": it["item_ref"], "description": it["description"], "unit": it["unit"],
                "qty": None, "rate": None, "section": draft["trade"],
            } for it in draft["additional_items"]], source="estimate-draft")
        return EstimateDraftResult(
            estimate=EstimateProject(**est.get_project(conn, estimate_id)),
            scope_of_works=draft["scope_of_works"],
            added_item_refs=[it["item_ref"] for it in draft["additional_items"]],
            trade_mapped=draft["trade_mapped"],
        )
    finally:
        conn.close()


@app.post("/estimate/{estimate_id}/check", response_model=EstimateCheckResult)
def post_estimate_check(estimate_id: int, req: EstimateCheckRequest) -> EstimateCheckResult:
    """Error / omission check (Phase 3) — reports, never auto-fixes. Layer-1 deterministic
    checks against the supplied tender requirements (omissions, unit mismatches, unpriced
    lines), the corpus-gated ``rubric_items`` (empty until an archive fills it), and a Layer-2
    read of the scope-of-works for scope gaps. DEMO reads the baked fixture. Sync ``def``."""
    conn = store.get_connection()
    try:
        project = _require_estimate(conn, estimate_id)
        items = est.items_for(conn, estimate_id)
        rubric = bench.rubric_items_for_trade(conn, project["trade"])
    finally:
        conn.close()
    result = check_estimate(
        items, [t.model_dump() for t in req.tender], rubric, project["scope_of_works"],
        demo_fixture=ESTIMATE_CHECK_FIXTURE if demo_mode() else None,
    )
    return EstimateCheckResult(
        estimate_id=estimate_id, tender_checked=result["tender_checked"], rubric_size=result["rubric_size"],
        findings=[EstimateFinding(**f) for f in result["findings"]],
    )


@app.get("/estimate/{estimate_id}/rate-suggestions", response_model=RateSuggestions)
def get_estimate_rate_suggestions(estimate_id: int) -> RateSuggestions:
    """Rate precedent per line from the benchmark corpus (Phase 3, corpus-gated). Tier-1 exact
    ``item_ref`` + Tier-2 embedding retrieval over the confirmed tender/variance archive; each
    precedent carries the historical rate band and any rate warnings (reason codes under which
    the ref historically moved on rate). ``corpus_empty=true`` is the honest live pre-archive
    state — no rate is ever fabricated. Deterministic (no LLM); the person prices."""
    conn = store.get_connection()
    try:
        _require_estimate(conn, estimate_id)
        items = est.items_for(conn, estimate_id)
        corpus = bench.corpus_rate_rows(conn)
    finally:
        conn.close()
    result = suggest_rates(items, corpus)
    return RateSuggestions(
        estimate_id=estimate_id, corpus_empty=result["corpus_empty"], corpus_size=result["corpus_size"],
        suggestions=[RatePrecedent(**s) for s in result["suggestions"]],
    )


@app.post("/estimate/{estimate_id}/to-benchmark", response_model=ToBenchmarkResult)
def post_estimate_to_benchmark(estimate_id: int) -> ToBenchmarkResult:
    """Capture an awarded estimate as a benchmark tender snapshot (Phase 4c — the compounding
    loop). Creates (or reuses) a benchmark project and copies the estimate's priced lines into
    its tender_items, so a self-performed job also feeds the benchmark corpus on completion.
    Idempotent for a routed estimate via its run_ref (re-capture reuses the linked benchmark
    project). Marks the estimate 'awarded'. The benchmark project's provenance follows the mode
    (demo captures never count in the live summary)."""
    conn = store.get_connection()
    try:
        estimate = _require_estimate(conn, estimate_id)
        pid = None
        if estimate["run_ref"]:
            up = uproject.get_or_create(conn, estimate["run_ref"], name=estimate["name"])
            if up["benchmark_project_id"] and bench.get_project(conn, up["benchmark_project_id"]):
                pid = up["benchmark_project_id"]
        if pid is None:
            created = bench.create_project(
                conn, name=estimate["name"], trade=estimate["trade"], client=estimate["client"],
                contract_ref=estimate["contract_ref"], source="estimate",
                provenance=("demo" if demo_mode() else "live"),
                notes=f"Captured from estimate #{estimate_id} (self-perform).",
            )
            pid = created["id"]
            if estimate["run_ref"]:
                uproject.link_benchmark(conn, estimate["run_ref"], pid)
        items = [{
            "item_ref": it["item_ref"], "description": it["description"], "unit": it["unit"],
            "qty": it["qty"], "rate": it["rate"], "amount": it["amount"], "section": it["section"],
        } for it in est.items_for(conn, estimate_id)]
        written = bench.replace_tender_items(conn, pid, items, source="estimate", source_doc=estimate["name"])
        est.update_project(conn, estimate_id, {"status": "awarded"})
        updated = est.get_project(conn, estimate_id)
    finally:
        conn.close()
    return ToBenchmarkResult(estimate=EstimateProject(**updated), benchmark_project_id=pid, tender_item_count=len(written))


@app.post("/estimate/{estimate_id}/letter", response_model=LetterOfOffer)
def post_estimate_letter(estimate_id: int) -> LetterOfOffer:
    """Draft a letter of offer (Layer-2 assist, purpose ``letter-of-offer``) — a covering body,
    inclusions, exclusions, and assumptions from the estimate's scope + priced schedule. The
    person owns and issues the final letter; nothing here invents a total or a rate. DEMO reads
    the baked fixture; a deterministic fallback keeps a usable letter. Sync ``def``."""
    conn = store.get_connection()
    try:
        project = _require_estimate(conn, estimate_id)
        items = est.items_for(conn, estimate_id)
    finally:
        conn.close()
    return LetterOfOffer(**draft_letter(project, items, demo_fixture=LETTER_FIXTURE if demo_mode() else None))


@app.get("/estimate/{estimate_id}/items", response_model=list[EstimateItem])
def get_estimate_items(estimate_id: int) -> list[EstimateItem]:
    conn = store.get_connection()
    try:
        _require_estimate(conn, estimate_id)
        return [EstimateItem(**it) for it in est.items_for(conn, estimate_id)]
    finally:
        conn.close()


@app.post("/estimate/{estimate_id}/items", response_model=list[EstimateItem])
def post_estimate_items(estimate_id: int, req: EstimateItemsRequest) -> list[EstimateItem]:
    """Append item lines to the estimate (manual add). Rows with no item_ref are skipped."""
    conn = store.get_connection()
    try:
        _require_estimate(conn, estimate_id)
        written = est.add_items(conn, estimate_id, [i.model_dump() for i in req.items], source="manual")
        return [EstimateItem(**it) for it in written]
    finally:
        conn.close()


@app.patch("/estimate/{estimate_id}/items/{item_id}", response_model=EstimateItem)
def patch_estimate_item(estimate_id: int, item_id: int, req: EstimateItemUpdate) -> EstimateItem:
    """Edit one line — the human prices (qty / rate / description / unit / section). The
    computable amount is recomputed; nothing is ever fabricated for a rate-only line."""
    conn = store.get_connection()
    try:
        _require_estimate(conn, estimate_id)
        updated = est.update_item(conn, estimate_id, item_id, req.model_dump(exclude_none=True))
        if updated is None:
            raise HTTPException(status_code=404, detail=f"No item {item_id} in estimate {estimate_id}.")
        return EstimateItem(**updated)
    finally:
        conn.close()


@app.delete("/estimate/{estimate_id}/items/{item_id}")
def delete_estimate_item(estimate_id: int, item_id: int) -> dict:
    conn = store.get_connection()
    try:
        _require_estimate(conn, estimate_id)
        if not est.delete_item(conn, estimate_id, item_id):
            raise HTTPException(status_code=404, detail=f"No item {item_id} in estimate {estimate_id}.")
        return {"deleted": item_id}
    finally:
        conn.close()


# ===========================================================================
# Unified project (Phase 4) — the run_ref-keyed spine that ties a tender across the
# tracks: routing decisions (left/right), the left-track estimates, and the benchmark
# link. A read-model assembled from the existing tables; it holds no cost data of its own.
# ===========================================================================
def _dashboard(conn, run_ref: str) -> ProjectDashboard:
    up = uproject.get_or_create(conn, run_ref)
    routes = routing.read_proposal(conn, run_ref)
    estimates = est.list_by_run(conn, run_ref)
    est_by_pkg: dict = {}
    for e in estimates:
        est_by_pkg.setdefault(e["package_key"], e)
    packages = []
    for r in routes:
        chosen = r["chosen_route"]
        track = "left" if chosen == SELF_PERFORM else "right" if chosen == SUBLET else "undecided"
        e = est_by_pkg.get(r["package_key"])
        packages.append(DashboardPackage(
            package_key=r["package_key"], trade=r["trade"], scope_summary=r["scope_summary"],
            recommended_route=r["recommended_route"], chosen_route=chosen, track=track,
            estimate_id=(e["id"] if e else None), decided_by=r["decided_by"],
        ))
    return ProjectDashboard(
        run_ref=run_ref, name=up["name"], provenance=up["provenance"], packages=packages,
        estimates=[EstimateProject(**e) for e in estimates], benchmark_project_id=up["benchmark_project_id"],
    )


@app.get("/project", response_model=list[ProjectSummary])
def get_unified_projects() -> list[ProjectSummary]:
    """Every unified project (analysis run) with its track split — the dashboard list."""
    conn = store.get_connection()
    try:
        out = []
        for up in uproject.list_projects(conn):
            routes = routing.read_proposal(conn, up["run_ref"])
            estimates = est.list_by_run(conn, up["run_ref"])
            out.append(ProjectSummary(
                run_ref=up["run_ref"], name=up["name"], provenance=up["provenance"],
                package_count=len(routes),
                self_perform_count=sum(1 for r in routes if r["chosen_route"] == SELF_PERFORM),
                sublet_count=sum(1 for r in routes if r["chosen_route"] == SUBLET),
                estimate_count=len(estimates), benchmark_project_id=up["benchmark_project_id"],
            ))
        return out
    finally:
        conn.close()


@app.get("/project/{run_ref}", response_model=ProjectDashboard)
def get_unified_project(run_ref: str) -> ProjectDashboard:
    """One project's dashboard: its packages (each track + status), the left-track estimates,
    and the benchmark link. Assembled from routing + estimates keyed by run_ref."""
    conn = store.get_connection()
    try:
        return _dashboard(conn, run_ref)
    finally:
        conn.close()
