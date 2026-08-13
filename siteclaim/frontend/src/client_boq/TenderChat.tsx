// The tender's chat — one conversation per folder, and it cannot invent a number.
//
// WHY IT IS PER TENDER, structurally rather than by convention: every exchange is persisted
// against the SET id (`client_boq_site_log`, primary key set_id+seq), and the ground an answer is
// allowed to rest on is assembled for that set alone. Two tenders cannot bleed into one another
// because neither the memory nor the ground has a way to reach across — the folder IS the scope.
//
// WHAT IT CAN AND CANNOT DO. It answers from this tender's own ground: the register's clauses,
// what the engine derived from the bill, the take-off and the access board, the site photographs,
// the recorded conditions and the earlier discussions. It may quote a figure the engine computed
// and it may not invent one; every claim carries a citation validated on the server against the
// ground actually supplied, and anything it could not source is STRIPPED and shown as removed.
//
// AND THE ONE ACTION IT MAY PROPOSE is recording a condition — which then walks the ordinary
// propose-and-confirm path: you record it, the engine proposes the mapping, and a person confirms
// the number. That is the whole of its authority. The conversation feeds costing because every
// exchange re-enters the ground as a DISCUSSION the next answer can see and weigh — so talking
// through a site changes what the app understands, without ever letting the chat write a price.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { AskResponse, SiteLogEntry } from "./types";
import { Button, cx } from "./ui";

/** Openers, so the box is not a blank prompt. Each is a question the ground can actually answer. */
const STARTERS = [
  "What should I look at next on this tender?",
  "What is the biggest commercial risk in the register?",
  "What is still unresolved before I can price this?",
  "Explain how this bill's total was built.",
  "What did we already decide about site access?",
];

export function TenderChat({
  setId,
  tenderName,
  open,
  onClose,
  onError,
}: {
  setId: string;
  tenderName: string;
  open: boolean;
  onClose: () => void;
  onError: (msg: string) => void;
}) {
  const [log, setLog] = useState<SiteLogEntry[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<AskResponse | null>(null);
  const [recorded, setRecorded] = useState<Record<number, boolean>>({});
  const foot = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api.siteLog(setId);
      setLog(body.entries);
    } catch {
      // A log that will not load is memory missing, not a broken chat — asking still works, and
      // saying so is better than an error banner over a box that is fine.
      setLog([]);
    }
  }, [setId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  useEffect(() => {
    if (open) foot.current?.scrollIntoView({ behavior: "smooth" });
  }, [log.length, open, busy]);

  const ask = useCallback(
    async (text: string) => {
      const asked = text.trim();
      if (!asked || busy) return;
      setBusy(true);
      setQuestion("");
      try {
        const reply = await api.ask(setId, asked);
        setLast(reply);
        // log_seq 0 = the server deliberately logged nothing (nothing has been read for this
        // tender yet), so appending would show an entry no refresh could find.
        if (reply.log_seq > 0) {
          setLog((prev) => [...prev, {
            seq: reply.log_seq, question: reply.question, answer: reply.answer,
            cannot_answer: reply.cannot_answer, citations: reply.citations,
            figures: reply.figures, proposes: reply.proposes, stripped: reply.stripped,
            asked_by: reply.asked_by, asked_at: null, became_condition: "", became_status: "",
          }]);
        } else {
          setLog((prev) => [...prev, {
            seq: -1, question: asked, answer: "", cannot_answer: reply.cannot_answer,
            citations: [], figures: {}, proposes: "", stripped: [], asked_by: reply.asked_by,
            asked_at: null, became_condition: "", became_status: "",
          }]);
        }
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [setId, busy, onError],
  );

  const record = useCallback(
    async (entry: SiteLogEntry) => {
      try {
        await api.addCondition(setId, entry.proposes, "", entry.seq > 0 ? entry.seq : 0);
        setRecorded((prev) => ({ ...prev, [entry.seq]: true }));
        await load();
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    },
    [setId, load, onError],
  );

  if (!open) return null;

  return (
    <aside
      aria-label={`Chat about ${tenderName}`}
      className="fixed bottom-0 right-0 z-40 flex h-[min(680px,88vh)] w-[420px] flex-col rounded-tl-cb-card border-l border-t border-cb-border bg-cb-surface shadow-[0_-4px_24px_rgba(12,26,40,.16)]"
    >
      <header className="flex flex-none items-center gap-2 border-b border-cb-border bg-cb-panel px-3 py-2">
        <span className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">
          THIS TENDER
        </span>
        <span className="truncate font-cb-sans text-[11.5px] font-semibold text-cb-ink-text">
          {tenderName}
        </span>
        <button
          type="button"
          onClick={onClose}
          title="Close — the conversation is kept"
          className="cb-press ml-auto font-cb-mono text-[13px] text-cb-muted"
        >
          ✕
        </button>
      </header>

      <p className="flex-none border-b border-cb-divider px-3 py-1.5 font-cb-sans text-[9px] leading-[1.5] text-cb-muted">
        Answers come only from this tender&rsquo;s own ground, and this conversation stays with
        this folder. It can quote a figure the engine computed; it cannot invent one, and the one
        thing it may propose is recording a condition — which you then confirm.
      </p>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {log.length === 0 && !busy && (
          <div className="mt-2">
            <p className="font-cb-sans text-[10.5px] leading-[1.6] text-cb-muted">
              Nothing discussed yet. Start with one of these, or ask anything about this tender:
            </p>
            <div className="mt-2 flex flex-col gap-1.5">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void ask(s)}
                  className="cb-press rounded-cb-btn border border-cb-border bg-cb-page px-2.5 py-1.5 text-left font-cb-sans text-[10.5px] text-cb-body"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {log.map((entry, i) => (
          <div key={`${entry.seq}-${i}`} className="mb-3">
            <div className="flex justify-end">
              <p className="max-w-[86%] rounded-cb-card bg-cb-ink px-2.5 py-1.5 font-cb-sans text-[10.5px] leading-[1.5] text-white">
                {entry.question}
              </p>
            </div>
            <div className="mt-1.5">
              <p className="font-cb-serif text-[11.5px] leading-[1.6] text-cb-ink-text">
                {entry.answer || (
                  <span className="text-cb-muted">{entry.cannot_answer}</span>
                )}
              </p>

              {Object.keys(entry.figures ?? {}).length > 0 && (
                <p className="mt-1 font-cb-mono text-[8.5px] text-cb-brass-text">
                  figures quoted — {Object.keys(entry.figures ?? {}).join(" · ")}
                </p>
              )}
              {(entry.citations?.length ?? 0) > 0 && (
                <p className="mt-0.5 font-cb-sans text-[8.5px] leading-[1.45] text-cb-muted">
                  {entry.citations!.map((c) => (
                    <span key={c.source} className="mr-1.5 font-cb-mono text-cb-brass-text">
                      [{c.source}]
                    </span>
                  ))}
                </p>
              )}
              {(entry.stripped?.length ?? 0) > 0 && (
                <p className="mt-1 font-cb-sans text-[9px] leading-[1.45] text-cb-bad-dark">
                  {entry.stripped!.length} claim(s) were removed for citing nothing that was
                  supplied.
                </p>
              )}

              {entry.became_condition ? (
                <p
                  className={cx(
                    "mt-1 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip",
                    entry.became_status === "rejected" ? "text-cb-bad-dark" : "text-cb-ok-dark",
                  )}
                >
                  {entry.became_status === "rejected"
                    ? `✕ ${entry.became_condition} — recorded, then REJECTED`
                    : `✓ ${entry.became_condition} — on the register`}
                </p>
              ) : (
                entry.proposes && (
                  <div className="mt-1.5 rounded-cb-chip border border-cb-brass-line bg-cb-brass-tint px-2 py-1.5">
                    <p className="font-cb-sans text-[9.5px] leading-[1.45] text-cb-brass-text">
                      Suggests recording: <em>{entry.proposes}</em>
                    </p>
                    {recorded[entry.seq] ? (
                      <p className="mt-1 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-ok-dark">
                        RECORDED — CONFIRM THE MAPPING ON PRICE
                      </p>
                    ) : (
                      <Button className="mt-1.5" onClick={() => void record(entry)}>
                        Record it as a condition
                      </Button>
                    )}
                  </div>
                )
              )}
            </div>
          </div>
        ))}

        {busy && (
          <p className="font-cb-sans text-[10px] text-cb-muted">Reading this tender&rsquo;s ground…</p>
        )}
        {last && last.grounded_in.length > 0 && !busy && (
          <p className="font-cb-mono text-[8px] text-cb-faint">
            last answer grounded in {last.grounded_in.length} source(s)
          </p>
        )}
        <div ref={foot} />
      </div>

      <div className="flex-none border-t border-cb-border p-2">
        <div className="flex items-end gap-2">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void ask(question);
              }
            }}
            rows={2}
            placeholder="Ask about this tender — Enter to send, Shift+Enter for a new line"
            className="min-h-[38px] flex-1 resize-none rounded-cb-btn border border-cb-border bg-cb-warm px-2 py-1.5 font-cb-sans text-[11px] text-cb-ink-text placeholder:text-cb-faint"
          />
          <Button variant="brass" disabled={busy || !question.trim()} onClick={() => void ask(question)}>
            {busy ? "…" : "Ask"}
          </Button>
        </div>
      </div>
    </aside>
  );
}
