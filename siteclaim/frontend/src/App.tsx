import { useEffect, useState } from "react";
import { api } from "./api";
import { BenchmarkPage } from "./BenchmarkPage";
import { DatabasePage } from "./DatabasePage";
import { EstimatorPage } from "./EstimatorPage";
import { ProjectsPage } from "./ProjectsPage";
import { RouteDecisionPanel } from "./RouteDecisionPanel";
import { Header, StepHeading, Stepper, type StepIndex, type TopView } from "./components";
import { tradeLabel } from "./format";
import type {
  AwaitingPackage,
  BidReply,
  Coverage,
  DemoCaseSummary,
  DispatchSet,
  LevelledBid,
  Recommendation,
  RouteDecisionResult,
  RouteProposal,
  ScopePackages,
  ShortlistSet,
  TenderPackage,
} from "./types";
import { Button, Card, ErrorBanner, LayerBadge } from "./ui";
import { StepIngest } from "./steps/StepIngest";
import { StepShortlist } from "./steps/StepShortlist";
import { StepDispatch } from "./steps/StepDispatch";
import { StepLevel } from "./steps/StepLevel";
import { StepRecommend } from "./steps/StepRecommend";
import { IngestProgress, type IngestPhase } from "./IngestProgress";

export default function App() {
  // Meta
  const [demoMode, setDemoMode] = useState(true);
  const [view, setView] = useState<TopView>("wizard");
  const [demoCases, setDemoCases] = useState<DemoCaseSummary[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);

  // Navigation
  const [step, setStep] = useState<StepIndex>(1);
  const [maxReached, setMaxReached] = useState<StepIndex>(1);

  // Source
  const [caseId, setCaseId] = useState<string | null>(null);
  const [heroTrade, setHeroTrade] = useState("electrical");
  const [tender, setTender] = useState<TenderPackage | null>(null);
  const [replies, setReplies] = useState<BidReply[]>([]);
  // trade -> baked rationale fixture (DEMO); a trade with no entry narrates offline.
  const [rationaleFixtures, setRationaleFixtures] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<File[]>([]);
  // true when this run is a live upload (real extraction, no demo replies) vs a demo
  // scenario. In live mode the Level step never levels a scenario fixture — it shows the
  // awaiting-replies state until real priced returns land (inbound loop or manual upload).
  const [liveRun, setLiveRun] = useState(false);

  // Pipeline state
  const [scope, setScope] = useState<ScopePackages | null>(null);          // full ingest split (feeds Route)
  const [proposal, setProposal] = useState<RouteProposal | null>(null);    // routing gate
  const [chosen, setChosen] = useState<Record<string, string>>({});        // per-package route decision
  const [routeResult, setRouteResult] = useState<RouteDecisionResult | null>(null);
  const [sourceScope, setSourceScope] = useState<ScopePackages | null>(null); // sublet-only scope (feeds Shortlist→Recommend)
  const [tenderSlug, setTenderSlug] = useState("");  // server-derived slug for the replies panel
  const [shortlist, setShortlist] = useState<ShortlistSet | null>(null);
  const [approvals, setApprovals] = useState<Record<string, string[]>>({});
  const [dispatch, setDispatch] = useState<DispatchSet | null>(null);
  // Human-edited enquiry drafts, keyed "trade:firmId" — they persist across the dispatch
  // pop-up being closed and reopened (the send carries exactly the edited text).
  const [drafts, setDrafts] = useState<Record<string, { subject: string; body: string }>>({});
  // Per-section leveling: one LevelledBid[] per sublet trade — a trade is only ever
  // levelled against its own bids (Prompt 1).
  const [levelledByTrade, setLevelledByTrade] = useState<Record<string, LevelledBid[]> | null>(null);
  const [levelStale, setLevelStale] = useState(false);
  // One recommendation and one HUMAN award per sublet trade ("" = explicitly skipped).
  const [recommendationByTrade, setRecommendationByTrade] = useState<Record<string, Recommendation> | null>(null);
  const [awardByTrade, setAwardByTrade] = useState<Record<string, string>>({});

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Live-ingest progress modal (a big upload extracts for minutes). null = closed.
  const [ingestModal, setIngestModal] = useState<
    { phase: IngestPhase; startedAt: number; error?: string; summary?: { items: number; packages: number } } | null
  >(null);

  useEffect(() => {
    api.health().then((h) => setDemoMode(h.demo_mode)).catch(() => {});
    api.demoCases().then(setDemoCases).catch(() => {});
    api.coverage().then(setCoverage).catch(() => {});
  }, []);

  async function run(fn: () => Promise<void>) {
    setLoading(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function advance(to: StepIndex) {
    setStep(to);
    setMaxReached((m) => (to > m ? to : m));
  }

  // Editing a gate invalidates every later gate (the ICM review-gate rule). Steps:
  // 1 Ingest · 2 Route · 3 Shortlist · 4 Dispatch · 5 Level · 6 Recommend.
  function invalidateAfter(keep: StepIndex) {
    if (keep < 2) {
      // Re-ingesting resets the routing proposal + decision (and the sublet scope it feeds).
      setProposal(null);
      setChosen({});
      setRouteResult(null);
      setSourceScope(null);
    }
    if (keep < 3) {
      setShortlist(null);
      setApprovals({});
      setDrafts({});
    }
    if (keep < 4) setDispatch(null);
    if (keep < 5) {
      setLevelledByTrade(null);
      setLevelStale(false);
    }
    if (keep < 6) {
      setRecommendationByTrade(null);
      setAwardByTrade({});
    }
    setMaxReached((m) => (m > keep ? keep : m));
  }

  async function pickDemo(id: string) {
    await run(async () => {
      const source = await api.demoCase(id);
      setCaseId(id);
      setLiveRun(false); // a demo scenario — its baked replies drive Level & compare
      setHeroTrade(source.hero_trade);
      setTender(source.tender);
      setReplies(source.replies);
      setRationaleFixtures(source.rationale_fixtures ?? {});
      setFiles([]);
      setScope(null);
      invalidateAfter(1);
    });
  }

  // A live upload extracts for minutes — it runs the progress modal, then analyses routing
  // on the fresh scope and auto-advances to Route. The demo/scenario path is instant and
  // skips the modal.
  const runLiveIngest = async () => {
    const startedAt = Date.now();
    setError(null);
    setIngestModal({ phase: "uploading", startedAt });
    try {
      const uploaded = await api.ingestUpload(files, () =>
        setIngestModal((m) => (m && m.phase === "uploading" ? { ...m, phase: "processing" } : m)),
      );
      setTender(uploaded.tender); // trade-tagged tender -> per-trade routing at dispatch
      setTenderSlug(uploaded.tender_slug); // for the live replies panel on the dispatch step
      setScope(uploaded.scope);
      setCaseId(null);
      setLiveRun(true); // live run — Level shows awaiting states, never demo replies
      invalidateAfter(1);
      const items = uploaded.scope.packages.reduce((n, p) => n + p.sor_items.length, 0);
      setIngestModal({ phase: "done", startedAt, summary: { items, packages: uploaded.scope.packages.length } });
      // Analyse routing on the fresh scope (not the stale closure), then auto-advance to Route.
      const p = await api.routeAnalyze(uploaded.scope);
      setProposal(p);
      setChosen(Object.fromEntries(p.packages.map((pkg) => [pkg.package_key, pkg.recommended_route])));
      setRouteResult(null);
      setIngestModal(null);
      advance(2);
    } catch (e) {
      setIngestModal((m) => ({ phase: "error", startedAt: m?.startedAt ?? startedAt, error: e instanceof Error ? e.message : String(e) }));
    }
  };

  const runIngest = () => {
    if (!demoMode && files.length > 0) return runLiveIngest();
    return run(async () => {
      if (!tender) return;
      const result = await api.ingest(tender);
      setScope(result);
      setLiveRun(false);
      invalidateAfter(1);
    });
  };

  // Step 2 — Route. Analyse the ingested scope; default each package to its recommendation.
  // The decision is durable: if a proposal already exists for this scope (only a re-ingest
  // clears it, via invalidateAfter(1)), returning here shows the confirmed decision — the
  // chosen routes and split summary — never a blank re-analyze.
  const goRoute = () =>
    run(async () => {
      if (!scope) return;
      if (proposal) {
        advance(2);
        return;
      }
      const p = await api.routeAnalyze(scope);
      setProposal(p);
      setChosen(Object.fromEntries(p.packages.map((pkg) => [pkg.package_key, pkg.recommended_route])));
      setRouteResult(null);
      advance(2);
    });

  const acceptAllRoutes = () =>
    proposal && setChosen(Object.fromEntries(proposal.packages.map((p) => [p.package_key, p.recommended_route])));

  // Confirm the routing gate: record the decisions (the run seeds self-perform estimates on
  // the backend), then shortlist ONLY the sublet packages.
  const confirmRoute = () =>
    run(async () => {
      if (!proposal || !scope) return;
      const decisions = proposal.packages.map((p) => ({
        package_key: p.package_key,
        chosen_route: chosen[p.package_key] ?? p.recommended_route,
      }));
      const res = await api.routeConfirm(proposal.run_ref, decisions, "operator", scope);
      setRouteResult(res);
      // Sublet packages feed sourcing; self-perform packages branch to the Estimator. Build the
      // sourcing scope from the sublet ROUTED units: a section sub-package carries its
      // package_key (the sourcing/group key) and only its section's items; a whole/demo package
      // is unchanged (package_key == trade, all items). So a split tender sources each section
      // as its own package (own shortlist -> dispatch -> leveling section -> award).
      const subletKeys = new Set(res.sublet_packages);
      const packages = proposal.packages
        .filter((p) => subletKeys.has(p.package_key))
        .map((p) => {
          const parent = scope.packages.find((x) => x.trade === p.trade);
          const items = p.section
            ? (parent?.sor_items ?? []).filter((it) => (it.section ?? "") === p.section)
            : (parent?.sor_items ?? []);
          return {
            trade: p.package_key, // the sourcing key: bare trade, or trade:SECTION for a sub-package
            scope_summary: p.scope_summary,
            sor_items: items,
            source_refs: parent?.source_refs ?? [],
          };
        });
      const filtered: ScopePackages = { project_name: scope.project_name, packages };
      setSourceScope(filtered);
      invalidateAfter(2); // the routing decision changed — every sourcing gate below is stale
      if (filtered.packages.length === 0) return; // all self-performed — stay on Route (empty state)
      await shortlistScope(filtered);
    });

  // Shortlist a (sublet-filtered) scope and default the approval gate. Called inside `run`.
  async function shortlistScope(s: ScopePackages) {
    // Live engine: open the screened public pool and cap each trade at 8 candidates
    // (the flags / recommended_against markers render exactly as in demo). Demo mode
    // sends neither, preserving the assessed-firm shortlist the scenarios rely on.
    const result = await api.shortlist(s, demoMode ? undefined : { includePublic: true, k: 8 });
    setShortlist(result);
    const defaults: Record<string, string[]> = {};
    for (const [trade, cands] of Object.entries(result.per_trade)) {
      const pick = cands.find((c) => !c.recommended_against) ?? cands[0];
      if (pick) defaults[trade] = [pick.firm.firm_id];
    }
    setApprovals(defaults);
    advance(3);
  }

  const goDispatchStep = () => advance(4);

  function toggleApprove(trade: string, firmId: string) {
    setApprovals((cur) => {
      const ids = cur[trade] ?? [];
      const next = ids.includes(firmId) ? ids.filter((x) => x !== firmId) : [...ids, firmId];
      return { ...cur, [trade]: next };
    });
    setDispatch(null); // re-send required after changing approvals
  }

  // Compose the enquiry drafts WITHOUT sending — the pop-up's review surface. The person
  // edits any draft; only the confirm writes the outbox.
  const composeDrafts = () => {
    if (!shortlist || !sourceScope) return Promise.reject(new Error("nothing to compose"));
    return api.dispatch({
      shortlist,
      approvals,
      scope: sourceScope,
      project_name: sourceScope.project_name,
      send: false,
    });
  };

  const editDraft = (trade: string, firmId: string, value: { subject: string; body: string }) =>
    setDrafts((cur) => ({ ...cur, [`${trade}:${firmId}`]: value }));

  const sendDispatch = () =>
    run(async () => {
      if (!shortlist || !sourceScope) return;
      // Only edits for currently-approved firms ride along; the outbox stores exactly
      // the edited text (a blank field keeps the composed value).
      const draft_overrides = Object.entries(drafts)
        .map(([key, value]) => {
          const [trade, firm_id] = key.split(":");
          return { trade, firm_id, subject: value.subject, body: value.body };
        })
        .filter((o) => (approvals[o.trade] ?? []).includes(o.firm_id));
      const result = await api.dispatch({
        shortlist,
        approvals,
        scope: sourceScope,
        project_name: sourceScope.project_name,
        send: true,
        draft_overrides,
      });
      setDispatch(result);
    });

  // Only replies for trades the routing gate sent to sourcing are levelled — a trade
  // routed to self-perform never enters the comparison.
  function subletReplies(): BidReply[] {
    if (!sourceScope) return replies;
    const sublet = new Set(sourceScope.packages.map((p) => p.trade));
    return replies.filter((r) => sublet.has(r.trade));
  }

  const goLevel = () =>
    run(async () => {
      if (liveRun) {
        // Live: never level a scenario fixture (an empty replies set would make /level-all
        // fall back to the demo bids). Sections are built from real priced returns (manual
        // upload / inbound loop); dispatched packages with none show the awaiting state.
        setLevelledByTrade((cur) => cur ?? {});
        setLevelStale(false);
        advance(5);
        return;
      }
      const result = await api.levelAll(subletReplies(), sourceScope);
      setLevelledByTrade(Object.fromEntries(result.sections.map((s) => [s.trade, s.levelled])));
      setLevelStale(false);
      advance(5);
    });

  // Manual priced-return intake (live): level one firm's returned SoR and merge it into its
  // package's section so that section activates. Idempotent per firm (a re-upload replaces).
  const uploadReturn = async (trade: string, firmId: string, upload: File[]) => {
    const levelled = await api.levelUpload(upload, firmId, trade);
    setLevelledByTrade((cur) => {
      const kept = (cur?.[trade] ?? []).filter((b) => b.firm_id !== firmId);
      return { ...(cur ?? {}), [trade]: [...kept, ...levelled] };
    });
    setRecommendationByTrade(null); // a new return invalidates any prior recommendation
    setAwardByTrade({});
    setMaxReached((m) => (m > 5 ? 5 : m));
  };

  // The dispatched sublet packages awaiting returns (live) — each firm with its status and
  // the [SiteSource Ref] its enquiry carries. `received` flips once a return is levelled in.
  function awaitingPackages(): AwaitingPackage[] {
    if (!liveRun || !dispatch) return [];
    const sublet = new Set(sourceScope?.packages.map((p) => p.trade) ?? []);
    const byTrade = new Map<string, AwaitingPackage>();
    for (const b of dispatch.bundles) {
      if (!sublet.has(b.trade)) continue;
      const ref = b.email_subject.match(/\[SiteSource Ref:\s*([^\]]+)\]/)?.[1]?.trim() ?? "";
      const received = (levelledByTrade?.[b.trade] ?? []).some((x) => x.firm_id === b.firm_id);
      if (!byTrade.has(b.trade)) byTrade.set(b.trade, { trade: b.trade, firms: [] });
      byTrade.get(b.trade)!.firms.push({ firm_id: b.firm_id, firm_name: b.firm_name, ref, received, status: b.status });
    }
    return [...byTrade.values()];
  }

  function editRate(firmId: string, itemRef: string, rate: number | null) {
    setReplies((cur) =>
      cur.map((r) =>
        r.firm_id !== firmId
          ? r
          : {
              ...r,
              line_items: r.line_items.map((l) =>
                l.item_ref !== itemRef ? l : { ...l, rate, amount: rate == null ? null : l.qty * rate },
              ),
            },
      ),
    );
    setLevelStale(true);
    setRecommendationByTrade(null);
    setAwardByTrade({});
    setMaxReached((m) => (m > 5 ? 5 : m));
  }

  const recompute = () =>
    run(async () => {
      if (liveRun) return; // live sections come from uploaded returns; no fixture re-level
      const result = await api.levelAll(subletReplies(), sourceScope);
      setLevelledByTrade(Object.fromEntries(result.sections.map((s) => [s.trade, s.levelled])));
      setLevelStale(false);
    });

  const goRecommend = () =>
    run(async () => {
      if (!levelledByTrade) return;
      const flat = Object.values(levelledByTrade).flat();
      const result = await api.recommendAll(flat, rationaleFixtures);
      setRecommendationByTrade(Object.fromEntries(result.sections.map((s) => [s.trade, s.recommendation])));
      // Default each package's award to the engine's recommended firm — the human
      // changes/overrides/skips per package (the award stays a Layer-4 decision).
      const defaults: Record<string, string> = {};
      for (const s of result.sections) {
        if (s.recommendation.recommended_firm_id) defaults[s.trade] = s.recommendation.recommended_firm_id;
      }
      setAwardByTrade(defaults);
      advance(6);
    });

  function reset() {
    setStep(1);
    setMaxReached(1);
    setCaseId(null);
    setLiveRun(false);
    setTender(null);
    setReplies([]);
    setRationaleFixtures({});
    setFiles([]);
    setScope(null);
    setProposal(null);
    setChosen({});
    setRouteResult(null);
    setSourceScope(null);
    setShortlist(null);
    setApprovals({});
    setDrafts({});
    setDispatch(null);
    setLevelledByTrade(null);
    setLevelStale(false);
    setRecommendationByTrade(null);
    setAwardByTrade({});
    setError(null);
  }

  if (view === "estimator" || view === "benchmark" || view === "database" || view === "projects") {
    return (
      <div className="min-h-screen">
        <Header demoMode={demoMode} view={view} onNavigate={setView} />
        <main className="mx-auto max-w-6xl px-5 py-8">
          {view === "estimator" ? (
            <EstimatorPage />
          ) : view === "benchmark" ? (
            <BenchmarkPage />
          ) : view === "projects" ? (
            <ProjectsPage />
          ) : (
            <DatabasePage />
          )}
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <Header demoMode={demoMode} view={view} onNavigate={setView} />
      {ingestModal && (
        <IngestProgress
          phase={ingestModal.phase}
          startedAt={ingestModal.startedAt}
          error={ingestModal.error}
          summary={ingestModal.summary}
          onRetry={runLiveIngest}
          onCancel={() => setIngestModal(null)}
        />
      )}
      <main className="mx-auto max-w-6xl px-5 py-8">
        <div className="grid gap-8 lg:grid-cols-[16rem_1fr]">
          <Stepper current={step} maxReached={maxReached} onNavigate={setStep} />
          <div className="min-w-0 space-y-4">
            {error && <ErrorBanner message={error} />}

            {step === 1 && (
              <StepIngest
                demoMode={demoMode}
                demoCases={demoCases}
                caseId={caseId}
                files={files}
                scope={scope}
                onPickDemo={pickDemo}
                onAddFiles={(f) => setFiles((cur) => [...cur, ...f])}
                onRemoveFile={(i) => setFiles((cur) => cur.filter((_, idx) => idx !== i))}
                onRunIngest={runIngest}
                onContinue={goRoute}
                loading={loading}
              />
            )}

            {step === 2 && proposal && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <StepHeading
                    title="Route the packages"
                    lead="Each package carries a self-perform vs sublet recommendation with the coverage signal behind it. You decide: sublet packages go to sourcing next; self-perform packages open in the Estimator (they leave the sourcing flow). The recommendation is advisory."
                  />
                  <LayerBadge layer="L4" />
                </div>
                <RouteDecisionPanel
                  proposal={proposal}
                  chosen={chosen}
                  scope={scope}
                  onChoose={(key, route) => setChosen((cur) => ({ ...cur, [key]: route }))}
                  onAcceptAll={acceptAllRoutes}
                  onConfirm={confirmRoute}
                  busy={loading}
                  confirmLabel={routeResult ? "Re-confirm routing →" : "Confirm routing →"}
                />
                {routeResult && <RouteBranch result={routeResult} onOpenEstimator={() => setView("estimator")} />}
                <div className="pt-1">
                  <Button variant="ghost" onClick={() => setStep(1)}>← Back</Button>
                </div>
              </div>
            )}

            {step === 3 && shortlist && (
              <StepShortlist
                shortlist={shortlist}
                heroTrade={heroTrade}
                coverage={coverage}
                approvals={approvals}
                onToggleApprove={toggleApprove}
                onBack={() => setStep(2)}
                onNext={goDispatchStep}
                loading={loading}
              />
            )}

            {step === 4 && shortlist && (
              <StepDispatch
                shortlist={shortlist}
                heroTrade={heroTrade}
                approvals={approvals}
                dispatch={dispatch}
                demoMode={demoMode}
                tenderSlug={tenderSlug}
                scope={sourceScope}
                projectName={sourceScope?.project_name ?? ""}
                drafts={drafts}
                onToggleApprove={toggleApprove}
                onEditDraft={editDraft}
                onComposeDrafts={composeDrafts}
                onSend={sendDispatch}
                onBack={() => setStep(3)}
                onNext={goLevel}
                loading={loading}
              />
            )}

            {step === 5 && levelledByTrade && (
              <StepLevel
                sections={levelledByTrade}
                replies={subletReplies()}
                stale={levelStale}
                xlsxUrl={api.levelingXlsxUrl()}
                onEditRate={editRate}
                onRecompute={recompute}
                onBack={() => setStep(4)}
                onNext={goRecommend}
                loading={loading}
                live={liveRun}
                awaiting={awaitingPackages()}
                onUploadReturn={uploadReturn}
              />
            )}

            {step === 6 && recommendationByTrade && (
              <StepRecommend
                sections={recommendationByTrade}
                awards={awardByTrade}
                awaitingTrades={
                  liveRun
                    ? (sourceScope?.packages ?? [])
                        .map((p) => p.trade)
                        .filter((t) => !(t in recommendationByTrade))
                    : []
                }
                onSetAward={(trade, firmId) => setAwardByTrade((cur) => ({ ...cur, [trade]: firmId }))}
                onSkip={(trade) => setAwardByTrade((cur) => ({ ...cur, [trade]: "" }))}
                onBack={() => setStep(5)}
                onReset={reset}
              />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

// The durable split summary after the routing gate is confirmed. It persists on the Route
// step (App-level state survives tab switches and stepping back): sublet packages continue
// to sourcing; self-perform packages are opened in the Estimator, each chip linking to its
// seeded estimate (idempotent per run — re-confirming re-derives without duplicates). When
// nothing is left to source, the empty state says so plainly.
function RouteBranch({ result, onOpenEstimator }: { result: RouteDecisionResult; onOpenEstimator: () => void }) {
  const sublet = result.sublet_packages;
  const selfPerform = result.self_perform_packages;
  return (
    <Card className="border-ok/30 p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-ok text-[11px] text-white" aria-hidden>✓</span>
        <span className="text-sm font-semibold text-ink">Routing confirmed</span>
        <span className="text-xs text-ink-faint">— the decision persists; re-confirming re-derives the split without duplicating estimates.</span>
      </div>
      {sublet.length === 0 ? (
        <div className="rounded-lg border border-warn/40 bg-warn-bg px-3 py-2 text-sm text-ink">
          All packages are self-performed — nothing to source. Their estimates are open in the Estimator.
        </div>
      ) : (
        <p className="text-sm text-ink-soft">
          <span className="tabular font-semibold text-ink">{sublet.length}</span> package{sublet.length === 1 ? "" : "s"} sublet → continuing to sourcing
          {" ("}{sublet.map(tradeLabel).join(", ")}{")"}
          {selfPerform.length > 0 && (
            <>
              {" · "}
              <span className="tabular font-semibold text-ink">{selfPerform.length}</span> self-perform → opened in the Estimator
            </>
          )}
        </p>
      )}
      {selfPerform.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-eyebrow text-ink-faint">
            Self-perform estimates — left track
          </div>
          <div className="flex flex-wrap gap-1.5">
            {selfPerform.map((k) => (
              <button
                key={k}
                type="button"
                onClick={onOpenEstimator}
                title="Open this estimate in the Estimator"
                className="inline-flex items-center gap-1 rounded-full bg-violet-bg px-2.5 py-1 text-xs font-medium text-violet transition-opacity hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright"
              >
                {tradeLabel(k)}
                {result.estimate_ids[k] != null && <span className="tabular opacity-70">#{result.estimate_ids[k]}</span>}
                <span aria-hidden>→</span>
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-ink-faint">These live in the Estimator tab and persist there; they do not enter the sourcing flow.</p>
        </div>
      )}
    </Card>
  );
}
