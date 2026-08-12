// Typed client for /client-boq/*. Same BASE and the same error shape as src/api.ts — a 409 from
// a gate arrives as an Error carrying the backend's own sentence, because those sentences say
// exactly which gate refused and why, and rewriting them here would lose that.

import type {
  ArchiveUploadResponse,
  BenchmarkProject,
  BenchmarkSummary,
  BidReply,
  BillCandidate,
  BqCandidates,
  BridgeAward,
  BridgeCloseoutState,
  BridgeCombinedPricing,
  BridgeFinalApproval,
  BridgeHandover,
  BridgeLesson,
  BridgeOutcome,
  BridgePostSubmissionEvent,
  BridgeRouteDecisions,
  BridgeRouteProposal,
  BridgeRouteProposalRead,
  BridgeSplitRead,
  BridgeSplitResponse,
  BridgeSubmissionRecord,
  BridgeSubmissionState,
  CitationsResponse,
  Coverage,
  CriteriaResponse,
  CompanySettings,
  CriterionRow,
  DispatchDraftsResponse,
  DispatchSet,
  DocIndexState,
  EstimateResponse,
  EstimateScheduleInput,
  DocumentRow,
  FirmsPage,
  GateState,
  GmailIntegrationStatus,
  Highlight,
  JobState,
  LLMSettingsResponse,
  ModeResponse,
  LetterResponse,
  LevelAllResponse,
  LevelUploadResult,
  LevelledBid,
  Manifest,
  ManifestGateState,
  MatchConfirm,
  MatchProposal,
  PartContext,
  PartDetail,
  PartSpec,
  PartsResponse,
  AccessBoardResponse,
  AskResponse,
  BidBrief,
  BidDecision,
  ConditionRow,
  ConditionsResponse,
  CostingModelShape,
  CostingResponse,
  PhotoReadResponse,
  PhotoRow,
  LibraryModelResponse,
  DerivedResponse,
  GroupPreview,
  GroupsResponse,
  HoleGroup,
  OutputsResponse,
  ProjectDashboard,
  ProjectEOS,
  ProjectSummary,
  RFIBatchRow,
  RFIItem,
  RFIsResponse,
  RateRowFull,
  RatesResponse,
  ReasonCode,
  RecommendAllResponse,
  RegisterResponse,
  RevisionRow,
  ScheduleResponse,
  SchedulePasteResponse,
  ScheduleReadResponse,
  StationScheduleResponse,
  StationScheduleShape,
  ScopeGateState,
  ScopeItem,
  ScopeItemsResponse,
  ScopeResponse,
  ScopeSection,
  ScopeSourcesResponse,
  SearchResponse,
  SectionPlan,
  SetMeta,
  SetRow,
  ShortlistSet,
  TeamMember,
  TenderReplies,
  VarianceReasonSuggestions,
  VarianceRecord,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";
const ROOT = `${BASE}/client-boq`;

// --- who is acting ----------------------------------------------------------
// Named profiles, not auth: the header names a team member so ownership, verdicts and edits
// carry attribution. Set once by the profile picker; every mutating helper below sends it.
// An empty value is honest ("nobody said who they were"), never an error.
let currentActor = "";
try {
  currentActor = JSON.parse(window.localStorage.getItem("cboq.currentUser") ?? '""') as string;
} catch {
  currentActor = "";
}

export function setActor(memberId: string): void {
  currentActor = memberId;
}

function actorHeaders(): Record<string, string> {
  return currentActor ? { "X-CBOQ-Actor": currentActor } : {};
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status line */
    }
    const error = new Error(detail) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json() as Promise<T>;
}

/** Is this rejection the server saying "that has not happened yet", or a read that did not happen?
 *
 *  The distinction the whole app turns on. A 404 means the step has not run and a 409 means a gate
 *  is still shut — both are tender state, and `null` is the honest answer. Anything else (a 500, or
 *  a network failure with no status at all) is a read that FAILED, and flattening it to the same
 *  `null` makes a broken backend indistinguishable from an untouched tender: the screen then says
 *  "none yet" about groups it never asked for, or "no bill imported" about a bill that is there.
 *
 *  Absence reading as health is this codebase's recurring failure, and `.catch(() => null)` is how
 *  it gets written. This function is the one place the rule lives, so every reader applies the
 *  same one.
 */
export const isNotYet = (e: unknown): boolean => {
  const status = (e as { status?: number })?.status;
  return status === 404 || status === 409;
};

/** The message to show for a read that did not happen. Never a substitute for `isNotYet`. */
export const readFailure = (e: unknown): string =>
  e instanceof Error ? e.message : String(e);

const get = <T>(path: string): Promise<T> => fetch(ROOT + path).then((r) => handle<T>(r));

const post = <T>(path: string, body: unknown): Promise<T> =>
  fetch(ROOT + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...actorHeaders() },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));

const put = <T>(path: string, body: unknown): Promise<T> =>
  fetch(ROOT + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...actorHeaders() },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));

const del = <T>(path: string): Promise<T> =>
  fetch(ROOT + path, { method: "DELETE", headers: actorHeaders() }).then((r) => handle<T>(r));

// --- the bridge -------------------------------------------------------------
// Mounted at /bridge, not under /client-boq, so it needs its own root — everything else (the
// error shape, the actor header, the typing style) is identical. The bridge belongs to neither
// product: it carries one tender from this review into the procurement routing fork.
const BRIDGE = `${BASE}/bridge`;

const bget = <T>(path: string): Promise<T> => fetch(BRIDGE + path).then((r) => handle<T>(r));

const bpost = <T>(path: string, body: unknown): Promise<T> =>
  fetch(BRIDGE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...actorHeaders() },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));

const setPath = (setId: string) => `/${encodeURIComponent(setId)}`;

// --- procurement's own endpoints (sourcing) ---------------------------------
// At the bare BASE — /shortlist, /dispatch and friends are mounted at the root, under neither
// prefix. Reached through this client rather than by importing src/api.ts: one product, one
// client. Note src/api.ts throws a bare Error with no `.status`; going through `handle` here means
// a gate refusal keeps its status code, which is the whole reason this file has its own error shape.
const rget = <T>(path: string): Promise<T> => fetch(BASE + path).then((r) => handle<T>(r));

const rpost = <T>(path: string, body: unknown): Promise<T> =>
  fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...actorHeaders() },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));

/** Is this backend in DEMO mode? Drives the app-bar chip, which is not decoration: it means
 *  uploaded files were not read and every finding on screen came from a fixture. */
/** `review_gate` is `"soft"` (the V1 default) or `"hard"`. Soft means an unapproved register no
 *  longer blocks routing or pricing — it warns — so the step chips must stop saying those steps
 *  are waiting on it. Optional in the type because an older server does not send it, and the
 *  safe reading of a missing value is the stricter one. */
export const health = (): Promise<{ status: string; demo_mode: boolean; review_gate?: string }> =>
  fetch(`${BASE}/health`).then((r) => handle(r));

export const api = {
  // --- sets ----------------------------------------------------------------
  sets: (includeArchived = false) =>
    get<{ count: number; sets: SetRow[] }>(
      includeArchived ? "/sets?include_archived=true" : "/sets",
    ),
  /** The acceptable-terms library. Lets a register row say what `PS-01` actually means. */
  criteria: () => get<CriteriaResponse>("/criteria"),
  gate: (setId: string) => get<GateState>(`/gate/${setId}`),

  // --- the tender desk ------------------------------------------------------
  team: (includeArchived = false) =>
    get<{ count: number; members: TeamMember[] }>(
      includeArchived ? "/team?include_archived=true" : "/team",
    ),
  addTeamMember: (member: { name: string; initials?: string; colour?: string; role?: string }) =>
    post<{ member: TeamMember }>("/team", member),
  updateTeamMember: (memberId: string, member: Partial<TeamMember> & { name: string }) =>
    post<{ member: TeamMember }>(`/team/${memberId}`, member),
  /** Desk fields only. The close-date finding is deliberately not writable here. */
  setMeta: (
    setId: string,
    patch: { owner_id?: string; client?: string; package?: string; archived?: boolean; outcome?: string },
  ) => post<{ set_id: string; meta: SetMeta }>(`/sets/${setId}/meta`, patch),
  /** A person confirms the close date by hand — the only writer of a typed date. */
  confirmCloseDate: (setId: string, date: string, queryCutoff = "") =>
    post<{ set_id: string; meta: SetMeta }>(`/sets/${setId}/close-date`, {
      date,
      query_cutoff: queryCutoff,
    }),

  // --- criteria & rates editing ---------------------------------------------
  addCriterion: (body: {
    category_id: string;
    clause_area: string;
    acceptable_position?: string;
    why_it_matters?: string;
    red_flag?: string;
  }) => post<{ criterion: CriterionRow }>("/criteria", body),
  updateCriterion: (
    id: string,
    patch: {
      clause_area?: string;
      acceptable_position?: string;
      why_it_matters?: string;
      red_flag?: string;
      enabled?: boolean;
    },
  ) => post<{ criterion: CriterionRow }>(`/criteria/${id}`, patch),
  rates: () => get<RatesResponse>("/rates"),
  addRate: (body: {
    rate_id: string;
    category?: string;
    description?: string;
    unit?: string;
    rate: number;
    currency?: string;
    notes?: string;
  }) => post<{ rate: RateRowFull }>("/rates", body),
  updateRate: (
    rateId: string,
    patch: { category?: string; description?: string; unit?: string; rate?: number; currency?: string; notes?: string },
  ) => post<{ rate: RateRowFull }>(`/rates/${rateId}`, patch),
  /** Archive, never delete — the response's note states the missing_rate consequence. */
  archiveRate: (rateId: string) => del<{ rate: RateRowFull; note: string }>(`/rates/${rateId}`),

  // --- the output book ------------------------------------------------------
  outputs: () => get<OutputsResponse>("/library/outputs"),
  setOutputNorm: (key: string, value: number) =>
    post<{ key: string; value: number; default: number }>(`/library/outputs/${key}`, { value }),
  /** Forget your value and go back to the shipped default. A norm cannot be archived the way a
   *  rate can — the engine reads it whatever happens — so this is the only meaningful undo. */
  resetOutputNorm: (key: string) =>
    del<{ key: string; value: number; default: number; source: string }>(`/library/outputs/${key}`),

  // --- the bill: choosing one, without uploading it again --------------------
  /** Every workbook in this set's upload that reads as a bill of quantities. */
  billCandidates: (setId: string) =>
    get<{ set_id: string; count: number; candidates: BillCandidate[] }>(
      `/boq/${setId}/candidates`,
    ),
  /** Import one of them by its path inside the set — the file is already on the server. */
  importBillFromSet: (setId: string, relativePath: string) =>
    post<{ set_id: string; rev: number; items: number; priceable: number }>(
      `/boq/${setId}/import-from-set`,
      { relative_path: relativePath },
    ),

  // --- the costing engine ---------------------------------------------------
  costing: (setId: string) => get<CostingResponse>(`/costing/${setId}`),
  /** Point one item at what should price it — a build-up, a lab rate, or a site resource.
   *  All three empty clears the override and puts the app's own proposal back. */
  setItemBasis: (
    setId: string,
    fullRef: string,
    keys: { basis_key?: string; lab_key?: string; prelim_key?: string },
  ) =>
    post<{ full_ref: string; cleared: boolean }>("/costing/item-basis", {
      set_id: setId,
      full_ref: fullRef,
      ...keys,
    }),
  /** The deliverable: eight sheets with their formulas intact, so it still calculates in Excel. */
  costingWorkbookUrl: (setId: string) => `${ROOT}/costing/${setId}/workbook.xlsx`,
  /** Type a rate over the rounded proposal. `null` puts the proposal back. */
  setSubmittedRate: (setId: string, fullRef: string, rate: number | null) =>
    post<{ full_ref: string; rate: number | null; by: string }>("/costing/rate", {
      set_id: setId,
      full_ref: fullRef,
      rate,
    }),
  /** Type over the NUMBER a register row is about. Writes the model path the row names, so the
   *  programme, the rig curve, the group durations and every rate recompute from it. Copy-on-write:
   *  the first one makes this tender's model its own. */
  setAssumptionValue: (setId: string, key: string, value: number) =>
    post<{
      key: string;
      path: string;
      was: string;
      value: number;
      now: string;
      recomputed: { work_days: number; rigs_required: number; proposal_n: number | null; total: number };
      problems: string[];
    }>("/costing/assumption-value", { set_id: setId, key, value }),
  conditions: (setId: string) => get<ConditionsResponse>(`/costing/${setId}/conditions`),
  /** Ask about ONE tender, answered only from its own ground. See `boq/ask.py` for what the
   *  answer's shape refuses to let it say. */
  ask: (setId: string, question: string) =>
    post<AskResponse>("/costing/ask", { set_id: setId, question }),
  /** Record a condition AND ask the model which knob it moves. Recording is unconditional; the
   *  mapping is a proposal and writes nothing. */
  addCondition: (setId: string, text: string, note = "") =>
    post<{ condition: ConditionRow; proposal: Record<string, unknown>; awaiting: string }>(
      "/costing/conditions",
      { set_id: setId, text, note },
    ),
  /** The ONLY call that writes the model from a condition. `value` overrides the proposal. */
  decideCondition: (setId: string, conditionId: string, status: string, value?: number) =>
    post<{ condition: ConditionRow; applied: number | null }>("/costing/conditions/decide", {
      set_id: setId,
      condition_id: conditionId,
      status,
      ...(value === undefined ? {} : { value }),
    }),
  deleteCondition: (setId: string, conditionId: string) =>
    del<{ deleted: boolean; note: string }>(`/costing/${setId}/conditions/${conditionId}`),
  setAssumptionVerdict: (setId: string, key: string, status: string, comment = "") =>
    post<{ key: string; status: string; gate: string; outstanding: number }>(
      "/costing/assumption",
      { set_id: setId, key, status, comment },
    ),
  /** Copy-on-write: this is the call that makes the tender's model its own. */
  saveSetCostingModel: (setId: string, model: CostingModelShape) =>
    put<{ marks: Record<string, string>; problems: string[]; using_own_model: boolean }>(
      `/costing/${setId}/model`,
      { model },
    ),
  resetSetCostingModel: (setId: string) =>
    del<{ using_own_model: boolean; note: string }>(`/costing/${setId}/model`),
  /** THE LIBRARY's model — the company default every new tender inherits. Saving it changes every
   *  FUTURE tender and rewrites none already priced. Not the same call as the tender-level one
   *  above, and deliberately on a different screen. */
  libraryCostingModel: () => get<LibraryModelResponse>("/costing/model"),
  saveLibraryCostingModel: (model: CostingModelShape) =>
    put<{ model: CostingModelShape; problems: string[] }>("/costing/model", { model }),

  // --- the take-off (Site) --------------------------------------------------
  stationSchedule: (setId: string) => get<StationScheduleResponse>(`/site/${setId}/schedule`),
  /** Read a pasted table into a PROPOSED schedule. Saves nothing — see `saveStationSchedule`. */
  parseStationSchedule: (setId: string, text: string, sourceSheet = "") =>
    post<SchedulePasteResponse>("/site/schedule/parse", {
      set_id: setId,
      text,
      source_sheet: sourceSheet,
    }),
  /**
   * Read the take-off off the borehole details drawing(s). Hand it the drawing folder — it works
   * out which sheets carry a station table before opening any of them, off the drawing register's
   * own text layer, and it reads BOTH: the engineering schedule and the environmental one, which
   * are billed separately. Returns a proposal; saves nothing.
   */
  readStationSchedule(setId: string, files: File[]): Promise<ScheduleReadResponse> {
    const form = new FormData();
    form.append("set_id", setId);
    for (const file of files) form.append("files", file);
    return fetch(`${ROOT}/site/schedule/read`, { method: "POST", body: form }).then((r) =>
      handle<ScheduleReadResponse>(r),
    );
  },
  /** The writer that existed from the beginning and that nothing in this app ever called. */
  saveStationSchedule: (setId: string, schedule: StationScheduleShape, sourceSheet = "") =>
    post<{ set_id: string; usable: boolean; problems: string[] }>("/site/schedule", {
      set_id: setId,
      schedule,
      source_sheet: sourceSheet,
    }),
  derived: (setId: string) => get<DerivedResponse>(`/site/${setId}/derived`),
  holeGroups: (setId: string) => get<GroupsResponse>(`/site/${setId}/groups`),
  // --- site photographs -----------------------------------------------------
  sitePhotos: (setId: string) =>
    get<{ set_id: string; photos: PhotoRow[]; count: number }>(`/site/${setId}/photos`),
  sitePhotoUrl: (setId: string, photoId: string) =>
    `${ROOT}/site/${setId}/photos/${photoId}/file`,
  uploadSitePhoto(setId: string, file: File, caption = "", station = ""): Promise<{ photo: PhotoRow }> {
    const form = new FormData();
    form.append("set_id", setId);
    form.append("caption", caption);
    form.append("station", station);
    form.append("file", file);
    return fetch(`${ROOT}/site/photos`, {
      method: "POST",
      body: form,
      headers: actorHeaders(),
    }).then((r) => handle<{ photo: PhotoRow }>(r));
  },
  /** Vision over the photographs, alongside the schedule and the captions. Produces observations
   *  that name their photograph — never a class and never a cost. */
  readSitePhotos: (setId: string) =>
    post<PhotoReadResponse>(`/site/${setId}/photos/read`, {}),
  deleteSitePhoto: (setId: string, photoId: string) =>
    del<{ deleted: boolean; note: string }>(`/site/${setId}/photos/${photoId}`),
  /** The access board: proximity clusters over the map, and the evidence for reaching each. It
   *  assembles and never concludes — `proposed_class` comes back "" on every cluster. */
  accessBoard: (setId: string, radiusM?: number) =>
    get<AccessBoardResponse>(
      `/site/${setId}/access${radiusM ? `?radius_m=${radiusM}` : ""}`,
    ),
  /** Class one hole. "" un-decides it; C says in its note that it has no bill item to sit on. */
  setStationClass: (setId: string, station: string, accessClass: string) =>
    post<{ counts: Record<string, number>; decided_by: string; note: string }>("/site/class", {
      set_id: setId,
      station,
      access_class: accessClass,
    }),
  saveGroup: (setId: string, groupId: string, group: Partial<HoleGroup>) =>
    post<{ group: HoleGroup; ready: string[] }>("/site/group", {
      set_id: setId,
      group_id: groupId,
      group,
    }),
  deleteGroup: (setId: string, groupId: string) =>
    del<{ deleted: boolean; note: string }>(`/site/${setId}/group/${groupId}`),
  /** Days and the blend as you type. A round trip on purpose: the day-by-day simulation is the
   *  load-bearing calculation here, and a second copy of it in TypeScript would eventually
   *  disagree with the first with no way to tell which was right. It never prices. */
  previewGroup: (setId: string, group: Partial<HoleGroup>) =>
    post<GroupPreview>("/site/preview", { set_id: setId, group }),

  // --- demo or live ---------------------------------------------------------
  /** Which mode the whole app is in, where that came from, and what live would need.
   *
   *  Read this rather than `health().demo_mode` when the answer has to be current: the operator
   *  can change it mid-session, and `health` is fetched once at start-up. */
  mode: () => get<ModeResponse>("/mode"),
  /** Switch the app. `demo: null` gives the decision back to the deployment's own default.
   *
   *  Going LIVE requires `confirm: "LIVE"` and a configured key, and the server refuses with a
   *  409 naming the variable to set — going live decides whether outbound email is real and
   *  whether a token is spent, so it is never one click. Going back to demo is never refused. */
  setMode: (demo: boolean | null, confirm = "") =>
    post<ModeResponse & { changed_by: string }>("/mode", { demo, confirm }),

  // --- app-wide settings (the AI model) -------------------------------------
  settings: () => get<LLMSettingsResponse>("/settings"),
  saveSettings: (body: {
    provider: string;
    provider_ingest?: string;
    provider_drawing?: string;
    model_drawing?: string;
    model_anthropic?: string;
    model_deepseek?: string;
    model_openai?: string;
  }) =>
    post<LLMSettingsResponse>("/settings", {
      provider_ingest: "",
      provider_drawing: "",
      model_drawing: "",
      model_anthropic: "",
      model_deepseek: "",
      model_openai: "",
      ...body,
    }),

  // --- ingest & the manifest gate ------------------------------------------
  upload(files: File[], projectName: string): Promise<JobState> {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("project_name", projectName);
    return fetch(`${ROOT}/ingest/upload`, {
      method: "POST",
      body: form,
      headers: actorHeaders(),
    }).then((r) => handle<JobState>(r));
  },
  /** A folder that is already organised: each file becomes its own part, nothing is split.
   *
   *  The paths ride as their own field because a browser does not transmit
   *  `webkitRelativePath` over multipart — without them, two `BQ.pdf` in different subfolders
   *  arrive as one name and the second overwrites the first. The server pairs them by position. */
  uploadFolder(picked: { file: File; path: string }[], projectName: string): Promise<JobState> {
    const form = new FormData();
    picked.forEach(({ file, path }) => {
      form.append("files", file);
      form.append("relative_paths", path);
    });
    form.append("project_name", projectName);
    form.append("layout", "folder");
    return fetch(`${ROOT}/ingest/upload`, {
      method: "POST",
      body: form,
      headers: actorHeaders(),
    }).then((r) => handle<JobState>(r));
  },
  ingestStatus: (jobId: string) => get<JobState>(`/ingest/status/${jobId}`),
  manifest: (setId: string) => get<Manifest>(`/ingest/manifest/${setId}`),
  /** Gate 1. `parts` omitted approves the draft as-is; supplying it replaces the split, which
   *  is re-validated against the real page count before anything is stored. */
  approveManifest: (setId: string, parts?: PartSpec[], approved = true) =>
    post<ManifestGateState>("/ingest/manifest/approve", { set_id: setId, parts, approved }),
  split: (setId: string) => post<JobState>("/ingest/split", { set_id: setId }),

  /** Ask a running job to stop at its next stage boundary. ONE endpoint for every workflow,
   *  because there is one job store. It is a request, not a kill — the work between boundaries is
   *  a blocking model call the server cannot interrupt — so what it buys is that the next call is
   *  never started. On a ~100-call run that is nearly all of the saving. */
  cancelJob: (jobId: string) =>
    post<JobState>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {}),

  // --- parts ---------------------------------------------------------------
  parts: (setId: string) => get<PartsResponse>(`/ingest/parts/${setId}`),
  part: (setId: string, partId: string) => get<PartDetail>(`/ingest/parts/${setId}/${partId}`),
  downloadUrl: (setId: string) => `${ROOT}/ingest/${setId}/download`,

  // --- the document pane ---------------------------------------------------
  /** `page` is a SOURCE-document page number — the same numbering as manifest ranges,
   *  citation pages and highlight rectangles. There is deliberately only one convention. */
  pageUrl: (setId: string, partId: string, page: number, dpi = 110) =>
    `${ROOT}/ingest/parts/${setId}/${partId}/page/${page}.png?dpi=${dpi}`,
  search: (setId: string, partId: string, q: string) =>
    get<SearchResponse>(`/ingest/parts/${setId}/${partId}/search?q=${encodeURIComponent(q)}`),
  /** Read one part again — the retry for a scan that came back unread. The split is untouched. */
  reinterpret: (setId: string, partId: string) =>
    post<{ set_id: string; part_id: string; readable: boolean; context: PartContext }>(
      `/ingest/parts/${setId}/${partId}/reinterpret`,
      {},
    ),
  /** Correct a part's context card. Saving stamps it `user` server-side. `readable` is not
   *  editable — whether a page has a text layer is a measurement, not an opinion. */
  saveContext: (
    setId: string,
    partId: string,
    patch: {
      summary?: string;
      key_points?: string[];
      obligations?: string[];
      commercial_flags?: string[];
      notes?: string;
    },
  ) =>
    post<{ set_id: string; part_id: string; context: PartContext }>(
      `/ingest/parts/${setId}/${partId}/context`,
      patch,
    ),
  /** Where a quoted claim actually sits in this part. Same three verdicts as a citation. */
  locateQuote: (setId: string, partId: string, quote: string) =>
    post<{
      verdict: "located" | "unverifiable" | "not_located";
      page: number | null;
      match?: string;
      highlights: Highlight[];
      note: string;
    }>(`/ingest/parts/${setId}/${partId}/locate`, { quote }),
  /** Where a quoted claim sits **anywhere in the set**, and in which part.
   *
   *  What "show me on the page" needs. The per-part call above can only answer about the document
   *  already open, which on a folder set means it says "not found" for every part but the one
   *  holding the words — leaving the reader to find the right file themselves, which is the work
   *  the button exists to do. `preferPartId` is only a head start on the search order. */
  locateQuoteInSet: (setId: string, quote: string, preferPartId?: string) =>
    post<{
      verdict: "located" | "unverifiable" | "not_located";
      part_id: string;
      part_title: string;
      page: number | null;
      match?: string;
      highlights: Highlight[];
      note: string;
    }>(`/ingest/${setId}/locate`, { quote, prefer_part_id: preferPartId ?? "" }),

  // --- review --------------------------------------------------------------
  /** `includeSpecifications` reads the specification tree too. Off by default: on a real
   *  government pack that category is most of the set and is mostly appendices — borehole logs,
   *  test schedules — which carry no contractual position. The deferred parts are named in the
   *  run's notes rather than dropped, so this is a reversible choice, not a silent exclusion. */
  runReview(setId: string, projectName: string, includeSpecifications = false): Promise<JobState> {
    const form = new FormData();
    form.append("project_name", projectName);
    form.append("set_id", setId);
    form.append("include_specifications", String(includeSpecifications));
    return fetch(`${ROOT}/review/run`, { method: "POST", body: form }).then((r) =>
      handle<JobState>(r),
    );
  },
  reviewStatus: (jobId: string) => get<JobState>(`/review/status/${jobId}`),
  /** Whatever this set is doing right now, of any kind — `job_id: null` when nothing is.
   *
   *  The screen's recovery route. Every other status call needs a job id, which a freshly loaded
   *  browser does not have: the id lived in a poll loop belonging to a component that unmounted.
   *  So a review ran on the server while the Register tab rendered a Run button, and pressing it
   *  produced a 409 the UI had invited. Never 404s — "no job" is a state, not an error. */
  liveJob: (setId: string) => get<JobState>(`/jobs/live/${encodeURIComponent(setId)}`),
  /** EVERY job in flight for a set, oldest first.
   *
   *  The plural exists because the server pool is two wide: an ingest and a review genuinely run
   *  at the same time, so a singular answer was being asked to carry a choice it could not make.
   *  The shell picks the job belonging to the tab in view, and where more than one is live it says
   *  so rather than silently presenting one as the answer. */
  liveJobs: (setId: string) =>
    get<{ set_id: string; jobs: JobState[] }>(`/jobs/live-all/${encodeURIComponent(setId)}`),
  register: (setId: string) => get<RegisterResponse>(`/review/register/${setId}`),
  citations: (setId: string) => get<CitationsResponse>(`/review/${setId}/citations`),
  /** Gate 2. The only writer of a verdict. `approved: false` records verdicts without
   *  closing the register, which is what every per-row Confirm/Dismiss does — closing is a
   *  separate, deliberate act with its own button. `negotiations` writes what you will ask for
   *  instead, and is independent of any verdict. */
  approveReview: (
    setId: string,
    decisions: Record<number, string>,
    approved: boolean,
    negotiations: Record<number, string> = {},
  ) =>
    post<GateState>("/review/approve", {
      set_id: setId,
      decisions,
      negotiations,
      approved,
    }),

  // --- RFI -----------------------------------------------------------------
  rfis: (setId: string) => get<RFIsResponse>(`/rfi/${setId}`),
  raiseRfi: (body: {
    set_id: string;
    question: string;
    origin?: string;
    register_item?: number | null;
    part_id?: string;
    clause?: string;
    page?: number | null;
    context?: string;
  }) => post<{ set_id: string; rfi: RFIItem; open_queries: number }>("/rfi", body),
  /** Take a draft question out of its build. A withdrawal, not a delete — and the draft text it
   *  came from lives on the register line, so it survives. */
  withdrawRfi: (setId: string, rfiId: string) =>
    del<{ set_id: string; rfi: RFIItem; open_queries: number }>(`/rfi/${setId}/${rfiId}`),
  /** Batch the queued questions into one numbered letter and mark them sent. */
  sendRfiBatch: (setId: string, ref: string, rfiIds: string[]) =>
    post<{ set_id: string; batch: RFIBatchRow; letter_md: string }>("/rfi/batch", {
      set_id: setId,
      ref,
      rfi_ids: rfiIds,
    }),

  // --- documents & revisions ----------------------------------------------
  revisions: (setId: string) =>
    get<{ set_id: string; documents: DocumentRow[]; revisions: RevisionRow[] }>(
      `/revisions/${setId}`,
    ),
  revisionsWorkbookUrl: (setId: string) => `${ROOT}/revisions/${setId}/workbook`,

  // --- estimate scope (gate 3) --------------------------------------------
  scope: (setId: string) => get<ScopeResponse>(`/estimate/scope/${setId}`),
  runScope: (setId: string) => post<JobState>("/estimate/scope", { set_id: setId }),
  estimateStatus: (jobId: string) => get<JobState>(`/estimate/status/${jobId}`),
  approveScope: (setId: string, approved = true, amendedSummary?: string) =>
    post<ScopeGateState>("/estimate/scope/approve", {
      set_id: setId,
      approved,
      amended_summary: amendedSummary,
    }),

  // --- the scope of record, item by item (the freeze gate) ----------------
  /** What the scope could be built from, and what it already is. Sources are DERIVED on every
   *  read from the register, the open questions and the change log — never stored, so they
   *  cannot go stale behind a changed verdict. */
  scopeSources: (setId: string) => get<ScopeSourcesResponse>(`/estimate/scope/${setId}/sources`),
  mapScope: (setId: string, sourceRef: string, section?: ScopeSection) =>
    post<{ item: ScopeItem } & ScopeItemsResponse>("/estimate/scope/map", {
      set_id: setId,
      source_ref: sourceRef,
      section,
    }),
  /** Edit / accept a fallback / take ownership. Editing always stamps `user` server-side. */
  updateScopeItem: (
    setId: string,
    itemId: string,
    patch: { text?: string; section?: ScopeSection; accept?: boolean; convert_to_user?: boolean },
  ) =>
    post<{ item: ScopeItem } & ScopeItemsResponse>("/estimate/scope/item", {
      set_id: setId,
      item_id: itemId,
      ...patch,
    }),
  // --- the priced estimate (gate 3 must be passed) -------------------------
  /** Run the deterministic cost spine. Refuses with a 409 until BOTH the register and the scope
   *  are approved — two distinct messages, and the tab shows whichever one came back rather than
   *  inventing its own. In DEMO the schedule and margin come from the fixture and it runs inline;
   *  in LIVE both are required and the work happens on a thread, which is why this goes through
   *  `runJob` like every other job start. */
  runEstimate: (setId: string, body?: { margin_pct?: number; schedule?: unknown; letter?: unknown }) =>
    post<JobState>("/estimate/run", { set_id: setId, ...(body ?? {}) }),
  estimate: (setId: string) => get<EstimateResponse>(`/estimate/${setId}`),
  /** The schedule a live estimate is run FROM. `saved: false` means this tender has never had
   *  one — the editor opens empty rather than erroring. */
  schedule: (setId: string) => get<ScheduleResponse>(`/estimate/schedule/${setId}`),
  saveSchedule: (setId: string, schedule: EstimateScheduleInput, marginPct: number) =>
    post<ScheduleResponse>("/estimate/schedule", {
      set_id: setId,
      schedule,
      margin_pct: marginPct,
    }),
  /** The app-wide letterhead. The client and project are NOT here — they come from the tender's
   *  own desk metadata, so they are never typed twice. */
  saveCompany: (company: CompanySettings) => post<LLMSettingsResponse>("/company", company),
  workbookUrl: (setId: string) => `${ROOT}/estimate/${setId}/workbook`,

  // --- the offer letter ----------------------------------------------------
  /** The assembled draft. Nothing sends it — there is no transmit path in this product at all. */
  letter: (setId: string) => get<LetterResponse>(`/estimate/${setId}/letter`),
  /** The assumptions the price rests on. `internal` carries each line's source; `submission`
   *  adds the tender's own warning clause, because qualifying a bid can disqualify it. */
  qualificationsUrl: (setId: string, audience: "internal" | "submission" = "internal") =>
    `${ROOT}/estimate/${setId}/qualifications?audience=${audience}`,
  departureScheduleUrl: (setId: string, audience: "internal" | "submission" = "internal", fmt = "md") =>
    `${ROOT}/review/${setId}/departure-schedule?audience=${audience}&format=${fmt}`,

  unmapScope: (setId: string, itemId: string) =>
    del<ScopeItemsResponse>(`/estimate/scope/item/${setId}/${itemId}`),

  // --- the bridge: this review -> the procurement routing fork --------------
  // set_id IS the procurement run_ref, so every call here is keyed by the same id the desk uses.
  bridge: {
    /** A ZIP of the whole tender pack. Streams to disk a chunk at a time on the server, checks the
     *  uncompressed size from the central directory BEFORE extracting anything, and returns a
     *  PROPOSED manifest. Extracts nothing — `archiveExtract` does that, after the same manifest
     *  gate a single PDF passes.
     *
     *  This endpoint has existed and worked since it was written, and nothing in this application
     *  ever called it: a dropped .zip was filtered out client-side with "Drop a PDF", so a 230 MB
     *  pack produced a banner and no network request at all. */
    archiveUpload(file: File, projectName = ""): Promise<ArchiveUploadResponse> {
      const form = new FormData();
      form.append("file", file);
      form.append("project_name", projectName);
      return fetch(`${BRIDGE}/archive/upload`, { method: "POST", body: form }).then((r) =>
        handle<ArchiveUploadResponse>(r),
      );
    },
    /** Extract the approved pack, as a job on the same pool with the same STOP. 409s until the
     *  manifest is approved. */
    archiveExtract: (setId: string) => bpost<JobState>("/archive/extract", { set_id: setId }),
    /** Every part in the set, with which one(s) are PROPOSED as the priced bill. Proposing is not
     *  confirming: the category comes from an AI interpretation stage, so a human picks. 404s only
     *  when the set has no parts at all. */
    candidates: (setId: string) =>
      bget<BqCandidates>(`${setPath(setId)}/bq-candidates`),

    /** Confirm the SET of bill parts — several are legitimate (a bill of quantities AND a daywork
     *  schedule are both priceable). 400 on an unknown id or an empty selection. */
    confirmBillParts: (setId: string, partIds: string[]) =>
      bpost<BqCandidates>(`${setPath(setId)}/bq-part`, { part_ids: partIds }),

    /** Run the bill split. 409 until a bill part is confirmed — the message names bq-part; also
     *  409 when a split is already running for this set.
     *
     *  Answers in ONE of two shapes. DEMO has nothing to wait for and returns the finished payload
     *  directly. Live returns a job envelope — the split reads every part's pdf and indexes ~170
     *  documents on the real pack, which is minutes — and the finished `result` is byte-for-byte
     *  that same payload. `runSplitToCompletion` below is the caller that does not care which. */
    runSplit: (setId: string) =>
      bpost<BridgeSplitResponse | JobState>(`${setPath(setId)}/scope`, {}),
    /** Run the split and hand back the finished payload, whichever shape the server answered in.
     *
     *  `onJob` sees every poll, so the caller can render the stage and the N/M the way the ingest
     *  and review screens already do. A cancelled split resolves to `null` — it is a decision the
     *  operator made, not an error to put a red banner over. */
    async runSplitToCompletion(
      setId: string, onJob?: (job: JobState) => void,
    ): Promise<BridgeSplitResponse | null> {
      const first = await api.bridge.runSplit(setId);
      if ("scope" in first) return first as BridgeSplitResponse;   // DEMO answered inline
      let job = first as JobState;
      onJob?.(job);
      while (job.job_id && (job.status === "queued" || job.status === "running")) {
        await new Promise((r) => setTimeout(r, 1500));
        job = await api.ingestStatus(job.job_id);
        onJob?.(job);
      }
      if (job.status === "cancelled") return null;
      if (job.status === "error") throw new Error(job.error || "The scope split failed.");
      return (job.result ?? null) as BridgeSplitResponse | null;
    },

    /** The persisted split. 404 before it has been run. */
    split: (setId: string) => bget<BridgeSplitRead>(`${setPath(setId)}/scope`),

    /** Propose a route per package. 409 until the review register is approved — the backend's own
     *  sentence names the gate and how to clear it, and `.status` on the thrown Error is what lets
     *  the tab tell that apart from a real failure. */
    analyzeRoutes: (setId: string) =>
      bpost<BridgeRouteProposal>(`${setPath(setId)}/route/analyze`, {}),

    /** A PURE read — it never re-runs the analysis, which would be a write and, live, a model
     *  call. Empty `packages` means "not yet run", which is a state, not an error. */
    proposal: (setId: string) =>
      bget<BridgeRouteProposalRead>(`${setPath(setId)}/route/proposal`),

    /** A pure read. No decisions yet is an empty list, not a 404. */
    decisions: (setId: string) =>
      bget<BridgeRouteDecisions>(`${setPath(setId)}/route/decisions`),

    /** The Layer-4 gate: record the human's route per package. Seeds no estimate on either side. */
    confirmRoutes: (
      setId: string,
      decisions: { package_key: string; chosen_route: string }[],
    ) => bpost<BridgeRouteDecisions>(`${setPath(setId)}/route/confirm`, { decisions }),

    // --- the back of the funnel: final approval, then submission (nodes 46–48) ---
    /** Approval + submission + deadline + whether a letter exists to submit. A pure read; every
     *  field is a state and nothing 404s. */
    submission: (setId: string) =>
      bget<BridgeSubmissionState>(`${setPath(setId)}/submission`),

    /** The tender's last human gate: `approve` or `revise`. A `revise` MUST say what to correct
     *  (400 otherwise). The verdict is the human's — recorded, nothing else. */
    finalApproval: (
      setId: string, verdict: "approve" | "revise", rationale = "", approvedBy?: string,
    ) => bpost<BridgeFinalApproval>(`${setPath(setId)}/final-approval`, {
      verdict, rationale, ...(approvedBy ? { approved_by: approvedBy } : {}),
    }),

    /** Freeze the offer and record the submission. 409 (naming the missing approval) unless a
     *  final `approve` exists — a hard precondition. `proof` is stored verbatim, never invented. */
    submit: (setId: string, proof: string, submittedBy?: string) =>
      bpost<BridgeSubmissionRecord>(`${setPath(setId)}/submit`, {
        proof, ...(submittedBy ? { submitted_by: submittedBy } : {}),
      }),

    // --- the award + the combined tender total (node 43) ---
    /** Record which firm won a sublet package, at the levelled total of the return the human
     *  chose. 400 for a self-perform package — the double-count front door. */
    award: (setId: string, packageKey: string, firmId: string, firmName: string,
            total: number | null) =>
      bpost<BridgeAward>(`${setPath(setId)}/award`, {
        package_key: packageKey, firm_id: firmId, firm_name: firmName, total,
      }),

    /** Withdraw an award (skip pressed, or re-levelling). Idempotent. */
    clearAward: (setId: string, packageKey: string) =>
      fetch(`${BRIDGE}${setPath(setId)}/award/${encodeURIComponent(packageKey)}`, {
        method: "DELETE", headers: actorHeaders(),
      }).then((r) => handle<{ cleared: boolean }>(r)),

    awards: (setId: string) =>
      bget<{ set_id: string; awards: BridgeAward[] }>(`${setPath(setId)}/awards`),

    /** One tender total from both engines — a pure read; nothing rewrites the offer. */
    combinedPricing: (setId: string) =>
      bget<BridgeCombinedPricing>(`${setPath(setId)}/combined-pricing`),

    // --- the FIRST decision: bid / no-bid ---------------------------------
    /** The bid brief — navy signals with their sources, a brass recommendation with its reasons,
     *  and the human's decision if one exists. A pure read; opening it decides nothing. */
    bid: (setId: string) => bget<BidBrief>(`${setPath(setId)}/bid`),

    /** Record the verdict. `no_bid` and `clarify` must say why (400 otherwise). `factors` are the
     *  operator's own strategic judgement, stored verbatim — nothing computes any of it. */
    confirmBid: (setId: string, verdict: string, rationale = "",
                 factors: Record<string, string> = {}) =>
      bpost<BidDecision>(`${setPath(setId)}/bid/confirm`, { verdict, rationale, factors }),

    // --- closeout: outcome, lessons, change-control, handover (nodes 49–53) ---
    /** Outcome + lessons + events + whether a handover is meaningful. A pure read; nothing 404s. */
    closeout: (setId: string) =>
      bget<BridgeCloseoutState>(`${setPath(setId)}/closeout`),

    /** Record the tender outcome (did WE win — NOT the sublet award). A won/lost also feeds the
     *  benchmark corpus. `notes` are the human's. */
    setOutcome: (setId: string, status: string, notes = "") =>
      bpost<{ outcome: BridgeOutcome; corpus: { fed: boolean; benchmark_project_id: number | null } }>(
        `${setPath(setId)}/outcome`, { status, notes }),

    /** Add one human-authored lesson (400 on an empty note). */
    addLesson: (setId: string, category: string, lesson: string) =>
      bpost<BridgeLesson>(`${setPath(setId)}/lessons`, { category, lesson }),
    lessons: (setId: string) =>
      bget<{ set_id: string; lessons: BridgeLesson[] }>(`${setPath(setId)}/lessons`),

    /** Append one change-control entry (400 on an empty detail). */
    logEvent: (setId: string, kind: string, detail: string) =>
      bpost<BridgePostSubmissionEvent>(`${setPath(setId)}/post-submission`, { kind, detail }),
    events: (setId: string) =>
      bget<{ set_id: string; events: BridgePostSubmissionEvent[] }>(`${setPath(setId)}/post-submission`),

    /** The assembled handover projection — a preview before won, ready after. */
    handover: (setId: string) =>
      bget<BridgeHandover>(`${setPath(setId)}/handover`),

    /** Does a document index exist for this tender, when was it built, over how many documents.
     *
     *  The dispatch gate's precondition, made visible. Without an index every enquiry carries the
     *  generated pricing sheet instead of the bill sliced to its section, and no specification at
     *  all — which is what happened live when the split ran under one slug and the drafts were
     *  assembled under another. Never 404s: "no index" is the answer this exists to give. */
    docIndex: (setId: string) => bget<DocIndexState>(`${setPath(setId)}/doc-index`),

    /** The stored SHORTLIST — the candidates, not the ticks. `shortlist: null` means it has never
     *  been run for this set; never a 404.
     *
     *  Persisting the ticks was useless without this: `shortlist` was React state, so after a
     *  refresh the restored selection had no candidate list to land on and the operator re-ran a
     *  148-firm screen to get back where they already were. */
    shortlist: (setId: string) =>
      bget<{ set_id: string; shortlist: ShortlistSet | null; created_at: string }>(
        `${setPath(setId)}/shortlist`),

    /** Store the computed shortlist. NOT an approval and not the dispatch gate — it records the
     *  candidates, which are a deterministic Layer-1 answer, so a refresh does not throw them away. */
    saveShortlist: (setId: string, shortlist: ShortlistSet) =>
      bpost<{ set_id: string; stored: boolean }>(`${setPath(setId)}/shortlist`, { shortlist }),

    /** The persisted shortlist selection for a set — `{package_key: [firm_id, …]}`. Empty is a
     *  legitimate answer (nothing selected yet), never a 404. */
    approvals: (setId: string) =>
      bget<{ set_id: string; approvals: Record<string, string[]> }>(`${setPath(setId)}/approvals`),

    /** Record the selection so a reload does not lose it.
     *
     *  NOT the dispatch gate: nothing is composed, drafted or sent, and the operator still presses
     *  Compose/Prepare on the Dispatch step. This only stops the selection evaporating between the
     *  click and the decision. Replaces the stored list for every package named in the payload, so
     *  a deselection persists too — an empty list means "none of them", which is a decision. */
    saveApprovals: (setId: string, approvals: Record<string, string[]>) =>
      bpost<{ set_id: string; approvals: Record<string, string[]> }>(
        `${setPath(setId)}/approvals`, { approvals }),
  },

  // --- sourcing: the sublet fork -------------------------------------------
  // These are procurement's own endpoints, at the bare BASE rather than under /client-boq or
  // /bridge. They are reached through THIS client rather than by importing src/api.ts, for the
  // same reason the types are copied: one product, one client, no cross-import.
  sourcing: {
    /** Ranked candidates per package, with cited evidence and deterministic risk flags. */
    shortlist: (scope: unknown, opts?: { includePublic?: boolean; k?: number }) =>
      rpost<ShortlistSet>("/shortlist", {
        scope,
        ...(opts?.includePublic ? { include_public: true } : {}),
        ...(opts?.k ? { k: opts.k } : {}),
      }),
    /** How wide the screen is — shown so a shortlist is read against the pool it came from. */
    coverage: () => rget<Coverage>("/coverage"),
    /** Compose (send:false) or record (send:true) the enquiry bundles. */
    dispatch: (body: unknown) => rpost<DispatchSet>("/dispatch", body),
    /** Assemble the relevant-only attachments and create ONE Gmail DRAFT per firm. Never a send:
     *  the operator reviews and sends from Gmail. A Gmail failure comes back as partial success. */
    dispatchDrafts: (body: unknown) => rpost<DispatchDraftsResponse>("/dispatch/drafts", body),
    /** The per-section relevant-document plan, previewed before anything is drafted. */
    dispatchPlan: (scope: unknown, approvals: Record<string, string[]>, projectName: string) =>
      rpost<SectionPlan[]>("/dispatch/plan", {
        scope,
        approvals,
        project_name: projectName,
      }),

    // --- level & award ------------------------------------------------------
    /** One leveling section per sublet package. Layer 1 recomputes every amount — the corrected
     *  total is OURS, and the difference from what a firm claimed is the finding. */
    levelAll: (replies: BidReply[], scope: unknown) =>
      rpost<LevelAllResponse>("/level-all", { replies, scope }),
    /** One risk-adjusted recommendation per package. `demoFixtures` maps package -> baked
     *  rationale so the narration works offline; a missing package simply narrates nothing. */
    recommendAll: (
      levelled: LevelledBid[],
      demoFixtures: Record<string, string>,
      scope: unknown = null,
    ) => rpost<RecommendAllResponse>("/recommend-all", { levelled, demo_fixtures: demoFixtures, scope }),
    levelingXlsxUrl: () => `${BASE}/leveling.xlsx`,

    /** Manual priced-return intake (live): a subcontractor's returned bill for one firm+package.
     *  Passing the tender lets the backend run the misdirect guard against the scope. */
    levelUpload: (files: File[], firmId: string, trade: string, tender = "") => {
      const fd = new FormData();
      for (const f of files) fd.append("files", f);
      fd.append("firm_id", firmId);
      fd.append("trade", trade);
      if (tender) fd.append("tender", tender);
      return fetch(`${BASE}/level-upload`, { method: "POST", body: fd, headers: actorHeaders() }).then(
        (r) => handle<LevelUploadResult>(r),
      );
    },

    /** Which replies have landed for a tender.
     *
     *  Polled on `poll_seconds` while Level & compare is the visible step AND the server's poller
     *  is enabled — otherwise refreshed on demand. Nothing here auto-levels: a comparison must not
     *  silently recompute under someone mid-decision, so a new arrival offers a re-level and never
     *  performs one. */
    tenderReplies: (slug: string) =>
      rget<TenderReplies>(`/tender/${encodeURIComponent(slug)}/replies`),

    /** The Gmail integration's state: credential, token, and — the part Level & compare needs —
     *  whether the reply poller is actually watching. `polling_enabled` defaults FALSE, so a
     *  default install watches nothing and an empty comparison looks exactly like an empty inbox. */
    gmailStatus: () => rget<GmailIntegrationStatus>("/integrations/gmail"),
    tenderComparisonUrl: (slug: string) =>
      `${BASE}/tender/${encodeURIComponent(slug)}/comparison.xlsx`,
    /** The human gate: take a firm's reply out of the comparison for one unit. The reply is KEPT
     *  as history server-side — never deleted — and the comparison is re-levelled without it. */
    withdrawReply: (slug: string, firmId: string, packageKey: string) =>
      rpost<{ withdrawn: boolean; firm_id: string; package_key: string; reply_count: number }>(
        `/tender/${encodeURIComponent(slug)}/replies/withdraw`,
        { firm_id: firmId, package_key: packageKey },
      ),
  },
  // --- the management screens ----------------------------------------------
  // Firm register, benchmark corpus and projects — procurement's own root-mounted endpoints,
  // reached through this client for the same reason `sourcing` is: one product, one client, and a
  // gate refusal keeps its status code.
  manage: {
    /** The browseable firm database — real-provenance register firms only. */
    firms: (opts?: { q?: string; trade?: string; limit?: number; offset?: number }) => {
      const p = new URLSearchParams();
      if (opts?.q) p.set("q", opts.q);
      if (opts?.trade) p.set("trade", opts.trade);
      if (opts?.limit != null) p.set("limit", String(opts.limit));
      if (opts?.offset != null) p.set("offset", String(opts.offset));
      const qs = p.toString();
      return rget<FirmsPage>(`/firms${qs ? `?${qs}` : ""}`);
    },
    coverage: () => rget<Coverage>("/coverage"),

    projects: () => rget<ProjectSummary[]>("/project"),
    projectDashboard: (runRef: string) =>
      rget<ProjectDashboard>(`/project/${encodeURIComponent(runRef)}`),

    benchmarkProjects: () => rget<BenchmarkProject[]>("/benchmark/projects"),
    benchmarkSummary: () => rget<BenchmarkSummary>("/benchmark/summary"),
    createBenchmarkProject: (body: { name: string; trade?: string; client?: string; contract_ref?: string }) =>
      rpost<BenchmarkProject>("/benchmark/projects", body),
    benchmarkMatches: (id: number) => rget<MatchProposal>(`/benchmark/${id}/matches`),
    /** The human gate: a proposed match becomes a variance record only when confirmed here. */
    confirmMatches: (id: number, confirm: MatchConfirm[]) =>
      rpost<VarianceRecord[]>(`/benchmark/${id}/matches/confirm`, { confirm }),
    benchmarkVariance: (id: number) => rget<VarianceRecord[]>(`/benchmark/${id}/variance`),
    /** The SOLE writer of a reason code. A suggestion is never a reason until a person posts it. */
    setVarianceReason: (id: number, recordId: number, body: { reason_code: string; note?: string }) =>
      rpost<VarianceRecord>(`/benchmark/${id}/variance/${recordId}/reason`, body),
    reasonCodes: () => rget<ReasonCode[]>("/benchmark/reason-codes"),
    reasonSuggestions: (id: number) =>
      rget<VarianceReasonSuggestions>(`/benchmark/${id}/variance/reason-suggestions`),
    benchmarkEos: (id: number) => rget<ProjectEOS | null>(`/benchmark/${id}/eos`),
    attachEos: (id: number, narrative: string, summary = "") => {
      const fd = new FormData();
      fd.append("narrative", narrative);
      if (summary) fd.append("summary", summary);
      return fetch(`${BASE}/benchmark/${id}/eos-upload`, {
        method: "POST",
        body: fd,
        headers: actorHeaders(),
      }).then((r) => handle<ProjectEOS>(r));
    },
    uploadBenchmarkFile: (path: string, files: File[]) => {
      const fd = new FormData();
      for (const f of files) fd.append("files", f);
      return fetch(BASE + path, { method: "POST", body: fd, headers: actorHeaders() }).then((r) =>
        handle<unknown>(r),
      );
    },
    actualsTemplateUrl: (id: number) => `${BASE}/benchmark/actuals-template.xlsx?project=${id}`,
  },
};

/** Every job id with a poll loop running for it right now, and everyone listening to that loop.
 *
 *  ONE LOOP PER JOB, EVER. Four review job ids were once being polled at once on a single set —
 *  four independent `setTimeout` chains, each writing through `onProgress` into the shell's single
 *  `job` slot, so the strip showed whichever loop happened to answer last and the progress jumped
 *  between unrelated runs. Two things produced that, and both are now closed: the server refuses a
 *  second review on a set that already has one (409, `_no_review_in_flight_or_409`), and this map
 *  makes a second loop for one job impossible.
 *
 *  Note what is deliberately NOT done here: a loop is not aborted when the component that started
 *  it unmounts. Tabs render through a ternary, so `Register` unmounts the moment you navigate
 *  away, and the whole point of the shell-level strip is that a run you walked away from is still
 *  reported. Killing the loop on unmount would blank the strip — the exact failure `track()` was
 *  added to fix. A loop is bounded by its JOB, not by a component: it ends when the server says
 *  done, error or cancelled, when the job 404s, or after six consecutive transport failures. */
const LIVE_POLLS = new Map<
  string,
  { promise: Promise<JobState>; subscribers: Set<(s: JobState) => void> }
>();

/** Which jobs are being polled right now. Exported so the condition can be asserted rather than
 *  eyeballed in a network tab — "four ids at once" was diagnosed from a screenshot. */
export function pollingJobIds(): string[] {
  return [...LIVE_POLLS.keys()];
}

/** Poll a background job to completion. No ceiling — a 400-page binder takes as long as it takes.
 *
 *  Calling this for a job already being polled JOINS the existing loop instead of starting a
 *  second: the caller gets the same promise, and its `onProgress` is added to the subscribers the
 *  one loop feeds. */
export function pollJob(
  poll: (jobId: string) => Promise<JobState>,
  jobId: string,
  onProgress?: (s: JobState) => void,
): Promise<JobState> {
  const existing = LIVE_POLLS.get(jobId);
  if (existing) {
    if (onProgress) existing.subscribers.add(onProgress);
    return existing.promise;
  }

  const subscribers = new Set<(s: JobState) => void>(onProgress ? [onProgress] : []);
  const promise = new Promise<JobState>((resolve, reject) => {
    let failures = 0;
    // Every exit drops the registry entry FIRST, so a finished or failed job is never left
    // looking live and a re-run gets a fresh loop rather than a settled promise.
    const finish = (fn: () => void) => {
      LIVE_POLLS.delete(jobId);
      fn();
    };
    const tick = () => {
      poll(jobId)
        .then((state) => {
          failures = 0;
          subscribers.forEach((fn) => fn(state));
          if (state.status === "done") finish(() => resolve(state));
          else if (state.status === "error")
            finish(() => reject(new Error(state.error || "The job failed")));
          // A cancelled run RESOLVES. It is not a failure — somebody asked for it — so it must
          // not reach an error banner; the caller reads `.status` and refreshes as it would after
          // any other ending.
          else if (state.status === "cancelled") finish(() => resolve(state));
          else setTimeout(tick, 1500);
        })
        .catch((e: unknown) => {
          const message = e instanceof Error ? e.message : String(e);
          // A 404 means the job is GONE — the process restarted, or the id expired — and there is
          // nothing to wait for. Anything else may be a blip worth riding out.
          //
          // This read `message.startsWith("404")`, which never matched: `handle()` replaces the
          // status line with the JSON `detail` whenever there is one, and the status endpoints
          // answer `"Unknown or expired client_boq job"`. So a vanished job was treated as a blip
          // and retried six times, while the strip claimed a run that had stopped existing.
          // `handle()` already sets `error.status`; read the property, not the prose.
          const status = (e as { status?: number } | null)?.status;
          if (status === 404 || ++failures > 5) finish(() => reject(new Error(message)));
          else setTimeout(tick, 2000);
        });
    };
    tick();
  });

  LIVE_POLLS.set(jobId, { promise, subscribers });
  return promise;
}

/** Start a job and see it through, whichever mode the backend is in.
 *
 *  This exists because forgetting it broke LIVE entirely. In DEMO these endpoints run inline and
 *  return `{status: "done", result}`; in LIVE they return `{status: "queued", job_id}` and the
 *  work happens on a pool thread. Code that reads `.result` off the first response therefore
 *  works perfectly offline and silently does nothing at all with a real API key — the screen just
 *  never updates. Every caller goes through here so that cannot happen again.
 */
export async function runJob(
  start: () => Promise<JobState>,
  poll: (jobId: string) => Promise<JobState>,
  onProgress?: (s: JobState) => void,
): Promise<JobState> {
  const started = await start();
  onProgress?.(started);
  if (
    started.status === "done" || started.status === "error" ||
    started.status === "cancelled" || !started.job_id
  ) {
    if (started.status === "error") throw new Error(started.error || "The job failed");
    return started;
  }
  return pollJob(poll, started.job_id, onProgress);
}
