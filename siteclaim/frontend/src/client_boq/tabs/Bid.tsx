// The Bid tab — the tender's first real decision, and the one the system used to assume.
//
// It sits after Register and before Scope because that is where the decision actually falls: read
// the pack, review the terms, then decide whether to pursue it. Everything downstream — route,
// sourcing, costing, offer, submission — began on the assumption that this decision had been made.
// Nothing recorded it.
//
// THE AUTHORSHIP MODEL, rendered as three separate blocks so a reader can see whose each is:
//
//   SIGNALS (navy)         hard reads of artifacts that already exist. Each names its source, and
//                          each says "unknown" where it cannot be read honestly. A failed check —
//                          the review not approved — is red.
//   RECOMMENDATION (brass) a deterministic rule over those signals, with the reasons that drove
//                          it. Plainly a suggestion, and freely overridable.
//   YOUR JUDGEMENT         fit, capacity, win probability, notes. The machine never fills these,
//                          and there is no field on this screen it could fill — they are typed,
//                          they are stored verbatim, and the placeholder text says so.
//   THE VERDICT            bid / no-bid / clarify, with a rationale required for the last two.
//
// The rule can only propose `bid` or `clarify`. A PERSON can record `no_bid`, and when they do,
// both stay on screen: the machine's proposal and the human's decision, side by side, because the
// interesting case is the one where they disagree.

import { useCallback, useEffect, useState } from "react";
import type { SetData } from "../App";
import { api } from "../api";
import type { BidBrief } from "../types";
import { Button, Card, Consequence, SectionLabel, WaitingOn, cx } from "../ui";

const VERDICTS: { value: string; label: string; needsWhy: boolean; cls: string }[] = [
  { value: "bid", label: "Bid", needsWhy: false, cls: "bg-cb-ok-tint text-cb-ok-dark" },
  { value: "no_bid", label: "No bid", needsWhy: true, cls: "bg-cb-bad-tint text-cb-bad-dark" },
  { value: "clarify", label: "Clarify first", needsWhy: true,
    cls: "bg-cb-brass-tint text-cb-brass-text" },
];

// The operator's own fields. Declared here rather than free-form so the four questions worth
// asking are always asked — and every one of them is theirs to answer. `unknown` is a perfectly
// good answer and the placeholder says so, because the alternative is somebody typing a number
// they do not have to fill a box that looks like it wants one.
const FACTORS: { key: string; label: string; placeholder: string }[] = [
  { key: "fit", label: "Strategic fit",
    placeholder: "why this job suits us, or does not — your words" },
  { key: "capacity", label: "Capacity",
    placeholder: "rigs and people free in that window — or \"unknown\"" },
  { key: "win_probability", label: "Win probability",
    placeholder: "your read. Leave \"unknown\" rather than guessing a number" },
  { key: "notes", label: "Notes", placeholder: "anything else that bears on pursuing this" },
];

export function BidTab({
  data,
  onError,
  onRefresh,
}: {
  data: SetData;
  onError: (message: string) => void;
  onRefresh?: () => Promise<void> | void;
}) {
  const [brief, setBrief] = useState<BidBrief | null>(null);
  const [verdict, setVerdict] = useState("");
  const [rationale, setRationale] = useState("");
  const [factors, setFactors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const fresh = await api.bridge.bid(data.setId);
      setBrief(fresh);
      if (fresh.decision) {
        setVerdict(fresh.decision.verdict);
        setRationale(fresh.decision.rationale);
        setFactors(fresh.decision.factors ?? {});
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [data.setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!brief) {
    return <WaitingOn title="Reading the tender…">Assembling the signals behind this decision.</WaitingOn>;
  }

  const { signals, recommendation, decision } = brief;
  const chosen = VERDICTS.find((v) => v.value === verdict);
  const needsWhy = Boolean(chosen?.needsWhy);
  const canRecord = Boolean(verdict) && (!needsWhy || rationale.trim().length > 0);
  const overridden = Boolean(decision) && decision!.verdict !== recommendation.verdict;

  const record = async () => {
    setBusy(true);
    try {
      await api.bridge.confirmBid(data.setId, verdict, rationale, factors);
      await load();
      await onRefresh?.();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[980px] p-[18px]">
        <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">
          Bid or no bid
        </h1>
        <p className="mt-1 max-w-[700px] font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          The first decision on this tender, and the one everything after it assumes. The signals
          below are read from what has already been done; the suggestion is a rule over them.
          The decision is yours.
        </p>

        {/* ---- navy: what is actually known ---- */}
        <section className="mt-5">
          <SectionLabel>THE SIGNALS</SectionLabel>
          <div className="mt-2 grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(230px,1fr))]">
            <Signal
              label="Deadline"
              value={
                signals.deadline.days_remaining === "unknown"
                  ? "unknown"
                  : `${signals.deadline.days_remaining} days`
              }
              detail={
                signals.deadline.days_remaining === "unknown"
                  ? signals.deadline.why_unknown ?? ""
                  : signals.deadline.close_date
              }
              source={signals.deadline.source}
              unknown={signals.deadline.days_remaining === "unknown"}
            />
            <Signal
              label="Open clarifications"
              value={String(signals.open_clarifications.count)}
              detail="still with the client"
              source={signals.open_clarifications.source}
              warn={signals.open_clarifications.count > 0}
            />
            <Signal
              label="Review approved"
              value={signals.review_approved.value ? "yes" : "no"}
              detail={
                signals.review_approved.value
                  ? "the terms have been read and signed off"
                  : "nobody has signed off the contract terms"
              }
              source={signals.review_approved.source}
              bad={!signals.review_approved.value}
            />
            {/* "0 of 0" in the ordinary tone is what a register that WAS read and came out clean
                looks like. With no register nothing is known about the pack's departures at all,
                and on the screen where bid or no-bid is decided those two must not look alike. */}
            <Signal
              label="Departures"
              value={
                signals.departures.total === "unknown"
                  ? "unknown"
                  : `${signals.departures.unresolved} of ${signals.departures.total}`
              }
              detail={
                signals.departures.total === "unknown"
                  ? signals.departures.why_unknown ?? ""
                  : "unresolved on the register"
              }
              source={signals.departures.source}
              unknown={signals.departures.total === "unknown"}
              warn={
                signals.departures.unresolved !== "unknown" && signals.departures.unresolved > 0
              }
            />
            <Signal
              label="Scope gaps"
              value={signals.scope_gaps.gaps === "unknown" ? "unknown" : String(signals.scope_gaps.gaps)}
              detail={
                signals.scope_gaps.gaps === "unknown"
                  ? signals.scope_gaps.why_unknown ?? ""
                  : `${signals.scope_gaps.inputs_missing} input(s) the contract did not give us`
              }
              source={signals.scope_gaps.source}
              unknown={signals.scope_gaps.gaps === "unknown"}
              warn={signals.scope_gaps.gaps !== "unknown" && signals.scope_gaps.gaps > 0}
            />
            <Signal
              label="Coverage readiness"
              value={
                signals.coverage.bills_without_list === "unknown"
                  ? "unknown"
                  : `${signals.coverage.bills_without_list.length} bill(s) without a list`
              }
              detail={
                signals.coverage.bills_without_list === "unknown"
                  ? signals.coverage.why_unknown ?? ""
                  : signals.coverage.bills_without_list.length
                    ? `Bill ${signals.coverage.bills_without_list.join(", ")} — rates here cannot be checked for completeness`
                    : "every bill has an item-coverage list"
              }
              source={signals.coverage.source}
              unknown={signals.coverage.bills_without_list === "unknown"}
              warn={
                signals.coverage.bills_without_list !== "unknown" &&
                signals.coverage.bills_without_list.length > 0
              }
            />
          </div>
        </section>

        {/* ---- brass: the machine's proposal, with its evidence ---- */}
        <section className="mt-6">
          <SectionLabel>THE SUGGESTION</SectionLabel>
          <Card className="mt-2 border-l-[3px] border-l-cb-brass">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="rounded-cb-chip bg-cb-brass-tint px-2 py-[2px] font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-brass-text">
                {recommendation.verdict === "bid" ? "BID" : "CLARIFY FIRST"}
              </span>
              <span className="font-cb-sans text-[10px] text-cb-faint">
                a rule over the signals above — not a finding, and yours to overrule
              </span>
            </div>
            <ul className="mt-2 space-y-0.5">
              {recommendation.reasons.map((reason) => (
                <li key={reason} className="font-cb-sans text-[11px] leading-[1.5] text-cb-body">
                  · {reason}
                </li>
              ))}
            </ul>
            <p className="mt-2 font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
              {recommendation.basis}
            </p>
          </Card>
        </section>

        {/* ---- the human's own judgement — the machine never fills these ---- */}
        <section className="mt-6">
          <SectionLabel>YOUR JUDGEMENT</SectionLabel>
          <p className="mt-1 max-w-[700px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            These are yours. Nothing computes fit, capacity or a win probability — there is no
            basis in this data for any of them, and a number that looked like one would be
            believed. Leave a box saying <span className="font-cb-mono text-[10px]">unknown</span>{" "}
            rather than filling it.
          </p>
          <div className="mt-2 grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(300px,1fr))]">
            {FACTORS.map((factor) => (
              <label key={factor.key} className="block">
                <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-faint">
                  {factor.label.toUpperCase()}
                </span>
                <input
                  value={factors[factor.key] ?? ""}
                  onChange={(e) => setFactors({ ...factors, [factor.key]: e.target.value })}
                  placeholder={factor.placeholder}
                  className="mt-0.5 w-full rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[11px] text-cb-ink-text placeholder:text-cb-faint"
                />
              </label>
            ))}
          </div>
        </section>

        {/* ---- the verdict ---- */}
        <section className="mt-6">
          <SectionLabel>THE DECISION</SectionLabel>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {VERDICTS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setVerdict(option.value)}
                className={cx(
                  "cb-press rounded-cb-btn border px-3 py-1.5 font-cb-sans text-[11px] font-medium",
                  verdict === option.value
                    ? `border-cb-brass ${option.cls}`
                    : "border-cb-border bg-white text-cb-muted",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>

          {verdict && (
            <div className="mt-2.5">
              <textarea
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                rows={2}
                placeholder={
                  needsWhy
                    ? "Why — required. Somebody will be asked about this decision months from now."
                    : "Anything worth recording (optional for a bid)."
                }
                className={cx(
                  "w-full rounded-cb-btn border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[11.5px] leading-[1.5] text-cb-ink-text placeholder:text-cb-faint",
                  needsWhy && !rationale.trim() ? "border-cb-bad" : "border-cb-border",
                )}
              />
              <div className="mt-2 flex flex-wrap items-center gap-4">
                <Button variant="brass" onClick={() => void record()} disabled={!canRecord || busy}>
                  {busy ? "Recording…" : decision ? "Change the decision" : "Record the decision"}
                </Button>
                <Consequence>
                  {verdict === "bid"
                    ? "Route and Sourcing proceed without a warning once this is recorded."
                    : "Route and Sourcing will warn that they are running against this decision — and refuse outright where the bid gate is set to hard."}{" "}
                  Re-deciding later replaces the verdict; the rule's own suggestion stays visible
                  beside whatever is decided.
                </Consequence>
              </div>
            </div>
          )}

          {decision && (
            <Card className="mt-3">
              <div className="flex flex-wrap items-baseline gap-2">
                <span
                  className={cx(
                    "rounded-cb-chip px-2 py-[2px] font-cb-mono text-[10px] font-semibold tracking-cb-chip",
                    VERDICTS.find((v) => v.value === decision.verdict)?.cls ?? "",
                  )}
                >
                  {VERDICTS.find((v) => v.value === decision.verdict)?.label.toUpperCase() ??
                    decision.verdict}
                </span>
                <span className="font-cb-mono text-[10px] text-cb-faint">
                  {decision.decided_by} · {decision.decided_at?.slice(0, 16).replace("T", " ")}
                </span>
                {overridden && (
                  <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-brass-text">
                    OVERRULES THE SUGGESTION
                  </span>
                )}
              </div>
              {decision.rationale && (
                <p className="mt-1 font-cb-serif text-[12px] leading-[1.5] text-cb-ink-text">
                  {decision.rationale}
                </p>
              )}
            </Card>
          )}
        </section>
      </div>
    </div>
  );
}

/** One hard signal: the number, what it means, and where it was read from.
 *
 *  `unknown` is styled as a fact rather than a fault — a close date nobody confirmed is not a
 *  failure, it is a thing we do not know, and dressing it in red would push somebody to invent
 *  one. A failed CHECK (the review not approved) is red, because that one is actionable. */
function Signal({
  label,
  value,
  detail,
  source,
  warn,
  bad,
  unknown,
}: {
  label: string;
  value: string;
  detail: string;
  source: string;
  warn?: boolean;
  bad?: boolean;
  unknown?: boolean;
}) {
  return (
    <div
      className={cx(
        "rounded-cb-card border bg-cb-page px-3 py-2",
        bad ? "border-cb-bad" : warn ? "border-cb-brass-line" : "border-cb-border",
      )}
    >
      <div className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-faint">
        {label.toUpperCase()}
      </div>
      <div
        className={cx(
          "mt-0.5 font-cb-mono text-[15px] font-semibold",
          bad ? "text-cb-bad-dark" : unknown ? "text-cb-muted" : "text-cb-ink-text",
        )}
      >
        {value}
      </div>
      {detail && (
        <div className="mt-0.5 font-cb-sans text-[10px] leading-[1.4] text-cb-muted">{detail}</div>
      )}
      <div className="mt-1 font-cb-mono text-[10px] leading-[1.35] text-cb-faint">{source}</div>
    </div>
  );
}
