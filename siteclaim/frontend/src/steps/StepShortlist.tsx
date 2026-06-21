import { useState } from "react";
import type { Candidate, ShortlistSet } from "../types";
import { Pill, RiskFlagList, StepHeading, StepNav } from "../components";
import { Card, MatchChip, cx } from "../ui";
import { tradeLabel } from "../format";

export function StepShortlist({
  shortlist,
  heroTrade,
  onBack,
  onNext,
  loading,
}: {
  shortlist: ShortlistSet;
  heroTrade: string;
  onBack: () => void;
  onNext: () => void;
  loading: boolean;
}) {
  // Hero trade stays expanded; the rest collapse so the hero reads on a projector.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const trades = Object.keys(shortlist.per_trade).sort((a, b) =>
    a === heroTrade ? -1 : b === heroTrade ? 1 : a.localeCompare(b),
  );

  return (
    <div className="space-y-6">
      <StepHeading
        title="Shortlist per trade"
        lead="For each trade the database returns firms scored by how well their closeout history matches the scope, each with cited evidence and risk flags. The ranking is deterministic — a firm with a fatal flag is demoted below every clean firm regardless of price or match. This is data a generic chatbot cannot reach."
      />

      {trades.map((trade) => {
        const candidates = shortlist.per_trade[trade];
        const isHero = trade === heroTrade;
        const open = isHero || !!expanded[trade];
        const flagged = candidates.filter((c) => c.recommended_against).length;
        return (
          <Card key={trade} className={cx("overflow-hidden", isHero && "ring-2 ring-brand/30")}>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-soft px-4 py-2.5">
              <h2 className="text-sm font-semibold text-ink">
                {tradeLabel(trade)}
                {isHero && <span className="ml-2 text-xs font-normal text-brand">— watch this trade</span>}
              </h2>
              <div className="flex items-center gap-2">
                {flagged > 0 && <Pill tone="bad">{flagged} flagged</Pill>}
                <Pill>{candidates.length} firms</Pill>
                {!isHero && (
                  <button
                    type="button"
                    onClick={() => setExpanded((e) => ({ ...e, [trade]: !e[trade] }))}
                    className="text-xs font-semibold text-brand hover:underline"
                  >
                    {open ? "Hide" : "Show"}
                  </button>
                )}
              </div>
            </div>
            {open ? (
              <ol className="divide-y divide-line-soft">
                {candidates.map((c, i) => (
                  <CandidateRow key={c.firm.firm_id} candidate={c} rank={i + 1} top={i === 0} />
                ))}
              </ol>
            ) : (
              <div className="px-4 py-2.5 text-xs text-ink-soft">
                Top pick: <span className="font-semibold text-ink">{candidates[0]?.firm.name}</span>
              </div>
            )}
          </Card>
        );
      })}

      <StepNav onBack={onBack} onNext={onNext} nextLabel="Dispatch enquiries →" loading={loading} />
    </div>
  );
}

function CandidateRow({ candidate, rank, top }: { candidate: Candidate; rank: number; top: boolean }) {
  const { firm } = candidate;
  const against = candidate.recommended_against;
  const fatal = candidate.risk_flags.filter((f) => f.severity === "fatal");
  const warnings = candidate.risk_flags.filter((f) => f.severity !== "fatal");

  return (
    <li className={cx("px-4 py-3", against && "bg-bad-bg/40")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="tabular flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line text-xs font-semibold text-ink-soft">
          {rank}
        </span>
        <span className="text-sm font-semibold text-ink">{firm.name}</span>
        <span className="tabular text-xs text-ink-faint">{firm.firm_id}</span>
        <MatchChip score={candidate.match_score} />
        {top && !against && <Pill tone="ok">Top pick</Pill>}
        {against && <Pill tone="bad">⛔ Recommend against</Pill>}
        <span className="ml-auto text-xs text-ink-faint">
          {firm.registered_grade} · {firm.value_band.replace(/_/g, " ")}
        </span>
      </div>

      {firm.closeout_summary && <p className="mt-1.5 text-xs text-ink-soft">{firm.closeout_summary}</p>}

      {against && (
        <div className="mt-2 rounded-lg border border-bad/40 bg-card p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-bad">
            Disqualifying — do not award regardless of price
          </p>
          <RiskFlagList flags={fatal} />
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mt-2">
          <RiskFlagList flags={warnings} />
        </div>
      )}
    </li>
  );
}
