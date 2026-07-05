import { useState } from "react";
import type { Candidate, Coverage, ShortlistSet } from "../types";
import { FirmRecord, Pill, RiskFlagList, StepHeading, StepNav } from "../components";
import { Card, Collapse, Drawer, MatchChip, cx } from "../ui";
import { tradeLabel } from "../format";

export function StepShortlist({
  shortlist,
  heroTrade,
  coverage,
  onBack,
  onNext,
  loading,
}: {
  shortlist: ShortlistSet;
  heroTrade: string;
  coverage: Coverage | null;
  onBack: () => void;
  onNext: () => void;
  loading: boolean;
}) {
  // Hero trade stays expanded; the rest collapse so the hero reads on a projector.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [detail, setDetail] = useState<Candidate | null>(null);
  const [focusTrade, setFocusTrade] = useState(""); // "" = show every trade
  const trades = Object.keys(shortlist.per_trade).sort((a, b) =>
    a === heroTrade ? -1 : b === heroTrade ? 1 : a.localeCompare(b),
  );
  const shownTrades = focusTrade ? trades.filter((t) => t === focusTrade) : trades;

  return (
    <div className="space-y-6">
      <StepHeading
        title="Shortlist per trade"
        lead="For each trade the database returns firms scored by how well their closeout history matches the scope, each with cited evidence and risk flags. The ranking is deterministic — a firm with a fatal flag is demoted below every clean firm regardless of price or match. This is data a generic chatbot cannot reach."
      />

      {coverage && (
        <div className="rounded-lg border border-brand/20 bg-brand-bg/50 px-4 py-2.5 text-sm text-ink">
          Screening against <span className="tabular font-semibold">{coverage.total_firms.toLocaleString("en-HK")}</span> firms
          sourced from official Hong Kong registers —{" "}
          <span className="tabular font-semibold">{coverage.flagged_firms.toLocaleString("en-HK")}</span> carry verified
          public risk flags, each linked to its government source. Only firms with an assessable closeout record are shortlisted below.
        </div>
      )}

      {trades.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ink-soft">Focus a trade:</span>
          <select
            value={focusTrade}
            onChange={(e) => setFocusTrade(e.target.value)}
            className="rounded-lg border border-line px-2 py-1.5 text-sm text-ink-soft focus:border-brand focus:outline-none"
          >
            <option value="">All trades ({trades.length})</option>
            {trades.map((t) => (
              <option key={t} value={t}>{tradeLabel(t)}{t === heroTrade ? " — watch this" : ""}</option>
            ))}
          </select>
        </div>
      )}

      {shownTrades.map((trade) => {
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
                  <CandidateRow key={c.firm.firm_id} candidate={c} rank={i + 1} top={i === 0} onOpen={() => setDetail(c)} />
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

      <FirmDrawer candidate={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

function CandidateRow({ candidate, rank, top, onOpen }: { candidate: Candidate; rank: number; top: boolean; onOpen: () => void }) {
  const { firm } = candidate;
  const against = candidate.recommended_against;
  const fatal = candidate.risk_flags.filter((f) => f.severity === "fatal");
  const warnings = candidate.risk_flags.filter((f) => f.severity !== "fatal");

  return (
    <li className={cx("px-4 py-3 transition-colors", against ? "bg-bad-bg/40" : "hover:bg-paper-soft/70")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="tabular flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line text-xs font-semibold text-ink-soft">
          {rank}
        </span>
        <button
          type="button"
          onClick={onOpen}
          title="Open the firm record"
          className="text-sm font-semibold text-ink hover:text-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright"
        >
          {firm.name}
        </button>
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
          <p className="mb-2 text-xs font-semibold uppercase tracking-eyebrow text-bad">
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

// The firm record drawer — the full fused profile already delivered with the shortlist
// (no extra fetch): registration, trades, closeout record, adjudicated flags with their
// cited evidence, and award history.
function FirmDrawer({ candidate, onClose }: { candidate: Candidate | null; onClose: () => void }) {
  const firm = candidate?.firm;
  return (
    <Drawer
      open={candidate != null}
      onClose={onClose}
      eyebrow="Firm record"
      tone={candidate?.recommended_against ? "bad" : "violet"}
      title={firm?.name ?? ""}
      subtitle={
        firm && (
          <span className="flex flex-wrap items-center gap-2">
            <MatchChip score={candidate.match_score} />
            {candidate.recommended_against && <Pill tone="bad">⛔ Recommend against</Pill>}
          </span>
        )
      }
      footer="SiteSource asserts nothing without a record — every flag above carries its issuing source and reference."
    >
      {candidate && firm && (
        // The per-scope adjudicated risk_flags drive the "Risk flags" section here; the raw
        // public_flags are the browse view. Scope evidence is candidate-specific.
        <FirmRecord firm={firm} flags={candidate.risk_flags} flagsLabel="Risk flags">
          <Collapse title="Scope evidence" count={candidate.evidence.length}>
            {candidate.evidence.length > 0 ? (
              <ul className="space-y-2">
                {candidate.evidence.map((e, i) => (
                  <li key={i} className="text-xs leading-relaxed text-ink-soft">
                    <span className="font-semibold text-ink">{e.source}</span>
                    <span className="tabular text-ink-faint"> · {e.reference}</span>
                    <div>{e.snippet}</div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-ink-faint">No matched closeout evidence.</p>
            )}
          </Collapse>
        </FirmRecord>
      )}
    </Drawer>
  );
}
