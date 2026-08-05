// Typed client for /client-boq/*. Same BASE and the same error shape as src/api.ts — a 409 from
// a gate arrives as an Error carrying the backend's own sentence, because those sentences say
// exactly which gate refused and why, and rewriting them here would lose that.

import type {
  BillCandidate,
  CitationsResponse,
  CriteriaResponse,
  CompanySettings,
  CriterionRow,
  EstimateResponse,
  EstimateScheduleInput,
  DocumentRow,
  Highlight,
  GateState,
  JobState,
  LetterResponse,
  LLMSettingsResponse,
  ManifestGateState,
  Manifest,
  PartContext,
  PartDetail,
  PartSpec,
  PartsResponse,
  CostingModelShape,
  CostingResponse,
  DerivedResponse,
  GroupPreview,
  GroupsResponse,
  HoleGroup,
  OutputsResponse,
  RateRowFull,
  RatesResponse,
  StationScheduleResponse,
  RegisterResponse,
  RevisionRow,
  RFIBatchRow,
  RFIItem,
  RFIsResponse,
  ScheduleResponse,
  ScopeGateState,
  ScopeItem,
  ScopeItemsResponse,
  ScopeResponse,
  ScopeSection,
  ScopeSourcesResponse,
  SearchResponse,
  SetMeta,
  SetRow,
  TeamMember,
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

/** Is this backend in DEMO mode? Drives the app-bar chip, which is not decoration: it means
 *  uploaded files were not read and every finding on screen came from a fixture. */
export const health = (): Promise<{ status: string; demo_mode: boolean }> =>
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

  // --- the take-off (Site) --------------------------------------------------
  stationSchedule: (setId: string) => get<StationScheduleResponse>(`/site/${setId}/schedule`),
  derived: (setId: string) => get<DerivedResponse>(`/site/${setId}/derived`),
  holeGroups: (setId: string) => get<GroupsResponse>(`/site/${setId}/groups`),
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

  // --- app-wide settings (the AI model) -------------------------------------
  settings: () => get<LLMSettingsResponse>("/settings"),
  saveSettings: (body: {
    provider: string;
    provider_ingest?: string;
    model_anthropic?: string;
    model_deepseek?: string;
    model_openai?: string;
  }) =>
    post<LLMSettingsResponse>("/settings", {
      provider_ingest: "",
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
  runReview(setId: string, projectName: string): Promise<JobState> {
    const form = new FormData();
    form.append("project_name", projectName);
    form.append("set_id", setId);
    return fetch(`${ROOT}/review/run`, { method: "POST", body: form }).then((r) =>
      handle<JobState>(r),
    );
  },
  reviewStatus: (jobId: string) => get<JobState>(`/review/status/${jobId}`),
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
};

/** Poll a background job to completion. No ceiling — a 400-page binder takes as long as it takes. */
export function pollJob(
  poll: (jobId: string) => Promise<JobState>,
  jobId: string,
  onProgress?: (s: JobState) => void,
): Promise<JobState> {
  return new Promise((resolve, reject) => {
    let failures = 0;
    const tick = () => {
      poll(jobId)
        .then((state) => {
          failures = 0;
          onProgress?.(state);
          if (state.status === "done") resolve(state);
          else if (state.status === "error") reject(new Error(state.error || "The job failed"));
          else setTimeout(tick, 1500);
        })
        .catch((e: unknown) => {
          const message = e instanceof Error ? e.message : String(e);
          // A 404 means the job is gone; anything else may be a blip worth riding out.
          if (message.startsWith("404") || ++failures > 5) reject(new Error(message));
          else setTimeout(tick, 2000);
        });
    };
    tick();
  });
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
  if (started.status === "done" || started.status === "error" || !started.job_id) {
    if (started.status === "error") throw new Error(started.error || "The job failed");
    return started;
  }
  return pollJob(poll, started.job_id, onProgress);
}
