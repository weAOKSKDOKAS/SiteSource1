import { useCallback, useRef, useState } from "react";

import { api } from "./api";
import type { IngestUpload } from "./types";

// The live-ingest job phases the UI renders: uploading (bytes going up), processing (the
// background extraction the client polls), done, error.
export type IngestPhase = "uploading" | "processing" | "done" | "error";

// The app-level snapshot of one live-ingest run. Held here (not inside the ingest step) so the
// progress indicator can render on any page and survive navigation.
export interface IngestJob {
  phase: IngestPhase;
  startedAt: number;
  stage?: string; // the background job's stage — uploading | classifying | extracting | splitting
  progress?: { done: number; total: number };
  warnings?: string[]; // per-section batches the extractor couldn't read (non-fatal)
  summary?: { items: number; packages: number };
  error?: string;
}

export interface IngestJobHandle {
  job: IngestJob | null;
  start: (files: File[]) => void; // kick off a live upload + poll (the demo/instant path is elsewhere)
  cancel: () => void; // explicit: stop caring about the running job (never a side effect of nav)
  dismiss: () => void; // clear a done/error notification
  retry: () => void; // re-run the last upload (error → try again)
}

// App-level owner of the live-ingest background job. The poll itself lives in api.ingestUpload —
// a JS loop, independent of React rendering — so once started it keeps running no matter which
// page is shown; this hook just holds the job snapshot the indicator renders. A generation guard
// makes cancel real and race-proof: cancelling (or starting a new run) bumps the generation, so a
// superseded poll's late callbacks — including onDone — never write state or fire side effects.
// onDone runs the caller's post-ingest wiring (route analyze + advance); kept out of here so this
// stays a generic store with no knowledge of the wizard.
export function useIngestJob(onDone: (uploaded: IngestUpload) => void): IngestJobHandle {
  const [job, setJob] = useState<IngestJob | null>(null);
  const genRef = useRef(0);
  const filesRef = useRef<File[]>([]);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const run = useCallback((files: File[]) => {
    const gen = ++genRef.current; // invalidates any in-flight run's callbacks
    const alive = () => genRef.current === gen;
    const startedAt = Date.now();
    filesRef.current = files;
    setJob({ phase: "uploading", startedAt });
    api
      .ingestUpload(files, {
        onUploaded: () =>
          alive() && setJob((m) => (m && m.phase === "uploading" ? { ...m, phase: "processing" } : m)),
        // Each poll advances the indicator: the stage ticks the checklist; the chunk counter (when
        // known) shows extraction progress; elapsed keeps counting with no ceiling.
        onProgress: (s) =>
          alive() &&
          setJob((m) =>
            m
              ? { ...m, phase: "processing", stage: s.stage, progress: s.progress ?? undefined, warnings: s.warnings ?? m.warnings }
              : m,
          ),
      })
      .then((uploaded) => {
        if (!alive()) return; // cancelled / superseded — drop the result silently, never yank
        const items = uploaded.scope.packages.reduce((n, p) => n + p.sor_items.length, 0);
        setJob((m) => ({
          phase: "done",
          startedAt,
          summary: { items, packages: uploaded.scope.packages.length },
          warnings: m?.warnings, // sections the extractor couldn't read — surfaced, not hidden
        }));
        onDoneRef.current(uploaded);
      })
      .catch((e: unknown) => {
        if (!alive()) return;
        setJob((m) => ({
          phase: "error",
          startedAt: m?.startedAt ?? startedAt,
          error: e instanceof Error ? e.message : String(e),
          warnings: m?.warnings,
        }));
      });
  }, []);

  const start = useCallback((files: File[]) => run(files), [run]);
  const retry = useCallback(() => run(filesRef.current), [run]);
  // Cancel and dismiss both bump the generation (so no late poll callback writes state) and clear
  // the snapshot. They differ only in intent: cancel stops a running job; dismiss closes a
  // finished notification.
  const cancel = useCallback(() => {
    genRef.current++;
    setJob(null);
  }, []);
  const dismiss = cancel;

  return { job, start, cancel, dismiss, retry };
}
