import type { ReactNode } from "react";
import { tradeLabel } from "./format";
import { shownEmail } from "./theme";
import type { Evidence, FirmProfile, RiskFlag } from "./types";
import { Button, Collapse, Docket, MonoLabel, SeverityTag, cx } from "./ui";

export const STEPS = ["Ingest", "Route", "Shortlist", "Dispatch", "Level", "Recommend"] as const;
export type StepIndex = 1 | 2 | 3 | 4 | 5 | 6;

const GATE_HINT: Record<number, string> = {
  1: "Split the tender by trade",
  2: "Self-perform vs sublet per package",
  3: "Rank firms with evidence",
  4: "Invite & send (mock)",
  5: "Correct & compare bids",
  6: "Risk-adjusted award",
};

// --- Chrome ----------------------------------------------------------------
// The routing gate lives INSIDE the Sourcing wizard (step 2) — there is no standalone
// Routing tab; the confirmed decision persists in the wizard's App-level state.
export type TopView = "wizard" | "estimator" | "benchmark" | "database" | "projects";

// The app shell sections. Each track flips its `enabled` flag on as its phase lands.
const NAV: { view: TopView; label: string; enabled: boolean; soon?: string }[] = [
  { view: "wizard", label: "Sourcing", enabled: true },
  { view: "estimator", label: "Estimator", enabled: true },
  { view: "benchmark", label: "Benchmark", enabled: true },
  { view: "projects", label: "Projects", enabled: true },
  { view: "database", label: "Database", enabled: true },
];

export function Header({
  demoMode,
  view,
  onNavigate,
}: {
  demoMode: boolean;
  view?: TopView;
  onNavigate?: (v: TopView) => void;
}) {
  const tab = ({ view: v, label, enabled, soon }: (typeof NAV)[number]) =>
    enabled ? (
      <button
        key={v}
        onClick={() => onNavigate?.(v)}
        className={cx(
          "rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors",
          view === v
            ? "bg-brand-violet text-white shadow-[0_4px_12px_rgba(31,111,235,0.35)]"
            : "text-ink-soft hover:bg-line-soft hover:text-ink",
        )}
      >
        {label}
      </button>
    ) : (
      <span
        key={v}
        title={`${label} — coming in ${soon}`}
        className="cursor-not-allowed rounded-lg px-3 py-1.5 text-sm font-semibold text-ink-faint/70"
      >
        {label}
      </span>
    );
  return (
    // Frosted sticky chrome: a translucent paper surface with a saturate+blur backdrop, so
    // page content scrolls under it (ported from the prototype's top bar).
    <header className="sticky top-0 z-50 border-b border-ink/[0.08] bg-paper/80 backdrop-blur-[12px] backdrop-saturate-150">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="font-display text-lg font-bold tracking-display text-ink">
            Site<span className="text-brand">Source</span>
          </span>
          {demoMode && (
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-ink px-2.5 py-1 text-xs font-bold uppercase tracking-eyebrow text-white"
              title="Running offline against the seeded database — zero network calls."
            >
              <span className="ssDot h-1.5 w-1.5 rounded-full bg-ok" />
              Demo mode
            </span>
          )}
        </div>
        {onNavigate && <nav className="flex flex-wrap items-center gap-1">{NAV.map(tab)}</nav>}
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
    <nav aria-label="Progress" className="lg:sticky lg:top-20">
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
                    {state === "active" && <span className="ssLive ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-brand align-middle" aria-hidden />}
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
      <h1 className="font-display text-2xl font-semibold tracking-display text-ink">{title}</h1>
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
          <span
            className="tabular ml-1.5 inline-flex cursor-help items-center rounded border border-line px-1.5 py-px text-[11px] text-ink-soft transition-colors hover:border-brand/40 hover:bg-brand-bg/50"
            title={`${e.source} — reference ${e.reference}`}
          >
            {e.reference}
          </span>
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

// A firm's fused record body, shared by the shortlist firm drawer and the Database browse
// drawer so both render one implementation. `flags` defaults to the raw public_flags (the
// browse view); the shortlist drawer passes the per-scope adjudicated risk_flags instead.
// Extra candidate-specific sections (e.g. scope evidence) are passed as children and chain
// into the same collapse group.
export function FirmRecord({
  firm,
  flags = firm.public_flags,
  flagsLabel = "Public flags",
  children,
}: {
  firm: FirmProfile;
  flags?: RiskFlag[];
  flagsLabel?: string;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-3">
      <Docket label="Firm reference" code={firm.firm_id} />
      {firm.description && <p className="text-xs leading-relaxed text-ink-soft">{firm.description}</p>}
      <div>
        <MonoLabel className="mb-1">Registration</MonoLabel>
        <div className="text-xs text-ink-soft">
          {firm.registered_grade || "—"} · {firm.value_band.replace(/_/g, " ") || "unbanded"}
        </div>
        {(firm.reg_date || firm.expiry_date) && (
          <div className="tabular mt-0.5 text-[11px] text-ink-faint">
            {firm.reg_date || "—"}{firm.expiry_date ? ` → ${firm.expiry_date}` : ""}
          </div>
        )}
        {firm.br_no && <div className="tabular mt-0.5 text-[11px] text-ink-faint">BR {firm.br_no}</div>}
      </div>
      {(shownEmail(firm.enquiry_email) || firm.address) && (
        <div>
          <MonoLabel className="mb-1">Contact</MonoLabel>
          {shownEmail(firm.enquiry_email) && (
            <a href={`mailto:${shownEmail(firm.enquiry_email)}`} className="tabular block text-[11.5px] text-brand hover:underline">
              ✉ {shownEmail(firm.enquiry_email)}
            </a>
          )}
          {firm.address && <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">{firm.address}</div>}
        </div>
      )}
      {firm.trades.length > 0 && (
        <div>
          <MonoLabel className="mb-1.5">Registered trades</MonoLabel>
          <div className="flex flex-wrap gap-1.5">
            {firm.trades.map((t) => <Pill key={t} tone="violet">{tradeLabel(t)}</Pill>)}
          </div>
        </div>
      )}
      <div>
        <Collapse title="Closeout record" defaultOpen>
          <p className="text-xs leading-relaxed text-ink-soft">
            {firm.closeout_summary || "No assessable closeout record."}
          </p>
        </Collapse>
        <Collapse title={flagsLabel} count={flags.length} defaultOpen={flags.length > 0}>
          {flags.length > 0 ? (
            <RiskFlagList flags={flags} />
          ) : (
            <p className="text-xs text-ink-faint">No flags on record for this firm.</p>
          )}
        </Collapse>
        <Collapse title="Award history" count={firm.award_history.length}>
          {firm.award_history.length > 0 ? (
            <ul className="space-y-1 text-xs text-ink-soft">
              {firm.award_history.map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          ) : (
            <p className="text-xs text-ink-faint">No recorded public awards.</p>
          )}
        </Collapse>
        {children}
      </div>
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "bad" | "brand" | "violet" | "warn" }) {
  const tones = {
    neutral: "bg-line-soft text-ink-soft",
    ok: "bg-ok-bg text-ok",
    bad: "bg-bad-bg text-bad",
    brand: "bg-brand-bg text-brand",
    violet: "bg-violet-bg text-violet",
    warn: "bg-warn-bg text-warn",
  };
  return <span className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}
