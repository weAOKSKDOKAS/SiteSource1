// Typed client for /client-boq/*. Same BASE and the same error shape as src/api.ts — a 409 from
// a gate arrives as an Error carrying the backend's own sentence, because those sentences say
// exactly which gate refused and why, and rewriting them here would lose that.

import type {
  BqCandidates,
  BridgeRouteDecisions,
  BridgeRouteProposal,
  BridgeRouteProposalRead,
  BridgeSplitRead,
  BridgeSplitResponse,
  CitationsResponse,
  CriteriaResponse,
  CriterionRow,
  DocumentRow,
  EstimateResponse,
  GateState,
  Highlight,
  JobState,
  LLMSettingsResponse,
  LetterResponse,
  Manifest,
  ManifestGateState,
  PartContext,
  PartDetail,
  PartSpec,
  PartsResponse,
  RFIBatchRow,
  RFIItem,
  RFIsResponse,
  RateRowFull,
  RatesResponse,
  RegisterResponse,
  RevisionRow,
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

  // --- app-wide settings (the AI model) -------------------------------------
  settings: () => get<LLMSettingsResponse>("/settings"),
  saveSettings: (body: { provider: string; model_anthropic?: string; model_deepseek?: string }) =>
    post<LLMSettingsResponse>("/settings", {
      model_anthropic: "",
      model_deepseek: "",
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
    /** Every part in the set, with which one(s) are PROPOSED as the priced bill. Proposing is not
     *  confirming: the category comes from an AI interpretation stage, so a human picks. 404s only
     *  when the set has no parts at all. */
    candidates: (setId: string) =>
      bget<BqCandidates>(`${setPath(setId)}/bq-candidates`),

    /** Confirm the SET of bill parts — several are legitimate (a bill of quantities AND a daywork
     *  schedule are both priceable). 400 on an unknown id or an empty selection. */
    confirmBillParts: (setId: string, partIds: string[]) =>
      bpost<BqCandidates>(`${setPath(setId)}/bq-part`, { part_ids: partIds }),

    /** Run the bill split. 409 until a bill part is confirmed — the message names bq-part. */
    runSplit: (setId: string) => bpost<BridgeSplitResponse>(`${setPath(setId)}/scope`, {}),
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
  },
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
