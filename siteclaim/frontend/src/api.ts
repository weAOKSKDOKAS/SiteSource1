import type {
  BenchmarkProject,
  BenchmarkSummary,
  BidReply,
  Coverage,
  DemoCase,
  DemoCaseSummary,
  DispatchSet,
  Health,
  IngestUpload,
  LevelledBid,
  MatchConfirm,
  MatchProposal,
  ReasonCode,
  Recommendation,
  RouteDecision,
  RouteDecisionResult,
  RouteProposal,
  ScopePackages,
  ShortlistSet,
  TenderPackage,
  TenderReplies,
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

export interface DispatchRequest {
  shortlist: ShortlistSet;
  approvals: Record<string, string[]>;
  scope: ScopePackages | null;
  project_name: string;
  send: boolean;
}

export const api = {
  base: BASE,
  health: () => get<Health>("/health"),
  coverage: () => get<Coverage>("/coverage"),
  demoCases: () => get<DemoCaseSummary[]>("/demo/cases"),
  demoCase: (id: string) => get<DemoCase>(`/demo/${id}`),

  ingest: (tender: TenderPackage) => post<ScopePackages>("/ingest", { tender }),
  // Live multimodal ingest: POST the raw tender files as multipart/form-data.
  // Returns the scope split plus the trade-tagged tender (pass the tender to /dispatch).
  ingestUpload: (files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return fetch(BASE + "/ingest-upload", { method: "POST", body: fd }).then((r) => handle<IngestUpload>(r));
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

  // --- Routing gate (Phase 1) ----------------------------------------------
  routeAnalyze: (scope: ScopePackages, run_ref = "") => post<RouteProposal>("/route/analyze", { scope, run_ref }),
  routeConfirm: (run_ref: string, decisions: RouteDecision[], decided_by = "operator") =>
    post<RouteDecisionResult>("/route/confirm", { run_ref, decisions, decided_by }),
  uploadBenchmarkFile: (path: string, files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return fetch(BASE + path, { method: "POST", body: fd }).then((r) => handle<unknown>(r));
  },
};
