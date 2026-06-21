import type {
  BidReply,
  DemoCase,
  DemoCaseSummary,
  DispatchSet,
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
  shortlist: ShortlistSet;
  approvals: Record<string, string[]>;
  scope: ScopePackages | null;
  project_name: string;
  send: boolean;
}

export const api = {
  base: BASE,
  health: () => get<Health>("/health"),
  demoCases: () => get<DemoCaseSummary[]>("/demo/cases"),
  demoCase: (id: string) => get<DemoCase>(`/demo/${id}`),

  ingest: (tender: TenderPackage) => post<ScopePackages>("/ingest", { tender }),
  // Live multimodal ingest: POST the raw tender files as multipart/form-data.
  ingestUpload: (files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return fetch(BASE + "/ingest-upload", { method: "POST", body: fd }).then((r) => handle<ScopePackages>(r));
  },

  shortlist: (scope: ScopePackages) => post<ShortlistSet>("/shortlist", { scope }),
  dispatch: (req: DispatchRequest) => post<DispatchSet>("/dispatch", req),
  level: (replies: BidReply[], scope: ScopePackages | null) => post<LevelledBid[]>("/level", { replies, scope }),
  recommend: (levelled: LevelledBid[], trade: string, rationaleFixture: string | null) =>
    post<Recommendation>("/recommend", { levelled, trade, demo_fixture: rationaleFixture }),

  levelingXlsxUrl: () => BASE + "/leveling.xlsx",
};
