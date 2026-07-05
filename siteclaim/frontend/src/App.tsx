import { useEffect, useState } from "react";
import { api } from "./api";
import { BenchmarkPage } from "./BenchmarkPage";
import { DatabasePage } from "./DatabasePage";
import { RoutingPage } from "./RoutingPage";
import { Header, Stepper, type StepIndex, type TopView } from "./components";
import type {
  BidReply,
  Coverage,
  DemoCaseSummary,
  DispatchSet,
  LevelledBid,
  Recommendation,
  ScopePackages,
  ShortlistSet,
  TenderPackage,
} from "./types";
import { ErrorBanner } from "./ui";
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
  const [scope, setScope] = useState<ScopePackages | null>(null);
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

  // Editing a gate invalidates every later gate (the ICM review-gate rule).
  function invalidateAfter(keep: StepIndex) {
    if (keep < 2) {
      setShortlist(null);
      setApprovals({});
    }
    if (keep < 3) setDispatch(null);
    if (keep < 4) {
      setLevelled(null);
      setLevelStale(false);
    }
    if (keep < 5) setRecommendation(null);
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

  const goShortlist = () =>
    run(async () => {
      if (!scope) return;
      // Live engine: open the screened public pool and cap each trade at 8 candidates
      // (the flags / recommended_against markers render exactly as in demo). Demo mode
      // sends neither, preserving the assessed-firm shortlist the scenarios rely on.
      const result = await api.shortlist(scope, demoMode ? undefined : { includePublic: true, k: 8 });
      setShortlist(result);
      // Default the approval gate to the top clean firm per trade.
      const defaults: Record<string, string[]> = {};
      for (const [trade, cands] of Object.entries(result.per_trade)) {
        const pick = cands.find((c) => !c.recommended_against) ?? cands[0];
        if (pick) defaults[trade] = [pick.firm.firm_id];
      }
      setApprovals(defaults);
      advance(2);
    });

  const goDispatchStep = () => advance(3);

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
      if (!shortlist || !scope) return;
      const result = await api.dispatch({
        shortlist,
        approvals,
        scope,
        project_name: scope.project_name,
        send: true,
      });
      setDispatch(result);
    });

  const goLevel = () =>
    run(async () => {
      const result = await api.level(replies, scope);
      setLevelled(result);
      setLevelStale(false);
      advance(4);
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
    setMaxReached((m) => (m > 4 ? 4 : m));
  }

  const recompute = () =>
    run(async () => {
      const result = await api.level(replies, scope);
      setLevelled(result);
      setLevelStale(false);
    });

  const goRecommend = () =>
    run(async () => {
      if (!levelled) return;
      const result = await api.recommend(levelled, heroTrade, rationaleFixture);
      setRecommendation(result);
      setAward(result.recommended_firm_id);
      advance(5);
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
    setShortlist(null);
    setApprovals({});
    setDispatch(null);
    setLevelled(null);
    setLevelStale(false);
    setRecommendation(null);
    setAward(null);
    setError(null);
  }

  if (view === "routing" || view === "benchmark" || view === "database") {
    return (
      <div className="min-h-screen">
        <Header demoMode={demoMode} view={view} onNavigate={setView} />
        <main className="mx-auto max-w-6xl px-5 py-8">
          {view === "routing" ? <RoutingPage /> : view === "benchmark" ? <BenchmarkPage /> : <DatabasePage />}
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
                onContinue={goShortlist}
                loading={loading}
              />
            )}

            {step === 2 && shortlist && (
              <StepShortlist
                shortlist={shortlist}
                heroTrade={heroTrade}
                coverage={coverage}
                onBack={() => setStep(1)}
                onNext={goDispatchStep}
                loading={loading}
              />
            )}

            {step === 3 && shortlist && (
              <StepDispatch
                shortlist={shortlist}
                heroTrade={heroTrade}
                approvals={approvals}
                dispatch={dispatch}
                demoMode={demoMode}
                tenderSlug={tenderSlug}
                onToggleApprove={toggleApprove}
                onSend={sendDispatch}
                onBack={() => setStep(2)}
                onNext={goLevel}
                loading={loading}
              />
            )}

            {step === 4 && levelled && (
              <StepLevel
                levelled={levelled}
                replies={replies}
                stale={levelStale}
                xlsxUrl={api.levelingXlsxUrl()}
                onEditRate={editRate}
                onRecompute={recompute}
                onBack={() => setStep(3)}
                onNext={goRecommend}
                loading={loading}
              />
            )}

            {step === 5 && recommendation && (
              <StepRecommend
                recommendation={recommendation}
                award={award}
                onSetAward={setAward}
                onBack={() => setStep(4)}
                onReset={reset}
              />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
