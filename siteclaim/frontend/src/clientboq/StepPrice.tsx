// Step 4 — the cost build-up.
//
// One decision shapes this whole screen: **the screen does not price anything.** It would be
// easy to multiply qty × rate in the browser and show a running total as the estimator types,
// and it would be wrong — the module's rule is that arithmetic belongs to the rules engine,
// and a figure the UI invented is a figure nobody can defend. So the editor collects a
// schedule, the run computes, and every number on this page arrives from the backend with the
// working shown beside it.
//
// That is also why each priced line renders as a trace rather than a total: `800 m2 ÷ 2.5 =
// 320 hr × HK$580 = HK$185,600`. An estimator can check the machine with a calculator, which
// is the only reason to trust it.

import { useMemo, useState } from "react";

import { Pill, StepHeading } from "../components";
import { Button, Card, Collapse, LayerBadge, LoadingDots, ScanLine, SectionHeader, StatCallout, cx } from "../ui";
import { EmptyState, Trace, humanise, money, num } from "./boqUi";
import type {
  CostActivity,
  CostLine,
  Estimate,
  EstimateFlag,
  EstimateResult,
  EstimateSchedule,
  RateRow,
  ResourceLine,
  ScheduleItem,
} from "./types";

// ---------------------------------------------------------------------------
// Flags. The rules engine raises them; none of them block a price. They are the
// "look at this before you send it" list.
// ---------------------------------------------------------------------------
const FLAG_META: Record<string, { label: string; tone: "bad" | "warn" | "neutral"; note: string }> = {
  missing_rate: { label: "No rate on file", tone: "bad", note: "Costed as zero — the price is understated until a rate exists." },
  zero_or_negative_qty: { label: "Quantity is zero", tone: "warn", note: "The line contributes nothing." },
  empty_activity: { label: "Nothing priced", tone: "warn", note: "The activity has no resource lines." },
  rate_outlier: { label: "Rate out of line", tone: "warn", note: "An inline rate is far from the rate book. Benchmark only." },
  unclassified_item: { label: "Not classified", tone: "bad", note: "Neither direct nor indirect, so it was never costed — never guessed." },
};

function FlagRow({ flag }: { flag: EstimateFlag }) {
  const meta = FLAG_META[flag.kind] ?? { label: humanise(flag.kind), tone: "neutral" as const, note: "" };
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 py-2">
      <Pill tone={meta.tone === "neutral" ? "neutral" : meta.tone}>{meta.label}</Pill>
      <span className="tabular text-xs font-semibold text-ink">{flag.item_id}</span>
      <span className="min-w-0 flex-1 text-sm text-ink-soft">{flag.message}</span>
      {meta.note && <span className="w-full text-xs text-ink-faint">{meta.note}</span>}
    </li>
  );
}

// ---------------------------------------------------------------------------
// A priced line, with its arithmetic on the surface.
// ---------------------------------------------------------------------------
function LineTrace({ line }: { line: CostLine }) {
  const missing = line.rate_source === "missing";
  return (
    <div className="py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-sm text-ink">{line.description}</span>
        <span className={cx("tabular text-sm font-semibold", missing ? "text-bad" : "text-ink")}>
          {money(line.amount)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <Trace>
          {num(line.qty)} {line.unit}
          {line.productivity != null && line.hours != null ? (
            <>
              {" ÷ "}
              {num(line.productivity)} {line.unit}/hr = {num(line.hours)} hr
            </>
          ) : null}
          {" × "}
          {money(line.rate)}
          {" = "}
          <span className="font-semibold text-ink">{money(line.amount)}</span>
        </Trace>
        {line.resource_ref && (
          <span
            className="tabular text-[11px] text-ink-faint"
            title={
              line.rate_source === "csv"
                ? "Rate taken from the rate book"
                : line.rate_source === "inline"
                  ? "Rate stated on the line, overriding the rate book"
                  : "No rate on file for this reference"
            }
          >
            {line.resource_ref} · {line.rate_source}
          </span>
        )}
      </div>
    </div>
  );
}

function ActivityCard({ activity }: { activity: CostActivity }) {
  return (
    <div className="border-t border-line-soft px-4 py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="tabular rounded border border-line px-1.5 py-px text-[11px] font-semibold text-ink-soft">
            {activity.item_id}
          </span>
          <span className="text-sm font-semibold text-ink">{activity.description}</span>
        </div>
        <span className="tabular text-sm font-bold text-ink">{money(activity.activity_total)}</span>
      </div>
      {activity.lines.length === 0 ? (
        <p className="mt-1 text-xs text-warn">No resource lines — this activity prices at zero.</p>
      ) : (
        <div className="mt-1 divide-y divide-line-soft">
          {activity.lines.map((l, i) => (
            <LineTrace key={i} line={l} />
          ))}
        </div>
      )}
    </div>
  );
}

function PricedEstimate({ estimate }: { estimate: Estimate }) {
  return (
    <>
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-soft px-4 py-2.5">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">Direct cost</h3>
            <span className="text-xs text-ink-faint">every line, with the arithmetic that produced it</span>
          </div>
          <LayerBadge layer="L1" />
        </div>
        {estimate.activities.map((a) => (
          <ActivityCard key={a.item_id} activity={a} />
        ))}
        <div className="flex items-baseline justify-between border-t border-line px-4 py-2.5">
          <span className="text-sm font-semibold text-ink">Total direct</span>
          <span className="tabular text-sm font-bold text-ink">{money(estimate.totals.total_direct)}</span>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-soft px-4 py-2.5">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">Indirect cost</h3>
            <span className="text-xs text-ink-faint">
              {estimate.duration_weeks != null ? `priced over ${num(estimate.duration_weeks)} weeks` : "site and company costs"}
            </span>
          </div>
          <LayerBadge layer="L1" />
        </div>
        <ul className="divide-y divide-line-soft">
          {estimate.indirects.map((ind) => (
            <li key={ind.item_id} className="px-4 py-2.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="tabular rounded border border-line px-1.5 py-px text-[11px] font-semibold text-ink-soft">
                    {ind.item_id}
                  </span>
                  <span className="text-sm text-ink">{ind.label}</span>
                  <Pill>{humanise(ind.basis)}</Pill>
                </div>
                <span className="tabular text-sm font-semibold text-ink">{money(ind.amount)}</span>
              </div>
              <div className="mt-1">
                <Trace>{ind.detail}</Trace>
              </div>
            </li>
          ))}
        </ul>
        <div className="flex items-baseline justify-between border-t border-line px-4 py-2.5">
          <span className="text-sm font-semibold text-ink">Total indirect</span>
          <span className="tabular text-sm font-bold text-ink">{money(estimate.totals.total_indirect)}</span>
        </div>
      </Card>

      {estimate.unclassified.length > 0 && (
        <Card className="border-bad/25 p-4">
          <SectionHeader
            title="Not costed"
            lead="These schedule items name a category the estimate does not recognise, so nothing was priced for them. The rules engine flags rather than guesses — a guessed classification is a wrong price nobody can trace."
            right={<Pill tone="bad">{estimate.unclassified.length}</Pill>}
          />
          <ul className="mt-3 space-y-1.5">
            {estimate.unclassified.map((u) => (
              <li key={u.item_id} className="flex flex-wrap items-baseline gap-2 text-sm">
                <span className="tabular font-semibold text-ink">{u.item_id}</span>
                <span className="text-ink-soft">{u.description}</span>
                <span className="tabular text-xs text-bad">category “{u.category}”</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {estimate.flags.length > 0 && (
        <Card className="p-4">
          <SectionHeader
            title="Check before you send"
            lead="Raised by the rules engine on the priced result. None of them block the price — they are the things an estimator would want a second look at."
            right={<Pill tone="warn">{estimate.flags.length}</Pill>}
          />
          <ul className="mt-2 divide-y divide-line-soft">
            {estimate.flags.map((f, i) => (
              <FlagRow key={i} flag={f} />
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// The schedule editor. Collects input; never prices it.
// ---------------------------------------------------------------------------
const EMPTY_LINE: ResourceLine = {
  description: "",
  resource_ref: "",
  inline_rate: null,
  qty: 0,
  unit: "",
  productivity: null,
};

function newItem(index: number, category: "direct" | "indirect"): ScheduleItem {
  return {
    item_id: category === "direct" ? `A${index}` : `I${index}`,
    description: "",
    category,
    unit: "item",
    lines: category === "direct" ? [{ ...EMPTY_LINE }] : [],
    basis: category === "indirect" ? "lump" : "",
    amount: null,
    rate: null,
    pct: null,
  };
}

/** A number field that keeps its own text so a half-typed "1." is never clobbered. */
function NumField({
  value,
  onCommit,
  placeholder,
  width = "w-20",
}: {
  value: number | null;
  onCommit: (v: number | null) => void;
  placeholder?: string;
  width?: string;
}) {
  const [text, setText] = useState(value == null ? "" : String(value));
  return (
    <input
      className={cx("tabular rounded border border-line px-2 py-1 text-right text-xs focus:border-brand focus:outline-none", width)}
      value={text}
      inputMode="decimal"
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const t = text.trim();
        if (t === "") {
          onCommit(null);
          return;
        }
        const n = Number(t);
        if (Number.isNaN(n)) {
          setText(value == null ? "" : String(value));
          return;
        }
        onCommit(n);
      }}
    />
  );
}

function ResourceLineRow({
  line,
  rates,
  onChange,
  onRemove,
}: {
  line: ResourceLine;
  rates: RateRow[];
  onChange: (next: ResourceLine) => void;
  onRemove: () => void;
}) {
  const byCategory = useMemo(() => {
    const groups = new Map<string, RateRow[]>();
    for (const r of rates) {
      if (!groups.has(r.category)) groups.set(r.category, []);
      groups.get(r.category)!.push(r);
    }
    return [...groups.entries()];
  }, [rates]);
  const picked = rates.find((r) => r.rate_id === line.resource_ref);

  return (
    <div className="flex flex-wrap items-center gap-1.5 border-t border-line-soft py-2 first:border-t-0">
      <input
        className="min-w-[10rem] flex-1 rounded border border-line px-2 py-1 text-xs focus:border-brand focus:outline-none"
        placeholder="Resource description"
        value={line.description}
        onChange={(e) => onChange({ ...line, description: e.target.value })}
      />
      <select
        className="tabular w-36 rounded border border-line bg-card px-1.5 py-1 text-xs focus:border-brand focus:outline-none"
        value={line.resource_ref}
        onChange={(e) => onChange({ ...line, resource_ref: e.target.value })}
        title={picked ? `${picked.description} — ${money(picked.rate)}/${picked.unit}` : "Pick a rate from the rate book"}
      >
        <option value="">— rate book —</option>
        {byCategory.map(([cat, rows]) => (
          <optgroup key={cat} label={humanise(cat)}>
            {rows.map((r) => (
              <option key={r.rate_id} value={r.rate_id}>
                {r.rate_id}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <NumField value={line.qty} onCommit={(v) => onChange({ ...line, qty: v ?? 0 })} placeholder="qty" />
      <input
        className="w-16 rounded border border-line px-2 py-1 text-xs focus:border-brand focus:outline-none"
        placeholder="unit"
        value={line.unit}
        onChange={(e) => onChange({ ...line, unit: e.target.value })}
      />
      <NumField
        value={line.productivity}
        onCommit={(v) => onChange({ ...line, productivity: v })}
        placeholder="out/hr"
      />
      <NumField
        value={line.inline_rate}
        onCommit={(v) => onChange({ ...line, inline_rate: v })}
        placeholder="rate"
        width="w-24"
      />
      <span className="tabular w-24 shrink-0 text-right text-[11px] text-ink-faint">
        {line.inline_rate != null
          ? "inline rate"
          : picked
            ? `${money(picked.rate)}/${picked.unit}`
            : line.resource_ref
              ? "not on file"
              : "no rate"}
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove resource line"
        className="shrink-0 px-1 text-xs text-ink-faint hover:text-bad"
      >
        ✕
      </button>
    </div>
  );
}

function ScheduleEditor({
  schedule,
  rates,
  priced,
  onChange,
}: {
  schedule: EstimateSchedule;
  rates: RateRow[];
  priced: boolean;
  onChange: (next: EstimateSchedule) => void;
}) {
  const setItem = (i: number, next: ScheduleItem) =>
    onChange({ ...schedule, items: schedule.items.map((it, j) => (j === i ? next : it)) });
  const removeItem = (i: number) => onChange({ ...schedule, items: schedule.items.filter((_, j) => j !== i) });
  const addItem = (category: "direct" | "indirect") =>
    onChange({
      ...schedule,
      items: [...schedule.items, newItem(schedule.items.filter((it) => it.category === category).length + 1, category)],
    });

  return (
    <div className="space-y-3">
      {schedule.items.length === 0 && (
        <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-ink-faint">
          {priced
            ? "The editor is empty — the run priced the schedule the backend held. Load it above to adjust the quantities, rates or margin and price it again."
            : "No schedule yet. Add a direct activity to start pricing, or an indirect item for site and company costs."}
        </p>
      )}

      {schedule.items.map((item, i) => (
        <div key={i} className="rounded-xl border border-line-soft bg-paper-soft/60 p-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <input
              className="tabular w-20 rounded border border-line px-2 py-1 text-xs font-semibold focus:border-brand focus:outline-none"
              placeholder="A1"
              value={item.item_id}
              onChange={(e) => setItem(i, { ...item, item_id: e.target.value })}
            />
            <input
              className="min-w-[12rem] flex-1 rounded border border-line px-2 py-1 text-sm focus:border-brand focus:outline-none"
              placeholder="Activity description"
              value={item.description}
              onChange={(e) => setItem(i, { ...item, description: e.target.value })}
            />
            <select
              className="rounded border border-line bg-card px-1.5 py-1 text-xs focus:border-brand focus:outline-none"
              value={item.category}
              onChange={(e) => {
                const category = e.target.value;
                setItem(i, {
                  ...item,
                  category,
                  lines: category === "direct" ? (item.lines.length ? item.lines : [{ ...EMPTY_LINE }]) : [],
                  basis: category === "indirect" ? item.basis || "lump" : "",
                });
              }}
            >
              <option value="direct">Direct</option>
              <option value="indirect">Indirect</option>
            </select>
            <button
              type="button"
              onClick={() => removeItem(i)}
              aria-label="Remove item"
              className="px-1 text-xs text-ink-faint hover:text-bad"
            >
              ✕
            </button>
          </div>

          {item.category === "direct" ? (
            <div className="mt-2">
              {item.lines.map((line, li) => (
                <ResourceLineRow
                  key={li}
                  line={line}
                  rates={rates}
                  onChange={(next) => setItem(i, { ...item, lines: item.lines.map((l, k) => (k === li ? next : l)) })}
                  onRemove={() => setItem(i, { ...item, lines: item.lines.filter((_, k) => k !== li) })}
                />
              ))}
              <button
                type="button"
                onClick={() => setItem(i, { ...item, lines: [...item.lines, { ...EMPTY_LINE }] })}
                className="mt-2 text-xs font-semibold text-brand hover:underline"
              >
                + Add resource line
              </button>
            </div>
          ) : (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select
                className="rounded border border-line bg-card px-1.5 py-1 text-xs focus:border-brand focus:outline-none"
                value={item.basis || "lump"}
                onChange={(e) => setItem(i, { ...item, basis: e.target.value })}
              >
                <option value="lump">Lump sum</option>
                <option value="per_week">Per week</option>
                <option value="pct_of_direct">% of direct</option>
              </select>
              {item.basis === "per_week" ? (
                <NumField value={item.rate} onCommit={(v) => setItem(i, { ...item, rate: v })} placeholder="per week" width="w-28" />
              ) : item.basis === "pct_of_direct" ? (
                <NumField value={item.pct} onCommit={(v) => setItem(i, { ...item, pct: v })} placeholder="%" />
              ) : (
                <NumField value={item.amount} onCommit={(v) => setItem(i, { ...item, amount: v })} placeholder="amount" width="w-28" />
              )}
              <span className="text-[11px] text-ink-faint">
                {item.basis === "per_week"
                  ? "multiplied by the programme duration on the run"
                  : item.basis === "pct_of_direct"
                    ? "applied to the direct subtotal on the run"
                    : "taken as stated"}
              </span>
            </div>
          )}
        </div>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" onClick={() => addItem("direct")}>
          + Direct activity
        </Button>
        <Button variant="ghost" onClick={() => addItem("indirect")}>
          + Indirect item
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
export function StepPrice({
  demoMode,
  result,
  rates,
  schedule,
  marginPct,
  running,
  stage,
  onSchedule,
  onMarginPct,
  onRun,
  onCopyPriced,
  onBack,
  onContinue,
}: {
  demoMode: boolean;
  result: EstimateResult | null;
  rates: RateRow[];
  schedule: EstimateSchedule;
  marginPct: number;
  running: boolean;
  stage: string;
  onSchedule: (s: EstimateSchedule) => void;
  onMarginPct: (v: number) => void;
  onRun: () => void;
  onCopyPriced: () => void;
  onBack: () => void;
  onContinue: () => void;
}) {
  const totals = result?.totals;
  const canRun = demoMode || (schedule.items.length > 0 && marginPct >= 0);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <StepHeading
          title="Build up the cost"
          lead="Quantities are given, rates come from the rate book, and the arithmetic is the rules engine's. This screen collects the schedule and shows the working — it never prices anything itself, so every figure below can be checked by hand."
        />
        <LayerBadge layer="L1" />
      </div>

      <Card className="relative p-4">
        <ScanLine active={running} />
        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <label className="text-xs font-medium text-ink-soft">
            Programme duration
            <span className="mt-1 flex items-center gap-1.5">
              <NumField
                value={schedule.duration_weeks}
                onCommit={(v) => onSchedule({ ...schedule, duration_weeks: v })}
                placeholder="20"
              />
              <span className="text-xs text-ink-faint">weeks</span>
            </span>
          </label>
          <label className="text-xs font-medium text-ink-soft">
            Margin
            <span className="mt-1 flex items-center gap-1.5">
              <NumField value={marginPct} onCommit={(v) => onMarginPct(v ?? 0)} placeholder="15" />
              <span className="text-xs text-ink-faint">% — yours to state, never suggested</span>
            </span>
          </label>
          <div className="ml-auto flex items-center gap-3">
            {running && <LoadingDots label={stage ? `Pricing — ${stage}` : "Pricing"} />}
            <Button onClick={onRun} loading={running} disabled={!canRun}>
              {result ? "Re-price →" : "Price the schedule →"}
            </Button>
          </div>
        </div>
        {demoMode && (
          <p className="mt-3 text-xs text-warn">
            Demo mode prices the baked schedule and its 15% margin offline. The editor below still works — its
            schedule is what a live run would send.
          </p>
        )}
      </Card>

      {/* Three readings, not five. Direct and indirect each already total at the foot of their
          own card, and five money tiles across one row leaves none of them room to be read. */}
      {totals && (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCallout
            label="Total cost"
            value={money(totals.total_cost)}
            hint={`${money(totals.total_direct)} direct · ${money(totals.total_indirect)} indirect`}
          />
          <StatCallout
            label={`Margin at ${num(totals.margin_pct)}%`}
            value={money(totals.margin_amount)}
            tone="violet"
            hint="a readout, not a verdict"
          />
          <StatCallout label="Offer price" value={money(totals.price)} tone="brand" hint="excluding GST" />
        </div>
      )}

      <Card className="p-4">
        <SectionHeader
          title="Pricing schedule"
          lead="Direct activities are priced from their resource lines; indirect items from a basis. A quantity, a rate reference and an output rate are all this needs — the run does the rest."
          right={
            result ? (
              <Button variant="ghost" onClick={onCopyPriced}>
                Load the priced schedule
              </Button>
            ) : undefined
          }
        />
        <div className="mt-3">
          <ScheduleEditor schedule={schedule} rates={rates} priced={!!result} onChange={onSchedule} />
        </div>
        <Collapse title="Rate book" count={rates.length}>
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-line-soft text-left text-ink-faint">
                  <th className="py-1.5 pr-3 font-medium">Reference</th>
                  <th className="py-1.5 pr-3 font-medium">Description</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Rate</th>
                  <th className="py-1.5 font-medium">Unit</th>
                </tr>
              </thead>
              <tbody>
                {rates.map((r) => (
                  <tr key={r.rate_id} className="border-b border-line-soft last:border-0">
                    <td className="tabular py-1.5 pr-3 font-semibold text-ink">{r.rate_id}</td>
                    <td className="py-1.5 pr-3 text-ink-soft">{r.description}</td>
                    <td className="tabular py-1.5 pr-3 text-right text-ink-soft">{money(r.rate)}</td>
                    <td className="py-1.5 text-ink-faint">{r.unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-ink-faint">
            Hand-edited in <span className="tabular">client_boq/data/rates.csv</span>. It is the seam a company rate
            database replaces later — nothing downstream reads the file directly.
          </p>
        </Collapse>
      </Card>

      {!result && !running && (
        <EmptyState title="Nothing priced yet">
          Set the duration and margin, then run the schedule. Totals, per-line traces and the rules-engine flags
          appear here.
        </EmptyState>
      )}

      {result && <PricedEstimate estimate={result.estimate} />}

      <div className="flex items-center justify-between gap-3 pt-1">
        <Button variant="ghost" onClick={onBack}>
          ← Scope
        </Button>
        {result && <Button onClick={onContinue}>Workbook and letter →</Button>}
      </div>
    </div>
  );
}
