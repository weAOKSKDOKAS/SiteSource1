// The Closeout tab — the only feedback edge in the whole workflow. After a tender goes out, this
// is where its outcome is recorded, its lessons captured, its post-submission trail kept, and — if
// we won — a handover package assembled from what already exists.
//
// The rules it holds, the ones the rest of the product lives by:
//   * THE TENDER OUTCOME IS NOT THE SUBLET AWARD. "Did we win the tender from the client" is a
//     tender-level fact; "which subcontractor wins a package" is decided on Sourcing. They are
//     named apart here so no reader confuses them.
//   * OUTCOME NOTES AND LESSONS ARE THE HUMAN'S. There is no model drafting on this screen.
//   * THE HANDOVER IS A PROJECTION, NOT RE-ENTRY. It is assembled from the scope, the register,
//     the estimate and the awards that already exist; anything missing is NAMED, never dropped.

import { useEffect, useState } from "react";
import type { SetData } from "../App";
import { api } from "../api";
import type { BridgeCloseoutState, BridgeHandover } from "../types";
import { Button, Chip, OpenTab, SectionLabel, WaitingOn, cx } from "../ui";

const OUTCOMES: { value: string; label: string; cls: string }[] = [
  { value: "won", label: "Won", cls: "bg-cb-ok-tint text-cb-ok-dark" },
  { value: "lost", label: "Lost", cls: "bg-cb-bad-tint text-cb-bad-dark" },
  { value: "withdrawn", label: "Withdrawn", cls: "bg-cb-panel text-cb-muted" },
];
const LESSON_CATEGORIES = ["pricing", "scope", "programme", "commercial", "other"];
const EVENT_KINDS = ["clarification", "negotiation", "change", "note"];

export function CloseoutTab({
  data,
  onError,
  onRefresh,
}: {
  data: SetData;
  onError: (message: string) => void;
  onRefresh?: () => Promise<void> | void;
}) {
  const state: BridgeCloseoutState | null = data.closeout;
  const submitted = Boolean(data.submission?.submission);
  const outcome = state?.outcome ?? null;

  const [notes, setNotes] = useState("");
  const [lessonCat, setLessonCat] = useState("pricing");
  const [lessonText, setLessonText] = useState("");
  const [eventKind, setEventKind] = useState("clarification");
  const [eventText, setEventText] = useState("");
  const [busy, setBusy] = useState("");
  const [handover, setHandover] = useState<BridgeHandover | null>(null);

  useEffect(() => {
    if (!submitted) return;
    let live = true;
    api.bridge
      .handover(data.setId)
      .then((h) => live && setHandover(h))
      .catch(() => live && setHandover(null));
    return () => {
      live = false;
    };
  }, [data.setId, submitted, outcome?.status]);

  if (!submitted) {
    return (
      <WaitingOn
        title="The closeout waits on submission"
        action={<OpenTab setId={data.setId} tab="offer">Open Offer</OpenTab>}
      >
        There is nothing to close out until the tender has gone out. Approve and submit it on the
        Offer tab, then record here whether we won.
      </WaitingOn>
    );
  }

  const run = async (label: string, fn: () => Promise<unknown>, clear?: () => void) => {
    setBusy(label);
    try {
      await fn();
      clear?.();
      await onRefresh?.();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const downloadHandover = () => {
    if (!handover) return;
    const blob = new Blob([handover.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `handover-${data.setId}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[760px] flex-col gap-4 p-[18px]">
          {/* --- Outcome: did WE win the tender (not the sublet award) --- */}
          <section className="rounded-cb-card border border-cb-border bg-cb-page p-[14px]">
            <div className="flex flex-wrap items-center gap-2">
              <SectionLabel>TENDER OUTCOME</SectionLabel>
              {outcome && outcome.status !== "submitted" ? (
                <Chip
                  className={cx(
                    "font-cb-mono text-[10px]",
                    OUTCOMES.find((o) => o.value === outcome.status)?.cls ?? "bg-cb-panel text-cb-muted",
                  )}
                >
                  {outcome.status.toUpperCase()}
                </Chip>
              ) : (
                <Chip className="bg-cb-panel text-cb-muted font-cb-mono text-[10px]">AWAITING OUTCOME</Chip>
              )}
            </div>
            <p className="mt-1 font-cb-sans text-[10.5px] text-cb-muted">
              Did we win the tender from the client? This is the tender-level outcome — not a sublet
              award, which is decided per package on Sourcing.
            </p>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Award value, competitor, why we won or lost (your words)"
              rows={2}
              className="mt-2 w-full rounded-cb-btn border border-cb-border-strong bg-white px-2.5 py-1.5 text-[11px] leading-relaxed text-cb-ink-text"
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {OUTCOMES.map((o) => (
                <Button
                  key={o.value}
                  variant={o.value === "won" ? "brass" : "outline"}
                  disabled={busy !== ""}
                  onClick={() =>
                    void run(`outcome-${o.value}`, () =>
                      api.bridge.setOutcome(data.setId, o.value, notes.trim()),
                    () => setNotes(""))
                  }
                >
                  {busy === `outcome-${o.value}` ? "Recording…" : `Mark ${o.label}`}
                </Button>
              ))}
            </div>
            {outcome && outcome.status !== "submitted" && (
              <p className="mt-2 font-cb-sans text-[10px] text-cb-faint">
                Recorded {outcome.decided_at} by {outcome.decided_by}
                {outcome.outcome_notes ? ` — ${outcome.outcome_notes}` : ""}.
                {(outcome.status === "won" || outcome.status === "lost") &&
                  " Fed into the benchmark corpus for future tenders."}
              </p>
            )}
          </section>

          {/* --- Lessons learned (human-authored) --- */}
          <section className="rounded-cb-card border border-cb-border bg-cb-page p-[14px]">
            <SectionLabel>LESSONS LEARNED</SectionLabel>
            <div className="mt-2 flex flex-wrap items-start gap-2">
              <select
                value={lessonCat}
                onChange={(e) => setLessonCat(e.target.value)}
                className="rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1.5 font-cb-sans text-[11px] text-cb-ink-text"
              >
                {LESSON_CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <input
                value={lessonText}
                onChange={(e) => setLessonText(e.target.value)}
                placeholder="A lesson for the next tender (your words)"
                className="min-w-[200px] flex-1 rounded-cb-btn border border-cb-border-strong bg-white px-2.5 py-1.5 text-[11px] text-cb-ink-text"
              />
              <Button
                variant="outline"
                disabled={busy !== "" || !lessonText.trim()}
                onClick={() =>
                  void run("lesson", () =>
                    api.bridge.addLesson(data.setId, lessonCat, lessonText.trim()),
                  () => setLessonText(""))
                }
              >
                Add
              </Button>
            </div>
            {state?.lessons.length ? (
              <ul className="mt-2 flex flex-col gap-1">
                {state.lessons.map((l) => (
                  <li key={l.id} className="flex gap-2 font-cb-sans text-[11px] leading-[1.5]">
                    <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-brass-text">
                      {l.category.toUpperCase()}
                    </span>
                    <span className="text-cb-body">{l.lesson}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 font-cb-sans text-[10.5px] text-cb-muted">No lessons recorded yet.</p>
            )}
          </section>

          {/* --- Post-submission change-control log (light) --- */}
          <section className="rounded-cb-card border border-cb-border bg-cb-page p-[14px]">
            <SectionLabel>POST-SUBMISSION CHANGE-CONTROL</SectionLabel>
            <p className="mt-1 font-cb-sans text-[10px] text-cb-muted">
              A trail of clarifications and negotiation after submission. If a price or bill changed,
              state it here — this log records the fact, it does not re-price.
            </p>
            <div className="mt-2 flex flex-wrap items-start gap-2">
              <select
                value={eventKind}
                onChange={(e) => setEventKind(e.target.value)}
                className="rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1.5 font-cb-sans text-[11px] text-cb-ink-text"
              >
                {EVENT_KINDS.map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
              <input
                value={eventText}
                onChange={(e) => setEventText(e.target.value)}
                placeholder="What was asked, negotiated or changed"
                className="min-w-[200px] flex-1 rounded-cb-btn border border-cb-border-strong bg-white px-2.5 py-1.5 text-[11px] text-cb-ink-text"
              />
              <Button
                variant="outline"
                disabled={busy !== "" || !eventText.trim()}
                onClick={() =>
                  void run("event", () =>
                    api.bridge.logEvent(data.setId, eventKind, eventText.trim()),
                  () => setEventText(""))
                }
              >
                Log
              </Button>
            </div>
            {state?.events.length ? (
              <ul className="mt-2 flex flex-col gap-1">
                {state.events.map((ev) => (
                  <li key={ev.id} className="flex gap-2 font-cb-sans text-[11px] leading-[1.5]">
                    <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-navy">
                      {ev.kind.toUpperCase()}
                    </span>
                    <span className="text-cb-body">{ev.detail}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 font-cb-sans text-[10.5px] text-cb-muted">No entries yet.</p>
            )}
          </section>

          {/* --- Handover: assembled once won, a preview before --- */}
          <section
            className={cx(
              "rounded-cb-card border p-[14px]",
              handover?.ready ? "border-cb-ok bg-cb-ok-tint/40" : "border-cb-brass-line bg-cb-warm",
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <SectionLabel>HANDOVER PACKAGE</SectionLabel>
              {handover?.ready ? (
                <Chip className="bg-cb-ok-tint text-cb-ok-dark font-cb-mono text-[10px]">READY</Chip>
              ) : (
                <Chip className="bg-cb-panel text-cb-muted font-cb-mono text-[10px]">PREVIEW</Chip>
              )}
            </div>
            {handover?.pending && (
              <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text">
                {handover.pending}
              </p>
            )}
            {handover?.missing?.length ? (
              <div className="mt-2">
                <div className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-bad-dark">
                  NOT YET AVAILABLE
                </div>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {handover.missing.map((m, i) => (
                    <li key={i} className="font-cb-sans text-[10.5px] text-cb-body">— {m}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {handover && (
              <>
                <pre className="mt-3 max-h-[280px] overflow-auto whitespace-pre-wrap rounded-cb-card border border-cb-border bg-cb-page p-3 font-cb-mono text-[10px] leading-[1.55] text-cb-ink-text">
                  {handover.markdown}
                </pre>
                <div className="mt-2">
                  <Button variant="dark" disabled={!handover.ready} onClick={downloadHandover}>
                    Download handover (.md)
                  </Button>
                  {!handover.ready && (
                    <span className="ml-2 font-cb-sans text-[10px] text-cb-muted">
                      Mark the tender Won to enable the download.
                    </span>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
