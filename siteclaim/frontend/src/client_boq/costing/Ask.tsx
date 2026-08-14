// Ask — a question about this tender, answered from this tender's own ground.
//
// A chat box is the front door for a made-up number. Ask a language model what to price rock
// drilling at and it will answer, fluently, in the same typeface as the figures the engine
// computed. So this box does not pretend to be a chat: it is a question, an answer, and the
// answer's receipts.
//
// WHAT THE SCREEN SHOWS, and why each part is there:
//
//   the answer          prose only
//   figures used        every number it quoted, WITH the engine's own key beside it — so a reader
//                       can see which figures in the sentence are this tender's
//   citations           every source it leaned on, each one validated on the backend against the
//                       ground that was actually supplied
//   stripped            what was removed on the way through. A fabricated citation reads exactly
//                       like a real one; the only defence is saying that one was removed.
//   proposes            the ONE action it may suggest: record a condition. Pressing it records —
//                       it does not apply anything. The Costing step still proposes the mapping
//                       and a person still confirms.
//
// An answer with no citation is marked as a suggestion rather than a finding, by the backend, and
// rendered that way here.

import { useEffect, useState } from "react";
import { api } from "../api";
import type { AskResponse, SiteLogEntry } from "../types";
import { Button, Card, SectionLabel, cx } from "../ui";

export function Ask({
  setId,
  onError,
  onRecorded,
}: {
  setId: string;
  onError: (msg: string) => void;
  /** A recorded condition shows up on the register below, so the panel re-reads. */
  onRecorded: () => Promise<void>;
}) {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<AskResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [recorded, setRecorded] = useState(false);
  // THE TENDER REMEMBERS. Every exchange is persisted server-side, so a discussion that decided
  // something real survives a refresh, later questions are grounded in it, and a condition can
  // say which conversation it was born of.
  const [log, setLog] = useState<SiteLogEntry[]>([]);

  useEffect(() => {
    let live = true;
    api
      .siteLog(setId)
      .then((r) => live && setLog(r.entries))
      .catch(() => live && setLog([]));   // 404 = no log yet; a failed read leaves history blank,
    return () => {                        // and asking still works — the log is memory, not gate
      live = false;
    };
  }, [setId, recorded]);

  const ask = async () => {
    if (!question.trim()) return;
    setBusy(true);
    setRecorded(false);
    try {
      const r = await api.ask(setId, question.trim());
      setReply(r);
      // log_seq 0 = the server deliberately logged nothing (the no-ground refusal) — appending
      // it would show a history entry the next refresh could not find.
      if (r.log_seq > 0) {
        setLog((prev) => [...prev, {
          seq: r.log_seq, question: r.question, answer: r.answer,
          cannot_answer: r.cannot_answer, citations: r.citations, figures: r.figures,
          proposes: r.proposes, stripped: r.stripped, asked_by: r.asked_by,
          asked_at: null, became_condition: "", became_status: "",
        }]);
      }
      setQuestion("");
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-6">
      <SectionLabel>ASK ABOUT THIS TENDER</SectionLabel>
      <p className="mt-1 max-w-[680px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
        Answered only from this tender's own ground — the review's clauses, what the engine derived
        from the bill, the locations, and your site photographs. It may quote a figure the engine
        computed and it may not invent one; every claim carries a citation, and anything it could
        not source is stripped and shown below the answer.
      </p>

      {log.length > 0 && (
        <div className="mt-3 max-h-[300px] overflow-y-auto rounded-cb-card border border-cb-border bg-cb-surface">
          {log.map((entry) => (
            <div key={entry.seq} className="border-b border-cb-divider px-3 py-2 last:border-b-0">
              <p className="font-cb-sans text-[10px] text-cb-muted">
                <span className="font-cb-mono text-[10px] text-cb-faint">#{entry.seq}</span>{" "}
                <span className="font-semibold text-cb-ink-text">
                  {entry.asked_by || "someone"}
                </span>{" "}
                asked: {entry.question}
              </p>
              <p className="mt-1 font-cb-serif text-[11.5px] leading-[1.55] text-cb-body">
                {entry.answer || entry.cannot_answer}
              </p>
              {/* The receipts survive into memory. A past answer without its figures and
                  citations would read as prose to trust — exactly what this screen exists
                  to avoid. */}
              {Object.keys(entry.figures ?? {}).length > 0 && (
                <p className="mt-0.5 font-cb-mono text-[10px] text-cb-ink-text">
                  {Object.keys(entry.figures ?? {}).map((key) => (
                    <span key={key} className="mr-2">
                      <span className="text-cb-brass-text">{key}</span>
                    </span>
                  ))}
                  <span className="text-cb-faint">— figures quoted, the engine's</span>
                </p>
              )}
              {(entry.citations?.length ?? 0) > 0 && (
                <p className="mt-0.5 font-cb-sans text-[10px] leading-[1.45] text-cb-muted">
                  cited{" "}
                  {entry.citations!.map((c) => (
                    <span key={c.source} className="mr-1.5 font-cb-mono text-[10px] text-cb-brass-text">
                      [{c.source}]
                    </span>
                  ))}
                </p>
              )}
              {entry.became_condition && (
                <p
                  className={cx(
                    "mt-1 font-cb-mono text-[10px] font-semibold tracking-cb-chip",
                    entry.became_status === "rejected"
                      ? "text-cb-bad-dark"
                      : "text-cb-ok-dark",
                  )}
                >
                  {entry.became_status === "rejected"
                    ? `✕ BECAME CONDITION ${entry.became_condition} — later REJECTED; do not rely on it`
                    : `✓ BECAME CONDITION ${entry.became_condition} — it is on the register below`}
                </p>
              )}
              {(entry.stripped?.length ?? 0) > 0 && (
                <p className="mt-1 font-cb-sans text-[10px] text-cb-bad-dark">
                  {entry.stripped!.length} claim(s) were stripped from this answer for citing
                  nothing that was supplied.
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-2 flex items-start gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void ask();
          }}
          placeholder="e.g. what did the review find about liquidated damages?"
          className="flex-1 rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[11.5px] text-cb-ink-text placeholder:text-cb-faint"
        />
        <Button variant="brass" onClick={() => void ask()} disabled={busy || !question.trim()}>
          {busy ? "Reading…" : "Ask"}
        </Button>
      </div>

      {reply && (
        <Card className="mt-2.5">
          {reply.answer && (
            <p className="font-cb-serif text-[12.5px] leading-[1.55] text-cb-ink-text">
              {reply.answer}
            </p>
          )}
          {reply.cannot_answer && (
            <p
              className={cx(
                "mt-1 rounded-cb-chip px-2 py-1 font-cb-sans text-[10px] leading-[1.5]",
                reply.answer
                  ? "bg-cb-brass-tint text-cb-brass-text"
                  : "bg-cb-panel text-cb-muted",
              )}
            >
              {reply.cannot_answer}
            </p>
          )}

          {Object.keys(reply.figures).length > 0 && (
            <div className="mt-2">
              <div className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-faint">
                FIGURES QUOTED — THE ENGINE'S, NOT THE MODEL'S
              </div>
              {Object.entries(reply.figures).map(([key, described]) => (
                <div key={key} className="font-cb-mono text-[10px] text-cb-ink-text">
                  <span className="text-cb-brass-text">{key}</span> · {described}
                </div>
              ))}
            </div>
          )}

          {reply.citations.length > 0 && (
            <div className="mt-2">
              <div className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-faint">
                CITED
              </div>
              {reply.citations.map((citation, i) => (
                <div key={i} className="mt-0.5 font-cb-sans text-[10px] leading-[1.45] text-cb-muted">
                  <span className="font-cb-mono text-[10px] text-cb-brass-text">
                    [{citation.source}]
                  </span>{" "}
                  {citation.quote}
                </div>
              ))}
            </div>
          )}

          {reply.stripped.length > 0 && (
            <div className="mt-2 rounded-cb-chip border border-cb-bad bg-cb-bad-tint px-2 py-1.5">
              <div className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-bad-dark">
                REMOVED FROM THIS ANSWER
              </div>
              {reply.stripped.map((line) => (
                <p key={line} className="mt-0.5 font-cb-sans text-[10px] leading-[1.45] text-cb-bad-dark">
                  {line}
                </p>
              ))}
            </div>
          )}

          {reply.proposes && (
            <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-cb-divider pt-2">
              <span className="font-cb-sans text-[10.5px] text-cb-body">
                Suggests recording: <em>{reply.proposes}</em>
              </span>
              {recorded ? (
                <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-ok-dark">
                  RECORDED — CONFIRM THE MAPPING BELOW
                </span>
              ) : (
                <Button
                  onClick={async () => {
                    try {
                      await api.addCondition(setId, reply.proposes, "", reply.log_seq);
                      setRecorded(true);
                      await onRecorded();
                    } catch (e) {
                      onError(e instanceof Error ? e.message : String(e));
                    }
                  }}
                >
                  Record it as a condition
                </Button>
              )}
            </div>
          )}

          <div className="mt-2 font-cb-mono text-[10px] text-cb-faint">
            grounded in {reply.grounded_in.length} source(s)
          </div>
        </Card>
      )}
    </section>
  );
}
