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

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # before anything reads env

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from pipeline.documents import to_images  # noqa: E402
from pipeline.llm_client import demo_mode  # noqa: E402
from pipeline.stage_01_ingest.ingest import ingest_tender  # noqa: E402
from pipeline.stage_02_shortlist.shortlist import shortlist  # noqa: E402
from pipeline.stage_03_dispatch.dispatch import build_dispatch  # noqa: E402
from pipeline.stage_03_dispatch.mailer import send_bundles  # noqa: E402
from pipeline.stage_04_level.export_xlsx import OUT_PATH, export_leveling_xlsx  # noqa: E402
from pipeline.stage_04_level.level import level_bids, load_demo_replies, parse_bid_reply  # noqa: E402
from pipeline.stage_05_recommend.recommend import recommend  # noqa: E402
from pipeline.workspace import Workspace  # noqa: E402
from db import store  # noqa: E402
from schemas.models import (  # noqa: E402
    BidReply,
    Contact,
    DispatchSet,
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
    "clean": {
        "name": "Clean — strong firms, confident pick",
        "blurb": "Joinery & fitting-out: a shortlist of strong firms, a clean leveling with no corrections, and a confident recommendation.",
        "hero_trade": "joinery_fitting_out",
        "replies_fixture": "cases/scenarios/clean_replies.json",
        "rationale_fixture": "cases/scenarios/clean_rationale.json",
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
async def post_ingest_upload(
    files: list[UploadFile] = File(...),
    project_name: str = Form("Uploaded tender"),
) -> ScopePackages:
    """Ingest live tender documents (PDF/image). In DEMO_MODE the upload is accepted
    but the baked scope fixture is returned (no model, no network). Live, each
    original is persisted to the tender workspace so dispatch can attach the real
    files, then rasterised for the vision model."""
    tender = TenderPackage(
        project_name=project_name,
        documents=[TenderDocument(doc_type=DocType.SCHEDULE_OF_RATES, filename=f.filename or "upload") for f in files],
    )
    if demo_mode():
        return ingest_tender(tender, demo_fixture=SCOPE_FIXTURE)

    workspace = Workspace()
    images: list[str] = []
    for upload in files:
        data = await upload.read()
        workspace.save_upload(project_name, upload.filename or "upload", data)
        try:
            images += to_images(data, upload.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ingest_tender(tender, images=images)


# ---------------------------------------------------------------------------
# Stage 02 — shortlist
# ---------------------------------------------------------------------------
class ShortlistRequest(BaseModel):
    scope: ScopePackages
    include_public: bool = False  # live engine sets True; demo/default stays assessed-firm


@app.post("/shortlist", response_model=ShortlistSet)
def post_shortlist(req: ShortlistRequest) -> ShortlistSet:
    return shortlist(req.scope, include_public=req.include_public)


# ---------------------------------------------------------------------------
# Stage 03 — dispatch
# ---------------------------------------------------------------------------
class DispatchRequest(BaseModel):
    shortlist: ShortlistSet
    approvals: dict[str, list[str]] = Field(default_factory=dict)
    scope: ScopePackages | None = None
    tender: TenderPackage | None = None  # live: routes real attachments by document
    project_name: str = ""
    send: bool = False
    dry_run: bool = False  # force the mock outbox even when SMTP is configured
    demo_fixture: str | None = DISPATCH_FIXTURE


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
    replies = req.replies or load_demo_replies(req.demo_fixture)
    levelled = level_bids(replies, req.scope)
    export_leveling_xlsx(levelled, replies, path=OUT_PATH)  # refresh the downloadable Excel
    return levelled


@app.post("/level-upload", response_model=list[LevelledBid])
async def post_level_upload(
    files: list[UploadFile] = File(...),
    firm_id: str = Form(...),
    trade: str = Form(...),
) -> list[LevelledBid]:
    """Inbound channel (Phase A): the operator drops a subcontractor's returned
    Schedule of Rates here. In DEMO_MODE the baked levelled comparison is returned;
    live, Layer 2 parses the document into a BidReply and Layer 1 levels it."""
    if demo_mode():
        levelled = level_bids([], demo_fixture=REPLIES_FIXTURE)
        export_leveling_xlsx(levelled, load_demo_replies(REPLIES_FIXTURE), path=OUT_PATH)
        return levelled

    images: list[str] = []
    for upload in files:
        try:
            images += to_images(await upload.read(), upload.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    reply = parse_bid_reply(firm_id=firm_id, trade=trade, images=images)
    levelled = level_bids([reply])
    export_leveling_xlsx(levelled, [reply], path=OUT_PATH)
    return levelled


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
# Stage 05 — recommend
# ---------------------------------------------------------------------------
class RecommendRequest(BaseModel):
    levelled: list[LevelledBid]
    trade: str
    demo_fixture: str | None = RATIONALE_FIXTURE


@app.post("/recommend", response_model=Recommendation)
def post_recommend(req: RecommendRequest) -> Recommendation:
    return recommend(req.levelled, req.trade, demo_fixture=req.demo_fixture)
