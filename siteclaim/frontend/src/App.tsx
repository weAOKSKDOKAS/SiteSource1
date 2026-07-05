import { useEffect, useState } from "react";
import { api } from "./api";
import { BenchmarkPage } from "./BenchmarkPage";
import { DatabasePage } from "./DatabasePage";
import { EstimatorPage } from "./EstimatorPage";
import { ProjectsPage } from "./ProjectsPage";
import { RouteDecisionPanel } from "./RouteDecisionPanel";
import { RoutingPage } from "./RoutingPage";
import { Header, StepHeading, Stepper, type StepIndex, type TopView } from "./components";
import { tradeLabel } from "./format";
import type {
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
  const [rationaleFixture, setRationaleFixture] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);

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
  const [levelled, setLevelled] = useState<LevelledBid[] | null>(null);
  const [levelStale, setLevelStale] = useState(false);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [award, setAward] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    }
    if (keep < 4) setDispatch(null);
    if (keep < 5) {
      setLevelled(null);
      setLevelStale(false);
    }
    if (keep < 6) setRecommendation(null);
    setMaxReached((m) => (m > keep ? keep : m));
  }

  async function pickDemo(id: string) {
    await run(async () => {
      const source = await api.demoCase(id);
      setCaseId(id);
      setHeroTrade(source.hero_trade);
      setTender(source.tender);
      setReplies(source.replies);
      setRationaleFixture(source.rationale_fixture);
      setFiles([]);
      setScope(null);
      invalidateAfter(1);
    });
  }

  const runIngest = () =>
    run(async () => {
      let result: ScopePackages;
      if (!demoMode && files.length > 0) {
        const uploaded = await api.ingestUpload(files);
        setTender(uploaded.tender); // trade-tagged tender -> per-trade routing at dispatch
        setTenderSlug(uploaded.tender_slug); // for the live replies panel on the dispatch step
        result = uploaded.scope;
      } else if (tender) {
        result = await api.ingest(tender);
      } else {
        return;
      }
      setScope(result);
      invalidateAfter(1);
    });

  // Step 2 — Route. Analyse the ingested scope; default each package to its recommendation.
  const goRoute = () =>
    run(async () => {
      if (!scope) return;
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
      // Sublet packages feed sourcing; self-perform packages branch to the Estimator and do
      // NOT enter the sourcing flow. Match scope packages to the routing package_key (= trade).
      const filtered: ScopePackages = {
        project_name: scope.project_name,
        packages: scope.packages.filter((pkg) => res.sublet_packages.includes(pkg.trade)),
      };
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

  const sendDispatch = () =>
    run(async () => {
      if (!shortlist || !sourceScope) return;
      const result = await api.dispatch({
        shortlist,
        approvals,
        scope: sourceScope,
        project_name: sourceScope.project_name,
        send: true,
      });
      setDispatch(result);
    });

  const goLevel = () =>
    run(async () => {
      const result = await api.level(replies, sourceScope);
      setLevelled(result);
      setLevelStale(false);
      advance(5);
    });

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
    setRecommendation(null);
    setMaxReached((m) => (m > 5 ? 5 : m));
  }

  const recompute = () =>
    run(async () => {
      const result = await api.level(replies, sourceScope);
      setLevelled(result);
      setLevelStale(false);
    });

  const goRecommend = () =>
    run(async () => {
      if (!levelled) return;
      const result = await api.recommend(levelled, heroTrade, rationaleFixture);
      setRecommendation(result);
      setAward(result.recommended_firm_id);
      advance(6);
    });

  function reset() {
    setStep(1);
    setMaxReached(1);
    setCaseId(null);
    setTender(null);
    setReplies([]);
    setRationaleFixture(null);
    setFiles([]);
    setScope(null);
    setProposal(null);
    setChosen({});
    setRouteResult(null);
    setSourceScope(null);
    setShortlist(null);
    setApprovals({});
    setDispatch(null);
    setLevelled(null);
    setLevelStale(false);
    setRecommendation(null);
    setAward(null);
    setError(null);
  }

  if (view === "routing" || view === "estimator" || view === "benchmark" || view === "database" || view === "projects") {
    return (
      <div className="min-h-screen">
        <Header demoMode={demoMode} view={view} onNavigate={setView} />
        <main className="mx-auto max-w-6xl px-5 py-8">
          {view === "routing" ? (
            <RoutingPage />
          ) : view === "estimator" ? (
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
                    lead="For each package the AI recommends self-perform vs sublet with the coverage signal behind it. You decide: sublet packages go to sourcing next; self-perform packages open in the Estimator (they leave the sourcing flow). The recommendation is advisory."
                  />
                  <LayerBadge layer="L4" />
                </div>
                <RouteDecisionPanel
                  proposal={proposal}
                  chosen={chosen}
                  onChoose={(key, route) => setChosen((cur) => ({ ...cur, [key]: route }))}
                  onAcceptAll={acceptAllRoutes}
                  onConfirm={confirmRoute}
                  busy={loading}
                  confirmLabel="Confirm routing →"
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
                onToggleApprove={toggleApprove}
                onSend={sendDispatch}
                onBack={() => setStep(3)}
                onNext={goLevel}
                loading={loading}
              />
            )}

            {step === 5 && levelled && (
              <StepLevel
                levelled={levelled}
                replies={replies}
                stale={levelStale}
                xlsxUrl={api.levelingXlsxUrl()}
                onEditRate={editRate}
                onRecompute={recompute}
                onBack={() => setStep(4)}
                onNext={goRecommend}
                loading={loading}
              />
            )}

            {step === 6 && recommendation && (
              <StepRecommend
                recommendation={recommendation}
                award={award}
                onSetAward={setAward}
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

// The self-perform / sublet split after the routing gate is confirmed: sublet packages
// continue to sourcing; self-perform packages branch to the Estimator (left track) and leave
// the sourcing flow. When nothing is left to source, the empty state says so plainly.
function RouteBranch({ result, onOpenEstimator }: { result: RouteDecisionResult; onOpenEstimator: () => void }) {
  const selfPerform = result.self_perform_packages;
  const nothingToSource = result.sublet_packages.length === 0;
  return (
    <Card className="p-4">
      {nothingToSource ? (
        <div className="rounded-lg border border-warn/40 bg-warn-bg px-3 py-2 text-sm text-ink">
          All packages are self-performed — nothing to source. Their estimates are in the Estimator.
        </div>
      ) : (
        <p className="text-sm text-ink-soft">
          <span className="font-semibold text-ink">{result.sublet_packages.length}</span> sublet package(s) continue to the
          shortlist{selfPerform.length > 0 ? ", the rest branch to the Estimator" : ""}.
        </p>
      )}
      {selfPerform.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-faint">
            {selfPerform.length} package(s) sent to the Estimator — left track
          </div>
          <div className="flex flex-wrap gap-1.5">
            {selfPerform.map((k) => (
              <button
                key={k}
                type="button"
                onClick={onOpenEstimator}
                title="Open the Estimator"
                className="inline-flex items-center gap-1 rounded-full bg-violet-bg px-2.5 py-1 text-xs font-medium text-violet transition-opacity hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright"
              >
                {tradeLabel(k)}
                {result.estimate_ids[k] != null && <span className="tabular opacity-70">#{result.estimate_ids[k]}</span>}
                <span aria-hidden>→</span>
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-ink-faint">These open in the Estimator; they do not enter the sourcing flow.</p>
        </div>
      )}
    </Card>
  );
}
