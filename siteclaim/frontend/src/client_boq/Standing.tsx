// WHERE THIS TENDER STANDS — computed from what is already loaded, with no model call at all.
//
// THE PROBLEM IT FIXES. Opening a tender landed you on Documents: for a real 206-part binder that
// is a wall of parts beside a column of page-render errors, and it tells you nothing about where
// the job is. The screen that was MEANT to tell you — the Brain — said "No briefing yet" until you
// spent an hour running a review, and then reported "0 findings · it proposed nothing" if the
// tender had not been read yet. So the one screen whose job is orientation was the one screen that
// could not orient you.
//
// THE SPLIT THIS RESTORES. The app knows a great deal about a tender the instant a binder lands:
// how many parts, which gates are shut, whether a bill is in, how many register lines still want a
// verdict. None of that needs a model — it is state, and it is already in `SetData` because the
// shell loads it for the step chips. What a MODEL adds is reading and judgement on top: what the
// terms mean, where two documents disagree, which of several open things matters most.
//
// So this board is the floor and the briefing is the ceiling. The floor is always there, instant,
// and free. That ordering is the same rule the rest of the product runs on — a measurement
// outranks a model proposal — applied to the screen that had it backwards.
//
// ABSENCE IS NAMED. A read that FAILED is not the same as a step that has not run, and both are
// different from a step with nothing in it. `data.failures` carries the first; this says so rather
// than reporting a confident zero about something nobody could load.

import type { SetData } from "./App";
import type { TabId } from "./chrome";
import { nextFor } from "./next";
import { SectionLabel, cx } from "./ui";

type Tone = "done" | "open" | "waiting" | "unknown";

interface Row {
  label: string;
  tone: Tone;
  detail: string;
  tab: TabId;
}

const TONE_MARK: Record<Tone, string> = {
  done: "✓",
  open: "●",
  waiting: "·",
  unknown: "?",
};

const TONE_CLS: Record<Tone, string> = {
  done: "text-cb-ok-dark",
  open: "text-cb-brass-text",
  waiting: "text-cb-muted",
  unknown: "text-cb-bad-dark",
};

/** One plain sentence for the top of the screen. Deliberately about the STAGE rather than a
 *  count — "where am I" is the question somebody opening a tender is actually asking. */
function headline(data: SetData): string {
  if (!data.gates.manifest) return "The binder is in and split. Nobody has approved the split yet.";
  if (!data.parts?.count) return "The split is approved, but no part came out of it.";
  if (!data.register) return "The parts are cut. The contract has not been reviewed yet.";
  if (!data.gates.review) return "The review has run. Its register still wants your verdicts.";
  if (!data.hasBill) return "The register is approved. No bill of quantities has been imported yet.";
  if (!data.gates.scope) return "The bill is in and pricing. The scope is not approved yet.";
  if (Boolean(data.submission?.submission)) return "Submitted. What remains is the outcome.";
  return "Everything upstream is approved. This tender is at the price.";
}

/** The gates and the stock, as facts. Every row names the screen that owns it. */
function rows(data: SetData): Row[] {
  const failed = (key: string) => data.failures[key];
  const partCount = data.parts?.count ?? 0;
  const unreadable = data.parts?.unreadable ?? 0;
  const statuses = data.register?.status_counts ?? {};
  const decided = (statuses.confirmed ?? 0) + (statuses.dismissed ?? 0);
  const undecided = statuses.proposed ?? 0;

  const out: Row[] = [];

  out.push({
    label: "The binder",
    tone: data.gates.manifest ? "done" : "open",
    tab: "documents",
    detail: failed("parts")
      ? `the parts could not be read (${failed("parts")}) — this is a gap in the read, not an empty tender`
      : data.gates.manifest
        ? `${partCount} part(s) cut and the split approved` +
          (unreadable ? ` · ${unreadable} could not be read` : "")
        : "the split is proposed and waiting for somebody to approve it",
  });

  out.push({
    label: "The review",
    tone: failed("register") ? "unknown" : !data.register ? "waiting"
      : data.gates.review ? "done" : "open",
    tab: "register",
    detail: failed("register")
      ? `the register could not be read (${failed("register")})`
      : !data.register
        ? "has not run — the contract has not been read against your positions"
        : data.gates.review
          ? `approved · ${decided} decided`
          : `${undecided} line(s) still want a verdict, ${decided} decided`,
  });

  out.push({
    label: "The bid decision",
    tone: data.bidVerdict ? "done" : data.register ? "open" : "waiting",
    tab: "bid",
    detail: data.bidVerdict
      ? `recorded: ${data.bidVerdict}`
      : data.register
        ? "not recorded — the terms are read, so this is the first real decision"
        : "waits on the review, because deciding before reading the terms is guessing",
  });

  out.push({
    label: "The scope",
    tone: data.gates.scope ? "done" : data.scope ? "open" : "waiting",
    tab: "scope",
    detail: data.gates.scope
      ? "approved"
      : data.scope
        ? "drafted and waiting for approval"
        : "not drafted yet",
  });

  out.push({
    label: "The price",
    tone: data.hasBill ? "open" : "waiting",
    tab: "price",
    detail: data.hasBill
      ? "the client's bill is imported and the engine is pricing from it"
      : "no bill of quantities imported — the engine prices the client's own bill",
  });

  out.push({
    label: "The offer",
    tone: Boolean(data.submission?.submission) ? "done" : data.hasBill ? "waiting" : "waiting",
    tab: "offer",
    detail: Boolean(data.submission?.submission)
      ? "submitted"
      : Boolean(data.submission?.approval)
        ? "approved and not yet submitted"
        : "waits on a price to put in it",
  });

  return out;
}

export function Standing({
  data,
  onGo,
}: {
  data: SetData;
  /** Navigation only — every row points at the screen that owns the act, and the act stays
   *  there. This board reports; it decides nothing, exactly like the briefing under it. */
  onGo: (tab: TabId) => void;
}) {
  const next = nextFor(data);
  const board = rows(data);

  return (
    <section className="flex flex-col gap-4">
      <p className="max-w-[62ch] font-cb-serif text-[17px] leading-[1.45] text-cb-ink-text">
        {headline(data)}
      </p>

      {/* THE ONE NEXT THING. The shell already computes this for the strip's NEXT line; showing
          it here as an action is the difference between a status page and a place to start. */}
      <div className="flex flex-wrap items-center gap-3 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-4 py-3">
        <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-brass-text">
          DO THIS NEXT
        </span>
        <span className="min-w-0 flex-1 font-cb-sans text-[12px] leading-[1.5] text-cb-body">
          {next.sentence}
        </span>
        {next.tab && next.go && (
          <button
            type="button"
            onClick={() => onGo(next.tab as TabId)}
            className="cb-press flex-none rounded-cb-btn bg-cb-ink px-3 py-1.5 font-cb-sans text-[11px] font-semibold text-cb-surface"
          >
            {next.go} →
          </button>
        )}
      </div>

      <div>
        <SectionLabel>WHERE IT STANDS — NO MODEL INVOLVED, THIS IS JUST THE STATE</SectionLabel>
        <div className="mt-2 overflow-hidden rounded-cb-card border border-cb-border">
          {board.map((row, i) => (
            <button
              key={row.label}
              type="button"
              onClick={() => onGo(row.tab)}
              className={cx(
                "cb-row flex w-full items-baseline gap-3 px-3 py-2.5 text-left",
                i > 0 && "border-t border-cb-divider",
              )}
            >
              <span
                aria-hidden
                className={cx("w-[12px] flex-none font-cb-mono text-[11px]", TONE_CLS[row.tone])}
              >
                {TONE_MARK[row.tone]}
              </span>
              <span className="w-[112px] flex-none font-cb-sans text-[12px] font-semibold text-cb-ink-text">
                {row.label}
              </span>
              <span className="min-w-0 flex-1 font-cb-sans text-[11.5px] leading-[1.5] text-cb-muted">
                {row.detail}
              </span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
