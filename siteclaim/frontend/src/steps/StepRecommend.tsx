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
import type { RankedFirm, Recommendation } from "../types";
import { Pill, RiskFlagList, StepHeading } from "../components";
import { Button, Card, cx } from "../ui";
import { hkd, tradeLabel } from "../format";

const INK = "#15212e";
const OK = "#1a7f55";
const BAD = "#b42318";
const FAINT = "#8595a3";
const BRAND_BG = "#e7eef8";
const BRAND = "#1f4e8c";

export function StepRecommend({
  recommendation,
  award,
  onSetAward,
  onBack,
  onReset,
}: {
  recommendation: Recommendation;
  award: string | null;
  onSetAward: (firmId: string) => void;
  onBack: () => void;
  onReset: () => void;
}) {
  const rec = recommendation;
  const winner = rec.ranked.find((r) => r.firm_id === rec.recommended_firm_id) ?? null;
  const against = rec.ranked.filter((r) => r.recommended_against);
  const awarded = rec.ranked.find((r) => r.firm_id === award) ?? null;
  const overriding = awarded != null && awarded.recommended_against;

  return (
    <div className="space-y-6">
      <StepHeading
        title="Risk-adjusted recommendation"
        lead={`For the ${tradeLabel(rec.trade)} package the engine ranks by corrected price but reads each firm against the database. A firm with a fatal flag is recommended against regardless of price. Claude narrates the rationale — it never chooses the winner.`}
      />

      {/* Headline */}
      <Card className="overflow-hidden">
        {winner && (
          <div className="flex flex-wrap items-center gap-3 border-b border-line-soft bg-ok-bg/40 px-4 py-3">
            <span className="text-lg">✅</span>
            <div>
              <div className="text-sm font-bold text-ink">Recommend {winner.firm_name}</div>
              <div className="tabular text-xs text-ink-soft">{winner.firm_id} · {hkd(winner.corrected_total)}</div>
            </div>
            <Pill tone="ok">cheapest clean bid</Pill>
          </div>
        )}
        {against.map((r) => (
          <div key={r.firm_id} className="px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg">⛔</span>
              <span className="text-sm font-bold text-ink">Recommend against {r.firm_name}</span>
              <span className="tabular text-xs text-ink-faint">{r.firm_id} · {hkd(r.corrected_total)}</span>
              <Pill tone="bad">cheapest overall</Pill>
            </div>
            <p className="mt-1 text-sm text-ink-soft">{r.reason}</p>
            <div className="mt-2">
              <RiskFlagList flags={r.risk_flags.filter((f) => f.severity === "fatal")} />
            </div>
          </div>
        ))}
      </Card>

      {/* Bid distribution chart */}
      <Card className="overflow-hidden">
        <div className="border-b border-line-soft px-4 py-2.5">
          <h2 className="text-sm font-semibold text-ink">Bid distribution &amp; historical band</h2>
          <p className="text-xs text-ink-faint">
            Corrected totals; the shaded region is the historical band (low–high), the dashed line the median.
          </p>
        </div>
        <div className="p-3">
          <BidChart rec={rec} />
        </div>
      </Card>

      {/* Ranked firms */}
      <Card className="overflow-hidden">
        <h2 className="border-b border-line-soft px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-soft">
          Ranked — clean firms first, flagged firms demoted
        </h2>
        <ol className="divide-y divide-line-soft">
          {rec.ranked.map((r, i) => (
            <li key={r.firm_id} className={cx("flex flex-wrap items-center gap-2 px-4 py-2.5", r.recommended_against && "bg-bad-bg/30")}>
              <span className="tabular flex h-6 w-6 items-center justify-center rounded-full border border-line text-xs font-semibold text-ink-soft">{i + 1}</span>
              <span className="text-sm font-medium text-ink">{r.firm_name}</span>
              <span className="tabular text-xs text-ink-faint">{r.firm_id}</span>
              {r.firm_id === rec.recommended_firm_id && <Pill tone="ok">recommended</Pill>}
              {r.recommended_against && <Pill tone="bad">recommended against</Pill>}
              <span className="tabular ml-auto text-sm font-semibold text-ink">{hkd(r.corrected_total)}</span>
            </li>
          ))}
        </ol>
      </Card>

      {/* Rationale */}
      <Card className="p-4">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Rationale — written by Claude (Layer 2)</h2>
        <blockquote className="border-l-3 border-brand bg-brand-bg/40 px-3 py-2 text-sm leading-relaxed text-ink">
          {rec.rationale}
        </blockquote>
      </Card>

      {/* Override & award (Layer 4) */}
      <Card className="p-4">
        <h2 className="mb-1 text-sm font-semibold text-ink">Award (human decision)</h2>
        <p className="mb-3 text-xs text-ink-faint">
          The recommendation is decision support. Select the firm to award — you may override, but overriding onto a flagged firm is recorded.
        </p>
        <div className="space-y-1.5">
          {rec.ranked.map((r) => (
            <label key={r.firm_id} className={cx("flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2", award === r.firm_id ? "border-brand bg-brand-bg" : "border-line bg-card hover:bg-line-soft")}>
              <input type="radio" name="award" checked={award === r.firm_id} onChange={() => onSetAward(r.firm_id)} className="h-4 w-4 accent-[var(--color-brand)]" />
              <span className="text-sm font-medium text-ink">{r.firm_name}</span>
              <span className="tabular text-xs text-ink-faint">{hkd(r.corrected_total)}</span>
              {r.recommended_against && <Pill tone="bad">flagged</Pill>}
            </label>
          ))}
        </div>
        {awarded && (
          <div className={cx("mt-3 rounded-lg px-3 py-2 text-sm", overriding ? "bg-bad-bg text-bad" : "bg-ok-bg text-ok")}>
            {overriding
              ? `Override recorded: awarding ${awarded.firm_name}, which the engine recommends against.`
              : `Award recorded: ${awarded.firm_name} (${hkd(awarded.corrected_total)}).`}
          </div>
        )}
      </Card>

      <div className="flex items-center justify-between gap-3 pt-2">
        <Button variant="ghost" onClick={onBack}>← Back</Button>
        <Button variant="ghost" onClick={onReset}>Start over</Button>
      </div>
    </div>
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
        <YAxis type="category" dataKey="name" width={180} tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: INK }} />
        {band && <ReferenceArea x1={band.low} x2={band.high} fill={BRAND_BG} fillOpacity={0.7} ifOverflow="extendDomain" />}
        {band && (
          <ReferenceLine
            x={band.median}
            stroke={BRAND}
            strokeDasharray="4 3"
            label={{ value: `median ${hkd(band.median)}`, position: "top", fontSize: 10, fill: BRAND }}
          />
        )}
        <Tooltip cursor={{ fill: "rgba(21,33,46,0.05)" }} content={<BidTooltip />} />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false} barSize={20}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.fill} />
          ))}
          <LabelList dataKey="value" position="right" formatter={(v: unknown) => hkd(Number(v))} style={{ fill: INK, fontSize: 12, fontWeight: 600 }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// recharts injects { active, payload }.
function BidTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as ChartRow;
  return (
    <div className="rounded-lg border border-line bg-card p-2 text-xs shadow-lg">
      <div className="tabular font-semibold text-ink">{row.name}</div>
      <div className="tabular text-ink-soft">{hkd(row.value)}</div>
    </div>
  );
}
