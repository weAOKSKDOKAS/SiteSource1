import { useEffect, useState } from "react";

import type { IngestJob, IngestPhase } from "./useIngestJob";
import { Button, Card, LoadingDots, ScanLine, cx } from "./ui";

// The live-ingest progress indicator. A live /ingest-upload runs as a BACKGROUND job the client
// polls, so the checklist ticks from the real server stage (uploading → classifying → extracting
// → splitting) and, when the extractor reports it, a chunk counter. It is NON-BLOCKING: a compact
// floating pill by default (the rest of the app stays interactive while a big tender extracts for
// minutes), which expands to the detailed checklist on click and minimizes back. Completion and
// failure are surfaced as dismissable notifications, never a full-screen backdrop.

const STAGES = [
  { key: "upload", label: "Uploading documents" },
  { key: "classify", label: "Classifying documents" },
  { key: "extract", label: "Extracting the Schedule of Rates" },
  { key: "split", label: "Splitting into packages" },
] as const;

// Backend stage label -> the checklist index it lights up.
const STAGE_INDEX: Record<string, number> = { uploading: 0, classifying: 1, extracting: 2, splitting: 3 };
// Backend stage label -> the short pill caption ("Reading tender · 1m 52s · 4/84").
const PILL_LABEL: Record<string, string> = {
  uploading: "Uploading tender",
  classifying: "Classifying documents",
  extracting: "Reading tender",
  splitting: "Splitting packages",
};

type StageState = "done" | "active" | "upcoming";

function stageState(phase: IngestPhase, i: number, activeIndex: number): StageState {
  if (phase === "done") return "done";
  if (phase === "error") return i === 0 ? "done" : "upcoming"; // upload finished; the rest is unknown
  if (i < activeIndex) return "done";
  if (i === activeIndex) return "active";
  return "upcoming";
}

function StageIcon({ state }: { state: StageState }) {
  if (state === "done")
    return <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ok text-[11px] font-bold text-white" aria-hidden>✓</span>;
  if (state === "active")
    return <span className="ssDot h-2.5 w-2.5 shrink-0 rounded-full bg-brand" aria-hidden />;
  return <span className="h-2.5 w-2.5 shrink-0 rounded-full border border-line" aria-hidden />;
}

function elapsedLabel(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

function activeIndexOf(job: IngestJob): number {
  return job.phase === "uploading" ? 0 : job.stage ? STAGE_INDEX[job.stage] ?? 1 : 1;
}

function pillLabel(job: IngestJob): string {
  if (job.phase === "uploading") return "Uploading tender";
  return (job.stage && PILL_LABEL[job.stage]) || "Reading tender";
}

function counterText(job: IngestJob): string | null {
  return job.progress && job.progress.total > 0 ? `${job.progress.done}/${job.progress.total}` : null;
}

// Elapsed seconds since the job started; keeps ticking while working (no ceiling — a big tender
// extracts for minutes) and freezes once the job is done or errored.
function useElapsed(job: IngestJob | null): number {
  const [elapsed, setElapsed] = useState(0);
  const startedAt = job?.startedAt ?? 0;
  const running = job?.phase === "uploading" || job?.phase === "processing";
  useEffect(() => {
    if (!startedAt) return;
    const compute = () => setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    compute();
    if (!running) return;
    const t = setInterval(compute, 500);
    return () => clearInterval(t);
  }, [running, startedAt]);
  return elapsed;
}

// The per-section batches the extractor couldn't read (non-fatal) — surfaced, not hidden. Rides
// along in the expanded panel and the completion notification exactly as before.
function WarningsNote({ warnings }: { warnings?: string[] }) {
  if (!warnings || warnings.length === 0) return null;
  return (
    <div className="mt-3 rounded-lg border border-warn/40 bg-warn-bg px-3 py-2 text-xs text-warn">
      <span className="font-semibold">
        {warnings.length} batch{warnings.length === 1 ? "" : "es"} couldn’t be read
      </span>{" "}
      and {warnings.length === 1 ? "was" : "were"} skipped — everything else was extracted. Re-run to retry, or review those rows by hand.
    </div>
  );
}

// The detailed stage checklist + hint — the body that renders inside the expanded panel (it used
// to live only inside the full-screen overlay).
function ProgressBody({ job }: { job: IngestJob }) {
  const activeIndex = activeIndexOf(job);
  return (
    <>
      <ul className="mt-4 space-y-3">
        {STAGES.map((item, i) => {
          const state = stageState(job.phase, i, activeIndex);
          const showCount = state === "active" && item.key === "extract" && job.progress && job.progress.total > 0;
          return (
            <li key={item.key} className="flex items-center gap-3">
              <StageIcon state={state} />
              <span className={cx("text-sm", state === "upcoming" ? "text-ink-faint" : state === "done" ? "text-ink-soft" : "font-semibold text-ink")}>
                {item.label}
              </span>
              {showCount ? (
                <span className="tabular ml-auto text-xs text-ink-faint">{job.progress!.done}/{job.progress!.total} chunks</span>
              ) : state === "active" ? (
                <span className="ml-auto"><LoadingDots /></span>
              ) : null}
            </li>
          );
        })}
      </ul>
      <p className="mt-4 text-xs leading-relaxed text-ink-faint">
        {job.phase === "uploading"
          ? "Sending the documents to the extractor."
          : "Reading the Schedule of Rates. Extraction runs in chunks, so a large tender can take a few minutes — you can keep working; this keeps running in the background."}
      </p>
      <WarningsNote warnings={job.warnings} />
    </>
  );
}

// The collapsed working state: a compact floating pill (active stage · elapsed · chunk counter).
function ProgressPill({ job, elapsed, onExpand }: { job: IngestJob; elapsed: number; onExpand: () => void }) {
  const counter = counterText(job);
  return (
    <button
      type="button"
      onClick={onExpand}
      aria-label="Show ingest progress"
      className="ssRise group flex items-center gap-2.5 rounded-full border border-line-soft bg-card px-4 py-2.5 shadow-card transition-colors hover:bg-line-soft focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright"
    >
      <span className="ssDot h-2 w-2 shrink-0 rounded-full bg-brand" aria-hidden />
      <span className="text-sm font-semibold text-ink">{pillLabel(job)}</span>
      <span className="tabular text-xs text-ink-faint">· {elapsedLabel(elapsed)}</span>
      {counter && <span className="tabular text-xs text-ink-faint">· {counter}</span>}
      <span className="text-[10px] text-ink-faint transition-transform group-hover:-translate-y-0.5" aria-hidden>▲</span>
    </button>
  );
}

// The expanded working state: the detailed checklist as a non-blocking popover anchored to the
// pill (no backdrop, does not eat clicks). Minimize returns to the pill; Cancel stops the job.
function ProgressPanel({
  job,
  elapsed,
  onMinimize,
  onCancel,
}: {
  job: IngestJob;
  elapsed: number;
  onMinimize: () => void;
  onCancel: () => void;
}) {
  return (
    <Card className="relative w-full overflow-hidden p-5">
      <ScanLine active />
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-base font-semibold tracking-display text-ink">Reading the tender…</h3>
        <div className="flex items-center gap-2">
          <span className="tabular text-xs text-ink-faint">{elapsedLabel(elapsed)}</span>
          <button
            type="button"
            onClick={onMinimize}
            aria-label="Minimize"
            title="Minimize"
            className="flex h-6 w-6 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-line-soft hover:text-ink"
          >
            ▾
          </button>
        </div>
      </div>
      <ProgressBody job={job} />
      <div className="mt-4 flex justify-end">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}

// Completion — a dismissable "Tender ready" notification. The operator opens Route when ready
// (they are never yanked there from another page); warnings ride along.
function DoneCard({
  job,
  onDismiss,
  onOpenRoute,
}: {
  job: IngestJob;
  onDismiss: () => void;
  onOpenRoute?: () => void;
}) {
  const s = job.summary;
  const detail = s
    ? `${s.items} items across ${s.packages} package${s.packages === 1 ? "" : "s"}.`
    : "Tender split into packages.";
  return (
    <Card className="relative w-full overflow-hidden p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ok text-[11px] font-bold text-white" aria-hidden>✓</span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink">Tender ready</p>
          <p className="mt-0.5 text-xs text-ink-soft">{detail}</p>
          <WarningsNote warnings={job.warnings} />
          <div className="mt-3 flex items-center gap-2">
            {onOpenRoute && <Button onClick={onOpenRoute}>Open Route →</Button>}
            <Button variant="ghost" onClick={onDismiss}>Dismiss</Button>
          </div>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-ink-faint transition-colors hover:text-ink"
        >
          ✕
        </button>
      </div>
    </Card>
  );
}

// Failure — a non-blocking notification with a retry. The retry decision is an explicit click;
// the working / among-stages state is never blocking.
function ErrorCard({ job, onDismiss, onRetry }: { job: IngestJob; onDismiss: () => void; onRetry: () => void }) {
  return (
    <Card className="relative w-full overflow-hidden border-bad/30 p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-bad">Couldn’t read the tender</p>
          {job.error && <p className="mt-0.5 break-words text-xs text-ink-soft">{job.error}</p>}
          <div className="mt-3 flex items-center gap-2">
            <Button onClick={onRetry}>Try again</Button>
            <Button variant="ghost" onClick={onDismiss}>Dismiss</Button>
          </div>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-ink-faint transition-colors hover:text-ink"
        >
          ✕
        </button>
      </div>
    </Card>
  );
}

// The app-shell ingest indicator: one fixed, bottom-right, non-blocking surface that renders on
// every page. Working -> pill (or the expanded checklist popover); done -> completion toast;
// error -> retry notification. `null` job renders nothing.
export function IngestIndicator({
  job,
  onCancel,
  onDismiss,
  onRetry,
  onOpenRoute,
}: {
  job: IngestJob | null;
  onCancel: () => void; // explicit stop of a running job (in the expanded panel)
  onDismiss: () => void; // close a done/error notification
  onRetry: () => void; // re-run after a failure
  onOpenRoute?: () => void; // open Route from the completion toast
}) {
  const [expanded, setExpanded] = useState(false);
  const elapsed = useElapsed(job);
  // A fresh run always starts collapsed to the pill, even though this indicator never unmounts.
  const startedAt = job?.startedAt ?? 0;
  useEffect(() => {
    setExpanded(false);
  }, [startedAt]);

  if (!job) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col items-end">
      {job.phase === "error" ? (
        <ErrorCard job={job} onDismiss={onDismiss} onRetry={onRetry} />
      ) : job.phase === "done" ? (
        <DoneCard job={job} onDismiss={onDismiss} onOpenRoute={onOpenRoute} />
      ) : expanded ? (
        <ProgressPanel job={job} elapsed={elapsed} onMinimize={() => setExpanded(false)} onCancel={onCancel} />
      ) : (
        <ProgressPill job={job} elapsed={elapsed} onExpand={() => setExpanded(true)} />
      )}
    </div>
  );
}
