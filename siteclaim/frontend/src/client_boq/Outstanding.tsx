// What is still unpriced, how much of the total nobody chose, and the three ways to fix it.
//
// The design rule, from `how_an_estimator_works.md` Stage 6: an estimator does not price a hundred
// preliminary lines one at a time. They write down the resources standing on site — an office, a
// car, a store — and every bill line falls out of that list times its own duration. So this screen
// leads with the resource list and treats line-by-line entry as the fallback it is.
//
// Three ways to answer a red line, and the screen has to offer all three or it is just a list of
// complaints:
//
//   1. fill in a RESOURCE          → many lines price themselves, showing their working
//   2. point the line at a BASIS   → when the match was wrong, not the number missing
//   3. type a RATE on the line     → the last resort, and always available
//
// And the fourth thing, which is not a fix: a PLACEHOLDER. A stand-in keyed on how a line is
// measured, so a bill reads end to end while the real numbers are found. Every one is counted and
// its money is shown separately, because a number nobody chose must never pass as one somebody did.

import { useMemo, useState } from "react";
import { api } from "./api";
import type { CostingResponse, PricedRow } from "./types";
import { Button, SectionLabel, cx, money } from "./ui";

const BEHAVIOUR: Record<string, { label: string; how: string }> = {
  time: { label: "RUNS WITH TIME", how: "a rate times how long it stands" },
  fixed: {
    label: "ONE-OFF",
    how: "billed as an item, so it takes a lump. SMM S01 ¶1.01A pays these in monthly instalments — they cannot be front-loaded",
  },
  measured: { label: "MEASURED WORK", how: "a rate per unit of whatever is measured" },
};

const ORDER = ["time", "fixed", "measured"];

/** How much of the job a line carries — the reading order, not a price.
 *
 *  A line with no rate has no amount, so this cannot be money. It is the quantity, with
 *  time-related lines lifted above the rest because something running for the length of the
 *  contract is nearly always the bigger exposure. Crude on purpose: it decides what to read first
 *  and nothing else, and a wrong order costs a moment where a wrong number costs a tender. */
function atStake(row: PricedRow): number {
  return row.behaviour === "time" ? (row.qty ?? 1) * 1000 : (row.qty ?? 1);
}

export function Outstanding({
  data,
  setId,
  onChanged,
  onError,
}: {
  data: CostingResponse;
  setId: string;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  const needsWork = useMemo(
    () => data.priced.rows.filter((r) => r.source === "unpriced" || r.source === "placeholder"),
    [data.priced.rows],
  );
  const groups = useMemo(() => {
    const by = new Map<string, PricedRow[]>();
    for (const row of needsWork) {
      const key = row.behaviour || "measured";
      by.set(key, [...(by.get(key) ?? []), row]);
    }
    for (const rows of by.values()) rows.sort((a, b) => atStake(b) - atStake(a));
    return ORDER.filter((k) => by.has(k)).map((k) => [k, by.get(k)!] as const);
  }, [needsWork]);

  const prelims = useMemo(
    () => data.model.spread.filter((line) => line.charge === "prelim"),
    [data.model.spread],
  );
  const unrated = prelims.filter((line) => line.rate <= 0).length;
  const priced = data.priced.total - data.priced.placeholder_total;

  async function patchModel(change: (m: CostingResponse["model"]) => CostingResponse["model"]) {
    setBusy(true);
    try {
      // Copy-on-write: the first edit makes this tender's model its own, so nothing entered here
      // reaches back into the library or another tender.
      await api.saveSetCostingModel(setId, change(data.model));
      await onChanged();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!needsWork.length && !unrated) return null;

  return (
    <section className="mt-6">
      <SectionLabel>Still to price</SectionLabel>

      {/* ---- how much of this total nobody chose ---- */}
      {data.priced.provisional && (
        <div className="mt-2 rounded-cb-card border border-cb-bad bg-cb-bad-tint px-3 py-2">
          <div className="font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-bad-dark">
            PROVISIONAL TOTAL — DO NOT SUBMIT
          </div>
          <p className="mt-1 font-cb-sans text-[11px] leading-[1.55] text-cb-bad-dark">
            <strong>{data.priced.placeholders.length}</strong> lines stand on a placeholder — a
            stand-in for the <em>shape</em> of a line, not an estimate of it.
          </p>
          <div className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 font-cb-mono text-[10px]">
            <span className="text-cb-bad-dark">
              nobody chose {money(data.priced.placeholder_total)}
            </span>
            <span className="text-cb-ink-text">actually priced {money(priced)}</span>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void patchModel((m) => ({ ...m, use_placeholders: !m.use_placeholders }))
            }
            className="cb-press mt-1.5 font-cb-mono text-[9px] font-semibold tracking-cb-chip text-cb-bad-dark underline underline-offset-2"
          >
            SHOW IT WITHOUT PLACEHOLDERS
          </button>
        </div>
      )}

      {/* ---- 1 · the list that prices many lines at once ---- */}
      {prelims.length > 0 && (
        <div className="mt-3 rounded-cb-card border border-cb-border bg-cb-page px-3 py-2.5">
          <div className="font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-muted">
            1 · WHAT IS STANDING ON SITE
          </div>
          <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-muted">
            These are yours — nobody else in the market has them, which is why none is filled in.
            Enter what each costs you and every line using it prices itself, showing its working.
            {unrated > 0 && (
              <>
                {" "}
                <strong className="text-cb-bad-dark">{unrated} still blank.</strong>
              </>
            )}
          </p>
          <div className="mt-2 flex flex-col gap-1">
            {prelims.map((line) => (
              <RateRow
                key={line.key}
                label={line.label}
                unit={line.unit}
                rate={line.rate}
                busy={busy}
                onSave={(rate) =>
                  patchModel((m) => ({
                    ...m,
                    spread: m.spread.map((l) => (l.key === line.key ? { ...l, rate } : l)),
                  }))
                }
              />
            ))}
          </div>
        </div>
      )}

      {/* ---- 2 · the stand-ins ---- */}
      <div className="mt-3 rounded-cb-card border border-cb-border bg-cb-page px-3 py-2.5">
        <div className="font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-muted">
          2 · THE PLACEHOLDERS
        </div>
        <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-muted">
          Keyed on how a line is <strong>measured</strong>, not on what it is called — which is why
          the same short table fills in any bill you insert. Every one of them is wrong for your
          job; they exist so the tender reads end to end while you find the real numbers.
        </p>
        <div className="mt-2 flex flex-col gap-1">
          {data.model.placeholders.map((row) => (
            <RateRow
              key={row.unit || "catch-all"}
              label={row.unit ? `per ${row.unit}` : "anything else"}
              unit={row.label}
              rate={row.rate}
              busy={busy}
              onSave={(rate) =>
                patchModel((m) => ({
                  ...m,
                  placeholders: m.placeholders.map((p) =>
                    p.unit === row.unit ? { ...p, rate } : p,
                  ),
                }))
              }
            />
          ))}
        </div>
      </div>

      {/* ---- 3 · the lines themselves ---- */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="cb-press mt-3 font-cb-mono text-[9px] font-semibold tracking-cb-chip text-cb-brass-text"
      >
        {open ? "▾" : "▸"} 3 · THE {needsWork.length} LINES, BIGGEST FIRST
      </button>

      {open &&
        groups.map(([key, rows]) => (
          <div key={key} className="mt-2">
            <div className="font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint">
              {BEHAVIOUR[key]?.label ?? key} · {rows.length} · {BEHAVIOUR[key]?.how}
            </div>
            <div className="mt-1 flex flex-col">
              {rows.map((row) => (
                <div
                  key={row.full_ref}
                  className="flex flex-wrap items-baseline gap-2 border-b border-cb-divider py-1 last:border-0"
                >
                  <span className="w-[46px] flex-none font-cb-mono text-[9.5px] font-semibold text-cb-ink-text">
                    {row.full_ref}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-cb-sans text-[10.5px] text-cb-body">
                    {row.description}
                  </span>
                  <span className="flex-none font-cb-mono text-[9.5px] text-cb-muted">
                    {row.lump ? "lump" : `${row.qty?.toLocaleString("en-US")} ${row.unit}`}
                  </span>
                  {row.source === "placeholder" && (
                    <span className="flex-none font-cb-mono text-[8.5px] font-semibold text-cb-bad-dark">
                      {money(row.amount ?? 0)} PROVISIONAL
                    </span>
                  )}
                  {row.note && (
                    <span className="w-full font-cb-sans text-[9.5px] leading-[1.45] text-cb-faint">
                      {row.note}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}

      <p className="mt-2 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
        The third way to answer a line is on the table above: click its rate and type your own. A
        rate you type is a selling rate — it is not marked up again, because your margin is already
        in it.
      </p>
    </section>
  );
}

function RateRow({
  label,
  unit,
  rate,
  busy,
  onSave,
}: {
  label: string;
  unit: string;
  rate: number;
  busy: boolean;
  onSave: (rate: number) => void | Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const numeric = draft.trim() !== "" && !Number.isNaN(Number(draft));

  function commit() {
    if (!numeric) return;
    void onSave(Number(draft));
    setDraft("");
  }

  return (
    <div className="flex flex-wrap items-baseline gap-2">
      <span className="min-w-0 flex-1 truncate font-cb-sans text-[10.5px] text-cb-body">
        {label}
      </span>
      <span className="flex-none font-cb-mono text-[9px] text-cb-faint">{unit}</span>
      <span
        className={cx(
          "w-[74px] flex-none text-right font-cb-mono text-[10px] font-semibold",
          rate > 0 ? "text-cb-ink-text" : "text-cb-bad-dark",
        )}
      >
        {rate > 0 ? money(rate) : "not set"}
      </span>
      <input
        value={draft}
        disabled={busy}
        placeholder="your cost"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && commit()}
        className={cx(
          "w-[88px] flex-none rounded-cb-chip border bg-cb-warm px-1.5 py-0.5 text-right font-cb-mono text-[10px]",
          draft && !numeric ? "border-cb-bad" : "border-cb-border",
        )}
      />
      <Button variant="ghost" disabled={busy || !numeric} onClick={commit}>
        Set
      </Button>
    </div>
  );
}
