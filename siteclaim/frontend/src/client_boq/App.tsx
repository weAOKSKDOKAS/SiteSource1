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
import { api, health, isNotYet, pollJob, readFailure, runJob, setActor } from "./api";
import { GlobalBar, StepStrip, TAB_FOR_JOB, TAB_FOR_READ, stepStates, usePersisted } from "./chrome";
import type { TabId } from "./chrome";
import { Home } from "./home/Home";
import { NavSidebar } from "./nav/NavSidebar";
import type { NotDesignedId, ScreenId, Surface } from "./nav/routes";
import { go, hashFor, parseHash } from "./nav/routes";
import { commonRoot, fromDrop, fromInput } from "./upload";
import type { PickedFile } from "./upload";
import { NextLine } from "./next";
import { AddendumPanel, RfiPanel } from "./panels";
import type { PanelRequest } from "./panels";
import { ProfilePicker } from "./profile/ProfilePicker";
import { CommandSearch } from "./search/CommandSearch";
import { Benchmarks } from "./screens/Benchmarks";
import { CriteriaLibrary } from "./screens/CriteriaLibrary";
import { NotDesigned } from "./screens/NotDesigned";
import { Outputs } from "./screens/Outputs";
import { Projects } from "./screens/Projects";
import { CostingModelScreen } from "./screens/CostingModel";
import { Rates } from "./screens/Rates";
import { Settings } from "./screens/Settings";
import { Subcontractors } from "./screens/Subcontractors";
import { Team } from "./screens/Team";
import { DocumentsTab } from "./tabs/Documents";
import { BidTab } from "./tabs/Bid";
import { BrainTab } from "./tabs/Brain";
import { Boundary } from "./Boundary";
import { CloseoutTab } from "./tabs/Closeout";
import { OfferTab } from "./tabs/Offer";
import { PriceTab } from "./tabs/Price";
import { RegisterTab } from "./tabs/Register";
import { RouteTab } from "./tabs/Route";
import { ScopeTab } from "./tabs/Scope";
import { SiteTab } from "./tabs/Site";
import { SourcingTab } from "./tabs/Sourcing";
import type {
  BridgeCloseoutState,
  BridgeSubmissionState,
  CitationsResponse,
  CriteriaResponse,
  GateStates,
  JobState,
  Manifest,
  PartsResponse,
  RegisterResponse,
  ScopeResponse,
  SetMeta,
  SetRow,
  Station,
  StationScheduleResponse,
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
  /** The take-off. Null until the borehole details schedule has been read. */
  site: StationScheduleResponse | null;
  /** The desk metadata — the client's name feeds the offer letter's header, so it is never
   *  typed a second time on the Offer screen. */
  meta: SetMeta | null;
  /** The RETIRED resource-schedule engine has run. */
  hasEstimate: boolean;
  /** The CURRENT costing engine has the client's bill and is pricing from it.
   *
   *  These are two flags because they are two engines. `hasEstimate` reads `client_boq_estimates`,
   *  which only `/estimate/run` writes — so a tender priced the normal way (import the bill,
   *  settle the rates) left it false forever, the next-action line never advanced past "build the
   *  price", the Offer chip read WAITS ON THE PRICE, and Offer's only button pointed back at
   *  Price. Two screens pointing at each other, with the way out on neither. */
  hasBill: boolean;
  /** The routing fork, read back from the bridge rather than remembered — a reload must not reset
   *  a step chip to a state the tender is already past. Both reads are pure: they never re-run the
   *  analysis, which would be a write and, live, a model call. */
  route: { hasProposal: boolean; hasDecisions: boolean };
  /** The back of the funnel — final approval + submission — read from the bridge, so a reload
   *  shows the tender's real state (approved / submitted) rather than resetting it. */
  submission: BridgeSubmissionState | null;
  /** The feedback edge — outcome, lessons, change-control — read from the bridge for the same
   *  reason: the Closeout chip and tab show the recorded outcome after a reload. */
  closeout: BridgeCloseoutState | null;
  /** The recorded bid verdict, or "" when nobody has decided. Read back like the rest so a reload
   *  does not reset the Bid chip to a state the tender is already past. */
  bidVerdict: string;
  /**
   * Reads that FAILED, by name — not reads that returned nothing.
   *
   * Every field above is `null` for two different reasons: the step has not run, or the read did
   * not happen. Those were the same value, so a 500 arrived as tender state and every screen
   * believed it. A key in here means the corresponding field's `null` is a hole in what we know,
   * and a screen that would otherwise render nothing must say so instead.
   */
  failures: Record<string, string>;
}

const EMPTY_GATES: GateStates = { manifest: false, review: false, scope: false };

/** The app-bar title for every screen that is not a shelf or a set. Typed as a TOTAL record over
 *  both id unions, so adding a screen to `routes.ts` and forgetting its title is a compile error
 *  rather than an `undefined` in the app bar. The previous inline object literal was exactly the
 *  hand-maintained-copy trap `routes.ts` warns about, one level up. */
const SCREEN_TITLES: Record<ScreenId | NotDesignedId, string> = {
  criteria: "Criteria library",
  rates: "Pricing & rates",
  costing: "Costing model",
  outputs: "Outputs and norms",
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
  /** V1: an unapproved review register warns rather than blocking. The step chips have to
   *  agree, or `WAITS ON THE REGISTER` sits beside a button that works. */
  const [reviewGateSoft, setReviewGateSoft] = useState(false);
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
  /** Every run in flight on the open set, recovered from the server by `SetView`.
   *
   *  Plural because the server pool is TWO workers wide, so an ingest and a review genuinely run
   *  at the same time. The strip used to be handed whichever one `live_any_for` returned first and
   *  described that: observed reading `INGEST · INTERPRETING · STAGE 2 OF 3` while a review ran on
   *  the same set and the banner beside it discussed the review. */
  const [liveJobs, setLiveJobs] = useState<JobState[]>([]);
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
  /** What to do NEXT, offered where the person already is.
   *
   *  Every step after the review crosses a human gate — manifest approval, register verdicts, bill
   *  confirmation, the routing decision — so full automation is wrong and is not built. What was
   *  wrong is that after a stage finished the person had to find the right tab and the right button
   *  themselves. This offers it; it never presses it. Where a gate intervenes the offer is only
   *  ever "go to where the decision is". */
  const [nextUp, setNextUp] = useState<{ label: string; hint: string; go: () => void } | null>(null);

  /** Every job state the tabs report passes through here, so the shell can notice a completion the
   *  tab is about to clear. */
  const noteJob = useCallback((state: JobState | null) => {
    setJob(state);
    if (state?.status !== "done") return;
    const setId = window.location.hash.match(/#\/tender\/s\/([^/]+)/)?.[1];
    if (!setId) return;
    const open = (tab: TabId, label: string, hint: string) =>
      setNextUp({ label, hint, go: () => go({ kind: "set", setId: decodeURIComponent(setId), tab }) });
    // The offer per finished stage. NEVER an approval: where the next thing is a gate, the offer
    // opens the screen the gate lives on and the click is still the person's.
    if (state.kind === "ingest") {
      open("documents", "Review the split", "The manifest is drafted. Approving it is yours.");
    } else if (state.kind === "review") {
      open("register", "Open the register", "Each finding needs a verdict before anything downstream runs.");
    } else if (state.kind === "scope") {
      open("scope", "Open the scope", "The scope is drafted. Freezing it is yours.");
    } else if (state.kind === "estimate") {
      open("offer", "Open the offer letter", "The price is built. The letter draws on it.");
    }
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
      .then((h) => {
        setDemoMode(h.demo_mode);
        // Absent on an older server. The safe reading of a missing value is the STRICTER one:
        // claiming the gate is soft when it is hard would put a Run button in front of a 409.
        setReviewGateSoft(h.review_gate === "soft");
      })
      .catch(() => {
        setDemoMode(false);
        setReviewGateSoft(false);
      });
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

  // An error describes a MOMENT, and this one outlived every moment it described. `error` had
  // exactly one clear — the banner's own dismiss button — so a refusal stayed on screen after the
  // condition passed. Observed live: a 409 banner still up while the review it complained about
  // ran normally beside it.
  //
  // Cleared when the surface changes, which is the only place the shell can know the message is
  // about somewhere the person no longer is. Keyed on kind+setId rather than the object, because
  // `parseHash` builds a fresh one on every hash event and an object identity would clear on
  // every re-parse. Set→set and set→list both change this key; a tab change within one set does
  // not, because an error about that set is still about the set you are looking at.
  //
  // Deliberately NOT a timeout: an error that vanishes on a timer is worse than one that lingers,
  // because the person who looked away has no way to know it was ever there.
  // Every run in flight, deduped: the recovered list plus whatever a tab is reporting live.
  const inFlight = useMemo(() => {
    const byId = new Map<string, JobState>();
    liveJobs.forEach((j) => j.job_id && byId.set(j.job_id, j));
    if (job?.job_id && (job.status === "queued" || job.status === "running")) {
      byId.set(job.job_id, job);
    }
    return [...byId.values()];
  }, [liveJobs, job]);

  // WHICH run the strip describes. Prefer the one belonging to the tab in view; otherwise the most
  // recently started, whose progress is the least stale. The strip belongs to the shell, so the
  // choice does too — SetView reports the list and does not pick.
  const openTab = surface.kind === "set" ? surface.tab : null;
  const shownJob = useMemo(() => {
    if (!inFlight.length) return job;
    const mine = openTab ? inFlight.find((j) => TAB_FOR_JOB[j.kind] === openTab) : null;
    if (mine) return mine;
    return [...inFlight].sort((a, b) => (a.elapsed_seconds ?? 0) - (b.elapsed_seconds ?? 0))[0];
  }, [inFlight, openTab, job]);

  const surfaceKey = `${surface.kind}:${"setId" in surface ? surface.setId : ""}`;
  useEffect(() => {
    setError(null);
  }, [surfaceKey]);

  // --- upload: drop anywhere on the home page, or browse --------------------
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  /** A ZIP of the whole tender pack.
   *
   *  Deliberately not the binder path. `POST /client-boq/ingest/upload` calls `f.file.read()` on
   *  every part, which undoes Starlette's spool-to-disk and holds roughly TWICE the payload
   *  resident — measured at 852 MB RSS for a 241 MB folder. `/bridge/archive/upload` streams a
   *  megabyte at a time, reads the ZIP's central directory without decompressing a byte, and
   *  checks the UNCOMPRESSED total against the ceiling BEFORE opening any member — which is what
   *  makes it a zip-bomb guard rather than a limit discovered too late.
   *
   *  It extracts nothing. What comes back is a PROPOSED manifest, saved unapproved, and the person
   *  approves it on Documents through the same gate a single PDF passes. */
  const uploadArchive = useCallback(
    async (file: File) => {
      setError(null);
      const projectName = file.name.replace(/\.zip$/i, "");
      const mb = Math.round(file.size / (1024 * 1024));
      // The strip goes up before the send, not after: a 230 MB upload has no progress events to
      // report (fetch exposes none), and an unresponsive page is the same thing as a broken one to
      // whoever is watching it.
      setJob({ kind: "archive", status: "running", stage: `sending ${mb} MB` });
      try {
        const report = await track(`Reading the ${projectName} pack`, () =>
          api.bridge.archiveUpload(file, projectName),
        );
        setJob(null);
        await loadSets();
        setError(
          `${report.entries} entries read (${Math.round(report.uncompressed_bytes / (1024 * 1024))} MB ` +
            `unzipped) across ${report.folders.length} folders, proposing ${report.parts} part(s). ` +
            `Nothing has been extracted yet — check the shape and approve the split, and the pack ` +
            `is unpacked as a job you can watch and stop.`,
        );
        go({ kind: "set", setId: report.set_id, tab: "documents" });
      } catch (e) {
        setJob(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [loadSets, track],
  );

  const uploadFiles = useCallback(
    async (files: File[]) => {
      // A new run makes the previous failure history. Cleared at the START, before the work, so
      // the banner never describes a run that has been superseded.
      setError(null);
      // A ZIP of the whole pack takes the streaming archive route. This branch is the whole of
      // defect 3: a dropped .zip used to be filtered out here and answered with "Drop a PDF" —
      // a client-side banner, no request, no status code, no mention of archives — while
      // `/bridge/archive/upload` sat there working, streaming to disk a chunk at a time and
      // checking the uncompressed size before opening a member. The endpoint was never called by
      // anything in this application.
      const archives = files.filter((f) => f.name.toLowerCase().endsWith(".zip"));
      if (archives.length) {
        void uploadArchive(archives[0]);
        return;
      }
      const pdfs = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
      if (!pdfs.length) {
        setError("Drop a PDF binder, a ZIP of the whole tender pack, or the unzipped folder.");
        return;
      }
      const projectName = pdfs[0].name.replace(/\.pdf$/i, "");
      try {
        const done = await track(`Reading ${projectName}`, async () => {
          const state = await runJob(() => api.upload(pdfs, projectName), api.ingestStatus, noteJob);
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
    [loadSets, track, noteJob, uploadArchive],
  );

  /** A folder that is already organised. Nothing is filtered to PDFs here: a workbook is routed
   *  to the bill importer and anything else is listed as held, so dropping the whole tender folder
   *  keeps everything rather than quietly discarding the parts the ingest cannot read. */
  const uploadFolder = useCallback(
    async (picked: PickedFile[]) => {
      setError(null);
      if (!picked.length) {
        setError("That folder had no files in it.");
        return;
      }
      // The folder's own name, not whichever PDF happens to sort first.
      const projectName = commonRoot(picked) || picked[0].path.split("/")[0] || "Tender folder";
      // Two hundred files take a while to send before the job even starts, so the strip goes up
      // immediately — an unresponsive page is the same thing as a broken one to whoever is
      // watching it.
      setJob({ kind: "ingest", status: "running", stage: `sending ${picked.length} files` });
      try {
        // Polled like the binder path: the folder job runs all the way to interpreted parts, so
        // the response is a queued job rather than a finished one.
        const done = await track(`Reading ${projectName}`, async () => {
          const state = await runJob(
            () => api.uploadFolder(picked, projectName),
            api.ingestStatus,
            noteJob,
          );
          setJob(null);
          return state;
        });
        for (const note of done.warnings ?? []) setError(note);
        await loadSets();
        const result = done.result as { set_id?: string } | undefined;
        if (result?.set_id) go({ kind: "set", setId: result.set_id, tab: "documents" });
      } catch (e) {
        setJob(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [loadSets, track, noteJob],
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
      // A dropped DIRECTORY is absent from `dataTransfer.files` — it only exists behind
      // `items[i].webkitGetAsEntry()`. Without this branch, dropping a folder does nothing at all.
      // `fromDrop` returns null when no directory was involved, so two loose PDFs still take the
      // binder path rather than silently switching the whole ingest to folder mode.
      const transfer = e.dataTransfer;
      void fromDrop(transfer).then((picked) => {
        if (picked) {
          void uploadFolder(picked);
          return;
        }
        const files = [...(transfer?.files ?? [])];
        if (files.length) void uploadFiles(files);
      });
    };
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [surface.kind, uploadFiles, uploadFolder]);

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
        // The folder's slug, bare. It used to read `set_id · belvidere` — an internal key name in
        // the one strip of chrome the user never escapes, answering a question nobody asked.
        meta={isSet ? surface.setId : undefined}
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
      {(work || job || nextUp) && (
        <JobStrip
          work={work}
          job={shownJob}
          liveCount={inFlight.length}
          onStop={stopJob}
          next={nextUp}
          onDismissNext={() => setNextUp(null)}
        />
      )}

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
              onBrowseFolder={() => folderInput.current?.click()}
            />
          )
        ) : surface.kind === "screen" ? (
          surface.screen === "criteria" ? (
            <CriteriaLibrary criteria={criteria} onChanged={() => void loadCriteria()} onError={setError} />
          ) : surface.screen === "rates" ? (
            <RatesScreen onError={setError} />
          ) : surface.screen === "costing" ? (
            <CostingModelScreen onError={setError} />
          ) : surface.screen === "outputs" ? (
            <OutputsScreen onError={setError} />
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
            reviewGateSoft={reviewGateSoft}
            onError={setError}
            onJob={noteJob}
            onLiveJobs={setLiveJobs}
            job={shownJob}
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
        // The browse button was closed to archives the same way the drop handler was.
        accept="application/pdf,.zip,application/zip"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = [...(e.target.files ?? [])];
          e.target.value = "";
          if (files.length) void uploadFiles(files);
        }}
      />

      {/* A second input, because `webkitdirectory` turns a picker into a folder picker outright —
          it cannot be a mode on the one above. No `accept`: a tender folder holds workbooks and
          images too, and the point of this route is that none of them are dropped. */}
      <input
        ref={folderInput}
        type="file"
        multiple
        className="hidden"
        // React does not know these attributes; they are what makes it a directory picker.
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
        onChange={(e) => {
          const picked = fromInput(e.target.files);
          e.target.value = "";
          if (picked.length) void uploadFolder(picked);
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

/** The output book, same shape as Rates: its own fetch cycle, the screen stays pure. */
function OutputsScreen({ onError }: { onError: (msg: string) => void }) {
  const [outputs, setOutputs] = useState<Parameters<typeof Outputs>[0]["outputs"]>(null);
  const load = useCallback(async () => {
    try {
      setOutputs(await api.outputs());
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);
  useEffect(() => {
    void load();
  }, [load]);
  return <Outputs outputs={outputs} onChanged={() => void load()} onError={onError} />;
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
  reviewGateSoft,
  onError,
  onJob,
  onLiveJobs,
  job,
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
  /** V1: an unapproved register warns rather than blocking, so the step chips must not claim
   *  scope and route are waiting on it. */
  reviewGateSoft: boolean;
  onError: (msg: string) => void;
  onJob: (job: JobState | null) => void;
  /** Report EVERY run in flight on this set up to the shell, which owns the strip and therefore
   *  owns the choice of which one it describes. */
  onLiveJobs: React.Dispatch<React.SetStateAction<JobState[]>>;
  /** The run in flight, so the step chips and the tab bodies say the same thing the strip does. */
  job: JobState | null;
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

    // A READ THAT FAILED IS NOT A STEP THAT HAS NOT RUN.
    //
    // Every one of these used to be `p.catch(() => null)`, which made a 500 and a 404 the same
    // value — so a transport failure arrived as tender state and every screen believed it. The
    // sharpest case is `submission`: `Offer.tsx` reads `data.submission` and renders its
    // conservation banners off it, INCLUDING the one that says "you are signing without that check
    // having run". A failed read deleted the warning about the missing check, which is the failure
    // mode this whole codebase exists to refuse.
    //
    // The two are distinguishable and always were. `api.ts`'s `handle` attaches the status code, so
    // a 404/409 is genuinely "not yet" and null is the right answer; anything else — a 500, or a
    // network failure with no status at all — is a read that did not happen, and it is recorded
    // under its own name rather than flattened into the same null.
    const failures: Record<string, string> = {};
    const optional = <T,>(key: string, p: Promise<T>): Promise<T | null> =>
      p.catch((e: unknown) => {
        if (!isNotYet(e)) failures[key] = readFailure(e);
        return null;
      });

    const [manifest, parts, register, scope, proposal, decisions, site, submission] =
      await Promise.all([
        optional("manifest", api.manifest(setId)),
        optional("parts", api.parts(setId)),
        optional("register", api.register(setId)),
        optional("scope", api.scope(setId)),
        optional("proposal", api.bridge.proposal(setId)),
        optional("decisions", api.bridge.decisions(setId)),
        // The take-off, for the step strip: the Site chip must not say "not read yet" about a
        // schedule somebody has read, and Price carries the unassigned-hole count live.
        optional("site", api.stationSchedule(setId)),
        // The approval/submission state, read the same pure way — so the Offer chip and panel
        // show APPROVED / SUBMITTED after a reload instead of resetting to "not yet approved".
        optional("submission", api.bridge.submission(setId)),
      ]);
    const closeout = await optional("closeout", api.bridge.closeout(setId));
    // The tender's first decision, for the step strip and the tab chip. A pure read: asking for
    // the brief never records anything.
    const bidBrief = await optional("bid", api.bridge.bid(setId));
    // Citations need a reviewed register AND split parts; asking for them before either exists
    // is a 404/409, not a failure worth showing.
    const citations = register ? await optional("citations", api.citations(setId)) : null;

    setData({
      setId,
      name: setRow?.name ?? setId,
      gates: setRow?.gates ?? EMPTY_GATES,
      manifest,
      parts,
      register,
      citations,
      scope,
      site,
      meta: setRow?.meta ?? null,
      hasEstimate: setRow?.price != null,
      hasBill: Boolean(setRow?.has_bill),
      route: {
        hasProposal: Boolean(proposal?.packages.length),
        hasDecisions: Boolean(decisions?.decisions.length),
      },
      submission,
      closeout,
      bidVerdict: bidBrief?.decision?.verdict ?? "",
      failures,
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

  // Ask the server what this set is already doing, and adopt it.
  //
  // Without this the screen's only knowledge of a run was the poll loop that started it — which
  // lived in a tab component, and tabs unmount on navigation. So: start a review, switch tabs,
  // come back, and the Register tab rendered a Run button over a review that was still running.
  // Pressing it got a 409 refusing an action the UI had just invited. A hard browser refresh was
  // worse: nothing anywhere knew, and the strip stayed blank for the rest of the run.
  //
  // `pollJob` dedupes by job id (`LIVE_POLLS` in api.ts), so joining a loop that is already
  // running costs nothing and cannot produce a second one. Re-runs per `setId`, because that is
  // the question being asked — what is THIS set doing.
  useEffect(() => {
    let adopted = true;
    void api
      .liveJobs(setId)
      .then(({ jobs: live }) => {
        if (!adopted) return;
        const running = live.filter(
          (j) => j.job_id && (j.status === "queued" || j.status === "running"),
        );
        onLiveJobs(running);
        // Adopt EVERY one. `pollJob` dedupes by id, so joining costs nothing and cannot start a
        // second loop — and adopting only the first would leave the other invisible again, which
        // is the defect this plural exists to close.
        running.forEach((state) => {
          const status =
            state.kind === "review"
              ? api.reviewStatus
              : state.kind === "brain"
                ? api.brainStatus
                : state.kind === "ingest" || state.kind === "archive"
                  ? api.ingestStatus
                  : api.estimateStatus; // scope and estimate share the estimate poll endpoint
          void pollJob(status, state.job_id as string, onJob)
            .catch(() => undefined) // the banner belongs to whoever STARTED the run, not a re-join
            .finally(() => {
              if (!adopted) return;
              onLiveJobs((cur) => cur.filter((j) => j.job_id !== state.job_id));
              void refresh();
            });
        });
      })
      .catch(() => undefined); // a set with no job is the normal case, and never an error
    return () => {
      // Stops THIS effect adopting a late answer after the set changed. The poll loops themselves
      // are deliberately left alone: they belong to their jobs, and the shell-level strip is what
      // makes a run survive navigation in the first place.
      adopted = false;
    };
  }, [setId, refresh, onJob, onLiveJobs]);

  // Which tab's work is running, translated from the job's own vocabulary. Only while it is
  // actually in flight: a finished or cancelled job leaves the chips to `data`, which by then
  // reflects the result.
  const runningTab =
    job && (job.status === "queued" || job.status === "running")
      ? TAB_FOR_JOB[job.kind] ?? null
      : null;

  const states = useMemo(
    () =>
      stepStates(data?.gates ?? EMPTY_GATES, {
        parts: Boolean(data?.parts?.count),
        register: Boolean(data?.register),
        scope: Boolean(data?.scope),
        // Either engine. A chip that says WAITS ON THE PRICE about a tender that has been priced
        // is worse than no chip.
        estimate: Boolean(data?.hasEstimate || data?.hasBill),
        proposal: Boolean(data?.route.hasProposal),
        decisions: Boolean(data?.route.hasDecisions),
        site: Boolean(data?.site?.stations.length),
        // Two different states, and the count alone cannot tell them apart: every hole classified
        // reads 0, and no hole read at all also reads 0.
        noTakeOff: !data?.site?.stations.length,
        unassignedHoles: (data?.site?.stations ?? []).filter(
          (s: Station) => !data?.site?.classes[s.station]?.access_class,
        ).length,
        bidVerdict: data?.bidVerdict ?? "",
        submitted: Boolean(data?.submission?.submission),
        outcomeRecorded: Boolean(
          data?.closeout?.outcome && data.closeout.outcome.status !== "submitted"),
      }, runningTab, reviewGateSoft,
      // A chip must not report the state a missing read implies.
      [...new Set(Object.keys(data?.failures ?? {})
        .map((key) => TAB_FOR_READ[key])
        .filter(Boolean))] as TabId[]),
    [data, runningTab, reviewGateSoft],
  );

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <StepStrip current={tab} states={states} opened={opened} onSelect={selectTab} />
      {/* "What now?", answered in one consistent place on every tender screen — from the same
          data the chips read, so the two can never argue. The button only navigates. */}
      {data && <NextLine data={data} current={tab} onGo={selectTab} />}
      {/* A READ THAT FAILED, NAMED. Every one of these used to arrive as `null` and be shown as
          "this step has not run" — so the screens went on rendering a tender state nobody had
          actually read. Named rather than a generic banner, because "the submission state could
          not be read" and "the register could not be read" send a person to different places. */}
      {data && Object.keys(data.failures).length > 0 && (
        <div
          role="status"
          className="flex-none border-b border-cb-bad-line bg-cb-bad-tint px-[18px] py-1.5"
        >
          <p className="font-cb-sans text-[10.5px] leading-[1.55] text-cb-bad-dark">
            <span className="font-semibold">
              {Object.keys(data.failures).length} of this tender's reads did not come back
            </span>{" "}
            — {Object.keys(data.failures).join(", ")}. Anything on screen that depends on{" "}
            {Object.keys(data.failures).length > 1 ? "them" : "it"} is showing a gap in what was
            read, not a step that has not run. Reload once the server is answering again.
          </p>
        </div>
      )}
      {/* THE WHITE SCREEN, ENDED. A render error inside one tab used to unmount the whole
          application — shell, strip, rail and all — leaving a blank page and the real message in
          a console nobody had open. Keyed on the tab so moving to another step clears it, and
          scoped INSIDE <main> so the shell survives and you can navigate away from the screen
          that broke. */}
      <main className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <Boundary key={tab ?? "none"} label={tab ?? "this screen"} onReset={() => void refresh()}>
        {loading && !data ? (
          <WaitingOn title="Opening the set…">
            Reading the manifest, the parts and whatever has been run since.
          </WaitingOn>
        ) : !data ? (
          <WaitingOn title="This tender is not on the shelf">
            It may have been removed. Go back to the desk.
          </WaitingOn>
        ) : tab === "brain" ? (
          <BrainTab
            data={data}
            onError={onError}
            onProgress={onJob}
            onGo={(next) => go({ kind: "set", setId: data.setId, tab: next })}
          />
        ) : tab === "documents" ? (
          <DocumentsTab
            data={data}
            job={job}
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
            job={job}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={onError}
            onProgress={onJob}
            onOpenPanel={setPanel}
          />
        ) : tab === "bid" ? (
          <BidTab data={data} onError={onError} onRefresh={refresh} />
        ) : tab === "scope" ? (
          <ScopeTab
            data={data}
            job={job}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={onError}
            onProgress={onJob}
          />
        ) : tab === "site" ? (
          <SiteTab data={data} railOpen={railOpen} onError={onError} />
        ) : tab === "route" ? (
          <RouteTab data={data} onError={onError} onRefresh={refresh} onTrack={onTrack} />
        ) : tab === "sourcing" ? (
          <SourcingTab data={data} demoMode={demoMode} onError={onError} />
        ) : tab === "price" ? (
          <PriceTab
            data={data}
            job={job}
            railOpen={railOpen}
            onRefresh={refresh}
            onError={onError}
            onProgress={onJob}
            onTrack={onTrack}
          />
        ) : tab === "offer" ? (
          <OfferTab data={data} onError={onError} onRefresh={refresh} />
        ) : (
          // The fallthrough renders Closeout — the last tab. A tab appended after it would need its
          // own explicit branch above, exactly as `offer` now has one.
          <CloseoutTab data={data} onError={onError} onRefresh={refresh} />
        )}
        </Boundary>
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
  liveCount,
  onStop,
  next,
  onDismissNext,
}: {
  work: { label: string; status: "running" | "done" } | null;
  job: JobState | null;
  /** How many runs are in flight on this set. More than one is SAID rather than resolved
   *  silently — the strip can only describe one, and hiding the other is how it came to describe
   *  the wrong one. */
  liveCount?: number;
  onStop: (jobId: string) => void;
  /** The next action, offered — never taken. Outlives the six-second DONE strip, because an offer
   *  nobody had time to read is not an offer. */
  next: { label: string; hint: string; go: () => void } | null;
  onDismissNext: () => void;
}) {
  const running = Boolean(job) || work?.status === "running";
  const done = !running && (work?.status === "done" || Boolean(next));
  // Queued is a THIRD state, not a flavour of running: nothing has been spent, no stage has been
  // entered, and the bar must not imply otherwise.
  const queuing = job?.status === "queued";
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
  // THE HEADING NAMES WHOSE PROGRESS THIS IS.
  //
  // It used to read `work?.label ?? job?.kind` — and that `??` was a lie waiting to happen. `work`
  // is a per-ACTION label set by `track()`, with no job id, no kind and no link to anything on the
  // server; `job` is chosen per-SET out of `/jobs/live-all`. Nothing joins them, and the `??`
  // dropped the one token that would have exposed the mismatch precisely when a mismatch was
  // possible. Observed live: "PROPOSING A ROUTE PER PACKAGE · INGESTING · STAGE 1 · 0/94" — the
  // Route tab's label spliced onto a REVIEW job's first stage (which is called "ingesting", a
  // homonym of the ingest workflow), with a chunk counter that has nothing to do with packages.
  //
  // The Route tab's analyze is a blocking HTTP call that creates no job (`bridge/router.py:241`),
  // so it can never appear in `inFlight` — which is also why the "+N MORE RUNNING" chip, the one
  // guard built for this, could not fire. And `TAB_FOR_JOB` has no entry for "route", so the
  // "prefer the job this tab owns" branch is structurally dead there and the arbitrary fallback
  // always wins.
  //
  // The bar, the counter, the elapsed time and the STOP button all describe the JOB. So the job
  // keeps the heading and is always named by kind, and an unrelated action label is shown beside
  // it as its own statement rather than being joined to it as though they were one thing.
  const jobHeading = [job?.kind, job?.stage?.replace(/-/g, " ")]
    .filter(Boolean)
    .join(" · ")
    .toUpperCase();
  const heading = jobHeading || (work?.label ?? "").toUpperCase();
  // An action running BESIDE the job. Suppressed when it is the only thing running, because then
  // it is the heading.
  const alongside = jobHeading && work?.status === "running" ? work.label : "";
  return (
    <div
      // A live region: a run starting, progressing and finishing is exactly the kind of state
      // change a screen-reader user otherwise discovers by accident.
      role="status"
      aria-live="polite"
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
      {!done && alongside && (
        <Chip
          className="flex-none border border-cb-amber text-cb-amber"
          title={
            `"${alongside}" is running too. It is a direct call rather than a background job, so ` +
            `it has no progress of its own — everything else on this bar describes the ` +
            `${(job?.kind ?? "background").toUpperCase()} job, including STOP.`
          }
        >
          ALSO: {alongside.toUpperCase()}
        </Chip>
      )}
      {!done && (liveCount ?? 0) > 1 && (
        <Chip className="flex-none border border-cb-amber text-cb-amber">
          +{(liveCount ?? 1) - 1} MORE RUNNING
        </Chip>
      )}
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
          title={
            queuing
              ? "Waiting for a worker. The pool holds two, shared by every workflow, so this run has spent nothing yet."
              : (job.queued_seconds ?? 0) >= 1
                ? `Working for ${elapsed(job.running_seconds ?? 0)}, after waiting ${elapsed(job.queued_seconds ?? 0)} for a worker. There is no estimate of what remains — nothing here can honestly make one.`
                : "Time spent working. There is no estimate of what remains — nothing here can honestly make one."
          }
        >
          {/* Waiting is not working, and adding them together said the machine was slow when it
              was in fact busy elsewhere. A queued job shows its wait, labelled as a wait; a
              running one shows work time, and names the wait behind it only when there was one. */}
          {queuing ? `QUEUED ${elapsed(job.queued_seconds ?? 0)}` : elapsed(job.running_seconds ?? job.elapsed_seconds)}
          {!queuing && (job.queued_seconds ?? 0) >= 1 && (
            <span className="opacity-60"> · queued {elapsed(job.queued_seconds ?? 0)}</span>
          )}
        </span>
      )}
      <span
        className={cx("font-cb-sans text-[10px]", done ? "text-cb-ok-dark" : "text-cb-brass-text")}
      >
        {done
          ? next?.hint ?? "Finished. Open the tab that started it to see the result."
          : job?.cancel_requested
            ? "Stopping at the next step. The call already in flight has to finish first — it cannot be interrupted."
            : queuing
              ? "Waiting for a free worker — nothing has been spent yet, and stopping it now costs nothing."
              : "Still running — it keeps going wherever you navigate."}
      </span>
      {!done && job?.job_id && !job.cancel_requested && (
        <button
          type="button"
          onClick={() => onStop(job.job_id as string)}
          // Names the job, because the bar may be showing an unrelated action beside it and this
          // button has only ever cancelled the job. A STOP that does not say what it stops is the
          // same splice as the heading, one control further along.
          title={`Stop the ${(job.kind ?? "background").toUpperCase()} job after its current step `
            + `finishes.${alongside ? ` "${alongside}" is not a job and cannot be stopped here.` : ""}`}
          className="cb-press ml-auto flex-none rounded-cb-btn border border-cb-brass-line px-2.5 py-[3px] font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-brass-text"
        >
          STOP
        </button>
      )}
      {done && next && (
        <>
          <button
            type="button"
            onClick={() => {
              next.go();
              onDismissNext();
            }}
            title={next.hint}
            className="cb-press ml-auto flex-none rounded-cb-btn border border-cb-ok bg-white px-2.5 py-[3px] font-cb-sans text-[10.5px] font-semibold text-cb-ok-dark"
          >
            {next.label} →
          </button>
          <button
            type="button"
            onClick={onDismissNext}
            title="Dismiss"
            className="cb-press flex-none px-1 font-cb-mono text-[12px] text-cb-ok-dark"
          >
            ×
          </button>
        </>
      )}
    </div>
  );
}

// hashFor is imported for future use by panels that need absolute links; keep the reference.
void hashFor;
