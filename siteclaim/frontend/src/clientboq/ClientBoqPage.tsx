// Tender → BOQ. The page owns all of its own state.
//
// The Sourcing wizard threads its state through App.tsx, which is why App.tsx is 700 lines;
// this capability is self-contained in the backend and stays self-contained here. The rule it
// inherits from Sourcing is the one that matters — **editing a gate invalidates everything
// downstream of it**. Reopening the register drops the scope, the estimate and the letter,
// because an offer built on a register that has been reopened is an offer nobody can stand
// behind. `invalidateAfter` is that rule, in one place.

import { useCallback, useEffect, useState } from "react";

import { ErrorBanner, LayerBadge, SectionHeader, cx } from "../ui";
import { Pill } from "../components";
import { boqApi } from "./api";
import { StepDocuments } from "./StepDocuments";
import { StepOutputs } from "./StepOutputs";
import { StepPrice } from "./StepPrice";
import { StepRegister } from "./StepRegister";
import { StepScope } from "./StepScope";
import { BOQ_STEPS, WorkflowRail, type BoqStep } from "./WorkflowRail";
import type {
  EstimateResult,
  EstimateSchedule,
  HumanVerdict,
  LetterResult,
  RateRow,
  ReviewResult,
  ScopeResult,
} from "./types";

const EMPTY_SCHEDULE: EstimateSchedule = { duration_weeks: null, items: [] };

export function ClientBoqPage({ demoMode }: { demoMode: boolean }) {
  // Navigation
  const [step, setStep] = useState<BoqStep>(1);
  const [maxReached, setMaxReached] = useState<BoqStep>(1);

  // Source
  const [projectName, setProjectName] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  // Workflow state
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [verdicts, setVerdicts] = useState<Record<number, HumanVerdict>>({});
  const [scope, setScope] = useState<ScopeResult | null>(null);
  const [estimate, setEstimate] = useState<EstimateResult | null>(null);
  const [letter, setLetter] = useState<LetterResult | null>(null);

  // Pricing input
  const [rates, setRates] = useState<RateRow[]>([]);
  const [schedule, setSchedule] = useState<EstimateSchedule>(EMPTY_SCHEDULE);
  const [marginPct, setMarginPct] = useState(15);

  // Transient
  const [running, setRunning] = useState<"" | "review" | "scope" | "estimate">("");
  const [stage, setStage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setId = review?.set_id ?? null;

  useEffect(() => {
    boqApi.rates().then(setRates).catch(() => {
      /* the rate book is an aid, not a dependency — the editor still takes inline rates */
    });
  }, []);

  const advance = useCallback((to: BoqStep) => {
    setStep(to);
    setMaxReached((m) => (to > m ? to : m));
  }, []);

  /** The gate rule: everything after `keep` is cleared, and the rail closes behind it. */
  const invalidateAfter = useCallback((keep: BoqStep) => {
    if (keep < 3) setScope(null);
    if (keep < 4) {
      setEstimate(null);
      setLetter(null);
    }
    setMaxReached((m) => (m > keep ? keep : m));
    setStep((s) => (s > keep ? keep : s));
  }, []);

  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  // --- Step 1: the review run -----------------------------------------------
  const runReview = () =>
    run(async () => {
      setRunning("review");
      setStage("");
      try {
        const result = await boqApi.runReview(files, projectName, (p) => setStage(p.stage));
        setReview(result);
        setVerdicts({});
        setScope(null);
        setEstimate(null);
        setLetter(null);
        setMaxReached(2);
        setStep(2);
      } finally {
        setRunning("");
        setStage("");
      }
    });

  /** Reopen a document set that was reviewed in an earlier session. */
  const openExisting = (id: string) =>
    run(async () => {
      const result = await boqApi.register(id);
      setReview(result);
      setVerdicts({});
      setProjectName(result.register.project || id);
      setMaxReached(2);
      setStep(2);
      // Everything downstream is optional — a set may have been reviewed and never priced.
      if (result.review_approved) {
        const loadedScope = await boqApi.scope(id).catch(() => null);
        if (loadedScope) {
          setScope(loadedScope);
          setMaxReached(3);
          if (loadedScope.scope_approved) {
            const loadedEstimate = await boqApi.estimate(id).catch(() => null);
            if (loadedEstimate) {
              setEstimate(loadedEstimate);
              setMaxReached(4);
              const loadedLetter = await boqApi.letter(id).catch(() => null);
              if (loadedLetter) {
                setLetter(loadedLetter);
                setMaxReached(5);
              }
            }
          }
        }
      }
    });

  // --- Step 2: the register gate --------------------------------------------
  const setVerdict = (item: number, v: HumanVerdict) =>
    setVerdicts((cur) => (cur[item] === v ? omit(cur, item) : { ...cur, [item]: v }));

  const bulkVerdict = (items: number[], v: HumanVerdict) =>
    setVerdicts((cur) => ({ ...cur, ...Object.fromEntries(items.map((i) => [i, v])) }));

  const closeRegister = () =>
    run(async () => {
      if (!setId) return;
      await boqApi.approveRegister(setId, verdicts, true);
      setReview(await boqApi.register(setId)); // re-read: the verdicts are now the line statuses
      setVerdicts({});
      advance(3);
      await draftScope(setId);
    });

  const reopenRegister = () =>
    run(async () => {
      if (!setId) return;
      await boqApi.approveRegister(setId, {}, false);
      setReview(await boqApi.register(setId));
      invalidateAfter(2);
    });

  // --- Step 3: the scope gate -----------------------------------------------
  // Closing the register earns the next screen; making the operator press a second button to
  // populate it would be a dead click, so the draft runs as part of the same action.
  const draftScope = async (id: string) => {
    setRunning("scope");
    setStage("");
    try {
      setScope(await boqApi.runScope(id, (p) => setStage(p.stage)));
      setMaxReached((m) => (m < 3 ? 3 : m));
    } finally {
      setRunning("");
      setStage("");
    }
  };

  const runScope = () =>
    run(async () => {
      if (setId) await draftScope(setId);
    });

  /** The register's "Draft the scope →" — go to the step, and fill it if it is empty. */
  const goScope = () =>
    run(async () => {
      advance(3);
      if (!scope && setId) await draftScope(setId);
    });

  const approveScope = (amended: string) =>
    run(async () => {
      if (!setId) return;
      await boqApi.approveScope(setId, amended, true);
      setScope(await boqApi.scope(setId));
      advance(4);
    });

  const reopenScope = () =>
    run(async () => {
      if (!setId) return;
      await boqApi.approveScope(setId, "", false);
      setScope(await boqApi.scope(setId));
      invalidateAfter(3);
    });

  // --- Step 4: pricing ------------------------------------------------------
  const runEstimate = () =>
    run(async () => {
      if (!setId) return;
      setRunning("estimate");
      setStage("");
      try {
        const result = await boqApi.runEstimate(
          setId,
          marginPct,
          schedule.items.length ? schedule : null,
          projectName ? { project: projectName } : null,
          (p) => setStage(p.stage),
        );
        setEstimate(result);
        setMaxReached((m) => (m < 4 ? 4 : m));
        setLetter(await boqApi.letter(setId).catch(() => null));
      } finally {
        setRunning("");
        setStage("");
      }
    });

  /** Bring the priced result back into the editor, so a live re-run starts from something real. */
  const copyPricedSchedule = () => {
    if (!estimate) return;
    const e = estimate.estimate;
    setSchedule({
      duration_weeks: e.duration_weeks,
      items: [
        ...e.activities.map((a) => ({
          item_id: a.item_id,
          description: a.description,
          category: "direct",
          unit: a.unit,
          lines: a.lines.map((l) => ({
            description: l.description,
            resource_ref: l.resource_ref,
            inline_rate: l.rate_source === "inline" ? l.rate : null,
            qty: l.qty,
            unit: l.unit,
            productivity: l.productivity,
          })),
          basis: "",
          amount: null,
          rate: null,
          pct: null,
        })),
        ...e.indirects.map((ind) => ({
          item_id: ind.item_id,
          description: ind.label,
          category: "indirect",
          unit: "item",
          lines: [],
          basis: ind.basis,
          amount: ind.basis === "lump" ? ind.amount : null,
          rate: null,
          pct: null,
        })),
      ],
    });
    setMarginPct(estimate.totals.margin_pct);
  };

  const reviewApproved = review?.review_approved ?? false;
  const scopeApproved = scope?.scope_approved ?? false;

  return (
    <div className="min-w-0 space-y-4">
      <SectionHeader
        title="Tender → BOQ"
        lead="The client's tender comes in; a departure register and a priced offer go out. Two workflows, sequential, with a human gate between them — the register has to be closed before anything is priced against it."
        right={<LayerBadge layer="L4" />}
      />

      {setId && <SetBanner setId={setId} review={review} reviewApproved={reviewApproved} scopeApproved={scopeApproved} />}

      {error && <ErrorBanner message={error} />}

      <div className="grid gap-8 lg:grid-cols-[15rem_1fr]">
        <WorkflowRail
          current={step}
          maxReached={maxReached}
          reviewApproved={reviewApproved}
          scopeApproved={scopeApproved}
          onNavigate={setStep}
        />

        <div className="min-w-0 space-y-5">
          {step === 1 && (
            <StepDocuments
              demoMode={demoMode}
              projectName={projectName}
              files={files}
              running={running === "review"}
              stage={stage}
              setId={setId}
              onProjectName={setProjectName}
              onAddFiles={(f) => setFiles((cur) => [...cur, ...f])}
              onRemoveFile={(i) => setFiles((cur) => cur.filter((_, idx) => idx !== i))}
              onRun={runReview}
              onOpenExisting={openExisting}
              onContinue={() => advance(2)}
            />
          )}

          {step === 2 && review && (
            <StepRegister
              register={review.register}
              reviewApproved={reviewApproved}
              verdicts={verdicts}
              busy={busy}
              onVerdict={setVerdict}
              onBulkVerdict={bulkVerdict}
              onClearVerdicts={() => setVerdicts({})}
              onClose={closeRegister}
              onReopen={reopenRegister}
              onBack={() => setStep(1)}
              onContinue={goScope}
            />
          )}

          {step === 3 && (
            <StepScope
              scope={scope}
              running={running === "scope"}
              stage={stage}
              busy={busy}
              onRun={runScope}
              onApprove={approveScope}
              onReopen={reopenScope}
              onBack={() => setStep(2)}
              onContinue={() => advance(4)}
            />
          )}

          {step === 4 && (
            <StepPrice
              demoMode={demoMode}
              result={estimate}
              rates={rates}
              schedule={schedule}
              marginPct={marginPct}
              running={running === "estimate"}
              stage={stage}
              onSchedule={setSchedule}
              onMarginPct={setMarginPct}
              onRun={runEstimate}
              onCopyPriced={copyPricedSchedule}
              onBack={() => setStep(3)}
              onContinue={() => advance(5)}
            />
          )}

          {step === 5 && setId && (
            <StepOutputs
              setId={setId}
              estimate={estimate}
              letter={letter}
              workbookUrl={boqApi.workbookUrl(setId)}
              onBack={() => setStep(4)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * "Where am I." The set under work, its identity, and the two gates as a single glance —
 * present on every step so the answer never depends on which screen is open.
 */
function SetBanner({
  setId,
  review,
  reviewApproved,
  scopeApproved,
}: {
  setId: string;
  review: ReviewResult | null;
  reviewApproved: boolean;
  scopeApproved: boolean;
}) {
  const register = review?.register;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-line-soft bg-card px-4 py-2.5 shadow-card">
      <div className="min-w-0">
        <div className="truncate font-display text-sm font-semibold tracking-display text-ink">
          {register?.project || setId}
        </div>
        <div className="tabular text-[11px] text-ink-faint">{setId}</div>
      </div>
      {register && (
        <div className="tabular flex flex-wrap items-center gap-x-3 text-[11px] text-ink-faint">
          <span>{register.items.length} register lines</span>
          <span>{register.aligned.length} aligned</span>
          <span>{register.unresolved.count} unresolved</span>
        </div>
      )}
      <div className="ml-auto flex flex-wrap items-center gap-1.5">
        <GatePill label="Register" closed={reviewApproved} />
        <GatePill label="Scope" closed={scopeApproved} />
      </div>
    </div>
  );
}

function GatePill({ label, closed }: { label: string; closed: boolean }) {
  return (
    <Pill tone={closed ? "ok" : "warn"}>
      <span aria-hidden className={cx("mr-1", closed ? "text-ok" : "text-warn")}>
        {closed ? "✓" : "◌"}
      </span>
      {label} {closed ? "closed" : "open"}
    </Pill>
  );
}

function omit<T extends Record<number, unknown>>(obj: T, key: number): T {
  const next = { ...obj };
  delete next[key];
  return next;
}

// Re-exported so the rail's step list stays the single source of truth for step count.
export { BOQ_STEPS };
