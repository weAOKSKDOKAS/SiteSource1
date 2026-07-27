// The left rail for Client → BOQ.
//
// It borrows the Sourcing stepper's grammar — numbered node, connector, label + hint,
// unreachable steps disabled — but not its shape. Sourcing is one flat run of six steps;
// this is *two* workflows that only meet through a gate, so the rail says that: REVIEW and
// ESTIMATE are separate groups, and the gate that joins them is drawn between them as a
// seam rather than hidden inside a button. The second gate sits inside ESTIMATE for the
// same reason. Structure carrying information, not decoration.

import { cx } from "../ui";

export const BOQ_STEPS = [
  { step: 1, label: "Documents", hint: "Ingest the client's set", phase: "review" },
  { step: 2, label: "Register", hint: "Decide every departure", phase: "review" },
  { step: 3, label: "Scope", hint: "Agree what is priced", phase: "estimate" },
  { step: 4, label: "Price", hint: "Build up the cost", phase: "estimate" },
  { step: 5, label: "Offer", hint: "Workbook and letter", phase: "estimate" },
] as const;

export type BoqStep = 1 | 2 | 3 | 4 | 5;

function Seam({ label, closed }: { label: string; closed: boolean }) {
  return (
    <li className="relative flex shrink-0 items-center gap-2 py-2 lg:block lg:py-1.5">
      <div className="flex items-center gap-2 lg:pl-1">
        <span
          aria-hidden
          className={cx(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-[10px]",
            closed ? "border-ok/50 bg-ok-bg text-ok" : "border-warn/50 bg-warn-bg text-warn",
          )}
        >
          {closed ? "✓" : "◌"}
        </span>
        <span
          className={cx(
            "whitespace-nowrap text-[10.5px] font-semibold uppercase tracking-eyebrow",
            closed ? "text-ok" : "text-warn",
          )}
        >
          {label}
        </span>
        <span
          aria-hidden
          className={cx(
            "hidden h-px flex-1 lg:block",
            closed ? "bg-ok/30" : "bg-warn/30",
          )}
          style={{ backgroundImage: closed ? undefined : "repeating-linear-gradient(90deg,#d9951355 0 4px,transparent 4px 8px)" }}
        />
      </div>
    </li>
  );
}

function PhaseLabel({ children }: { children: string }) {
  return (
    <li className="hidden shrink-0 pb-1 pt-3 first:pt-0 lg:block">
      <span className="text-[10.5px] font-bold uppercase tracking-eyebrow text-ink-faint">{children}</span>
    </li>
  );
}

export function WorkflowRail({
  current,
  maxReached,
  reviewApproved,
  scopeApproved,
  onNavigate,
}: {
  current: BoqStep;
  maxReached: BoqStep;
  reviewApproved: boolean;
  scopeApproved: boolean;
  onNavigate: (s: BoqStep) => void;
}) {
  return (
    // min-w-0 so the horizontally scrolling mobile rail is clipped by its grid track instead
    // of stretching it — a grid item's default min-width:auto would push the whole page wide.
    <nav aria-label="Client to BOQ progress" className="min-w-0 lg:sticky lg:top-20">
      <ol className="flex items-center gap-2 overflow-x-auto pb-2 lg:block lg:gap-0 lg:overflow-visible lg:pb-0">
        <PhaseLabel>Review</PhaseLabel>
        {BOQ_STEPS.map((s, i) => {
          const state = s.step === current ? "active" : s.step < current ? "done" : "upcoming";
          const reachable = s.step <= maxReached;
          const nextInPhase = BOQ_STEPS[i + 1]?.phase === s.phase;
          const node = (
            <li key={s.label} className="relative flex shrink-0 lg:block">
              {nextInPhase && (
                <span
                  aria-hidden
                  className={cx(
                    "absolute left-[15px] top-8 hidden h-[calc(100%-1.5rem)] w-px lg:block",
                    s.step < current ? "bg-brand" : "bg-line",
                  )}
                />
              )}
              <button
                type="button"
                disabled={!reachable}
                onClick={() => reachable && onNavigate(s.step as BoqStep)}
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
                  {state === "done" ? "✓" : s.step}
                </span>
                <span className="pr-2">
                  <span className={cx("block text-sm font-semibold", state === "upcoming" ? "text-ink-faint" : "text-ink")}>
                    {s.label}
                    {state === "active" && (
                      <span className="ssLive ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-brand align-middle" aria-hidden />
                    )}
                  </span>
                  <span className="hidden text-xs text-ink-faint lg:block">{s.hint}</span>
                </span>
              </button>
            </li>
          );
          // The gates are drawn where they actually sit: after the register (review →
          // estimate) and after the scope (scope → pricing).
          if (s.step === 2) {
            return [
              node,
              <Seam key="gate-review" label="Register gate" closed={reviewApproved} />,
              <PhaseLabel key="phase-estimate">Estimate</PhaseLabel>,
            ];
          }
          if (s.step === 3) {
            return [node, <Seam key="gate-scope" label="Scope gate" closed={scopeApproved} />];
          }
          return node;
        })}
      </ol>
    </nav>
  );
}
