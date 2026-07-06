import type {
  BenchmarkProject,
  BenchmarkSummary,
  BidReply,
  Coverage,
  DemoCase,
  DemoCaseSummary,
  DispatchSet,
  DraftOverride,
  EstimateCheckResult,
  EstimateDraftResult,
  EstimateItem,
  EstimateProject,
  FirmProfile,
  FirmsPage,
  Health,
  IngestUpload,
  LetterOfOffer,
  LevelAllResponse,
  LevelledBid,
  MatchConfirm,
  MatchProposal,
  ProjectDashboard,
  ProjectEOS,
  ProjectSummary,
  RateSuggestions,
  ReasonCode,
  RecommendAllResponse,
  Recommendation,
  RouteDecision,
  RouteDecisionResult,
  RouteProposal,
  ScopePackages,
  ShortlistSet,
  TenderPackage,
  TenderReplies,
  TradeWorkPackage,
  VarianceReasonSuggestions,
  VarianceRecord,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

function get<T>(path: string): Promise<T> {
  return fetch(BASE + path).then((r) => handle<T>(r));
}

function post<T>(path: string, body: unknown): Promise<T> {
  return fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

function patch<T>(path: string, body: unknown): Promise<T> {
  return fetch(BASE + path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

function del<T>(path: string): Promise<T> {
  return fetch(BASE + path, { method: "DELETE" }).then((r) => handle<T>(r));
}

export interface DispatchRequest {
  shortlist: ShortlistSet;
  approvals: Record<string, string[]>;
  scope: ScopePackages | null;
  project_name: string;
  send: boolean;
  // Human-edited drafts per (trade, firm); the outbox stores exactly the edited text.
  draft_overrides?: DraftOverride[];
}

export const api = {
  base: BASE,
  health: () => get<Health>("/health"),
  coverage: () => get<Coverage>("/coverage"),

  // The browseable firm database (Layer 3) — real-provenance register firms only.
  firms: (opts?: { q?: string; trade?: string; limit?: number; offset?: number }) => {
    const p = new URLSearchParams();
    if (opts?.q) p.set("q", opts.q);
    if (opts?.trade) p.set("trade", opts.trade);
    if (opts?.limit != null) p.set("limit", String(opts.limit));
    if (opts?.offset != null) p.set("offset", String(opts.offset));
    const qs = p.toString();
    return get<FirmsPage>(`/firms${qs ? `?${qs}` : ""}`);
  },
  firm: (id: string) => get<FirmProfile>(`/firms/${encodeURIComponent(id)}`),
  demoCases: () => get<DemoCaseSummary[]>("/demo/cases"),
  demoCase: (id: string) => get<DemoCase>(`/demo/${id}`),

  ingest: (tender: TenderPackage) => post<ScopePackages>("/ingest", { tender }),
  // Live multimodal ingest: POST the raw tender files as multipart/form-data.
  // Returns the scope split plus the trade-tagged tender (pass the tender to /dispatch).
  // XHR (not fetch) so the progress modal gets a real "upload complete" tick — the only
  // intermediate signal the lifecycle honestly exposes before the (minutes-long) response.
  ingestUpload: (files: File[], onUploaded?: () => void) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return new Promise<IngestUpload>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", BASE + "/ingest-upload");
      xhr.upload.onload = () => onUploaded?.(); // bytes fully sent -> server-side processing begins
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText) as IngestUpload);
          } catch {
            reject(new Error("Malformed response from /ingest-upload"));
          }
        } else {
          let detail = `${xhr.status} ${xhr.statusText}`;
          try {
            const b = JSON.parse(xhr.responseText);
            if (b?.detail) detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
          } catch {
            /* keep the status line */
          }
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new Error("Network error during upload"));
      xhr.send(fd);
    });
  },

  // Live mode opens the shortlist to the screened public pool and caps each trade's
  // ranked list; demo mode sends neither, keeping the assessed-firm demo behaviour.
  shortlist: (scope: ScopePackages, opts?: { includePublic?: boolean; k?: number }) =>
    post<ShortlistSet>("/shortlist", {
      scope,
      ...(opts?.includePublic ? { include_public: true } : {}),
      ...(opts?.k != null ? { k: opts.k } : {}),
    }),
  dispatch: (req: DispatchRequest) => post<DispatchSet>("/dispatch", req),
  level: (replies: BidReply[], scope: ScopePackages | null) => post<LevelledBid[]>("/level", { replies, scope }),
  recommend: (levelled: LevelledBid[], trade: string, rationaleFixture: string | null) =>
    post<Recommendation>("/recommend", { levelled, trade, demo_fixture: rationaleFixture }),

  // Per-section path (Prompt 1): one leveling section and one recommendation per sublet
  // trade. demoFixtures maps trade -> baked rationale (a missing trade narrates offline).
  levelAll: (replies: BidReply[], scope: ScopePackages | null) =>
    post<LevelAllResponse>("/level-all", { replies, scope }),
  recommendAll: (levelled: LevelledBid[], demoFixtures: Record<string, string>) =>
    post<RecommendAllResponse>("/recommend-all", { levelled, demo_fixtures: demoFixtures }),

  levelingXlsxUrl: () => BASE + "/leveling.xlsx",

  // Reply visibility (live): which replies have landed for a tender, refreshed on demand.
  tenderReplies: (slug: string) => get<TenderReplies>(`/tender/${encodeURIComponent(slug)}/replies`),
  tenderComparisonUrl: (slug: string) => BASE + `/tender/${encodeURIComponent(slug)}/comparison.xlsx`,

  // --- Benchmark estimator (Phase B1) --------------------------------------
  benchmarkProjects: () => get<BenchmarkProject[]>("/benchmark/projects"),
  benchmarkProject: (id: number) => get<BenchmarkProject>(`/benchmark/projects/${id}`),
  benchmarkSummary: () => get<BenchmarkSummary>("/benchmark/summary"),
  reasonCodes: () => get<ReasonCode[]>("/benchmark/reason-codes"),
  createBenchmarkProject: (body: { name: string; trade?: string; client?: string; contract_ref?: string }) =>
    post<BenchmarkProject>("/benchmark/projects", body),
  benchmarkMatches: (id: number) => get<MatchProposal>(`/benchmark/${id}/matches`),
  confirmMatches: (id: number, confirm: MatchConfirm[]) =>
    post<VarianceRecord[]>(`/benchmark/${id}/matches/confirm`, { confirm }),
  benchmarkVariance: (id: number) => get<VarianceRecord[]>(`/benchmark/${id}/variance`),
  setVarianceReason: (id: number, recordId: number, body: { reason_code: string; note?: string }) =>
    post<VarianceRecord>(`/benchmark/${id}/variance/${recordId}/reason`, body),
  actualsTemplateUrl: (id: number) => BASE + `/benchmark/actuals-template.xlsx?project=${id}`,

  // EOS narrative → reason (Phase 2): the field account, and the per-record reason candidates
  // drawn from it (suggestion only — the reason POST stays the sole writer).
  benchmarkEos: (id: number) => get<ProjectEOS | null>(`/benchmark/${id}/eos`),
  reasonSuggestions: (id: number) => get<VarianceReasonSuggestions>(`/benchmark/${id}/variance/reason-suggestions`),
  attachEos: (id: number, narrative: string, summary = "") => {
    const fd = new FormData();
    fd.append("narrative", narrative);
    if (summary) fd.append("summary", summary);
    return fetch(BASE + `/benchmark/${id}/eos-upload`, { method: "POST", body: fd }).then((r) => handle<ProjectEOS>(r));
  },

  // --- Routing gate (Phase 1) ----------------------------------------------
  routeAnalyze: (scope: ScopePackages, run_ref = "") => post<RouteProposal>("/route/analyze", { scope, run_ref }),
  routeConfirm: (run_ref: string, decisions: RouteDecision[], decided_by = "operator", scope: ScopePackages | null = null) =>
    post<RouteDecisionResult>("/route/confirm", { run_ref, decisions, decided_by, ...(scope ? { scope } : {}) }),

  // --- Estimator (Phase 3) — the left track. The person prices every line and owns the offer.
  estimateProjects: () => get<EstimateProject[]>("/estimate/projects"),
  estimateProject: (id: number) => get<EstimateProject>(`/estimate/projects/${id}`),
  createEstimate: (body: { name: string; trade?: string; client?: string; contract_ref?: string }) =>
    post<EstimateProject>("/estimate/projects", body),
  patchEstimate: (id: number, body: Partial<Pick<EstimateProject, "name" | "trade" | "client" | "contract_ref" | "notes" | "status" | "scope_of_works">>) =>
    patch<EstimateProject>(`/estimate/projects/${id}`, body),
  estimateFromPackage: (pkg: TradeWorkPackage, opts?: { project_name?: string; run_ref?: string; client?: string; contract_ref?: string }) =>
    post<EstimateProject>("/estimate/from-package", { package: pkg, ...opts }),
  estimateItems: (id: number) => get<EstimateItem[]>(`/estimate/${id}/items`),
  addEstimateItems: (id: number, items: Array<{ item_ref: string; description?: string; unit?: string; qty?: number | null; rate?: number | null }>) =>
    post<EstimateItem[]>(`/estimate/${id}/items`, { items }),
  patchEstimateItem: (id: number, itemId: number, body: { description?: string; unit?: string; qty?: number | null; rate?: number | null }) =>
    patch<EstimateItem>(`/estimate/${id}/items/${itemId}`, body),
  deleteEstimateItem: (id: number, itemId: number) => del<{ deleted: number }>(`/estimate/${id}/items/${itemId}`),
  draftEstimate: (id: number) => post<EstimateDraftResult>(`/estimate/${id}/draft`, {}),
  estimateRateSuggestions: (id: number) => get<RateSuggestions>(`/estimate/${id}/rate-suggestions`),
  checkEstimate: (id: number) => post<EstimateCheckResult>(`/estimate/${id}/check`, { tender: [] }),
  estimateLetter: (id: number) => post<LetterOfOffer>(`/estimate/${id}/letter`, {}),
  estimateToBenchmark: (id: number) => post<{ estimate: EstimateProject; benchmark_project_id: number; tender_item_count: number }>(`/estimate/${id}/to-benchmark`, {}),

  // --- Unified project dashboard (Phase 4) ---------------------------------
  projects: () => get<ProjectSummary[]>("/project"),
  projectDashboard: (runRef: string) => get<ProjectDashboard>(`/project/${encodeURIComponent(runRef)}`),
  uploadBenchmarkFile: (path: string, files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return fetch(BASE + path, { method: "POST", body: fd }).then((r) => handle<unknown>(r));
  },
};
