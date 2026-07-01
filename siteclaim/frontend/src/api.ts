import type {
  BidReply,
  Coverage,
  DemoCase,
  DemoCaseSummary,
  DispatchSet,
  FirmsPage,
  FirmProfileFull,
  Health,
  LevelledBid,
  Recommendation,
  ScopePackages,
  ShortlistSet,
  TenderPackage,
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
  shortlist?: ShortlistSet;
  approvals?: Record<string, string[]>;
  scope?: ScopePackages | null;
  project_name?: string;
  // The approved (possibly edited) bundles to actually send — passed on the send=true
  // call so the Gmail draft carries the user's edits verbatim.
  dispatch?: DispatchSet;
  send?: boolean;
}

export const api = {
  base: BASE,
  health: () => get<Health>("/health"),
  coverage: () => get<Coverage>("/coverage"),
  demoCases: () => get<DemoCaseSummary[]>("/demo/cases"),
  demoCase: (id: string) => get<DemoCase>(`/demo/${id}`),

  // Server-side paginated register. Never loads all ~1,366 firms at once.
  firms: (params: { limit?: number; offset?: number; q?: string; sort?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    if (params.q) qs.set("q", params.q);
    if (params.sort) qs.set("sort", params.sort);
    const s = qs.toString();
    return get<FirmsPage>("/firms" + (s ? `?${s}` : ""));
  },

  // `scopeFixture` selects the per-scenario baked scope split in DEMO_MODE; omit it
  // to use the server's default (the building/fit-out scope).
  ingest: (tender: TenderPackage, scopeFixture?: string | null) =>
    post<ScopePackages>("/ingest", scopeFixture ? { tender, demo_fixture: scopeFixture } : { tender }),
  // Live multimodal ingest: POST the raw tender files as multipart/form-data.
  ingestUpload: (files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return fetch(BASE + "/ingest-upload", { method: "POST", body: fd }).then((r) => handle<ScopePackages>(r));
  },

  shortlist: (scope: ScopePackages) => post<ShortlistSet>("/shortlist", { scope }),
  dispatch: (req: DispatchRequest) => post<DispatchSet>("/dispatch", req),
  // Build the leveling replies from the firms approved in dispatch (approval-driven
  // cases ship a SoR template bank instead of a fixed replies list).
  collectReplies: (approvals: Record<string, string[]>, sorFixture: string) =>
    post<BidReply[]>("/collect-replies", { approvals, sor_fixture: sorFixture }),
  level: (replies: BidReply[], scope: ScopePackages | null) => post<LevelledBid[]>("/level", { replies, scope }),
  recommend: (levelled: LevelledBid[], trade: string, rationaleFixture: string | null) =>
    post<Recommendation>("/recommend", { levelled, trade, demo_fixture: rationaleFixture }),

  firmById: (id: string) => get<FirmProfileFull>("/firms/" + encodeURIComponent(id)),
  levelingXlsxUrl: () => BASE + "/leveling.xlsx",
};
