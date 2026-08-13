// Brain — what the tender's one strong model understood, and the moves it proposes.
//
// PROPOSE-ONLY, and the screen enforces its half of that: every action below is a NAVIGATION
// button. It opens the screen where the act lives; the consequential click — approve, decide,
// route, classify — stays on that screen, behind its own stated consequence, with the person's
// name on it. Nothing here executes anything. (The backend enforces the other half: the
// briefing's raw model has no field for a verdict, and an action is only an id into a fixed
// registry of screens.)
//
// The briefing shows its receipts: which focused reads ran, what validation STRIPPED (an
// invented action or a citation to nothing reads exactly like a real one — the only defence is
// saying one was removed), and the citations under each proposal.

import { useCallback, useEffect, useState } from "react";
import type { SetData } from "../App";
import { api, isNotYet, runJob } from "../api";
import type { TabId } from "../chrome";
import type { Briefing, JobState } from "../types";
import { Button, SectionLabel, WaitingOn } from "../ui";

export function BrainTab({
  data,
  onError,
  onGo,
  onProgress,
}: {
  data: SetData;
  onError: (msg: string) => void;
  /** Navigation ONLY — the whole contract of an action button. */
  onGo: (tab: TabId) => void;
  onProgress: (state: JobState | null) => void;
}) {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [count, setCount] = useState(0);
  const [waitingOn, setWaitingOn] = useState("");
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api.briefing(data.setId);
      setBriefing(body.briefing);
      setCount(body.count);
      setWaitingOn(body.waiting_on);
    } catch (e) {
      if (!isNotYet(e)) onError(e instanceof Error ? e.message : String(e));
    }
  }, [data.setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async () => {
    setRunning(true);
    try {
      await runJob(() => api.brainRun(data.setId), api.brainStatus, onProgress);
      await load();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
      onProgress(null);
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[880px] p-[18px]">
        <header className="flex flex-wrap items-baseline gap-3">
          <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">
            The tender's brain
          </h1>
          {briefing && (
            <span className="font-cb-mono text-[9.5px] text-cb-faint">
              briefing #{briefing.seq} of {count} · {briefing.created_by || "someone"} ·{" "}
              {briefing.created_at?.slice(0, 16).replace("T", " ")}
            </span>
          )}
          <span className="ml-auto">
            <Button variant="brass" disabled={running} onClick={() => void run()}>
              {running ? "Reading…" : briefing ? "Run it again" : "Run the brain"}
            </Button>
          </span>
        </header>
        <p className="mt-1 max-w-[680px] font-cb-sans text-[10.5px] leading-[1.6] text-cb-muted">
          One strong model reads everything this tender knows — the register, the parts, the
          take-off, the bill's state, the discussions — and reports what it understands, where
          sources disagree, and which screens deserve your next click. It proposes and never
          disposes: every approval, verdict and number on this product stays yours, on the screen
          that owns it.
        </p>

        {!briefing && (
          <div className="mt-6">
            <WaitingOn title="No briefing yet">
              {waitingOn || "the brain has not run on this tender yet"}. Running it reads what is
              already here; it changes nothing and decides nothing.
            </WaitingOn>
          </div>
        )}

        {briefing && (
          <>
            <section className="mt-6">
              <SectionLabel>WHAT IT UNDERSTANDS</SectionLabel>
              <p className="mt-2 max-w-[720px] font-cb-serif text-[13px] leading-[1.65] text-cb-ink-text">
                {briefing.understanding}
              </p>
              {briefing.cannot_assess && (
                <p className="mt-2 rounded-cb-chip bg-cb-panel px-2 py-1 font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
                  Could not assess: {briefing.cannot_assess}
                </p>
              )}
              {briefing.reads.length > 0 && (
                <p className="mt-2 font-cb-mono text-[8.5px] text-cb-faint">
                  reads — {briefing.reads.join(" · ")}
                </p>
              )}
            </section>

            {briefing.disagreements.length > 0 && (
              <section className="mt-5">
                <SectionLabel>WHERE SOURCES DISAGREE</SectionLabel>
                {briefing.disagreements.map((line) => (
                  <p
                    key={line}
                    className="mt-1.5 max-w-[720px] border-l-2 border-cb-amber pl-2.5 font-cb-sans text-[11px] leading-[1.6] text-cb-body"
                  >
                    {line}
                  </p>
                ))}
              </section>
            )}

            <section className="mt-5">
              <SectionLabel>PROPOSED NEXT ACTIONS — EACH IS A SCREEN, THE CLICK IS YOURS</SectionLabel>
              {briefing.actions.length === 0 && (
                <p className="mt-2 font-cb-sans text-[10.5px] text-cb-muted">
                  It proposed nothing — which is itself information.
                </p>
              )}
              {briefing.actions.map((action) => (
                <div
                  key={action.action_id}
                  className="mt-2 rounded-cb-card border border-cb-border bg-cb-page px-3 py-2.5"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-cb-sans text-[11.5px] font-semibold text-cb-ink-text">
                      {action.label}
                    </span>
                    <span className="font-cb-mono text-[8.5px] tracking-cb-chip text-cb-faint">
                      → {action.tab.toUpperCase()}
                    </span>
                    <span className="ml-auto">
                      <Button onClick={() => onGo(action.tab as TabId)}>Go — the decision is there</Button>
                    </span>
                  </div>
                  <p className="mt-1 max-w-[640px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-body">
                    {action.reasoning}
                  </p>
                  {action.citations.length > 0 && (
                    <p className="mt-1 font-cb-sans text-[9px] leading-[1.45] text-cb-muted">
                      leans on{" "}
                      {action.citations.map((c) => (
                        <span key={c.source} className="mr-1.5 font-cb-mono text-[8.5px] text-cb-brass-text">
                          [{c.source}]
                        </span>
                      ))}
                    </p>
                  )}
                </div>
              ))}
            </section>

            {briefing.stripped.length > 0 && (
              <section className="mt-5 rounded-cb-card border border-cb-bad bg-cb-bad-tint px-3 py-2">
                <div className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-bad-dark">
                  REMOVED FROM THIS BRIEFING
                </div>
                {briefing.stripped.map((line) => (
                  <p key={line} className="mt-0.5 font-cb-sans text-[9.5px] leading-[1.45] text-cb-bad-dark">
                    {line}
                  </p>
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
