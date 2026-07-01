"""SiteSource HTTP API — thin driver over the five-stage pipeline.

One POST per stage, plus the Excel download and the demo loaders. The chassis
pattern is preserved: ``.env`` is auto-loaded before anything reads env, DEMO_MODE
is respected end-to-end (the routes call the same stage functions the offline runner
does), CORS is permissive for local dev, and ``/health`` reports ``demo_mode``. The
multipart upload route lets a live tender PDF be ingested when DEMO_MODE is off.
"""

import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # before anything reads env

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from pipeline.documents import to_images  # noqa: E402
from pipeline.llm_client import demo_mode  # noqa: E402
from pipeline.stage_01_ingest.ingest import ingest_tender  # noqa: E402
from pipeline.stage_02_shortlist.shortlist import shortlist  # noqa: E402
from pipeline.stage_03_dispatch.dispatch import build_dispatch  # noqa: E402
from pipeline.stage_03_dispatch.n8n import draft_via_n8n  # noqa: E402
from pipeline.stage_04_level.export_xlsx import OUT_PATH, export_leveling_xlsx  # noqa: E402
from pipeline.stage_04_level.level import level_bids, load_demo_replies  # noqa: E402
from pipeline.stage_04_level.collect import build_replies_from_approvals, load_sor_templates  # noqa: E402
from pipeline.stage_05_recommend.recommend import recommend  # noqa: E402
from db import store  # noqa: E402
from db.outbox import send_mock  # noqa: E402
from schemas.models import (  # noqa: E402
    BidReply,
    DispatchSet,
    DispatchStatus,
    DocType,
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

app = FastAPI(
    title="SiteSource API",
    version="0.2.0",
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


class PublicFlagOut(BaseModel):
    signal_type: str
    label: str
    date: str | None = None
    source: str | None = None
    reference: str | None = None


class RegisteredTradeOut(BaseModel):
    code: str = ""
    group: str = ""
    specialty: str = ""


class FirmOut(BaseModel):
    firm_id: str
    name_en: str
    name_zh: str | None = None
    registered_grade: str
    value_band: str
    trades: list[str]
    registered_trades: list[RegisteredTradeOut] = Field(default_factory=list)
    description: str = ""
    enquiry_email: str = ""
    br_no: str = ""
    reg_date: str = ""
    expiry_date: str = ""
    public_flags: list[PublicFlagOut]


class FirmsPage(BaseModel):
    items: list[FirmOut]
    total: int
    limit: int
    offset: int


class AwardHistoryOut(BaseModel):
    project: str = ""
    client: str | None = None
    year: int | None = None
    source: str | None = None


class NotableProjectOut(BaseModel):
    title: str = ""
    source: str | None = None


class FirmProfileOut(BaseModel):
    """The curated, verifiable profile for a firm that genuinely does these trades.
    Empty for register-only firms (the modal then shows register data only)."""

    overview: str = ""
    services: list[str] = Field(default_factory=list)
    notable_projects: list[NotableProjectOut] = Field(default_factory=list)
    accreditations: list[str] = Field(default_factory=list)
    group_parent: str = ""
    staff_note: str = ""
    offices: list[str] = Field(default_factory=list)


class FirmFullOut(BaseModel):
    firm_id: str
    name_en: str
    name_zh: str | None = None
    registered_grade: str = ""
    value_band: str = ""
    registers: list[str] = Field(default_factory=list)
    trades: list[str] = Field(default_factory=list)
    registered_trades: list[RegisteredTradeOut] = Field(default_factory=list)
    description: str = ""
    enquiry_email: str = ""
    br_no: str = ""
    reg_date: str = ""
    expiry_date: str = ""
    public_flags: list[PublicFlagOut] = Field(default_factory=list)
    award_history: list[AwardHistoryOut] = Field(default_factory=list)
    provenance: str = ""
    profile: FirmProfileOut = Field(default_factory=FirmProfileOut)


_FIRM_PAGE_SIZES = {10, 25, 50, 100}


@app.get("/firms", response_model=FirmsPage)
def firms(limit: int = 25, offset: int = 0, q: str = "", sort: str = "name") -> dict:
    """The proprietary data asset: a server-paginated page of real-provenance Hong
    Kong register firms (never the illustrative demo firms). ``limit`` is one of
    10/25/50/100 (hard cap 100); ``q`` is a case-insensitive name search; default
    sort is name ascending. Returns ``{items, total, limit, offset}``."""
    if limit not in _FIRM_PAGE_SIZES:
        limit = 25
    conn = store.get_connection()
    try:
        return store.paged_firms(conn, limit=limit, offset=offset, q=q, sort=sort)
    finally:
        conn.close()


@app.get("/firms/{firm_id}", response_model=FirmFullOut)
def firm_detail(firm_id: str) -> dict:
    """Full firm profile for the shortlist card modal — all DB columns, award history
    with source URLs, and public flags with citation references."""
    conn = store.get_connection()
    try:
        result = store.firm_full_by_id(conn, firm_id)
    finally:
        conn.close()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Firm {firm_id!r} not found.")
    return result


# ---------------------------------------------------------------------------
# Demo loaders — the seeded tender and replies the wizard starts from
# ---------------------------------------------------------------------------
def _tender(project_name: str, description: str, docs: list[tuple[DocType, str]]) -> TenderPackage:
    return TenderPackage(
        project_name=project_name,
        description=description,
        documents=[TenderDocument(doc_type=dt, filename=fn) for dt, fn in docs],
    )


# A building/fit-out tender (the three electrical/joinery scenarios share it) and a
# real Hong Kong ground-investigation tender (the drainage scenario). Each scenario
# names its own tender and its own scope fixture, so ingest splits the right package
# structure — by trade for the building tender, by work section for the GI tender.
_KWUN_TONG_TENDER = _tender(
    "Kwun Tong Commercial Tower — Category-A Office Fit-out",
    "Cat-A office fit-out across 12 floors.",
    [
        (DocType.METHOD_OF_MEASUREMENT, "method_of_measurement.pdf"),
        (DocType.PARTICULAR_SPECIFICATION, "particular_specification.pdf"),
        (DocType.TENDER_ADDENDUM, "tender_addendum.pdf"),
        (DocType.SCHEDULE_OF_RATES, "schedule_of_rates.pdf"),
    ],
)
_DRAINAGE_TENDER = _tender(
    "GE/2026/14 — Ground Investigation, Man-made Slopes (Surface Drainage Water Study)",
    "Ground-investigation field testing, drilling and sampling for man-made slopes; "
    "surface drainage water study (drainage field test).",
    [
        (DocType.METHOD_OF_MEASUREMENT, "I-GE_2026_14_TSC-MM-01.pdf"),
        (DocType.PARTICULAR_SPECIFICATION, "I-GE_2026_14_TSC-PS-S07-00.pdf"),
        (DocType.TENDER_ADDENDUM, "AECOM Tender Clarification No.1.pdf"),
        (DocType.SCHEDULE_OF_RATES, "I-GE_2026_14_TSC-SR-01.pdf"),
    ],
)


# Four deterministic demo scenarios — seeded DB, each isolating one catch. All
# reproduce identically. The three building scenarios share the Kwun Tong tender and
# its scope split; drainage carries its own GI tender, scope split and replies.
_DEMO_CASES = {
    "clean": {
        "name": "Clean — strong firms, confident pick",
        "blurb": "Joinery & fitting-out: a shortlist of strong firms, a clean leveling with no corrections, and a confident recommendation.",
        "hero_trade": "joinery_fitting_out",
        "tender": _KWUN_TONG_TENDER,
        "scope_fixture": SCOPE_FIXTURE,
        "replies_fixture": "cases/scenarios/clean_replies.json",
        "rationale_fixture": "cases/scenarios/clean_rationale.json",
        "rationale_by_trade": {"joinery_fitting_out": "cases/scenarios/clean_rationale.json"},
    },
    "hero": {
        "name": "Hero — the cheapest bidder, flagged",
        "blurb": "Electrical: the cheapest, best-matching bidder looks clean on the bid sheet but carries an active winding-up petition and two safety prosecutions — recommended against despite the lowest price.",
        "hero_trade": "electrical",
        "tender": _KWUN_TONG_TENDER,
        "scope_fixture": SCOPE_FIXTURE,
        "replies_fixture": "cases/scenarios/hero_replies.json",
        "rationale_fixture": "cases/scenarios/hero_rationale.json",
        "rationale_by_trade": {"electrical": "cases/scenarios/hero_rationale.json"},
    },
    "messy": {
        "name": "Messy — leveling changes the ranking",
        "blurb": "Electrical: a reply hides an understated line, an unpriced provisional sum, and an exclusion; leveling corrects the total so the cheapest clean bid changes.",
        "hero_trade": "electrical",
        "tender": _KWUN_TONG_TENDER,
        "scope_fixture": SCOPE_FIXTURE,
        "replies_fixture": REPLIES_FIXTURE,
        "rationale_fixture": RATIONALE_FIXTURE,
        "rationale_by_trade": {"electrical": RATIONALE_FIXTURE},
    },
    "drainage": {
        "name": "Drainage field test — real HK tender, leveling decides",
        "blurb": "Ground investigation (Contract GE/2026/14): a civil tender splits by work section, no public-record risk screen applies, and the apparent-cheapest bid loses once its excluded water supply and freeboard are leveled back in.",
        "hero_trade": "field_testing",
        "tender": _DRAINAGE_TENDER,
        "scope_fixture": "cases/scenarios/drainage_scope.json",
        # Approval-driven: the leveling bids are built from the firms approved in
        # dispatch over this SoR template bank, so the Level columns always equal the
        # approved firms (no fixed replies list, no GI-1 in the leveling).
        "sor_fixture": "cases/scenarios/drainage_sor.json",
        "replies_fixture": None,
        # Recommendation is narrated by the always-accurate deterministic template
        # (no baked fixture), so it tracks whichever firms were approved.
        "rationale_fixture": "",
        "rationale_by_trade": {},
    },
}


class DemoCaseSummary(BaseModel):
    id: str
    name: str
    hero_trade: str
    blurb: str


class DemoCase(DemoCaseSummary):
    tender: TenderPackage
    scope_fixture: str
    replies: list[BidReply]
    rationale_fixture: str
    # Per-work-section rationale fixtures (trade -> fixture). The wizard runs the
    # recommendation once per section the bids cover and narrates each from here.
    rationale_by_trade: dict[str, str] = Field(default_factory=dict)
    # Approval-driven cases ship a SoR template bank instead of a fixed replies list:
    # the wizard builds the leveling replies from the approved firms via /collect-replies.
    sor_fixture: str | None = None


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
    replies_fixture = m.get("replies_fixture")
    return DemoCase(
        id=case_id,
        name=m["name"],
        hero_trade=m["hero_trade"],
        blurb=m["blurb"],
        tender=m["tender"],
        scope_fixture=m["scope_fixture"],
        # Approval-driven cases carry no fixed replies; the wizard builds them from the
        # approved firms over the SoR template bank.
        replies=load_demo_replies(replies_fixture) if replies_fixture else [],
        rationale_fixture=m["rationale_fixture"],
        rationale_by_trade=m.get("rationale_by_trade", {}),
        sor_fixture=m.get("sor_fixture"),
    )


# ---------------------------------------------------------------------------
# Stage 01 — ingest
# ---------------------------------------------------------------------------
class IngestRequest(BaseModel):
    tender: TenderPackage
    demo_fixture: str | None = SCOPE_FIXTURE


@app.post("/ingest", response_model=ScopePackages)
def post_ingest(req: IngestRequest) -> ScopePackages:
    return ingest_tender(req.tender, demo_fixture=req.demo_fixture)


@app.post("/ingest-upload", response_model=ScopePackages)
async def post_ingest_upload(files: list[UploadFile] = File(...)) -> ScopePackages:
    """Ingest live tender documents (PDF/image). In DEMO_MODE the upload is accepted
    but the baked GE/2026/14 drainage scope is returned (no model, no network) — every
    uploaded tender routes to the drainage field-investigation scenario for the demo."""
    tender = TenderPackage(
        project_name="Uploaded tender",
        documents=[TenderDocument(doc_type=DocType.SCHEDULE_OF_RATES, filename=f.filename or "upload") for f in files],
    )
    if demo_mode():
        return ingest_tender(tender, demo_fixture="cases/scenarios/drainage_scope.json")
    images: list[str] = []
    for upload in files:
        try:
            images += to_images(await upload.read(), upload.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ingest_tender(tender, images=images)


# ---------------------------------------------------------------------------
# Stage 02 — shortlist
# ---------------------------------------------------------------------------
class ShortlistRequest(BaseModel):
    scope: ScopePackages


@app.post("/shortlist", response_model=ShortlistSet)
def post_shortlist(req: ShortlistRequest) -> ShortlistSet:
    return shortlist(req.scope)


# ---------------------------------------------------------------------------
# Stage 03 — dispatch
# ---------------------------------------------------------------------------
class DispatchRequest(BaseModel):
    shortlist: ShortlistSet | None = None
    approvals: dict[str, list[str]] = Field(default_factory=dict)
    scope: ScopePackages | None = None
    project_name: str = ""
    # When the wizard sends the approved (possibly edited) bundles back to send them,
    # it passes them here so the webhook draft carries the user's edits verbatim.
    dispatch: DispatchSet | None = None
    send: bool = False
    demo_fixture: str | None = DISPATCH_FIXTURE


def _project_code(project_name: str) -> str:
    return (project_name or "").split(" — ")[0].strip() or "GE/2026/14"


def _stamp_name(project_name: str) -> str:
    """A dated, filesystem-safe download name, e.g. ``GE-2026-14_bid_adjudication_2026-06-23.xlsx``."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", _project_code(project_name)).strip("-") or "tender"
    return f"{slug}_bid_adjudication_{date.today().isoformat()}.xlsx"


def _adjudication_meta(project_name: str) -> dict[str, str]:
    """Real title-block parties for the known tender; empty for any other project."""
    if "GE/2026/14" in (project_name or ""):
        return {"employer": "VSL Intrafor Hong Kong Limited", "engineer": "AECOM"}
    return {}


@app.post("/dispatch", response_model=DispatchSet)
def post_dispatch(req: DispatchRequest) -> DispatchSet:
    if req.dispatch is not None:
        dispatch = req.dispatch
    elif req.shortlist is not None:
        dispatch = build_dispatch(
            req.shortlist, req.approvals, demo_fixture=req.demo_fixture,
            scope=req.scope, project_name=req.project_name,
        )
    else:
        dispatch = DispatchSet()
    if not req.send:
        return dispatch

    # Record to the mock outbox (always), then best-effort hand the bundles to n8n,
    # which creates the Gmail drafts. The webhook never breaks the endpoint.
    sent = send_mock(dispatch)
    if draft_via_n8n(sent, project=_project_code(req.project_name)):
        sent = DispatchSet(
            bundles=[b.model_copy(update={"status": DispatchStatus.DRAFTED_GMAIL}) for b in sent.bundles]
        )
    return sent


# ---------------------------------------------------------------------------
# Stage 04 — level (+ Excel export)
# ---------------------------------------------------------------------------
class CollectRequest(BaseModel):
    """Build the leveling replies from the firms approved in dispatch."""

    approvals: dict[str, list[str]] = Field(default_factory=dict)
    sor_fixture: str


@app.post("/collect-replies", response_model=list[BidReply])
def post_collect_replies(req: CollectRequest) -> list[BidReply]:
    """Return the approval-driven leveling replies: per section, the tender scheduled
    rates (benchmark) plus the approved firms over their pinned/representative SoR."""
    sor = load_sor_templates(req.sor_fixture)
    return build_replies_from_approvals(req.approvals, sor)


class LevelRequest(BaseModel):
    replies: list[BidReply] = Field(default_factory=list)
    scope: ScopePackages | None = None
    demo_fixture: str | None = REPLIES_FIXTURE


# The adjudication workbook is regenerated on every /level call and served from a
# fixed path; this carries the dated, project-stamped download name from the last
# /level to the /leveling.xlsx download.
_download_name = "leveling.xlsx"


@app.post("/level", response_model=list[LevelledBid])
def post_level(req: LevelRequest) -> list[LevelledBid]:
    global _download_name
    replies = req.replies or load_demo_replies(req.demo_fixture)
    levelled = level_bids(replies, req.scope)
    project_name = req.scope.project_name if req.scope else ""
    export_leveling_xlsx(  # refresh the downloadable adjudication workbook
        levelled, replies, path=OUT_PATH, project_name=project_name,
        **_adjudication_meta(project_name),
    )
    _download_name = _stamp_name(project_name)
    return levelled


@app.get("/leveling.xlsx")
def get_leveling_xlsx() -> FileResponse:
    if not OUT_PATH.is_file():
        replies = load_demo_replies(REPLIES_FIXTURE)
        export_leveling_xlsx(level_bids(replies), replies, path=OUT_PATH)
    return FileResponse(
        OUT_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=_download_name,
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
