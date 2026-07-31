// Typed client for /client-boq/*. Same BASE and the same error shape as src/api.ts — a 409 from
// a gate arrives as an Error carrying the backend's own sentence, because those sentences say
// exactly which gate refused and why, and rewriting them here would lose that.

import type {
  CitationsResponse,
  CriteriaResponse,
  DocumentRow,
  Highlight,
  GateState,
  JobState,
  ManifestGateState,
  Manifest,
  PartContext,
  PartDetail,
  PartSpec,
  PartsResponse,
  RegisterResponse,
  RevisionRow,
  RFIBatchRow,
  RFIItem,
  RFIsResponse,
  ScopeGateState,
  ScopeItem,
  ScopeItemsResponse,
  ScopeResponse,
  ScopeSection,
  ScopeSourcesResponse,
  SearchResponse,
  SetRow,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";
const ROOT = `${BASE}/client-boq`;

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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));

const del = <T>(path: string): Promise<T> =>
  fetch(ROOT + path, { method: "DELETE" }).then((r) => handle<T>(r));

/** Is this backend in DEMO mode? Drives the app-bar chip, which is not decoration: it means
 *  uploaded files were not read and every finding on screen came from a fixture. */
export const health = (): Promise<{ status: string; demo_mode: boolean }> =>
  fetch(`${BASE}/health`).then((r) => handle(r));

export const api = {
  // --- sets ----------------------------------------------------------------
  sets: () => get<{ count: number; sets: SetRow[] }>("/sets"),
  /** The acceptable-terms library. Lets a register row say what `PS-01` actually means. */
  criteria: () => get<CriteriaResponse>("/criteria"),
  gate: (setId: string) => get<GateState>(`/gate/${setId}`),

  // --- ingest & the manifest gate ------------------------------------------
  upload(files: File[], projectName: string): Promise<JobState> {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("project_name", projectName);
    return fetch(`${ROOT}/ingest/upload`, { method: "POST", body: form }).then((r) =>
      handle<JobState>(r),
    );
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
