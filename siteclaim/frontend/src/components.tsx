import type { ReactNode } from "react";
import type { Evidence, RiskFlag } from "./types";
import { Button, SeverityTag, cx } from "./ui";

export const STEPS = ["Ingest", "Shortlist", "Dispatch", "Level", "Recommend"] as const;
export type StepIndex = 1 | 2 | 3 | 4 | 5;

const GATE_HINT: Record<number, string> = {
  1: "Split the tender by trade",
  2: "Rank firms with evidence",
  3: "Invite & send (mock)",
  4: "Correct & compare bids",
  5: "Risk-adjusted award",
};

// --- Chrome ----------------------------------------------------------------
export function Header({ demoMode }: { demoMode: boolean }) {
  return (
    <header className="border-b border-line bg-card">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-lg font-bold tracking-tight text-ink">
            Site<span className="text-brand">Source</span>
          </span>
          {demoMode && (
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-ink px-2.5 py-1 text-xs font-bold uppercase tracking-wider text-white"
              title="Running offline against the seeded database — zero network calls."
            >
              <span className="h-1.5 w-1.5 rounded-full bg-ok" />
              Demo mode
            </span>
          )}
        </div>
        <p className="w-full text-xs text-ink-faint sm:ml-auto sm:w-auto sm:max-w-sm sm:text-right">
          Subcontractor sourcing &amp; bid-leveling — the proprietary data, brought to the award decision.
        </p>
      </div>
    </header>
  );
}

export function Stepper({
  current,
  maxReached,
  onNavigate,
}: {
  current: StepIndex;
  maxReached: StepIndex;
  onNavigate: (s: StepIndex) => void;
}) {
  return (
    <nav aria-label="Progress" className="lg:sticky lg:top-6">
      <ol className="flex gap-2 overflow-x-auto pb-2 lg:flex-col lg:gap-0 lg:overflow-visible lg:pb-0">
        {STEPS.map((label, i) => {
          const step = (i + 1) as StepIndex;
          const state = step === current ? "active" : step < current ? "done" : "upcoming";
          const reachable = step <= maxReached;
          const isLast = i === STEPS.length - 1;
          return (
            <li key={label} className="relative flex shrink-0 lg:block">
              {!isLast && (
                <span
                  aria-hidden
                  className={cx(
                    "absolute hidden lg:block left-[15px] top-8 h-[calc(100%-1.5rem)] w-px",
                    step < current ? "bg-brand" : "bg-line",
                  )}
                />
              )}
              <button
                type="button"
                disabled={!reachable}
                onClick={() => reachable && onNavigate(step)}
                className={cx(
                  "group flex items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors lg:w-full",
                  reachable ? "cursor-pointer hover:bg-line-soft" : "cursor-not-allowed",
                  state === "active" && "bg-brand-bg/60",
                )}
              >
                <span
                  className={cx(
                    "tabular flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold",
                    state === "active" && "border-brand bg-brand text-white",
                    state === "done" && "border-brand bg-card text-brand",
                    state === "upcoming" && "border-line bg-card text-ink-faint",
                  )}
                >
                  {state === "done" ? "✓" : step}
                </span>
                <span className="pr-2">
                  <span className={cx("block text-sm font-semibold", state === "upcoming" ? "text-ink-faint" : "text-ink")}>
                    {label}
                  </span>
                  <span className="hidden text-xs text-ink-faint lg:block">{GATE_HINT[step]}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// --- Shared step scaffolding ----------------------------------------------
export function StepHeading({ title, lead }: { title: string; lead: string }) {
  return (
    <div>
      <h1 className="text-xl font-bold tracking-tight text-ink">{title}</h1>
      <p className="mt-1.5 max-w-2xl text-sm text-ink-soft">{lead}</p>
    </div>
  );
}

export function StepNav({
  onBack,
  onNext,
  nextLabel = "Continue →",
  loading = false,
  nextDisabled = false,
}: {
  onBack?: () => void;
  onNext?: () => void;
  nextLabel?: string;
  loading?: boolean;
  nextDisabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 pt-2">
      {onBack ? (
        <Button variant="ghost" onClick={onBack}>
          ← Back
        </Button>
      ) : (
        <span />
      )}
      {onNext && (
        <Button onClick={onNext} loading={loading} disabled={nextDisabled}>
          {nextLabel}
        </Button>
      )}
    </div>
  );
}

// --- Risk + evidence (the hero's legibility lives here) --------------------
export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) return null;
  return (
    <ul className="mt-1.5 space-y-1">
      {evidence.map((e, j) => (
        <li key={j} className="text-xs leading-relaxed text-ink-soft">
          <span className="font-semibold text-ink">{e.source}</span>
          <span className="tabular text-ink-faint"> · {e.reference}</span>
          <div className="text-ink-soft">{e.snippet}</div>
        </li>
      ))}
    </ul>
  );
}

export function RiskFlagList({ flags }: { flags: RiskFlag[] }) {
  if (!flags.length) return null;
  return (
    <ul className="space-y-2">
      {flags.map((f, i) => (
        <li
          key={i}
          className={cx(
            "rounded-lg border px-3 py-2",
            f.severity === "fatal"
              ? "border-bad/50 bg-bad-bg"
              : f.severity === "warning"
                ? "border-warn/40 bg-warn-bg"
                : "border-line bg-card",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <SeverityTag severity={f.severity} />
            <span className="text-sm font-semibold text-ink">{f.label}</span>
            <span className="tabular text-xs text-ink-faint">{f.rule_ref}</span>
          </div>
          <EvidenceList evidence={f.evidence} />
        </li>
      ))}
    </ul>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "bad" | "brand" }) {
  const tones = {
    neutral: "bg-line-soft text-ink-soft",
    ok: "bg-ok-bg text-ok",
    bad: "bg-bad-bg text-bad",
    brand: "bg-brand-bg text-brand",
  };
  return <span className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}
