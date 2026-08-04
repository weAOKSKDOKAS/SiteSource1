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
import { GlobalBar, StepStrip, stepStates, usePersisted } from "./chrome";
import type { TabId } from "./chrome";
import { Home } from "./home/Home";
import { NavSidebar } from "./nav/NavSidebar";
import type { NotDesignedId, ScreenId, Surface } from "./nav/routes";
import { go, hashFor, parseHash } from "./nav/routes";
import { AddendumPanel, RfiPanel } from "./panels";
import type { PanelRequest } from "./panels";
import { ProfilePicker } from "./profile/ProfilePicker";
import { CommandSearch } from "./search/CommandSearch";
import { Benchmarks } from "./screens/Benchmarks";
import { CriteriaLibrary } from "./screens/CriteriaLibrary";
import { NotDesigned } from "./screens/NotDesigned";
import { Projects } from "./screens/Projects";
import { Rates } from "./screens/Rates";
import { Settings } from "./screens/Settings";
import { Subcontractors } from "./screens/Subcontractors";
import { Team } from "./screens/Team";
import { DocumentsTab } from "./tabs/Documents";
import { OfferTab } from "./tabs/Offer";
import { PriceTab } from "./tabs/Price";
import { RegisterTab } from "./tabs/Register";
import { RouteTab } from "./tabs/Route";
import { ScopeTab } from "./tabs/Scope";
import { SourcingTab } from "./tabs/Sourcing";
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
import { Avatar, Chip, ErrorNote, WaitingOn, cx } from "./ui";
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
  /** The routing fork, read back from the bridge rather than remembered — a reload must not reset
   *  a step chip to a state the tender is already past. Both reads are pure: they never re-run the
   *  analysis, which would be a write and, live, a model call. */
  route: { hasProposal: boolean; hasDecisions: boolean };
}

const EMPTY_GATES: GateStates = { manifest: false, review: false, scope: false };

/** The app-bar title for every screen that is not a shelf or a set. Typed as a TOTAL record over
 *  both id unions, so adding a screen to `routes.ts` and forgetting its title is a compile error
 *  rather than an `undefined` in the app bar. The previous inline object literal was exactly the
 *  hand-maintained-copy trap `routes.ts` warns about, one level up. */
const SCREEN_TITLES: Record<ScreenId | NotDesignedId, string> = {
  criteria: "Criteria library",
  rates: "Pricing & rates",
  team: "Team & access",
  settings: "AI model",
  subcontractors: "Subcontractors",
  benchmarks: "Benchmarks",
  projects: "Projects",
  letters: "Letter templates",
  positions: "Standard positions",
  clients: "Clients",
  audit: "Audit log",
};

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
  // What long-running work is in flight, ABOVE the tab that started it.
  //
  // A split on the Route tab looked like it paused when you navigated away. It did not: the work
  // is a sync handler on the server (or, for ingest/review/estimate, a thread on `jobs.POOL`), and
  // neither cares what the browser is showing. What died was the only record that it was running —
  // a `busy` string inside the tab component, which unmounts with the tab. So the record lives
  // here, on the root, which never unmounts; a 26-page bill takes minutes and nobody should have
  // to sit on one screen watching it.
  const [work, setWork] = useState<{ label: string; status: "running" | "done" } | null>(null);
  const doneTimer = useRef<number | null>(null);
  useEffect(() => () => {
    if (doneTimer.current) window.clearTimeout(doneTimer.current);
  }, []);

  /** Run something long and let the whole shell know. `job` still carries per-stage progress where
   *  the server exposes a job id; this carries the fact that ANYTHING is running, which is the part
   *  a blocking endpoint like the bridge split never had. A failure clears rather than marks: the
   *  error banner directly above is the report, and a red strip beside it would just compete. */
  const track = useCallback(async <T,>(label: string, run: () => Promise<T>): Promise<T> => {
    if (doneTimer.current) {
      window.clearTimeout(doneTimer.current);
      doneTimer.current = null;
    }
    setWork({ label, status: "running" });
    try {
      const out = await run();
      setWork({ label, status: "done" });
      doneTimer.current = window.setTimeout(() => setWork(null), 6000);
      return out;
    } catch (e) {
      setWork(null);
      throw e;
    }
  }, []);
  /** Ask the server to stop at its next stage boundary. The strip keeps showing the run until it
   *  actually stops — the current model call cannot be interrupted, and pretending otherwise
   *  would have the screen disagree with what the machine is doing. */
  const stopJob = useCallback((jobId: string) => {
    void api.cancelJob(jobId).then(setJob).catch(() => undefined);
  }, []);
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
        const done = await track(`Reading ${projectName}`, async () => {
          const state = await runJob(() => api.upload(pdfs, projectName), api.ingestStatus, setJob);
          setJob(null);
          return state;
        });
        // Whatever the ingest needs the person to know that is not in the manifest — today, that
        // this upload landed on a tender that already exists rather than starting a new one.
        for (const note of done.warnings ?? []) setError(note);
        await loadSets();
        const result = done.result as { set_id?: string } | undefined;
        if (result?.set_id) go({ kind: "set", setId: result.set_id, tab: "documents" });
      } catch (e) {
        setJob(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [loadSets, track],
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
        : SCREEN_TITLES[surface.screen];

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
      {/* Above the sidebar/content split, so it is on screen from every tab AND from the desk. */}
      {(work || job) && <JobStrip work={work} job={job} onStop={stopJob} />}

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
          ) : surface.screen === "subcontractors" ? (
            <Subcontractors onError={setError} />
          ) : surface.screen === "benchmarks" ? (
            <Benchmarks onError={setError} />
          ) : surface.screen === "projects" ? (
            <Projects onError={setError} />
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
            demoMode={demoMode}
            onError={setError}
            onJob={setJob}
            onTrack={track}
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
  demoMode,
  onError,
  onJob,
  onTrack,
  onSetsChanged,
  docTarget,
  onDocTargetUsed,
}: {
  setId: string;
  tab: TabId;
  railOpen: boolean;
  /** DEMO means uploaded files were not read. Sourcing needs it: the live path shows the assembled
   *  attachment plan and can hand bundles to Gmail; DEMO does neither. */
  demoMode: boolean;
  onError: (msg: string) => void;
  onJob: (job: JobState | null) => void;
  /** Register long work with the shell, so it stays visible after this tab unmounts. */
  onTrack: <T,>(label: string, run: () => Promise<T>) => Promise<T>;
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

    const [manifest, parts, register, scope, proposal, decisions] = await Promise.all([
      optional(api.manifest(setId)),
      optional(api.parts(setId)),
      optional(api.register(setId)),
      optional(api.scope(setId)),
      optional(api.bridge.proposal(setId)),
      optional(api.bridge.decisions(setId)),
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
      route: {
        hasProposal: Boolean(proposal?.packages.length),
        hasDecisions: Boolean(decisions?.decisions.length),
      },
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
        proposal: Boolean(data?.route.hasProposal),
        decisions: Boolean(data?.route.hasDecisions),
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
            onTrack={onTrack}
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
        ) : tab === "route" ? (
          <RouteTab data={data} onError={onError} onRefresh={refresh} onTrack={onTrack} />
        ) : tab === "sourcing" ? (
          <SourcingTab data={data} demoMode={demoMode} onError={onError} />
        ) : tab === "price" ? (
          <PriceTab
            data={data}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={onError}
            onProgress={onJob}
            onTrack={onTrack}
          />
        ) : (
          <OfferTab data={data} onError={onError} />
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
/** `4m 12s`. Elapsed only — see `JobState.elapsed_seconds`. */
function elapsed(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

function JobStrip({
  work,
  job,
  onStop,
}: {
  work: { label: string; status: "running" | "done" } | null;
  job: JobState | null;
  onStop: (jobId: string) => void;
}) {
  const done = work?.status === "done" && !job;
  // A DETERMINATE bar only where the total is genuinely known. Everywhere else the bar is
  // indeterminate and says so by moving on nothing — a bar that advances on a timer rather than on
  // work is worse than one that admits it does not know.
  const pct = job?.total ? Math.round(((job.done ?? 0) / job.total) * 100) : null;
  // "stage 4 of 8" where the workflow's length is certain; "stage 4" where its tail is
  // conditional; neither where the sequence is not known at all.
  const position = job?.stage_index
    ? job.stage_total
      ? `STAGE ${job.stage_index} OF ${job.stage_total}`
      : `STAGE ${job.stage_index}`
    : "";
  const heading = [work?.label ?? job?.kind, job?.stage?.replace(/-/g, " ")]
    .filter(Boolean)
    .join(" · ")
    .toUpperCase();
  return (
    <div
      className={cx(
        "flex flex-none items-center gap-3 border-b px-[18px] py-2",
        done ? "border-cb-ok bg-cb-ok-tint" : "border-cb-brass-line bg-cb-brass-tint",
      )}
    >
      <span
        className={cx("h-2 w-2 flex-none rounded-full", done ? "bg-cb-ok" : "ssDot bg-cb-brass")}
      />
      <span
        className={cx(
          "flex-none font-cb-mono text-[9px] font-semibold tracking-cb-label",
          done ? "text-cb-ok-dark" : "text-cb-brass-text",
        )}
      >
        {done ? `${heading} · DONE` : heading}
      </span>
      {!done && position && (
        <Chip className="flex-none border border-cb-brass-line text-cb-brass-text">{position}</Chip>
      )}
      {!done && pct != null && (
        <span className="flex-none font-cb-mono text-[10px] text-cb-brass-text">
          {job?.done}/{job?.total}
        </span>
      )}
      {!done && (
        <div className="h-[4px] max-w-[280px] flex-1 overflow-hidden rounded-[2px] bg-cb-brass-line">
          <div
            style={{ width: pct != null ? `${pct}%` : "35%" }}
            className={cx(
              "h-full bg-cb-brass transition-[width] duration-300 ease-out",
              pct == null && "animate-pulse",
            )}
          />
        </div>
      )}
      {!done && job?.elapsed_seconds != null && (
        <span
          className="flex-none font-cb-mono text-[10px] text-cb-brass-text"
          title="Time since this run started. There is no estimate of what remains — nothing here can honestly make one."
        >
          {elapsed(job.elapsed_seconds)}
        </span>
      )}
      <span
        className={cx("font-cb-sans text-[10px]", done ? "text-cb-ok-dark" : "text-cb-brass-text")}
      >
        {done
          ? "Finished. Open the tab that started it to see the result."
          : job?.cancel_requested
            ? "Stopping at the next step. The call already in flight has to finish first — it cannot be interrupted."
            : "Still running — it keeps going wherever you navigate."}
      </span>
      {!done && job?.job_id && !job.cancel_requested && (
        <button
          type="button"
          onClick={() => onStop(job.job_id as string)}
          title="Stop after the current step finishes"
          className="cb-press ml-auto flex-none rounded-cb-btn border border-cb-brass-line px-2.5 py-[3px] font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-brass-text"
        >
          STOP
        </button>
      )}
    </div>
  );
}

// hashFor is imported for future use by panels that need absolute links; keep the reference.
void hashFor;
