// client_boq — the tender-review product. Mounted at #/tender, full viewport, ≥1280px.
//
// The app opens on the TENDER DESK: a shelf of folders, one per live tender, worked by a small
// team. Opening a folder enters that tender's five sequential steps. The hash IS the router —
// every surface is a URL, so the browser's own history powers ← / → and survives a reload:
//
//   #/tender                    the desk        #/tender/criteria|rates|team|settings
//   #/tender/archived           off the shelf   #/tender/letters|positions|clients|audit
//   #/tender/awaiting           open queries    #/tender/s/{setId}/{tab}   one tender

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, health, runJob, setActor } from "./api";
import { GlobalBar, StepStrip, TABS, stepStates, usePersisted } from "./chrome";
import type { TabId } from "./chrome";
import { Home } from "./home/Home";
import { NavSidebar } from "./nav/NavSidebar";
import type { Surface } from "./nav/routes";
import { go, hashFor, parseHash } from "./nav/routes";
import { AddendumPanel, RfiPanel } from "./panels";
import type { PanelRequest } from "./panels";
import { ProfilePicker } from "./profile/ProfilePicker";
import { CommandSearch } from "./search/CommandSearch";
import { CriteriaLibrary } from "./screens/CriteriaLibrary";
import { NotDesigned } from "./screens/NotDesigned";
import { Rates } from "./screens/Rates";
import { Settings } from "./screens/Settings";
import { Team } from "./screens/Team";
import { DocumentsTab } from "./tabs/Documents";
import { RegisterTab } from "./tabs/Register";
import { ScopeTab } from "./tabs/Scope";
import type {
  CitationsResponse,
  CriteriaResponse,
  GateStates,
  JobState,
  Manifest,
  PartsResponse,
  RegisterResponse,
  ScopeResponse,
  SetRow,
  TeamMember,
} from "./types";
import { Avatar, ErrorNote, WaitingOn, cx } from "./ui";
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
  const [surface, setSurface] = useState<Surface>(() => parseHash(window.location.hash));
  const [demoMode, setDemoMode] = useState(false);
  const [sets, setSets] = useState<SetRow[]>([]);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [criteria, setCriteria] = useState<CriteriaResponse | null>(null);
  const [navOpen, setNavOpen] = usePersisted("navOpen", true);
  const [railOpen, setRailOpen] = usePersisted("railOpen", true);
  const [currentUserId, setCurrentUserId] = usePersisted<string>("currentUser", "");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const [job, setJob] = useState<JobState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  /** A citation deep link for the open set's Documents tab (READ FROM COT on a card). */
  const [docTarget, setDocTarget] = useState<{ partId: string; page: number } | null>(null);

  // --- routing --------------------------------------------------------------
  useEffect(() => {
    const onHash = () => setSurface(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // --- global data ----------------------------------------------------------
  useEffect(() => {
    health()
      .then((h) => setDemoMode(h.demo_mode))
      .catch(() => setDemoMode(false));
  }, []);

  const loadSets = useCallback(async () => {
    const body = await api.sets(true); // the desk filters archived client-side; Archived needs them
    setSets(body.sets);
    return body.sets;
  }, []);

  const loadTeam = useCallback(async () => {
    const body = await api.team();
    setTeam(body.members);
    return body.members;
  }, []);

  const loadCriteria = useCallback(async () => {
    try {
      setCriteria(await api.criteria());
    } catch {
      setCriteria(null); // the library failing to load must not take the desk down with it
    }
  }, []);

  useEffect(() => {
    Promise.all([loadSets().catch(() => [] as SetRow[]), loadTeam().catch(() => [] as TeamMember[])])
      .then(([, members]) => {
        // First run with nobody picked: ask. Not a login — attribution.
        if (!members.length || !window.localStorage.getItem("cboq.currentUser")) setPickerOpen(true);
      })
      .finally(() => setLoaded(true));
    void loadCriteria();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => setActor(currentUserId), [currentUserId]);

  const currentUser = useMemo(
    () => team.find((m) => m.member_id === currentUserId) ?? null,
    [team, currentUserId],
  );

  // --- Ctrl-K ---------------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // --- upload: drop anywhere on the home page, or browse --------------------
  const fileInput = useRef<HTMLInputElement>(null);

  const uploadFiles = useCallback(
    async (files: File[]) => {
      const pdfs = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
      if (!pdfs.length) {
        setError("Drop a PDF — the binder is read as one document.");
        return;
      }
      const projectName = pdfs[0].name.replace(/\.pdf$/i, "");
      try {
        const done = await runJob(
          () => api.upload(pdfs, projectName),
          api.ingestStatus,
          setJob,
        );
        setJob(null);
        await loadSets();
        const result = done.result as { set_id?: string } | undefined;
        if (result?.set_id) go({ kind: "set", setId: result.set_id, tab: "documents" });
      } catch (e) {
        setJob(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [loadSets],
  );

  useEffect(() => {
    if (surface.kind !== "home") return;
    const onDragOver = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) {
        e.preventDefault();
        setDropActive(true);
      }
    };
    const onDragLeave = (e: DragEvent) => {
      if (!e.relatedTarget) setDropActive(false);
    };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      setDropActive(false);
      const files = [...(e.dataTransfer?.files ?? [])];
      if (files.length) void uploadFiles(files);
    };
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [surface.kind, uploadFiles]);

  // --- desk actions ---------------------------------------------------------
  const confirmCloseDate = useCallback(
    async (setId: string, date: string) => {
      try {
        await api.confirmCloseDate(setId, date);
        await loadSets();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [loadSets],
  );

  const openCitation = useCallback((setId: string, partId: string, page: number) => {
    setDocTarget({ partId, page });
    go({ kind: "set", setId, tab: "documents" });
  }, []);

  // --- shells ---------------------------------------------------------------
  const navCounts = useMemo(
    () => ({
      desk: sets.filter((s) => !s.meta.archived).length,
      archived: sets.filter((s) => s.meta.archived).length,
      awaiting: sets.filter((s) => !s.meta.archived && s.counts.open_rfis > 0).length,
      criteria: criteria?.count ?? 0,
      team: team.length,
    }),
    [sets, criteria, team],
  );

  const isSet = surface.kind === "set";
  const openSetRow = isSet ? sets.find((s) => s.set_id === surface.setId) ?? null : null;

  const barTitle =
    surface.kind === "home"
      ? surface.shelf === "desk"
        ? "Tender desk"
        : surface.shelf === "archived"
          ? "Archived"
          : "Awaiting client"
      : surface.kind === "set"
        ? openSetRow?.name ?? surface.setId
        : {
            criteria: "Criteria library",
            rates: "Pricing & rates",
            team: "Team & access",
            settings: "AI model",
            letters: "Letter templates",
            positions: "Standard positions",
            clients: "Clients",
            audit: "Audit log",
          }[surface.screen];

  const deadlineChip =
    isSet && openSetRow?.meta.close_date
      ? (() => {
          const days = Math.ceil(
            (new Date(`${openSetRow.meta.close_date}T00:00:00`).getTime() - Date.now()) / 86_400_000,
          );
          return (
            <span
              className={cx(
                "rounded-cb-chip border border-cb-navy-line px-2 py-[3px] font-cb-mono text-[9.5px] font-semibold",
                days <= 7 ? "text-[#E0A392]" : "text-cb-dim",
              )}
            >
              {days} DAYS TO CLOSE
            </span>
          );
        })()
      : null;

  return (
    <div data-app="cboq" className="flex h-screen flex-col overflow-hidden">
      <GlobalBar
        navOpen={navOpen}
        onToggleNav={() => setNavOpen(!navOpen)}
        railOpen={railOpen}
        onToggleRail={() => setRailOpen(!railOpen)}
        railEnabled={isSet}
        onSearch={() => setSearchOpen(true)}
        title={barTitle}
        meta={isSet ? `set_id · ${surface.setId}` : undefined}
        demoMode={demoMode}
        right={
          <>
            {deadlineChip}
            <button type="button" onClick={() => setPickerOpen(true)} title="Switch profile">
              <Avatar member={currentUser} size={22} ring />
            </button>
          </>
        }
      />

      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
      {job && <JobStrip job={job} />}

      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <NavSidebar
          open={navOpen}
          surface={surface}
          counts={navCounts}
          currentUser={currentUser}
          onNewTender={() => fileInput.current?.click()}
          onSwitchUser={() => setPickerOpen(true)}
        />

        {surface.kind === "home" ? (
          !loaded ? (
            <WaitingOn title="Opening the desk…">Reading the shelf.</WaitingOn>
          ) : (
            <Home
              rows={sets}
              shelf={surface.shelf}
              team={team}
              currentUserId={currentUserId}
              navOpen={navOpen}
              onOpenSet={(setId) => go({ kind: "set", setId, tab: "documents" })}
              onOpenCitation={openCitation}
              onConfirmCloseDate={(setId, date) => void confirmCloseDate(setId, date)}
              onBrowse={() => fileInput.current?.click()}
            />
          )
        ) : surface.kind === "screen" ? (
          surface.screen === "criteria" ? (
            <CriteriaLibrary criteria={criteria} onChanged={() => void loadCriteria()} onError={setError} />
          ) : surface.screen === "rates" ? (
            <RatesScreen onError={setError} />
          ) : surface.screen === "team" ? (
            <Team
              team={team}
              currentUserId={currentUserId}
              onChanged={() => void loadTeam()}
              onError={setError}
              onPick={(m) => {
                setCurrentUserId(m.member_id);
              }}
            />
          ) : (
            <Settings demoMode={demoMode} onError={setError} />
          )
        ) : surface.kind === "notdesigned" ? (
          <NotDesigned screen={surface.screen} />
        ) : (
          <SetView
            key={surface.setId}
            setId={surface.setId}
            tab={surface.tab}
            railOpen={railOpen}
            onError={setError}
            onJob={setJob}
            onSetsChanged={() => void loadSets()}
            docTarget={docTarget}
            onDocTargetUsed={() => setDocTarget(null)}
          />
        )}
      </div>

      {/* the whole home page is a drop target; this is the moment of the drop */}
      {dropActive && surface.kind === "home" && (
        <div className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center border-[3px] border-dashed border-cb-brass bg-cb-selected/80">
          <div className="rounded-cb-card bg-cb-page px-6 py-4 font-cb-serif text-[16px] font-semibold text-cb-ink-text shadow-cb-card">
            Drop the binder to start a new tender
          </div>
        </div>
      )}

      <input
        ref={fileInput}
        type="file"
        accept="application/pdf"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = [...(e.target.files ?? [])];
          e.target.value = "";
          if (files.length) void uploadFiles(files);
        }}
      />

      {searchOpen && (
        <CommandSearch
          sets={sets}
          team={team}
          criteria={criteria}
          openSetId={isSet ? surface.setId : null}
          parts={null}
          onClose={() => setSearchOpen(false)}
        />
      )}

      {pickerOpen && loaded && (
        <ProfilePicker
          team={team}
          currentId={currentUserId}
          onPicked={(m) => {
            setCurrentUserId(m.member_id);
            setPickerOpen(false);
            void loadTeam();
          }}
          onError={setError}
          onClose={currentUserId ? () => setPickerOpen(false) : undefined}
        />
      )}
    </div>
  );
}

/** Rates needs its own fetch cycle; kept beside App so the screen component stays pure. */
function RatesScreen({ onError }: { onError: (msg: string) => void }) {
  const [rates, setRates] = useState<Parameters<typeof Rates>[0]["rates"]>(null);
  const load = useCallback(async () => {
    try {
      setRates(await api.rates());
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);
  useEffect(() => {
    void load();
  }, [load]);
  return <Rates rates={rates} onChanged={() => void load()} onError={onError} />;
}

// ---------------------------------------------------------------------------
// One tender — the five steps. The subtree the first build was; unchanged in behaviour, but
// the open set and tab now come from the hash instead of localStorage.
// ---------------------------------------------------------------------------
function SetView({
  setId,
  tab,
  railOpen,
  onError,
  onJob,
  onSetsChanged,
  docTarget,
  onDocTargetUsed,
}: {
  setId: string;
  tab: TabId;
  railOpen: boolean;
  onError: (msg: string) => void;
  onJob: (job: JobState | null) => void;
  onSetsChanged: () => void;
  docTarget: { partId: string; page: number } | null;
  onDocTargetUsed: () => void;
}) {
  const [data, setData] = useState<SetData | null>(null);
  const [opened, setOpened] = useState<Set<TabId>>(() => new Set<TabId>([tab]));
  const [panel, setPanel] = useState<PanelRequest | null>(null);
  const [loading, setLoading] = useState(true);

  // Each piece is optional: a set that has been split but not reviewed simply has no register,
  // and that is a state the UI shows rather than an error it reports.
  const loadSet = useCallback(async () => {
    const rows = await api.sets(true);
    const setRow = rows.sets.find((r) => r.set_id === setId);
    const optional = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

    const [manifest, parts, register, scope] = await Promise.all([
      optional(api.manifest(setId)),
      optional(api.parts(setId)),
      optional(api.register(setId)),
      optional(api.scope(setId)),
    ]);
    // Citations need a reviewed register AND split parts; asking for them before either exists
    // is a 404/409, not a failure worth showing.
    const citations = register ? await optional(api.citations(setId)) : null;

    setData({
      setId,
      name: setRow?.name ?? setId,
      gates: setRow?.gates ?? EMPTY_GATES,
      manifest,
      parts,
      register,
      citations,
      scope,
      hasEstimate: setRow?.price != null,
    });
  }, [setId]);

  useEffect(() => {
    setLoading(true);
    loadSet()
      .catch((e: unknown) => onError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [loadSet, onError]);

  const refresh = useCallback(async () => {
    await loadSet();
    onSetsChanged(); // the desk card's counts moved too
  }, [loadSet, onSetsChanged]);

  const selectTab = useCallback(
    (id: TabId) => {
      setOpened((cur) => (cur.has(id) ? cur : new Set(cur).add(id)));
      go({ kind: "set", setId, tab: id });
    },
    [setId],
  );

  // The deep link is one-shot: once the Documents tab has consumed it, arrow-key browsing and
  // part selection behave exactly as if the user had navigated here themselves.
  useEffect(() => {
    if (docTarget && tab === "documents" && data?.parts) {
      const timer = setTimeout(onDocTargetUsed, 500);
      return () => clearTimeout(timer);
    }
  }, [docTarget, tab, data, onDocTargetUsed]);

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

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <StepStrip current={tab} states={states} opened={opened} onSelect={selectTab} />
      <main className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        {loading && !data ? (
          <WaitingOn title="Opening the set…">
            Reading the manifest, the parts and whatever has been run since.
          </WaitingOn>
        ) : !data ? (
          <WaitingOn title="This tender is not on the shelf">
            It may have been removed. Go back to the desk.
          </WaitingOn>
        ) : tab === "documents" ? (
          <DocumentsTab
            data={data}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={onError}
            onProgress={onJob}
            initialTarget={docTarget}
          />
        ) : tab === "register" ? (
          <RegisterTab
            data={data}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={onError}
            onProgress={onJob}
            onOpenPanel={setPanel}
          />
        ) : tab === "scope" ? (
          <ScopeTab
            data={data}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={onError}
            onProgress={onJob}
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
          onError={onError}
          onChanged={() => void refresh()}
        />
      )}
      {panel?.kind === "addendum" && data && (
        <AddendumPanel
          setId={data.setId}
          docId={panel.docId}
          onClose={() => setPanel(null)}
          onError={onError}
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
 *  the same rule as a step that has not run. */
function NotBuiltYet({ tab }: { tab: TabId; data: SetData }) {
  const label = TABS.find((t) => t.id === tab)?.label ?? tab;
  const copy: Record<string, string> = {
    price: "The price is built and tested on the backend (the workbook and the cost build-up both run). It has no screen yet: this step has not been designed.",
    offer: "The offer letter is drafted by the backend already. It has no screen yet: this step has not been designed.",
  };
  return <WaitingOn title={`${label} — no screen yet`}>{copy[tab] ?? ""}</WaitingOn>;
}

// hashFor is imported for future use by panels that need absolute links; keep the reference.
void hashFor;
