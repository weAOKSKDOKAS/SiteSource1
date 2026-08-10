// Sourcing step 4 — the recommendation and the award. Ported from StepRecommend, restyled.
//
// The distinction this screen exists to hold, and which the visual treatment must never blur:
// THE ENGINE RANKS, CLAUDE NARRATES, A PERSON AWARDS. The ranking is deterministic (a firm with a
// fatal flag is demoted below every clean firm regardless of price); the rationale is prose and is
// labelled as prose; and the award is a radio button a human presses. An override onto a flagged
// firm is allowed and RECORDED — the product's job is to make the consequence unmissable, not to
// remove the choice.
//
// Two states that are deliberately not the same as "no award": a package awaiting a valid priced
// return has its award control CLOSED (there is nothing to award), and a firm whose return priced
// nothing is excluded from the award entirely — never awardable at HK$0.

import { useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { RiskFlagList } from "../../firm";
import type { RankedFirm, Recommendation } from "../../types";
import { Card, Chip, Collapse, Docket, Drawer, SectionLabel, cx, money } from "../../ui";

const hkd = (v: number) => money(v);

// Chart colours. THESE CARRY NO SEMANTIC LOAD beyond the two that do (ok = the recommended bar,
// bad = a recommended-against bar, faint = everything else); the rest are axis/label/band inks
// chosen only to sit correctly against the warm cb background. Do not go looking for a meaning in
// the band or axis values — there was never one to find.
const AXIS_INK = "#112233"; // cb-ink-text
const OK = "#3c8a63"; // cb-ok      — the recommended bar
const BAD = "#c25539"; // cb-bad     — a recommended-against bar
const FAINT = "#8a97a3"; // cb-faint   — every other bar
const BAND_FILL = "#eef3f8"; // cb-info    — the historical band
const BAND_LINE = "#2f6e8a"; // cb-blue    — the median line

/** How the recommended bid sits against the others and against history — READ OFF the numbers
 *  already on this screen, never recomputed from anything else.
 *
 *  Presentation only. The ranking, the recommendation and the demotion are the engine's and are
 *  untouched; this states what the ranked list and the chart already contain so a person does not
 *  have to subtract two figures in their head or read a bar chart to answer "by how much?".
 *
 *  `null` wherever the comparison does not exist — one bid has no runner-up, and a package with no
 *  historical band has no position against one. An absent comparison is shown as absent. */
function margins(rec: Recommendation) {
  const winner = rec.ranked.find((r) => r.firm_id === rec.recommended_firm_id) ?? null;
  if (!winner) return null;
  // Priced, awardable bids only: a firm that priced nothing is not a comparison, it is a gap, and
  // "cheaper than the firm that quoted zero" would be a meaningless saving.
  const priced = rec.ranked.filter((r) => !r.no_priced_coverage);
  const next = priced.filter((r) => r.firm_id !== winner.firm_id && !r.recommended_against)[0] ?? null;
  const cheapest = priced[0] ?? null;
  const band = rec.historical_band;
  return {
    winner,
    /** vs the next CLEAN bid — the real alternative, not merely the next row. */
    overNext: next ? next.corrected_total - winner.corrected_total : null,
    nextName: next?.firm_name ?? "",
    /** What the demotion costs, when the cheapest bid overall is one we recommend against. */
    demotionCost:
      cheapest && cheapest.recommended_against && cheapest.firm_id !== winner.firm_id
        ? winner.corrected_total - cheapest.corrected_total
        : null,
    demotedName: cheapest?.recommended_against ? cheapest.firm_name : "",
    band,
    /** below / within / above the historical band — the chart's shaded region, as a word. */
    vsBand: band
      ? winner.corrected_total < band.low
        ? "below"
        : winner.corrected_total > band.high
          ? "above"
          : "within"
      : null,
  };
}

function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}

export function Recommend({
  sections,
  awards,
  awaitingTrades = [],
  onSetAward,
  onSkip,
}: {
  sections: Record<string, Recommendation>;
  awards: Record<string, string>;
  awaitingTrades?: string[];
  onSetAward: (trade: string, firm: RankedFirm) => void;
  onSkip: (trade: string) => void;
}) {
  const trades = Object.keys(sections);
  // A package awaiting a valid priced return has no award to make, so it is not counted against
  // the "all decided" tally — the banner stays honest and the gate closes without blocking.
  const awardable = trades.filter((t) => !sections[t].awaiting_valid_return);
  const decided = awardable.filter((t) => awards[t] !== undefined);
  const gatedCount = trades.length - awardable.length;
  const [detail, setDetail] = useState<{ firm: RankedFirm; recommended: boolean } | null>(null);

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-[12px] leading-relaxed text-cb-muted">
        Each sourced package gets its own recommendation and its own award. The engine ranks by
        corrected price but reads each firm against the database — a firm with a fatal flag is
        recommended against regardless of price. Claude narrates the rationale; it never chooses the
        winner. You award each package, or skip it.
      </p>

      {trades.length > 1 && (
        <Card
          className={cx(
            "text-[12px]",
            decided.length === awardable.length
              ? "border-cb-ok bg-cb-ok-tint text-cb-ink-text"
              : "text-cb-body",
          )}
        >
          {decided.length === awardable.length ? (
            <>
              All <span className="font-cb-mono font-semibold">{awardable.length}</span> awardable
              packages decided — each award below is recorded.
            </>
          ) : (
            <>
              <span className="font-cb-mono font-semibold">
                {decided.length}/{awardable.length}
              </span>{" "}
              awardable packages decided — award or skip each package to finish.
            </>
          )}
          {gatedCount > 0 && (
            <>
              {" "}
              <span className="font-cb-mono font-semibold">{gatedCount}</span> awaiting a valid
              priced return (award withheld).
            </>
          )}
        </Card>
      )}

      {awaitingTrades.length > 0 && (
        <Card className="text-[12px] text-cb-body">
          Awaiting returns — no award yet for{" "}
          <span className="font-medium text-cb-ink-text">
            {awaitingTrades.map(tradeLabel).join(", ")}
          </span>
          . Upload a priced return on Level &amp; compare to activate a package's recommendation.
        </Card>
      )}

      {trades.map((trade) => (
        <TradeRecommendation
          key={trade}
          trade={trade}
          rec={sections[trade]}
          award={awards[trade]}
          onSetAward={(firm) => onSetAward(trade, firm)}
          onSkip={() => onSkip(trade)}
          onOpenDetail={(firm, recommended) => setDetail({ firm, recommended })}
        />
      ))}

      <RankingDrawer
        firm={detail?.firm ?? null}
        recommended={detail?.recommended ?? false}
        onClose={() => setDetail(null)}
      />
    </div>
  );
}

function TradeRecommendation({
  trade,
  rec,
  award,
  onSetAward,
  onSkip,
  onOpenDetail,
}: {
  trade: string;
  rec: Recommendation;
  award: string | undefined;
  onSetAward: (firm: RankedFirm) => void;
  onSkip: () => void;
  onOpenDetail: (firm: RankedFirm, recommended: boolean) => void;
}) {
  const winner = rec.ranked.find((r) => r.firm_id === rec.recommended_firm_id) ?? null;
  const m = margins(rec);
  const against = rec.ranked.filter((r) => r.recommended_against);
  const awaiting = rec.awaiting_valid_return;
  const skipped = award === "";
  const awarded = award ? rec.ranked.find((r) => r.firm_id === award) ?? null : null;
  const overriding = awarded != null && awarded.recommended_against;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-cb-border pb-1.5">
        <h3 className="font-cb-serif text-[14px] font-semibold text-cb-ink-text">
          {tradeLabel(trade)}
        </h3>
        <button
          type="button"
          onClick={onSkip}
          className="font-cb-sans text-[10px] font-semibold text-cb-faint hover:text-cb-ink-text"
        >
          {skipped ? "Skipped — no award for this package" : "Skip this package"}
        </button>
      </div>

      <Card flush className="overflow-hidden">
        {awaiting && (
          <div className="flex flex-wrap items-center gap-3 border-b border-cb-divider px-3 py-2.5">
            <span className="text-[16px]">⏳</span>
            <div>
              <div className="text-[12px] font-bold text-cb-ink-text">
                Awaiting a valid priced return
              </div>
              <div className="text-[11px] text-cb-body">
                No return has priced this scope yet — the award is withheld until one does.
              </div>
            </div>
            <Chip className="bg-cb-panel text-cb-muted">no valid bid</Chip>
          </div>
        )}
        {winner && (
          <div className="border-b border-cb-divider bg-cb-ok-tint px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-[16px]">✅</span>
              <div>
                <div className="text-[12px] font-bold text-cb-ink-text">
                  Recommend {winner.firm_name}
                </div>
                <div className="font-cb-mono text-[10px] text-cb-body">
                  {winner.firm_id} · {hkd(winner.corrected_total)}
                </div>
              </div>
              <Chip className="bg-white text-cb-ok-dark">cheapest clean bid</Chip>
            </div>
            {/* BY HOW MUCH — subtraction the reader was doing in their head, or reading off a bar
                chart. Every figure here is already on this screen; nothing is recomputed and
                nothing about the ranking changes. An absent comparison is shown as absent. */}
            {m && (m.overNext != null || m.demotionCost != null || m.vsBand) && (
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-cb-mono text-[10px] text-cb-body">
                {m.overNext != null && (
                  <span>
                    {hkd(Math.abs(m.overNext))} {m.overNext >= 0 ? "under" : "over"} {m.nextName}
                    <span className="text-cb-faint"> · next clean bid</span>
                  </span>
                )}
                {m.demotionCost != null && (
                  <span className="text-cb-bad-dark">
                    {hkd(Math.abs(m.demotionCost))} more than {m.demotedName}
                    <span className="opacity-70"> · the flagged cheapest</span>
                  </span>
                )}
                {m.vsBand && m.band && (
                  <span>
                    {m.vsBand} the historical band
                    <span className="text-cb-faint">
                      {" "}
                      · {hkd(m.band.low)}–{hkd(m.band.high)}
                    </span>
                  </span>
                )}
              </div>
            )}
            {/* A clean winner can still carry NON-fatal flags. Showing them makes "clean" a thing
                the reader can see rather than infer from the absence of a red block below. */}
            {winner.risk_flags.some((f) => f.severity !== "fatal") && (
              <div className="mt-2">
                <RiskFlagList flags={winner.risk_flags.filter((f) => f.severity !== "fatal")} />
              </div>
            )}
          </div>
        )}
        {against.map((r) => (
          <div key={r.firm_id} className="px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[16px]">⛔</span>
              <span className="text-[12px] font-bold text-cb-ink-text">
                Recommend against {r.firm_name}
              </span>
              <span className="font-cb-mono text-[10px] text-cb-faint">
                {r.firm_id} · {hkd(r.corrected_total)}
              </span>
              <Chip className="bg-cb-bad-tint text-cb-bad-dark">cheapest overall</Chip>
            </div>
            {/* The reason, given the weight of the claim it supports. It was body text under a
                bold headline; a person scanning for WHY had to stop and look for it. */}
            <p className="mt-1.5 border-l-[3px] border-cb-bad bg-cb-bad-tint/40 px-3 py-2 text-[12px] leading-relaxed text-cb-ink-text">
              {r.reason}
            </p>
            <div className="mt-2">
              <RiskFlagList flags={r.risk_flags.filter((f) => f.severity === "fatal")} />
            </div>
          </div>
        ))}
      </Card>

      <Card flush className="overflow-hidden">
        <div className="border-b border-cb-divider px-3 py-2">
          <h4 className="text-[12px] font-semibold text-cb-ink-text">
            Bid distribution &amp; historical band
          </h4>
          <p className="text-[10px] text-cb-faint">
            Corrected totals; the shaded region is the historical band (low–high), the dashed line
            the median.
          </p>
        </div>
        <div className="p-3">
          <BidChart rec={rec} />
        </div>
      </Card>

      <Card flush className="overflow-hidden">
        <h4 className="border-b border-cb-divider px-3 py-2 font-cb-sans text-[9px] font-semibold uppercase tracking-cb-chip text-cb-muted">
          Ranked — clean firms first, flagged firms demoted
        </h4>
        <ol className="divide-y divide-cb-divider">
          {rec.ranked.map((r, i) => (
            <li
              key={r.firm_id}
              className={cx(
                "flex flex-wrap items-center gap-2 px-3 py-2",
                r.recommended_against ? "bg-cb-bad-tint/40" : "hover:bg-cb-panel/70",
              )}
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full border border-cb-border font-cb-mono text-[10px] text-cb-muted">
                {i + 1}
              </span>
              <button
                type="button"
                onClick={() => onOpenDetail(r, r.firm_id === rec.recommended_firm_id)}
                title="Open the ranking record"
                className="text-[12px] font-medium text-cb-ink-text hover:text-cb-brass-text"
              >
                {r.firm_name}
              </button>
              <span className="font-cb-mono text-[10px] text-cb-faint">{r.firm_id}</span>
              {r.firm_id === rec.recommended_firm_id && (
                <Chip className="bg-cb-ok-tint text-cb-ok-dark">recommended</Chip>
              )}
              {r.recommended_against && (
                <Chip className="bg-cb-bad-tint text-cb-bad-dark">recommended against</Chip>
              )}
              {r.no_priced_coverage && (
                <Chip className="bg-cb-panel text-cb-muted">no priced return</Chip>
              )}
              <span className="ml-auto text-right font-cb-mono text-[12px] font-semibold text-cb-ink-text">
                {r.no_priced_coverage ? (
                  <span className="text-cb-faint">{r.reason || "priced nothing"}</span>
                ) : (
                  <>
                    {hkd(r.corrected_total)}
                    {/* The gap to the recommended bid, so the list reads as a comparison rather
                        than four unrelated numbers. Pure subtraction of two figures already in
                        this row and the banner above; the ORDER is the engine's and is untouched. */}
                    {winner && r.firm_id !== winner.firm_id && (
                      <span className="ml-2 font-normal text-cb-faint">
                        {r.corrected_total >= winner.corrected_total ? "+" : "−"}
                        {hkd(Math.abs(r.corrected_total - winner.corrected_total))}
                      </span>
                    )}
                  </>
                )}
              </span>
            </li>
          ))}
        </ol>
      </Card>

      <Card>
        {/* Brass: this paragraph is prose a model wrote. Labelling it is the point — every number
            around it came from the engine, and the two must not be mistaken for one another. */}
        <SectionLabel className="mb-2">Rationale — written by Claude</SectionLabel>
        <blockquote className="border-l-[3px] border-cb-brass bg-cb-brass-tint/40 px-3 py-2 text-[12px] leading-relaxed text-cb-ink-text">
          {rec.rationale}
        </blockquote>
      </Card>

      <Card>
        <h4 className="mb-1 text-[12px] font-semibold text-cb-ink-text">
          Award — {tradeLabel(trade)} (human decision)
        </h4>
        {awaiting ? (
          <div className="rounded-cb-card bg-cb-panel px-3 py-2 text-[12px] text-cb-body">
            No valid priced return has arrived for this package — the award control is closed. It
            opens once a return prices this scope (upload one on Level &amp; compare).
          </div>
        ) : (
          <>
            <p className="mb-3 text-[10px] text-cb-faint">
              The recommendation is decision support. Select the firm to award this package — you may
              override, but overriding onto a flagged firm is recorded.
            </p>
            <div className="space-y-1.5">
              {rec.ranked.map((r) => {
                const noCoverage = r.no_priced_coverage;
                return (
                  <label
                    key={r.firm_id}
                    className={cx(
                      "flex items-center gap-2 rounded-cb-card border px-3 py-2",
                      noCoverage
                        ? "cursor-not-allowed border-cb-border bg-cb-panel opacity-60"
                        : award === r.firm_id
                          ? "cursor-pointer border-cb-brass bg-cb-selected"
                          : "cursor-pointer border-cb-border bg-white hover:bg-cb-panel",
                    )}
                  >
                    <input
                      type="radio"
                      name={`award-${trade}`}
                      checked={award === r.firm_id}
                      disabled={noCoverage}
                      onChange={() => !noCoverage && onSetAward(r)}
                      className="h-4 w-4 accent-[var(--color-cb-brass)]"
                    />
                    <span className="text-[12px] font-medium text-cb-ink-text">{r.firm_name}</span>
                    <span className="font-cb-mono text-[10px] text-cb-faint">
                      {noCoverage ? "no priced return" : hkd(r.corrected_total)}
                    </span>
                    {r.recommended_against && (
                      <Chip className="bg-cb-bad-tint text-cb-bad-dark">flagged</Chip>
                    )}
                    {noCoverage && <Chip className="bg-cb-panel text-cb-muted">excluded</Chip>}
                  </label>
                );
              })}
            </div>
          </>
        )}
        {!awaiting && awarded && (
          <div
            className={cx(
              "mt-3 rounded-cb-card px-3 py-2 text-[12px]",
              overriding ? "bg-cb-bad-tint text-cb-bad-dark" : "bg-cb-ok-tint text-cb-ok-dark",
            )}
          >
            {overriding
              ? `Override recorded: awarding ${awarded.firm_name} for ${tradeLabel(trade)}, which the engine recommends against.`
              : `Award recorded: ${awarded.firm_name} for ${tradeLabel(trade)} (${hkd(awarded.corrected_total)}).`}
          </div>
        )}
        {skipped && (
          <div className="mt-3 rounded-cb-card bg-cb-panel px-3 py-2 text-[12px] text-cb-body">
            Skipped — no award recorded for this package. Pick a firm above to award it after all.
          </div>
        )}
      </Card>
    </section>
  );
}

/** Why this firm sits where it does: its corrected price, the engine's reason line, and the
 *  adjudicated flags with their cited evidence. */
function RankingDrawer({
  firm,
  recommended,
  onClose,
}: {
  firm: RankedFirm | null;
  recommended: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer
      open={firm != null}
      onClose={onClose}
      eyebrow="Ranking record"
      accent={
        firm?.recommended_against ? "bg-cb-bad" : recommended ? "bg-cb-ok" : "bg-cb-navy"
      }
      title={firm?.firm_name ?? ""}
      subtitle={
        firm && (
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-cb-mono">{firm.firm_id}</span>
            {recommended && <Chip className="bg-cb-ok-tint text-cb-ok-dark">recommended</Chip>}
            {firm.recommended_against && (
              <Chip className="bg-cb-bad-tint text-cb-bad-dark">recommended against</Chip>
            )}
          </span>
        )
      }
      footer="The ranking is decision support — the award is a human decision, and an override onto a flagged firm is recorded."
    >
      {firm && (
        <div className="space-y-3">
          <Docket label="Corrected total" code={hkd(firm.corrected_total)} />
          {firm.reason && <p className="text-[11px] leading-relaxed text-cb-body">{firm.reason}</p>}
          <Collapse
            title="Risk flags"
            count={firm.risk_flags.length}
            defaultOpen={firm.risk_flags.length > 0}
          >
            {firm.risk_flags.length > 0 ? (
              <RiskFlagList flags={firm.risk_flags} />
            ) : (
              <p className="text-[11px] text-cb-faint">No adjudicated flags — a clean public record.</p>
            )}
          </Collapse>
        </div>
      )}
    </Drawer>
  );
}

interface ChartRow {
  name: string;
  value: number;
  fill: string;
}

function BidChart({ rec }: { rec: Recommendation }) {
  const byName = new Map<string, RankedFirm>(rec.ranked.map((r) => [r.firm_name, r]));
  const data: ChartRow[] = rec.bid_distribution
    .map((p) => {
      const r = byName.get(p.firm_name);
      const fill = r && r.firm_id === rec.recommended_firm_id ? OK : r?.recommended_against ? BAD : FAINT;
      return { name: p.firm_name, value: p.corrected_total, fill };
    })
    .sort((a, b) => a.value - b.value);

  const band = rec.historical_band;
  const maxVal = Math.max(...data.map((d) => d.value), band?.high ?? 0) * 1.18;

  return (
    <ResponsiveContainer width="100%" height={Math.max(140, data.length * 42)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 110, bottom: 4, left: 8 }}>
        <XAxis type="number" domain={[0, maxVal]} hide />
        <YAxis
          type="category"
          dataKey="name"
          width={180}
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 11, fill: AXIS_INK }}
        />
        {band && (
          <ReferenceArea
            x1={band.low}
            x2={band.high}
            fill={BAND_FILL}
            fillOpacity={0.8}
            ifOverflow="extendDomain"
          />
        )}
        {band && (
          <ReferenceLine
            x={band.median}
            stroke={BAND_LINE}
            strokeDasharray="4 3"
            label={{
              value: `median ${hkd(band.median)}`,
              position: "top",
              fontSize: 10,
              fill: BAND_LINE,
            }}
          />
        )}
        <Tooltip cursor={{ fill: "rgba(12,26,40,0.05)" }} content={<BidTooltip />} />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false} barSize={20}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.fill} />
          ))}
          <LabelList
            dataKey="value"
            position="right"
            formatter={(v: unknown) => hkd(Number(v))}
            style={{ fill: AXIS_INK, fontSize: 11, fontWeight: 600 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// recharts injects { active, payload }.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function BidTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as ChartRow;
  return (
    <div className="rounded-cb-card border border-cb-border bg-white p-2 text-[11px] shadow-cb-card">
      <div className="font-cb-mono font-semibold text-cb-ink-text">{row.name}</div>
      <div className="font-cb-mono text-cb-body">{hkd(row.value)}</div>
    </div>
  );
}
