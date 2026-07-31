// client_boq — the tender-review product. Mounted at #/tender, full viewport, ≥1280px.
//
// One document set is open at a time. All three tabs read from the same loaded set, so switching
// tabs never re-fetches and never loses a selection; a gate that passes refreshes the state the
// tabs derive from, which is what makes the step strip move on its own.

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, health } from "./api";
import { AppBar, StepStrip, TABS, stepStates, usePersisted } from "./chrome";
import type { TabId } from "./chrome";
import { AddendumPanel, RfiPanel } from "./panels";
import type { PanelRequest } from "./panels";
import { DocumentsTab } from "./tabs/Documents";
import { RegisterTab } from "./tabs/Register";
import { ScopeTab } from "./tabs/Scope";
import type {
  CitationsResponse,
  GateStates,
  JobState,
  Manifest,
  PartsResponse,
  RegisterResponse,
  ScopeResponse,
  SetRow,
} from "./types";
import { ErrorNote, WaitingOn, cx } from "./ui";
// tokens.css is imported from src/index.css, not here — see the note there.

/** Everything loaded for the open set. Null fields are "not run yet", which the tabs render as
 *  an explanation rather than an empty screen. */
export interface SetData {
  setId: string;
  name: string;
  gates: GateStates;
  manifest: Manifest | null;
  parts: PartsResponse | null;
  register: RegisterResponse | null;
  citations: CitationsResponse | null;
  scope: ScopeResponse | null;
  hasEstimate: boolean;
}

const EMPTY_GATES: GateStates = { manifest: false, review: false, scope: false };

export default function ClientBoqApp() {
  const [demoMode, setDemoMode] = useState(false);
  const [sets, setSets] = useState<SetRow[]>([]);
  const [setId, setSetId] = usePersisted<string>("openSet", "");
  const [data, setData] = useState<SetData | null>(null);
  const [tab, setTab] = usePersisted<TabId>("tab", "documents");
  const [opened, setOpened] = useState<Set<TabId>>(() => new Set<TabId>(["documents"]));
  const [railOpen, setRailOpen] = usePersisted("railOpen", true);
  const [panel, setPanel] = useState<PanelRequest | null>(null);
  const [job, setJob] = useState<JobState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    health()
      .then((h) => setDemoMode(h.demo_mode))
      .catch(() => setDemoMode(false));
  }, []);

  // --- load the set list, and pick one -------------------------------------
  const loadSets = useCallback(async () => {
    const body = await api.sets();
    setSets(body.sets);
    return body.sets;
  }, []);

  useEffect(() => {
    loadSets()
      .then((rows) => {
        if (!rows.length) return;
        // A remembered set that has since been removed must not strand the app on nothing.
        if (!rows.some((r) => r.set_id === setId)) setSetId(rows[0].set_id);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- load everything for the open set ------------------------------------
  // Each piece is optional: a set that has been split but not reviewed simply has no register,
  // and that is a state the UI shows rather than an error it reports.
  const loadSet = useCallback(async (id: string) => {
    if (!id) {
      setData(null);
      return;
    }
    const rows = await api.sets();
    setSets(rows.sets);
    const row = rows.sets.find((r) => r.set_id === id);
    const optional = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

    const [manifest, parts, register, scope] = await Promise.all([
      optional(api.manifest(id)),
      optional(api.parts(id)),
      optional(api.register(id)),
      optional(api.scope(id)),
    ]);
    // Citations need a reviewed register AND split parts; asking for them before either exists
    // is a 404/409, not a failure worth showing.
    const citations = register ? await optional(api.citations(id)) : null;

    setData({
      setId: id,
      name: row?.name ?? id,
      gates: row?.gates ?? EMPTY_GATES,
      manifest,
      parts,
      register,
      citations,
      scope,
      hasEstimate: row?.price != null,
    });
  }, []);

  useEffect(() => {
    if (!setId) return;
    setLoading(true);
    loadSet(setId)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [setId, loadSet]);

  const refresh = useCallback(() => loadSet(setId), [loadSet, setId]);

  const selectTab = useCallback(
    (id: TabId) => {
      setTab(id);
      setOpened((cur) => (cur.has(id) ? cur : new Set(cur).add(id)));
    },
    [setTab],
  );

  const states = useMemo(
    () =>
      stepStates(data?.gates ?? EMPTY_GATES, {
        parts: Boolean(data?.parts?.count),
        register: Boolean(data?.register),
        scope: Boolean(data?.scope),
        estimate: Boolean(data?.hasEstimate),
      }),
    [data],
  );

  // --- nothing ingested yet ------------------------------------------------
  if (!loading && !sets.length) {
    return (
      <div data-app="cboq" className="flex min-h-screen flex-col">
        <div className="flex flex-1 items-center justify-center">
          <div className="max-w-md text-center">
            <h1 className="font-cb-serif text-[22px] font-semibold text-cb-ink-text">
              No tender has been ingested yet.
            </h1>
            <p className="mt-3 font-cb-sans text-[12px] leading-[1.65] text-cb-muted">
              Upload a tender binder to begin. It is read for its own structure, split into parts,
              and stops at the split manifest so you can correct the boundaries before anything
              downstream depends on them.
            </p>
            {error && (
              <div className="mt-4 text-left">
                <ErrorNote message={error} onDismiss={() => setError(null)} />
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div data-app="cboq" className="flex h-screen flex-col overflow-hidden">
      <AppBar
        projectName={data?.name ?? "—"}
        setId={setId || "—"}
        demoMode={demoMode}
        sets={sets}
        railOpen={railOpen}
        onToggleRail={() => setRailOpen(!railOpen)}
        onReopen={setSetId}
      />
      <StepStrip current={tab} states={states} opened={opened} onSelect={selectTab} />

      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
      {job && <JobStrip job={job} />}

      <main className="flex min-h-0 flex-1">
        {loading && !data ? (
          <WaitingOn title="Opening the set…">
            Reading the manifest, the parts and whatever has been run since.
          </WaitingOn>
        ) : !data ? (
          <WaitingOn title="No set open">Choose one from the app bar.</WaitingOn>
        ) : tab === "documents" ? (
          <DocumentsTab
            data={data}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={setError}
            onProgress={setJob}
          />
        ) : tab === "register" ? (
          <RegisterTab
            data={data}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={setError}
            onProgress={setJob}
            onOpenPanel={setPanel}
          />
        ) : tab === "scope" ? (
          <ScopeTab
            data={data}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={setError}
            onProgress={setJob}
          />
        ) : (
          <NotBuiltYet tab={tab} data={data} />
        )}
      </main>

      {panel?.kind === "rfi" && data && (
        <RfiPanel
          setId={data.setId}
          batchId={panel.batchId}
          onClose={() => setPanel(null)}
          onError={setError}
          onChanged={() => void refresh()}
        />
      )}
      {panel?.kind === "addendum" && data && (
        <AddendumPanel
          setId={data.setId}
          docId={panel.docId}
          onClose={() => setPanel(null)}
          onError={setError}
        />
      )}
    </div>
  );
}

/** What a background job is doing. Only ever visible in LIVE — DEMO runs everything inline, which
 *  is exactly why the polling this reports on was so easy to leave out. `done`/`total` have been
 *  on the Job model since ingest was built and this is the first thing to show them. */
function JobStrip({ job }: { job: JobState }) {
  const pct = job.total ? Math.round(((job.done ?? 0) / job.total) * 100) : null;
  return (
    <div className="flex flex-none items-center gap-3 border-b border-cb-brass-line bg-cb-brass-tint px-[18px] py-2">
      <span className="ssDot h-2 w-2 flex-none rounded-full bg-cb-brass" />
      <span className="flex-none font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-brass-text">
        {job.kind.toUpperCase()} · {job.stage.toUpperCase().replace(/-/g, " ")}
      </span>
      {pct != null && (
        <span className="flex-none font-cb-mono text-[10px] text-cb-brass-text">
          {job.done}/{job.total}
        </span>
      )}
      <div className="h-[4px] max-w-[280px] flex-1 overflow-hidden rounded-[2px] bg-cb-brass-line">
        <div
          style={{ width: pct != null ? `${pct}%` : "35%" }}
          className={cx(
            "h-full bg-cb-brass transition-[width] duration-300 ease-out",
            pct == null && "animate-pulse",
          )}
        />
      </div>
      <span className="font-cb-sans text-[10px] text-cb-brass-text">
        Reading your documents. This is a live model run, so it takes as long as it takes.
      </span>
    </div>
  );
}

/** A step that exists but has no screen yet. It opens and says so, rather than being locked —
 *  the same rule as a step that has not run. Replaced tab by tab through U3–U5. */
function NotBuiltYet({ tab, data }: { tab: TabId; data: SetData }) {
  const label = TABS.find((t) => t.id === tab)?.label ?? tab;
  const copy: Record<string, string> = {
    register: `The register for ${data.name} is reachable over the API today; this screen lands next.`,
    scope: "The scope of record — what the register decided, what the client has not answered, and what the addenda changed — lands with the freeze gate.",
    price: "The price is built and tested on the backend (the workbook and the cost build-up both run). It has no screen yet: this step has not been designed.",
    offer: "The offer letter is drafted by the backend already. It has no screen yet: this step has not been designed.",
  };
  return <WaitingOn title={`${label} — no screen yet`}>{copy[tab] ?? ""}</WaitingOn>;
}
