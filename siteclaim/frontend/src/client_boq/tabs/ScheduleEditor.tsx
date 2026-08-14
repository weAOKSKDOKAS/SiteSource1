// The pricing schedule editor — where a bill of quantities is entered so a LIVE estimate has
// something to price.
//
// `/estimate/run` has always taken `margin_pct` and a structured `schedule` in its request body,
// and DEMO filled both from a fixture. So the whole workflow ran offline and could not run for
// real: there was nowhere to type a quantity. This is that door.
//
// TWO RULES SHAPE EVERY DECISION HERE:
//
//  * IT DOES NOT PRICE AS YOU TYPE. Showing a running total means re-implementing the cost
//    build-up in TypeScript — productivity conversion, inline-over-book precedence,
//    missing-rate-to-zero, rounding — and a pricing screen whose total disagrees with the server's
//    is worse than one that shows no total at all. So this shows the INPUTS and the book's rate
//    (facts, both checkable), and the arithmetic happens once, on the server, where it is tested.
//  * QUANTITIES ARE GIVEN. There is no take-off here, per the locked v1 decision. A quantity is
//    something a person read off a bill and typed; this screen never derives one.

import { useEffect, useMemo, useState } from "react";
import type {
  EstimateScheduleInput,
  IndirectBasis,
  RateRowFull,
  ResourceLineInput,
  ScheduleItemInput,
} from "../types";
import { Button, Chip, SectionLabel, cx, money } from "../ui";

export const EMPTY_SCHEDULE: EstimateScheduleInput = { duration_weeks: null, items: [] };

function newLine(): ResourceLineInput {
  return { description: "", resource_ref: "", inline_rate: null, qty: 0, unit: "", productivity: null };
}

function newItem(category: "direct" | "indirect", n: number): ScheduleItemInput {
  return {
    item_id: `${category === "direct" ? "A" : "I"}${n}`,
    description: "",
    category,
    unit: "",
    lines: category === "direct" ? [newLine()] : [],
    basis: category === "indirect" ? "lump" : "",
    amount: null,
    rate: null,
    pct: null,
  };
}

/** What each indirect basis multiplies, in the words the backend's own `detail` string uses. */
const BASIS_HELP: Record<Exclude<IndirectBasis, "">, string> = {
  lump: "A fixed sum. Priced exactly as entered.",
  per_week: "Rate × the schedule's duration in weeks — so it needs a duration above.",
  pct_of_direct: "A percentage of the direct subtotal, computed after the directs are priced.",
};

export function ScheduleEditor({
  schedule,
  marginPct,
  rates,
  savedAt,
  savedBy,
  dirty,
  busy,
  onChange,
  onMargin,
  onSave,
  onRun,
}: {
  schedule: EstimateScheduleInput;
  marginPct: number;
  rates: RateRowFull[];
  savedAt: string | null;
  savedBy: string;
  dirty: boolean;
  busy: boolean;
  onChange: (next: EstimateScheduleInput) => void;
  onMargin: (pct: number) => void;
  onSave: () => void;
  onRun: () => void;
}) {
  const byId = useMemo(() => {
    const map = new Map<string, RateRowFull>();
    rates.forEach((r) => map.set(r.rate_id, r));
    return map;
  }, [rates]);

  const directs = schedule.items.filter((i) => i.category === "direct");
  const indirects = schedule.items.filter((i) => i.category === "indirect");

  const patchItem = (index: number, patch: Partial<ScheduleItemInput>) =>
    onChange({
      ...schedule,
      items: schedule.items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    });

  const addItem = (category: "direct" | "indirect") =>
    onChange({
      ...schedule,
      items: [
        ...schedule.items,
        newItem(category, (category === "direct" ? directs.length : indirects.length) + 1),
      ],
    });

  const removeItem = (index: number) =>
    onChange({ ...schedule, items: schedule.items.filter((_, i) => i !== index) });

  const needsDuration =
    schedule.duration_weeks == null && indirects.some((i) => i.basis === "per_week");

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      {/* --- the two numbers that frame everything else --- */}
      <div className="border-b border-cb-border bg-cb-panel px-4 py-3">
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1">
            <SectionLabel>DURATION</SectionLabel>
            <span className="flex items-baseline gap-1.5">
              <input
                type="number"
                min={0}
                step={0.5}
                value={schedule.duration_weeks ?? ""}
                placeholder="—"
                onChange={(e) =>
                  onChange({
                    ...schedule,
                    duration_weeks: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
                className="w-[74px] rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1 text-right font-cb-mono text-[12px] text-cb-ink-text"
              />
              <span className="font-cb-sans text-[10.5px] text-cb-muted">weeks</span>
            </span>
          </label>

          <label className="flex flex-col gap-1">
            <SectionLabel>MARGIN</SectionLabel>
            <span className="flex items-baseline gap-1.5">
              <input
                type="number"
                min={0}
                step={0.5}
                value={marginPct}
                onChange={(e) => onMargin(Number(e.target.value))}
                className="w-[64px] rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1 text-right font-cb-mono text-[12px] text-cb-ink-text"
              />
              <span className="font-cb-sans text-[10.5px] text-cb-muted">%</span>
            </span>
          </label>

          <div className="ml-auto flex items-center gap-2">
            {savedAt && (
              <span className="font-cb-mono text-[10px] text-cb-faint">
                SAVED {savedAt.slice(0, 16).replace("T", " ")}
                {savedBy ? ` · ${savedBy.toUpperCase()}` : ""}
              </span>
            )}
            <Button variant="outline" onClick={onSave} disabled={busy || !dirty}>
              {dirty ? "Save" : "Saved"}
            </Button>
            <Button
              variant="brass"
              onClick={onRun}
              disabled={busy || !schedule.items.length || needsDuration}
            >
              {busy ? "Pricing…" : "Price it"}
            </Button>
          </div>
        </div>

        {needsDuration && (
          <p className="mt-2 font-cb-sans text-[10px] text-cb-bad-dark">
            A per-week indirect multiplies by the duration, and there is no duration. Enter one, or
            change that line's basis — the estimate would otherwise price it at nothing without
            saying why.
          </p>
        )}
        <p className="mt-2 font-cb-sans text-[10px] leading-[1.45] text-cb-faint">
          Nothing here is priced until you run it. The cost build-up is deterministic code on the
          server — this screen holds its input, so the two can never disagree.
        </p>
      </div>

      {/* --- direct activities --- */}
      <div className="px-4 py-3">
        <div className="mb-1.5 flex items-center gap-2">
          <SectionLabel>DIRECT ACTIVITIES · {directs.length}</SectionLabel>
          <button
            type="button"
            onClick={() => addItem("direct")}
            className="cb-press ml-auto rounded-cb-btn border border-cb-border-strong bg-white px-2 py-0.5 font-cb-sans text-[10px] text-cb-body"
          >
            + activity
          </button>
        </div>

        {!directs.length && (
          <p className="py-3 font-cb-sans text-[11px] text-cb-muted">
            No activities yet. Each one holds the resource lines that price it.
          </p>
        )}

        {schedule.items.map((item, index) =>
          item.category !== "direct" ? null : (
            <DirectItem
              key={index}
              item={item}
              byId={byId}
              rates={rates}
              onPatch={(patch) => patchItem(index, patch)}
              onRemove={() => removeItem(index)}
            />
          ),
        )}
      </div>

      {/* --- indirects --- */}
      <div className="border-t border-cb-border px-4 py-3">
        <div className="mb-1.5 flex items-center gap-2">
          <SectionLabel>INDIRECTS · {indirects.length}</SectionLabel>
          <button
            type="button"
            onClick={() => addItem("indirect")}
            className="cb-press ml-auto rounded-cb-btn border border-cb-border-strong bg-white px-2 py-0.5 font-cb-sans text-[10px] text-cb-body"
          >
            + indirect
          </button>
        </div>

        {schedule.items.map((item, index) =>
          item.category !== "indirect" ? null : (
            <IndirectItem
              key={index}
              item={item}
              onPatch={(patch) => patchItem(index, patch)}
              onRemove={() => removeItem(index)}
            />
          ),
        )}
      </div>
    </div>
  );
}

function DirectItem({
  item,
  byId,
  rates,
  onPatch,
  onRemove,
}: {
  item: ScheduleItemInput;
  byId: Map<string, RateRowFull>;
  rates: RateRowFull[];
  onPatch: (patch: Partial<ScheduleItemInput>) => void;
  onRemove: () => void;
}) {
  const patchLine = (i: number, patch: Partial<ResourceLineInput>) =>
    onPatch({ lines: item.lines.map((l, n) => (n === i ? { ...l, ...patch } : l)) });

  return (
    <div className="mb-2 rounded-cb-card border border-cb-border bg-cb-page">
      <div className="flex items-center gap-2 border-b border-cb-divider px-2.5 py-2">
        <input
          value={item.item_id}
          onChange={(e) => onPatch({ item_id: e.target.value })}
          className="w-[52px] flex-none rounded-cb-btn border border-cb-border bg-white px-1.5 py-1 font-cb-mono text-[10px] text-cb-muted"
        />
        <input
          value={item.description}
          placeholder="What this activity is"
          onChange={(e) => onPatch({ description: e.target.value })}
          className="min-w-0 flex-1 rounded-cb-btn border border-cb-border bg-white px-2 py-1 font-cb-sans text-[11.5px] text-cb-ink-text"
        />
        <button
          type="button"
          onClick={onRemove}
          title="Remove this activity"
          className="cb-press flex-none rounded-cb-btn px-1.5 py-1 font-cb-mono text-[11px] text-cb-faint hover:text-cb-bad-dark"
        >
          ×
        </button>
      </div>

      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-cb-divider">
            {["RESOURCE", "RATE ID", "QTY", "UNIT", "PROD.", "BOOK RATE", ""].map((h, i) => (
              <th
                key={h || i}
                className={cx(
                  "px-2 pb-1 pt-1.5 font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-faint",
                  i >= 2 && i <= 5 && "text-right",
                )}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {item.lines.map((line, i) => {
            const book = line.resource_ref ? byId.get(line.resource_ref) : undefined;
            // A ref that names nothing in the book prices at zero and flags `missing_rate`. Saying
            // so here — before the run — is the whole point of showing the book rate at all.
            const missing = Boolean(line.resource_ref) && !book;
            return (
              <tr key={i} className="border-b border-cb-divider last:border-0">
                <td className="px-2 py-1">
                  <input
                    value={line.description}
                    placeholder="labour, material, plant…"
                    onChange={(e) => patchLine(i, { description: e.target.value })}
                    className="w-full rounded-cb-btn border border-cb-border bg-white px-1.5 py-0.5 font-cb-sans text-[10.5px]"
                  />
                </td>
                <td className="px-2 py-1">
                  <input
                    list="cb-rate-ids"
                    value={line.resource_ref}
                    placeholder="from the book"
                    onChange={(e) => {
                      const ref = e.target.value;
                      const hit = byId.get(ref);
                      // Adopt the book's unit and description when they are still empty — the rate
                      // book already knows them, and retyping is how they drift apart.
                      patchLine(i, {
                        resource_ref: ref,
                        unit: line.unit || hit?.unit || "",
                        description: line.description || hit?.description || "",
                      });
                    }}
                    className={cx(
                      "w-full rounded-cb-btn border bg-white px-1.5 py-0.5 font-cb-mono text-[10px]",
                      missing ? "border-cb-bad text-cb-bad-dark" : "border-cb-border",
                    )}
                  />
                </td>
                <td className="px-2 py-1 text-right">
                  <input
                    type="number"
                    value={line.qty || ""}
                    onChange={(e) => patchLine(i, { qty: Number(e.target.value) })}
                    className="w-[68px] rounded-cb-btn border border-cb-border bg-white px-1.5 py-0.5 text-right font-cb-mono text-[10px]"
                  />
                </td>
                <td className="px-2 py-1 text-right">
                  <input
                    value={line.unit}
                    onChange={(e) => patchLine(i, { unit: e.target.value })}
                    className="w-[46px] rounded-cb-btn border border-cb-border bg-white px-1.5 py-0.5 text-right font-cb-mono text-[10px]"
                  />
                </td>
                <td className="px-2 py-1 text-right">
                  <input
                    type="number"
                    value={line.productivity ?? ""}
                    placeholder="—"
                    title="Output units per hour. Given, qty ÷ productivity becomes hours and the rate applies to those."
                    onChange={(e) =>
                      patchLine(i, {
                        productivity: e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                    className="w-[56px] rounded-cb-btn border border-cb-border bg-white px-1.5 py-0.5 text-right font-cb-mono text-[10px]"
                  />
                </td>
                <td className="px-2 py-1 text-right">
                  {/* A FACT from the book, not a computed line total — see the header comment. */}
                  {book ? (
                    <span className="font-cb-mono text-[10px] text-cb-body">
                      {money(book.rate)}
                      <span className="ml-1 text-[10px] text-cb-faint">/{book.unit}</span>
                    </span>
                  ) : missing ? (
                    <Chip className="bg-cb-bad-tint font-cb-mono text-[10px] text-cb-bad-dark">
                      NOT IN BOOK
                    </Chip>
                  ) : (
                    <input
                      type="number"
                      value={line.inline_rate ?? ""}
                      placeholder="inline"
                      title="A rate given on the line itself, used when the book has none."
                      onChange={(e) =>
                        patchLine(i, {
                          inline_rate: e.target.value === "" ? null : Number(e.target.value),
                        })
                      }
                      className="w-[74px] rounded-cb-btn border border-cb-border bg-white px-1.5 py-0.5 text-right font-cb-mono text-[10px]"
                    />
                  )}
                </td>
                <td className="px-1 py-1 text-right">
                  <button
                    type="button"
                    onClick={() => onPatch({ lines: item.lines.filter((_, n) => n !== i) })}
                    className="cb-press font-cb-mono text-[10px] text-cb-faint hover:text-cb-bad-dark"
                  >
                    ×
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="px-2.5 py-1.5">
        <button
          type="button"
          onClick={() => onPatch({ lines: [...item.lines, newLine()] })}
          className="cb-press font-cb-sans text-[10px] text-cb-brass-text underline underline-offset-2"
        >
          + resource line
        </button>
      </div>

      {/* The rate book, once, for every rate-id input on the page. */}
      <datalist id="cb-rate-ids">
        {rates.map((r) => (
          <option key={r.rate_id} value={r.rate_id}>
            {r.description} · {money(r.rate)}/{r.unit}
          </option>
        ))}
      </datalist>
    </div>
  );
}

function IndirectItem({
  item,
  onPatch,
  onRemove,
}: {
  item: ScheduleItemInput;
  onPatch: (patch: Partial<ScheduleItemInput>) => void;
  onRemove: () => void;
}) {
  const basis = (item.basis || "lump") as Exclude<IndirectBasis, "">;
  return (
    <div className="mb-2 rounded-cb-card border border-cb-border bg-cb-page px-2.5 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={item.item_id}
          onChange={(e) => onPatch({ item_id: e.target.value })}
          className="w-[52px] flex-none rounded-cb-btn border border-cb-border bg-white px-1.5 py-1 font-cb-mono text-[10px] text-cb-muted"
        />
        <input
          value={item.description}
          placeholder="Site management, insurances, mobilisation…"
          onChange={(e) => onPatch({ description: e.target.value })}
          className="min-w-[160px] flex-1 rounded-cb-btn border border-cb-border bg-white px-2 py-1 font-cb-sans text-[11.5px] text-cb-ink-text"
        />
        <select
          value={basis}
          onChange={(e) => onPatch({ basis: e.target.value as IndirectBasis })}
          className="flex-none rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1 font-cb-mono text-[10px] text-cb-body"
        >
          <option value="lump">lump</option>
          <option value="per_week">per_week</option>
          <option value="pct_of_direct">pct_of_direct</option>
        </select>

        {/* One input, whichever field the chosen basis actually reads. */}
        {basis === "lump" && (
          <NumberField
            label="amount"
            value={item.amount}
            onChange={(v) => onPatch({ amount: v, rate: null, pct: null })}
          />
        )}
        {basis === "per_week" && (
          <NumberField
            label="rate / week"
            value={item.rate}
            onChange={(v) => onPatch({ rate: v, amount: null, pct: null })}
          />
        )}
        {basis === "pct_of_direct" && (
          <NumberField
            label="%"
            value={item.pct}
            onChange={(v) => onPatch({ pct: v, amount: null, rate: null })}
          />
        )}

        <button
          type="button"
          onClick={onRemove}
          className="cb-press flex-none rounded-cb-btn px-1.5 py-1 font-cb-mono text-[11px] text-cb-faint hover:text-cb-bad-dark"
        >
          ×
        </button>
      </div>
      <p className="mt-1 font-cb-sans text-[10px] text-cb-faint">{BASIS_HELP[basis]}</p>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <label className="flex flex-none items-center gap-1">
      <span className="font-cb-mono text-[10px] tracking-cb-chip text-cb-faint">
        {label.toUpperCase()}
      </span>
      <input
        type="number"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-[86px] rounded-cb-btn border border-cb-border bg-white px-1.5 py-1 text-right font-cb-mono text-[10px]"
      />
    </label>
  );
}

/** Was anything actually changed since it was loaded? Compared as JSON because the shape is a
 *  plain data tree — no identity to track, and a deep-equal helper would be more code than this. */
export function scheduleDirty(
  a: { schedule: EstimateScheduleInput; margin: number },
  b: { schedule: EstimateScheduleInput; margin: number },
): boolean {
  return a.margin !== b.margin || JSON.stringify(a.schedule) !== JSON.stringify(b.schedule);
}

/** Hold a schedule being edited, plus whether it differs from what was last saved. */
export function useScheduleDraft(loaded: { schedule: EstimateScheduleInput; margin: number } | null) {
  const [draft, setDraft] = useState<EstimateScheduleInput>(EMPTY_SCHEDULE);
  const [margin, setMargin] = useState(0);
  useEffect(() => {
    if (!loaded) return;
    setDraft(loaded.schedule);
    setMargin(loaded.margin);
  }, [loaded]);
  const dirty = loaded ? scheduleDirty({ schedule: draft, margin }, loaded) : false;
  return { draft, setDraft, margin, setMargin, dirty };
}
