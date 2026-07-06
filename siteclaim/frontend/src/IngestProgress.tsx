import { useEffect, useState } from "react";

import { Button, Card, LoadingDots, ScanLine, cx } from "./ui";

// The live-ingest progress modal (a centered overlay, never a drawer). A live
// /ingest-upload now runs as a BACKGROUND job the client polls, so the checklist ticks from the
// real server stage (uploading → classifying → extracting → splitting) and, when the extractor
// reports it, a chunk counter. The scan sweep sits on the active stage and the elapsed timer
// keeps counting with no ceiling — a big tender can extract for minutes. We only show what the
// job actually reports; before any poll lands it falls back to a single indeterminate stage.
export type IngestPhase = "uploading" | "processing" | "done" | "error";

const STAGES = [
  { key: "upload", label: "Uploading documents" },
  { key: "classify", label: "Classifying documents" },
  { key: "extract", label: "Extracting the Schedule of Rates" },
  { key: "split", label: "Splitting into packages" },
] as const;

// Backend stage label -> the checklist index it lights up.
const STAGE_INDEX: Record<string, number> = { uploading: 0, classifying: 1, extracting: 2, splitting: 3 };

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

export function IngestProgress({
  phase,
  startedAt,
  stage,
  progress,
  warnings,
  error,
  summary,
  onRetry,
  onCancel,
}: {
  phase: IngestPhase;
  startedAt: number;
  stage?: string; // the background job's stage — uploading | classifying | extracting | splitting
  progress?: { done: number; total: number };
  warnings?: string[]; // per-section batches the extractor couldn't read (non-fatal)
  error?: string;
  summary?: { items: number; packages: number };
  onRetry: () => void;
  onCancel: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    if (phase === "done" || phase === "error") return;
    const t = setInterval(() => setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000))), 500);
    return () => clearInterval(t);
  }, [phase, startedAt]);

  const working = phase === "uploading" || phase === "processing";
  const title = phase === "done" ? "Tender read" : phase === "error" ? "Couldn't read the tender" : "Reading the tender…";
  // Which checklist row is active: the reported stage while processing, else the upload row.
  const activeIndex = phase === "uploading" ? 0 : stage ? STAGE_INDEX[stage] ?? 1 : 1;

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-ink/45 px-4">
      <Card className="relative w-full max-w-md overflow-hidden p-6">
        <ScanLine active={working} />
        <div className="flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold tracking-display text-ink">{title}</h3>
          <span className="tabular text-xs text-ink-faint">{elapsedLabel(elapsed)}</span>
        </div>

        {phase === "error" ? (
          <div className="mt-4 space-y-4">
            <p className="rounded-lg border border-bad/30 bg-bad-bg px-4 py-3 text-sm text-bad">
              <span className="font-semibold">Extraction failed.</span> {error}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onCancel}>Cancel</Button>
              <Button onClick={onRetry}>Try again</Button>
            </div>
          </div>
        ) : (
          <>
            <ul className="mt-4 space-y-3">
              {STAGES.map((item, i) => {
                const state = stageState(phase, i, activeIndex);
                const showCount = state === "active" && item.key === "extract" && progress && progress.total > 0;
                return (
                  <li key={item.key} className="flex items-center gap-3">
                    <StageIcon state={state} />
                    <span className={cx("text-sm", state === "upcoming" ? "text-ink-faint" : state === "done" ? "text-ink-soft" : "font-semibold text-ink")}>
                      {item.label}
                    </span>
                    {showCount ? (
                      <span className="tabular ml-auto text-xs text-ink-faint">{progress!.done}/{progress!.total} chunks</span>
                    ) : state === "active" ? (
                      <span className="ml-auto"><LoadingDots /></span>
                    ) : null}
                  </li>
                );
              })}
            </ul>

            {phase === "done" ? (
              <>
                <p className="mt-5 rounded-lg border border-ok/30 bg-ok-bg px-4 py-3 text-sm text-ink">
                  <span className="font-semibold text-ok">Done.</span>{" "}
                  {summary ? `${summary.items} items across ${summary.packages} package${summary.packages === 1 ? "" : "s"}.` : "Tender split into packages."}{" "}
                  Opening Route…
                </p>
                {warnings && warnings.length > 0 && (
                  <div className="mt-3 rounded-lg border border-warn/40 bg-warn-bg px-4 py-3 text-xs text-warn">
                    <span className="font-semibold">
                      {warnings.length} batch{warnings.length === 1 ? "" : "es"} couldn’t be read
                    </span>{" "}
                    and {warnings.length === 1 ? "was" : "were"} skipped — everything else was extracted. Re-run to retry, or review those rows by hand.
                  </div>
                )}
              </>
            ) : (
              <p className="mt-5 text-xs leading-relaxed text-ink-faint">
                {phase === "uploading"
                  ? "Sending the documents to the extractor."
                  : "Reading the Schedule of Rates. Extraction runs in chunks, so a large tender can take a few minutes — this stays open until it finishes."}
              </p>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
