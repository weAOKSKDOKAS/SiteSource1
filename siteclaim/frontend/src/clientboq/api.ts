// The /client-boq HTTP surface. One method per backend route (backend/client_boq/router.py),
// on the shared transport from src/api.ts — same base URL, same FastAPI {detail} unwrapping,
// so every failure reaches the UI as a readable sentence in an ErrorBanner.
//
// Two shapes to know:
//   * Long-running stages (review, scope, estimate) return a JOB ENVELOPE. In DEMO the backend
//     runs inline and returns {status:"done", result}; in live it returns a job_id to poll.
//     `settle()` collapses both into one promise so no caller branches on the mode.
//   * Binary deliverables (the .xlsx workbook) follow the app convention of returning a URL
//     string, never fetched bytes.

import { api, get, handle, post } from "../api";
import type {
  EstimateResult,
  EstimateSchedule,
  GateState,
  JobState,
  LetterMeta,
  LetterResult,
  RateRow,
  ReviewResult,
  ScopeGateState,
  ScopeResult,
} from "./types";

const BASE = api.base;
const PREFIX = "/client-boq";

// How often a live job is polled, and how many consecutive transport failures are tolerated
// before giving up — one dropped request must never abort a multi-minute review.
const POLL_MS = 1500;
const MAX_CONSECUTIVE_FAILURES = 5;

export interface JobProgress {
  status: string;
  stage: string;
  warnings: string[];
}

/**
 * Collapse a job envelope into the finished result.
 *
 * DEMO answers inline (`status: "done"` with the result attached) and resolves immediately.
 * Live answers with a `job_id`; this polls `statusPath(job_id)` until the job reports done or
 * error, reporting each stage through `onProgress`. A vanished job (404) gives up at once;
 * a handful of transient network failures are absorbed.
 */
function settle<T>(
  envelope: JobState<T>,
  statusPath: (jobId: string) => string,
  onProgress?: (p: JobProgress) => void,
): Promise<T> {
  onProgress?.({ status: envelope.status, stage: envelope.stage, warnings: envelope.warnings ?? [] });
  if (envelope.status === "done") {
    return envelope.result
      ? Promise.resolve(envelope.result)
      : Promise.reject(new Error("The stage finished without a result."));
  }
  if (envelope.status === "error") return Promise.reject(new Error(envelope.error || "The stage failed."));
  if (!envelope.job_id) return Promise.reject(new Error("No job id returned for a background stage."));

  const jobId = envelope.job_id;
  return new Promise<T>((resolve, reject) => {
    let consecutiveFailures = 0;
    const tick = () => {
      get<JobState<T>>(statusPath(jobId))
        .then((state) => {
          consecutiveFailures = 0;
          onProgress?.({ status: state.status, stage: state.stage, warnings: state.warnings ?? [] });
          if (state.status === "done") {
            if (state.result) resolve(state.result);
            else reject(new Error("The stage finished without a result."));
          } else if (state.status === "error") {
            reject(new Error(state.error || "The stage failed."));
          } else {
            setTimeout(tick, POLL_MS);
          }
        })
        .catch((e: unknown) => {
          const msg = e instanceof Error ? e.message : String(e);
          if (msg.includes("Unknown or expired") || ++consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
            reject(new Error(msg));
          } else {
            setTimeout(tick, POLL_MS);
          }
        });
    };
    setTimeout(tick, POLL_MS);
  });
}

const reviewStatus = (jobId: string) => `${PREFIX}/review/status/${jobId}`;
const estimateStatus = (jobId: string) => `${PREFIX}/estimate/status/${jobId}`;

export const boqApi = {
  // --- REVIEW ---------------------------------------------------------------
  /** Run REVIEW over an uploaded document set. Multipart, because the documents are the input. */
  runReview: (files: File[], projectName: string, onProgress?: (p: JobProgress) => void): Promise<ReviewResult> => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    fd.append("project_name", projectName);
    return fetch(BASE + `${PREFIX}/review/run`, { method: "POST", body: fd })
      .then((r) => handle<JobState<ReviewResult>>(r))
      .then((env) => settle(env, reviewStatus, onProgress));
  },

  /** The persisted register for a document set — the source of truth, re-readable at any time. */
  register: (setId: string) => get<ReviewResult>(`${PREFIX}/review/register/${encodeURIComponent(setId)}`),

  /**
   * The human gate. `decisions` maps an item number to a verdict; it is the ONLY path that
   * writes confirmed/dismissed. `approved` opens the review→estimate gate.
   */
  approveRegister: (setId: string, decisions: Record<number, string>, approved: boolean) =>
    post<GateState>(`${PREFIX}/review/approve`, { set_id: setId, decisions, approved }),

  gate: (setId: string) => get<GateState>(`${PREFIX}/gate/${encodeURIComponent(setId)}`),

  // --- ESTIMATE: scope ------------------------------------------------------
  /** Draft the estimate scope. Refused with a 409 until the register is approved. */
  runScope: (setId: string, onProgress?: (p: JobProgress) => void): Promise<ScopeResult> =>
    post<JobState<ScopeResult>>(`${PREFIX}/estimate/scope`, { set_id: setId })
      .then((env) => settle(env, estimateStatus, onProgress)),

  scope: (setId: string) => get<ScopeResult>(`${PREFIX}/estimate/scope/${encodeURIComponent(setId)}`),

  /** The scope gate. An `amended_summary` becomes the approved scope of record. */
  approveScope: (setId: string, amendedSummary: string, approved: boolean) =>
    post<ScopeGateState>(`${PREFIX}/estimate/scope/approve`, {
      set_id: setId,
      amended_summary: amendedSummary,
      approved,
    }),

  // --- ESTIMATE: price ------------------------------------------------------
  /**
   * Run the deterministic pricing spine. Both gates must be open (each returns its own 409).
   * DEMO ignores the schedule and margin and prices the fixture; live requires both.
   */
  runEstimate: (
    setId: string,
    marginPct: number | null,
    schedule: EstimateSchedule | null,
    letter: Partial<LetterMeta> | null,
    onProgress?: (p: JobProgress) => void,
  ): Promise<EstimateResult> =>
    post<JobState<EstimateResult>>(`${PREFIX}/estimate/run`, {
      set_id: setId,
      margin_pct: marginPct,
      schedule,
      letter,
    }).then((env) => settle(env, estimateStatus, onProgress)),

  estimate: (setId: string) => get<EstimateResult>(`${PREFIX}/estimate/${encodeURIComponent(setId)}`),

  // --- Deliverables ---------------------------------------------------------
  /** The pricing workbook is a file link, not fetched bytes (the app's convention for binaries). */
  workbookUrl: (setId: string) => `${BASE}${PREFIX}/estimate/${encodeURIComponent(setId)}/workbook`,

  letter: (setId: string) => get<LetterResult>(`${PREFIX}/estimate/${encodeURIComponent(setId)}/letter`),

  // --- The rate book --------------------------------------------------------
  rates: () => get<RateRow[]>(`${PREFIX}/rates`),
};
