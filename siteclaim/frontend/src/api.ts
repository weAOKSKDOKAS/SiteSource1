import type {
  BidReply,
  Coverage,
  DemoCase,
  DemoCaseSummary,
  DispatchSet,
  Health,
  IngestUpload,
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
};
