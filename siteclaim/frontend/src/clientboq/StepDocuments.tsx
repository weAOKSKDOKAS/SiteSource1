// Step 1 — the client's document set goes in.
//
// This is the only step where the operator hands over material rather than making a
// decision, so it stays deliberately plain: name the job, add the documents, run the review.
// The one thing it does insist on is honesty about what the run will actually read — in
// DEMO the backend answers from fixtures, and the screen says so rather than implying the
// uploaded files were parsed.

import type { ChangeEvent } from "react";
import { useState } from "react";

import { StepHeading } from "../components";
import { Button, Card, LayerBadge, LoadingDots, ScanLine, cx } from "../ui";
import { EmptyState } from "./boqUi";

export function StepDocuments({
  demoMode,
  projectName,
  files,
  running,
  stage,
  setId,
  onProjectName,
  onAddFiles,
  onRemoveFile,
  onRun,
  onOpenExisting,
  onContinue,
}: {
  demoMode: boolean;
  projectName: string;
  files: File[];
  running: boolean;
  stage: string;
  setId: string | null;
  onProjectName: (v: string) => void;
  onAddFiles: (files: File[]) => void;
  onRemoveFile: (i: number) => void;
  onRun: () => void;
  onOpenExisting: (setId: string) => void;
  onContinue: () => void;
}) {
  const [existing, setExisting] = useState("");

  function onFileInput(e: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length) onAddFiles(picked);
    e.target.value = "";
  }

  const canRun = demoMode || files.length > 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <StepHeading
          title="Take in the client's documents"
          lead="Hand over the tender and contract set the client issued. Claude reads and structures it; the rules engine checks the numeric terms against the criteria library. Nothing is decided here — the review produces a register you rule on next."
        />
        <LayerBadge layer="L2" />
      </div>

      <Card className="relative p-5">
        <ScanLine active={running} />
        <label className="block text-sm font-semibold text-ink" htmlFor="boq-project">
          Project or package name
        </label>
        <input
          id="boq-project"
          className="mt-1.5 w-full max-w-md rounded-lg border border-line px-3 py-2 text-sm focus:border-brand focus:outline-none"
          placeholder="Harbour Crest Residences — facade package"
          value={projectName}
          onChange={(e) => onProjectName(e.target.value)}
        />
        <p className="mt-1.5 text-xs text-ink-faint">
          Names the document set and heads the register, the workbook and the offer letter.
        </p>

        <div className="mt-5">
          <span className="block text-sm font-semibold text-ink">Contract documents</span>
          <label
            className={cx(
              "mt-1.5 flex cursor-pointer items-center justify-center rounded-lg border border-dashed border-line bg-paper/50 px-4 py-6 text-sm text-ink-soft transition-colors",
              "hover:border-brand hover:text-brand focus-within:border-brand",
            )}
          >
            <input type="file" multiple accept="application/pdf,image/*" className="sr-only" onChange={onFileInput} />
            Choose files — the subcontract, specification, drawings and any letter of offer (PDF, JPEG, PNG)
          </label>
          {files.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {files.map((f, i) => (
                <li
                  key={`${f.name}-${i}`}
                  className="flex items-center justify-between rounded-md border border-line-soft bg-paper/50 px-3 py-1.5 text-sm"
                >
                  <span className="truncate text-ink">{f.name}</span>
                  <button
                    type="button"
                    onClick={() => onRemoveFile(i)}
                    className="ml-3 shrink-0 text-xs font-medium text-ink-faint hover:text-bad"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          {demoMode && (
            <p className="mt-2 text-xs text-warn">
              Demo mode runs offline against the baked Harbour Crest set. Files you add are accepted but not
              read — turn DEMO_MODE off to review a real document set.
            </p>
          )}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          {running ? (
            <LoadingDots label={stage ? `Reviewing — ${stage}` : "Reviewing"} />
          ) : (
            <span className="text-xs text-ink-faint">
              A live review reads every document end to end; it runs in the background and can take a few minutes.
            </span>
          )}
          <Button onClick={onRun} loading={running} disabled={!canRun}>
            Run the review →
          </Button>
        </div>
      </Card>

      {!setId && !running && (
        <EmptyState title="No register yet">
          Run the review above, or reopen a document set you have already reviewed.
        </EmptyState>
      )}

      <Card className="p-5">
        <h3 className="text-sm font-semibold text-ink">Reopen a document set</h3>
        <p className="mt-0.5 text-xs text-ink-faint">
          Registers, scopes and estimates persist server-side. This screen does not, so a set id brings a
          finished job back.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            className="tabular w-72 rounded-lg border border-line px-3 py-2 text-sm focus:border-brand focus:outline-none"
            placeholder="harbour-crest-residences"
            value={existing}
            onChange={(e) => setExisting(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && existing.trim() && onOpenExisting(existing.trim())}
          />
          <Button variant="ghost" disabled={!existing.trim()} onClick={() => onOpenExisting(existing.trim())}>
            Open set
          </Button>
        </div>
      </Card>

      {setId && !running && (
        <div className="flex justify-end">
          <Button onClick={onContinue}>Open the register →</Button>
        </div>
      )}
    </div>
  );
}
