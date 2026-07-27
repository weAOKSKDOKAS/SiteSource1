// The cash-flow section of the departure register (REVIEW s06) — deterministic, Layer 1.
//
// Form: the data does two jobs at once, so it gets two marks on ONE axis (both are HK$ —
// never a second y-scale). Net per period is a polarity read, so it is a diverging bar
// around a zero baseline; the cumulative position is a running level, so it is a line. The
// peak funding requirement is the number a contractor actually acts on, so it is called out
// directly on the plot rather than left to be inferred.
//
// Colour: #1f6feb (positive) / #e5484d (negative) — validated as a pair for the lightness
// band, chroma floor, CVD separation, normal-vision separation and contrast against a white
// surface. The cumulative line wears the ink text token: it is a reference level, not a third
// category, and it must stay readable where it crosses either bar colour.

import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Collapse } from "../ui";
import { money } from "./boqUi";
import type { CashflowSection } from "./types";

const POSITIVE = "#1f6feb";
const NEGATIVE = "#e5484d";
const INK = "#0f1b2d";
const INK_FAINT = "#8a98ab";
const LINE = "#dbe3ec";

// Compact axis money — "-300k", "1.2m" — so the axis stays recessive.
function axisMoney(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}m`;
  if (abs >= 1_000) return `${sign}${Math.round(abs / 1_000)}k`;
  return `${sign}${abs}`;
}

interface Row {
  period: string;
  net: number;
  cumulative: number;
  inflow: number;
  outflow: number;
}

function CashTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-card p-2.5 text-xs shadow-lg">
      <div className="tabular mb-1 font-semibold text-ink">{r.period}</div>
      <dl className="tabular space-y-0.5">
        <div className="flex justify-between gap-4">
          <dt className="text-ink-faint">Receipts</dt>
          <dd className="text-ink-soft">{money(r.inflow)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-faint">Cost</dt>
          <dd className="text-ink-soft">{money(r.outflow)}</dd>
        </div>
        <div className="flex justify-between gap-4 border-t border-line-soft pt-0.5">
          <dt className="text-ink-faint">Net</dt>
          <dd className="font-semibold" style={{ color: r.net < 0 ? NEGATIVE : POSITIVE }}>{money(r.net)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-faint">Position</dt>
          <dd className="font-semibold text-ink">{money(r.cumulative)}</dd>
        </div>
      </dl>
    </div>
  );
}

export function CashflowChart({ cashflow }: { cashflow: CashflowSection }) {
  const data: Row[] = cashflow.points.map((p) => ({
    period: p.period,
    net: p.net,
    cumulative: p.cumulative,
    inflow: p.inflow,
    outflow: p.outflow,
  }));
  if (!data.length) return null;

  const peak = cashflow.working_capital_peak;
  const showPeak = peak < 0;

  return (
    <div>
      {/* The legend is written out rather than left to the chart library, because the net bar
          carries two colours for one series — a single "Net this period" swatch would be a
          lie about what the reader is looking at. */}
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-ink-faint">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: POSITIVE }} />
          Net — surplus
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: NEGATIVE }} />
          Net — shortfall
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-0.5 w-4 rounded-full" style={{ backgroundColor: INK }} />
          Cumulative position
        </span>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={LINE} strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="period"
            tickLine={false}
            axisLine={{ stroke: LINE }}
            tick={{ fontSize: 11, fill: INK_FAINT }}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={54}
            tickFormatter={axisMoney}
            tick={{ fontSize: 11, fill: INK_FAINT }}
          />
          <ReferenceLine y={0} stroke={INK_FAINT} strokeWidth={1} />
          {showPeak && (
            <ReferenceLine
              y={peak}
              stroke={NEGATIVE}
              strokeDasharray="4 3"
              label={{
                value: `peak funding ${money(Math.abs(peak))}`,
                position: "insideBottomRight",
                fontSize: 10,
                fill: NEGATIVE,
              }}
            />
          )}
          <Tooltip cursor={{ fill: "rgba(15,27,45,0.04)" }} content={<CashTooltip />} />
          {/* Rounded away from the baseline, square against it — so the bar reads as growing
              out of zero rather than floating. A negative bar rounds its bottom, a positive
              one its top. */}
          <Bar dataKey="net" name="Net this period" barSize={26} isAnimationActive={false}>
            {data.map((r, i) => (
              <Cell
                key={i}
                fill={r.net < 0 ? NEGATIVE : POSITIVE}
                // recharts' Rectangle accepts a four-corner radius; Cell's prop types inherit
                // the SVG `radius` (string | number), so the tuple needs the cast.
                radius={(r.net < 0 ? [0, 0, 4, 4] : [4, 4, 0, 0]) as unknown as number}
              />
            ))}
          </Bar>
          <Line
            type="monotone"
            dataKey="cumulative"
            name="Cumulative position"
            stroke={INK}
            strokeWidth={2}
            dot={{ r: 3, fill: INK, stroke: "#ffffff", strokeWidth: 2 }}
            activeDot={{ r: 5, fill: INK, stroke: "#ffffff", strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="mt-2">
        {/* The table view the chart owes every reader who cannot use the plot. */}
        <Collapse title="Period figures" count={data.length}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line-soft text-left text-ink-faint">
                  <th className="py-1.5 pr-3 font-medium">Period</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Receipts</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Cost</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Net</th>
                  <th className="py-1.5 text-right font-medium">Position</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {data.map((r) => (
                  <tr key={r.period} className="border-b border-line-soft last:border-0">
                    <td className="py-1.5 pr-3 font-semibold text-ink">{r.period}</td>
                    <td className="py-1.5 pr-3 text-right text-ink-soft">{money(r.inflow)}</td>
                    <td className="py-1.5 pr-3 text-right text-ink-soft">{money(r.outflow)}</td>
                    <td
                      className="py-1.5 pr-3 text-right font-semibold"
                      style={{ color: r.net < 0 ? NEGATIVE : r.net > 0 ? POSITIVE : INK_FAINT }}
                    >
                      {money(r.net)}
                    </td>
                    <td className="py-1.5 text-right font-semibold text-ink">{money(r.cumulative)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Collapse>
      </div>
    </div>
  );
}
