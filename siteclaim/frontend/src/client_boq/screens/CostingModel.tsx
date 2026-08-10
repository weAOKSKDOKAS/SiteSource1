// Library › Costing model — the company's pricing engine, finally editable in the app.
//
// This is the keystone of the library. `Pricing & rates` holds what an hour of a crew costs;
// `Outputs & norms` holds how many hours the work takes; THIS holds how the engine turns the two
// into a bill rate — the production bands, the daily spread, the drivers, the mark-up chain.
// Until now the only way to change any of it was to edit Python, or to hit one specific problem
// on a tender and fix it through the Outstanding panel.
//
// THREE RULES IT KEEPS, all inherited rather than invented here:
//
//   1. ONE-WAY. App → model → Excel. The workbook is a printout; nothing is ever read back from
//      it. What you change here is what the next run prices from, and what the sheet prints.
//   2. THE LIBRARY IS NOT A TENDER. Saving here changes every FUTURE tender and rewrites none
//      already priced — a tender that has touched its model is on a copy of its own.
//   3. CONSEQUENCE BEFORE THE ACT. Every destructive-looking control says what it costs before
//      you press it, in the same voice as the gates.
//
// The input declarations (label, unit, note, percent, key-assumption) come from the backend's
// `model.INPUT_SPECS`, which is the SAME declaration the workbook writes from. There is no second
// copy of that knowledge here on purpose — the two would have drifted the first time somebody
// added a knob.

import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { CostingModelShape, LibraryModelResponse, SpreadLine } from "../types";
import { Button, Card, Consequence, SectionLabel, WaitingOn, cx, money } from "../ui";

const CHARGE_ORDER = ["rig_day", "contract_day", "gft", "prelim", "none"] as const;

export function CostingModelScreen({ onError }: { onError: (msg: string) => void }) {
  const [data, setData] = useState<LibraryModelResponse | null>(null);
  const [draft, setDraft] = useState<CostingModelShape | null>(null);
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const loaded = await api.libraryCostingModel();
        setData(loaded);
        setDraft(loaded.model);
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [onError]);

  const dirty = useMemo(
    () => Boolean(data && draft && JSON.stringify(data.model) !== JSON.stringify(draft)),
    [data, draft],
  );

  if (!data || !draft) {
    return <WaitingOn title="Reading the company's costing model…">One object, all of it yours.</WaitingOn>;
  }

  const setInput = (key: string, value: number) =>
    setDraft({ ...draft, inputs: { ...draft.inputs, [key]: value } });

  const setSpread = (index: number, patch: Partial<SpreadLine>) =>
    setDraft({ ...draft, spread: draft.spread.map((l, i) => (i === index ? { ...l, ...patch } : l)) });

  const save = async () => {
    setBusy(true);
    try {
      const result = await api.saveLibraryCostingModel(draft);
      setData({ ...data, model: draft, problems: result.problems });
      setSavedAt(new Date().toLocaleTimeString());
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const byCharge = CHARGE_ORDER.map((charge) => ({
    charge,
    label: data.charge_labels[charge] ?? charge,
    lines: draft.spread.map((l, i) => ({ line: l, index: i })).filter((r) => r.line.charge === charge),
  })).filter((g) => g.lines.length > 0);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[980px] p-[18px] pb-[120px]">
        <div className="flex items-baseline gap-3">
          <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">Costing model</h1>
          <span className="font-cb-mono text-[10px] text-cb-muted">
            {Object.keys(draft.inputs).length} inputs · {draft.spread.length} spread lines
          </span>
        </div>
        <p className="mt-1 max-w-[680px] font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          How the engine turns quantities into rates. Everything on this page is the company's
          default and is inherited by every new tender; a tender that changes anything is put on a
          copy of its own and stops following this page. The workbook the estimator downloads is a
          printout of exactly these numbers — it is never read back.
        </p>

        {data.problems.length > 0 && (
          <div className="mt-3 rounded-cb-card border border-cb-bad bg-cb-bad-tint px-3 py-2">
            <div className="font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-bad-dark">
              THIS MODEL WILL NOT PRICE
            </div>
            {data.problems.map((p) => (
              <p key={p} className="mt-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-bad-dark">
                {p}
              </p>
            ))}
          </div>
        )}

        {data.retired.length > 0 && (
          <div className="mt-3 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2">
            <div className="font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-brass-text">
              INPUTS NOTHING READS ANY MORE
            </div>
            {data.retired.map((r) => (
              <p key={r.key} className="mt-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text">
                <span className="font-cb-mono">{r.key}</span> = {r.value} — {r.why}
              </p>
            ))}
          </div>
        )}

        {/* ---- the daily spread: the three day-costs, kept apart ---- */}
        <section className="mt-6">
          <SectionLabel>THE SPREAD — WHAT A DAY ON SITE COSTS</SectionLabel>
          <p className="mt-1 max-w-[680px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            Grouped by what each resource is charged to, because merging them is the error that
            costs money. Plant and crew scale with the rig count; the site team manages a site and
            does not move when a rig is added; the GFT manages the rigs at one per{" "}
            <span className="font-cb-mono">gft_ratio</span>. A preliminary is billed as its own item
            and belongs in neither day-cost.
          </p>
          {byCharge.map((group) => {
            const total = group.lines.reduce((sum, r) => sum + r.line.multiplier * r.line.rate, 0);
            const unrated = group.lines.filter((r) => r.line.rate <= 0).length;
            return (
              <div key={group.charge} className="mt-3">
                <div className="flex items-baseline justify-between">
                  <span className="font-cb-sans text-[11px] font-semibold text-cb-ink-text">
                    {group.label}
                  </span>
                  <span className="font-cb-mono text-[11px] font-semibold text-cb-ink-text">
                    {group.charge === "prelim" ? "—" : money(total)}
                    {group.charge !== "prelim" && (
                      <span className="ml-1 text-[8.5px] font-medium text-cb-faint">/ day</span>
                    )}
                  </span>
                </div>
                {unrated > 0 && (
                  <p className="mt-0.5 font-cb-sans text-[10px] text-cb-brass-text">
                    {unrated} line{unrated > 1 ? "s have" : " has"} no rate yet, so anything using
                    {unrated > 1 ? " them" : " it"} prices at nothing. That is deliberate — it is
                    your cost, not a market figure, and guessing it would be worse than a zero
                    somebody can see.
                  </p>
                )}
                <div className="mt-1.5 overflow-x-auto rounded-cb-card border border-cb-border bg-cb-page">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-cb-border">
                        {["RESOURCE", "MULTIPLIER", "RATE ($/day)", "COST ($/day)", "NOTE"].map((h) => (
                          <th
                            key={h}
                            className="px-3 py-2 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {group.lines.map(({ line, index }) => (
                        <tr key={line.key} className="cb-row border-b border-cb-divider last:border-0">
                          <td className="px-3 py-1.5">
                            <span className="font-cb-sans text-[11px] text-cb-body">{line.label}</span>
                            <span className="ml-2 font-cb-mono text-[8px] text-cb-faint">{line.key}</span>
                          </td>
                          <td className="px-3 py-1.5">
                            <NumberCell
                              value={line.multiplier}
                              width="w-[72px]"
                              onChange={(v) => setSpread(index, { multiplier: v })}
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <NumberCell
                              value={line.rate}
                              width="w-[96px]"
                              flag={line.rate <= 0}
                              onChange={(v) => setSpread(index, { rate: v })}
                            />
                          </td>
                          <td className="px-3 py-1.5 text-right font-cb-mono text-[11px] font-semibold text-cb-ink-text">
                            {(line.multiplier * line.rate).toLocaleString("en-US", {
                              maximumFractionDigits: 2,
                            })}
                          </td>
                          <td className="max-w-[280px] px-3 py-1.5 font-cb-sans text-[9.5px] leading-[1.4] text-cb-faint">
                            {line.note}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </section>

        {/* ---- the production bands ---- */}
        <section className="mt-7">
          <SectionLabel>PRODUCTION BANDS — A LOOKUP, NOT A REGRESSION</SectionLabel>
          <p className="mt-1 max-w-[680px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            All-in blended rates: total metres over total work-days, per-hole set-up included. The
            band is selected by the works' own rock fraction, which measures mode of working —
            washboring with a short socket against a coring operation. A rate here is a DIVISOR, so
            metres ÷ rate has to come back to a real day count; that is why the table is on a
            pooled basis rather than a mean of per-hole rates.
          </p>
          <div className="mt-2 overflow-x-auto rounded-cb-card border border-cb-border bg-cb-page">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-cb-border">
                  {["BAND", "FROM (rock %)", "m/WORK-DAY", "n HOLES", "CALIBRATION DEPTH"].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {draft.bands.bands.map((band, i) => (
                  <tr key={band.label} className="cb-row border-b border-cb-divider last:border-0">
                    <td className="px-3 py-1.5 font-cb-sans text-[11px] text-cb-body">{band.label}</td>
                    <td className="px-3 py-1.5 font-cb-mono text-[10px] text-cb-muted">
                      {(band.lower * 100).toFixed(0)}%
                    </td>
                    <td className="px-3 py-1.5">
                      <NumberCell
                        value={band.rate}
                        width="w-[80px]"
                        flag={band.rate <= 0}
                        onChange={(v) =>
                          setDraft({
                            ...draft,
                            bands: {
                              bands: draft.bands.bands.map((b, j) =>
                                j === i ? { ...b, rate: v } : b,
                              ),
                            },
                          })
                        }
                      />
                    </td>
                    <td className="px-3 py-1.5 font-cb-mono text-[10px] text-cb-muted">
                      {band.holes}
                      {band.holes < 10 && (
                        <span className="ml-1.5 text-[8px] font-semibold tracking-cb-chip text-cb-brass-text">
                          INDICATIVE
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 font-cb-mono text-[10px] text-cb-muted">
                      {band.calibration_depth_m ? `${band.calibration_depth_m} m` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* ---- every scalar input, in the blocks the workbook prints them in ---- */}
        {data.input_blocks.map((blockTitle) => {
          const specs = data.input_specs.filter((s) => s.block === blockTitle);
          if (!specs.length) return null;
          return (
            <section key={blockTitle} className="mt-7">
              <SectionLabel>{blockTitle}</SectionLabel>
              <div className="mt-2 grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(300px,1fr))]">
                {specs.map((spec) => (
                  <Card key={spec.key} className={cx(spec.key_assumption && "border-l-[3px] border-l-cb-brass")}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-cb-sans text-[11.5px] font-medium text-cb-ink-text">
                        {spec.label}
                      </span>
                      <NumberCell
                        value={spec.percent ? (draft.inputs[spec.key] ?? 0) * 100 : draft.inputs[spec.key] ?? 0}
                        width="w-[88px]"
                        suffix={spec.percent ? "%" : spec.unit}
                        onChange={(v) => setInput(spec.key, spec.percent ? v / 100 : v)}
                      />
                    </div>
                    {spec.note && (
                      <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.45] text-cb-faint">
                        {spec.note}
                      </p>
                    )}
                  </Card>
                ))}
              </div>
            </section>
          );
        })}

        {/* ---- the mark-up chain, read-only: a loading is not a margin ---- */}
        <section className="mt-7">
          <SectionLabel>THE MARK-UP CHAIN — IN THE ORDER IT IS APPLIED</SectionLabel>
          <p className="mt-1 max-w-[680px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            A <strong>loading</strong> adds to cost (×1 + v). A <strong>margin</strong> is taken on
            the selling price (×1 ÷ (1 − v)). Ten percent is not ten percent: ×1.100 against ×1.111.
            The percentages are edited above under {CHARGE_LABEL_COMMERCIAL}; the kinds and the order
            are structural and are changed in the model, not on a screen.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {draft.markup.map((step) => (
              <Card key={step.key} className="min-w-[190px]">
                <div className="font-cb-sans text-[11px] font-medium text-cb-ink-text">{step.label}</div>
                <div className="mt-0.5 font-cb-mono text-[9px] text-cb-faint">
                  {step.kind === "on_selling" ? "margin — on selling price" : "loading — added to cost"}
                </div>
                <div className="mt-1 font-cb-mono text-[10px] text-cb-muted">
                  {step.components.map((c) => `${(draft.inputs[c] ?? 0) * 100}%`).join(" + ")}
                </div>
              </Card>
            ))}
          </div>
        </section>
      </div>

      {/* ---- the save bar. It says what saving costs before it is pressed. ---- */}
      <div className="sticky bottom-0 border-t border-cb-border bg-cb-panel px-[18px] py-2.5">
        <div className="mx-auto flex max-w-[980px] items-center gap-4">
          <Button variant="brass" onClick={() => void save()} disabled={!dirty || busy}>
            {busy ? "Saving…" : "Save to the library"}
          </Button>
          <Consequence>
            {dirty
              ? "Every tender still on the library's model re-prices from these numbers on its next run. Tenders already on a copy of their own do not move."
              : savedAt
                ? `Saved at ${savedAt}. Nothing has changed since.`
                : "Nothing changed yet."}
          </Consequence>
          {dirty && (
            <button
              type="button"
              onClick={() => setDraft(data.model)}
              className="cb-press ml-auto font-cb-sans text-[10.5px] text-cb-muted underline underline-offset-2"
            >
              Discard my changes
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

const CHARGE_LABEL_COMMERCIAL = "COMMERCIAL";

/** A number you can type into. A non-numeric entry is refused rather than silently becoming 0 —
 *  the same rule the rate book keeps, for the same reason. */
function NumberCell({
  value,
  onChange,
  width,
  suffix,
  flag,
}: {
  value: number;
  onChange: (value: number) => void;
  width: string;
  suffix?: string;
  flag?: boolean;
}) {
  const [text, setText] = useState(String(value));
  const [focused, setFocused] = useState(false);
  const shown = focused ? text : String(value);
  const numeric = !Number.isNaN(Number(shown)) && shown.trim() !== "";

  return (
    <span className="inline-flex items-baseline gap-1">
      <input
        value={shown}
        onFocus={() => {
          setText(String(value));
          setFocused(true);
        }}
        onBlur={() => {
          setFocused(false);
          if (numeric) onChange(Number(text));
        }}
        onChange={(e) => setText(e.target.value)}
        title={numeric ? undefined : "A number, please — a bad entry never silently becomes 0."}
        className={cx(
          "rounded-cb-chip border bg-cb-warm px-2 py-0.5 text-right font-cb-mono text-[11px] text-cb-ink-text",
          width,
          !numeric ? "border-cb-bad" : flag ? "border-cb-brass-line" : "border-cb-border",
        )}
      />
      {suffix && <span className="font-cb-mono text-[8.5px] text-cb-faint">{suffix}</span>}
    </span>
  );
}
