// Costing — the bill in, the priced bill and a live Excel model out.
//
// The screen is laid out in the order somebody actually reads it: what the engine concluded about
// the programme (and whether it trusts itself), then the rates, then the assumptions behind them.
// The workbook download is the deliverable, and it is a MODEL rather than a report — the estimator
// changes a blue cell on 01 Inputs and every rate recalculates in Excel with the app switched off.
//
// Nothing here blocks. The register warns and the checks warn; the sweep is the app's only hard stop.

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { BillPicker } from "../BillPicker";
import { Ask } from "../costing/Ask";
import { Conditions } from "../costing/Conditions";
import { Outstanding } from "../Outstanding";
import type { AssumptionRow, CostingCheck, CostingResponse, PricedRow } from "../types";
import { Button, SectionLabel, WaitingOn, cx, formatNorm, money } from "../ui";

const VERDICTS = ["Accepted", "Revised", "Rejected"];

export function Costing({
  setId,
  onError,
}: {
  setId: string;
  onError: (msg: string) => void;
}) {
  const [data, setData] = useState<CostingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  // The engine failing is NOT the same state as no bill having been imported, and this screen used
  // to render them identically: any throw set `data` to null, so a 500 out of the costing run
  // produced "No bill of quantities yet" with a bill picker under it — a screen actively inviting
  // an estimator to re-import a bill that is already there. `GET /costing` re-runs the whole
  // engine on every read (propose, derive, spread, build, price, assumptions), so there is plenty
  // to throw. The message is kept so the screen can say which of the two happened.
  const [failure, setFailure] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api.costing(setId));
      setFailure("");
    } catch (e) {
      // A set with no bill yet is a state, not a failure — the empty view says what is missing.
      setData(null);
      const message = e instanceof Error ? e.message : String(e);
      if (message.includes("No bill of quantities")) {
        setFailure("");
      } else {
        setFailure(message);
        onError(message);
      }
    } finally {
      setLoading(false);
    }
  }, [setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <WaitingOn title="Running the costing model…">Reading the bill.</WaitingOn>;
  }
  if (!data && failure) {
    // The bill may well be imported and priced. Saying so, and offering the retry rather than the
    // importer, is the difference between a transient fault and a lost afternoon.
    return (
      <div className="flex h-full w-full items-start justify-center overflow-y-auto p-8">
        <div className="w-full max-w-2xl">
          <div className="font-cb-serif text-[17px] font-semibold text-cb-ink-text">
            The costing run did not finish
          </div>
          <p className="mt-2 font-cb-sans text-[11.5px] leading-[1.6] text-cb-muted">
            This is the engine failing, not a missing bill — whatever was imported is still
            imported, and nothing has been lost. The whole model is recomputed on every read, so a
            retry is free and often enough.
          </p>
          <p className="mt-2 font-cb-mono text-[10.5px] leading-[1.55] text-cb-bad-dark">{failure}</p>
          <div className="mt-4">
            <Button variant="dark" onClick={() => void load()}>Try again</Button>
          </div>
        </div>
      </div>
    );
  }
  if (!data) {
    // Not a dead end. This screen used to say "import the client's workbook on the Documents step"
    // — and Documents said "pick one on the Price step". Two screens pointing at each other, and
    // the button on neither. The choice belongs wherever you hit the wall.
    return (
      <div className="flex h-full w-full items-start justify-center overflow-y-auto p-8">
        <div className="w-full max-w-2xl">
          <div className="font-cb-serif text-[17px] font-semibold text-cb-ink-text">
            No bill of quantities yet
          </div>
          <p className="mt-2 font-cb-sans text-[11.5px] leading-[1.6] text-cb-muted">
            The costing engine prices the client's own bill: it reads the drillhole count and the
            soil, rock and hard-material metres out of it, and everything else follows.
          </p>
          <div className="mt-4">
            <BillPicker setId={setId} onImported={load} onError={onError} />
          </div>
        </div>
      </div>
    );
  }

  const { programme, priced, register, spread, buildup } = data;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1080px] p-[18px]">
        <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">
            Costing model
          </h1>
          <span className="font-cb-mono text-[10px] text-cb-muted">
            rev {data.rev} · {data.model.name}
            {data.using_own_model ? " · edited on this tender" : " · from the library"}
          </span>
          <a
            href={api.costingWorkbookUrl(setId)}
            className="cb-press ml-auto rounded-cb-btn bg-cb-brass px-4 py-2 font-cb-sans text-[11px] font-semibold text-cb-on-brass"
          >
            Download the workbook (.xlsx)
          </a>
        </header>
        <p className="mt-1 max-w-[680px] font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          Eight sheets with their formulas intact — a working model, not a report. Change a blue cell
          on <span className="font-cb-mono text-[10px]">01 Inputs</span> and every rate moves, in
          Excel, with this app switched off.
        </p>

        {data.mapping_problems.length > 0 && (
          <Banner tone="warn">
            {data.mapping_problems.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </Banner>
        )}

        {/* ---- what the engine concluded, and whether it trusts itself ---- */}
        <section className="mt-5">
          <SectionLabel>THE PROGRAMME</SectionLabel>
          <div className="mt-2 grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(158px,1fr))]">
            <Figure
              label="rock fraction"
              value={`${(programme.rock_fraction * 100).toFixed(1)}%`}
              note={programme.band ? programme.band.label : "no band"}
            />
            <Figure
              label="work-days (P50)"
              value={programme.work_days.toLocaleString("en-US", { maximumFractionDigits: 0 })}
              note={`P10 ${programme.work_days_p10.toFixed(0)} · P90 ${programme.work_days_p90.toFixed(0)}`}
              strong
            />
            <Figure
              label="rigs"
              value={String(programme.rigs_required)}
              note={`${programme.rigs_exact.toFixed(2)} exact · ${spread.gfts_required} GFT(s) at 1 per ${spread.gft_ratio}`}
            />
            <Figure
              label="site teams"
              value={String(spread.site_teams)}
              note={`${spread.site_count} site(s) × ${spread.site_team_per_site} — not per rig`}
            />
            <Figure
              label="standing time"
              value={programme.standing_hours.toLocaleString("en-US", { maximumFractionDigits: 0 })}
              note="hours"
            />
            <Figure
              label="cost per rig-day"
              value={money(spread.cost_per_rig_day)}
              note={`site team ${money(spread.cost_per_contract_day)} · GFT ${money(spread.cost_per_gft_day)}`}
            />
            <Figure
              label="selling factor"
              value={`×${buildup.selling_factor.toFixed(4)}`}
              note={buildup.markup_steps.map((s) => s.label.toLowerCase()).join(" · ")}
            />
          </div>

          <div className="mt-3 space-y-1.5">
            {data.checks.map((check) => (
              <CheckLine key={check.key} check={check} />
            ))}
          </div>
        </section>

        {/* ---- the rates ---- */}
        <section className="mt-6">
          <SectionLabel>
            THE PRICED BILL · {money(priced.total)}
            {/* The total is the one number somebody reads and remembers, so if part of it was
                invented that has to travel WITH it rather than sit in a panel further down. */}
            {priced.provisional && (
              <span className="ml-2 font-cb-mono text-[9px] font-semibold tracking-cb-chip text-cb-bad-dark">
                PROVISIONAL — {money(priced.placeholder_total)} OF THIS WAS CHOSEN BY NOBODY
              </span>
            )}
            {priced.unpriced.length > 0 && ` · ${priced.unpriced.length} unpriced`}
          </SectionLabel>
          <div className="mt-2 overflow-x-auto rounded-cb-card border border-cb-border bg-cb-page">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-cb-border">
                  {["REF", "DESCRIPTION", "QTY", "UNIT", "COST BASIS", "RATE TO SUBMIT", "AMOUNT"].map(
                    (head, i) => (
                      <th
                        key={head}
                        className={cx(
                          "px-3 py-2 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint",
                          i >= 2 && "text-right",
                        )}
                      >
                        {head}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {priced.rows.map((row) => (
                  <PriceRow
                    key={row.full_ref}
                    row={row}
                    onSubmit={async (rate) => {
                      try {
                        await api.setSubmittedRate(setId, row.full_ref, rate);
                        await load();
                      } catch (e) {
                        onError(e instanceof Error ? e.message : String(e));
                      }
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1.5 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            The rounded figure is a proposal. RATE TO SUBMIT is yours — type over it and the amount
            follows what you actually tender, not what the app suggested.
          </p>
        </section>

        <Outstanding data={data} setId={setId} onChanged={load} onError={onError} />

        {/* ---- the assumptions ---- */}
        <section className="mt-6">
          <SectionLabel>
            THE ASSUMPTIONS REGISTER · {register.summary} ·{" "}
            <span className={register.gate === "CLEARED" ? "text-cb-ok-dark" : "text-cb-amber"}>
              {register.gate}
            </span>
          </SectionLabel>
          <div className="mt-2 rounded-cb-card border border-cb-border bg-cb-page">
            {register.rows.map((row) => (
              <AssumptionLine
                key={row.key}
                row={row}
                onValue={async (value) => {
                  try {
                    await api.setAssumptionValue(setId, row.key, value);
                    await load();
                  } catch (e) {
                    onError(e instanceof Error ? e.message : String(e));
                  }
                }}
                onVerdict={async (status) => {
                  try {
                    await api.setAssumptionVerdict(setId, row.key, status);
                    await load();
                  } catch (e) {
                    onError(e instanceof Error ? e.message : String(e));
                  }
                }}
              />
            ))}
          </div>
          <p className="mt-1.5 max-w-[680px] font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            The register warns; it does not block. But the workbook prints NOT CLEARED until every
            row has a verdict, so a model nobody has reviewed cannot pass for one that somebody has.
            A row whose number is underlined can be typed over — it writes the model input the row
            is about, and everything derived from it recomputes.
          </p>
        </section>

        <Ask setId={setId} onError={onError} onRecorded={load} />

        <Conditions setId={setId} onChanged={load} onError={onError} />
      </div>
    </div>
  );
}

function Figure({
  label,
  value,
  note,
  strong,
}: {
  label: string;
  value: string;
  note?: string;
  strong?: boolean;
}) {
  return (
    <div className="rounded-cb-card border border-cb-border bg-cb-page px-3 py-2">
      <div className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">
        {label.toUpperCase()}
      </div>
      <div
        className={cx(
          "mt-0.5 font-cb-mono font-semibold text-cb-ink-text",
          strong ? "text-[19px]" : "text-[15px]",
        )}
      >
        {value}
      </div>
      {note && <div className="font-cb-sans text-[9px] text-cb-muted">{note}</div>}
    </div>
  );
}

function CheckLine({ check }: { check: CostingCheck }) {
  const tone =
    check.verdict === "stop"
      ? "border-cb-bad bg-cb-bad-tint text-cb-bad-dark"
      : check.verdict === "marginal"
        ? "border-cb-brass-line bg-cb-negotiated text-cb-brass-text"
        : "border-cb-border bg-cb-surface text-cb-muted";
  return (
    <div className={cx("rounded-cb-card border px-3 py-1.5", tone)}>
      <span className="font-cb-mono text-[8px] font-semibold tracking-cb-chip">
        {check.verdict === "stop" ? "DO NOT PRICE" : check.verdict.toUpperCase()}
      </span>
      <p className="font-cb-sans text-[10.5px] leading-[1.5]">{check.message}</p>
    </div>
  );
}

function PriceRow({ row, onSubmit }: { row: PricedRow; onSubmit: (rate: number | null) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const numeric = draft.trim() !== "" && !Number.isNaN(Number(draft));
  const cell = "px-3 py-1.5 font-cb-mono text-[10px]";

  return (
    <tr
      className={cx(
        "cb-row border-b border-cb-divider last:border-0",
        row.source === "unpriced" && "bg-cb-bad-tint",
        // A stand-in carries a number, so it cannot rely on being blank to look unfinished. The
        // stripe is what stops it reading as a priced line at a glance.
        row.source === "placeholder" && "bg-cb-bad-tint/50",
      )}
    >
      <td className={cx(cell, "font-semibold text-cb-ink-text")}>{row.full_ref}</td>
      <td className="px-3 py-1.5">
        <span className="font-cb-sans text-[10.5px] text-cb-body">{row.description}</span>
        {row.note && (
          <div className="font-cb-sans text-[9px] leading-[1.45] text-cb-bad-dark">{row.note}</div>
        )}
        {/* The arithmetic behind a proposed rate. A number an estimator cannot check is a number
            they have to redo, which is the one thing this product cannot afford to make them do. */}
        {row.working && (
          <div className="font-cb-mono text-[8.5px] leading-[1.5] text-cb-muted">{row.working}</div>
        )}
      </td>
      <td className={cx(cell, "text-right text-cb-muted")}>
        {row.lump ? "-" : row.qty?.toLocaleString("en-US")}
      </td>
      <td className={cx(cell, "text-right text-cb-faint")}>{row.unit}</td>
      <td className={cx(cell, "text-right text-cb-muted")}>
        {row.cost_basis === null ? "—" : formatNorm(Number(row.cost_basis.toFixed(2)))}
      </td>
      <td className="px-3 py-1.5 text-right">
        {/* An outstanding line used to render NO RATE as dead text, so the app named a decision and
            gave nowhere to make it — and `price()` discarded a submitted rate on such a line before
            it ever read it. Both halves are fixed; this is the input, and NO RATE is now the
            placeholder inside it rather than a label instead of it. */}
        {editing ? (
          <span className="inline-flex items-center gap-1">
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && numeric) {
                  onSubmit(Number(draft));
                  setEditing(false);
                }
                if (e.key === "Escape") setEditing(false);
              }}
              className={cx(
                "w-[84px] rounded-cb-chip border bg-cb-warm px-1.5 py-0.5 text-right font-cb-mono text-[10px]",
                numeric ? "border-cb-border" : "border-cb-bad",
              )}
            />
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="cb-press font-cb-mono text-[10px] text-cb-muted"
            >
              ×
            </button>
          </span>
        ) : (
          <button
            type="button"
            title={
              row.overridden
                ? `Yours. The proposal was ${row.rate_rounded?.toLocaleString("en-US")}.`
                : "Click to type your own rate"
            }
            onClick={() => {
              setDraft(String(row.rate_to_submit ?? ""));
              setEditing(true);
            }}
            className={cx(
              "cb-press font-cb-mono text-[11px] font-semibold",
              row.source === "unpriced"
                ? "text-cb-bad-dark underline decoration-dotted underline-offset-2"
                : row.overridden
                  ? "text-cb-brass-text underline underline-offset-2"
                  : "text-cb-ink-text",
            )}
          >
            {row.source === "unpriced"
              ? "NO RATE"
              : row.rate_to_submit === null
                ? "—"
                : row.rate_to_submit.toLocaleString("en-US")}
          </button>
        )}
        {row.overridden && (
          <button
            type="button"
            onClick={() => onSubmit(null)}
            title="Put the proposal back"
            className="cb-press ml-1 font-cb-mono text-[8px] text-cb-faint"
          >
            ↺
          </button>
        )}
      </td>
      <td className={cx(cell, "text-right font-semibold text-cb-ink-text")}>
        {row.amount === null ? "—" : money(row.amount)}
      </td>
    </tr>
  );
}

function AssumptionLine({
  row,
  onVerdict,
  onValue,
}: {
  row: AssumptionRow;
  onVerdict: (status: string) => void;
  /** Type over the NUMBER the row is about. Absent when the row names no model path. */
  onValue: (value: number) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const numeric = draft.trim() !== "" && !Number.isNaN(Number(draft));

  // What is typed is what is READ — a percentage row shows 22 and stores 0.22, and the conversion
  // happens in one place so the box and the label can never disagree about which it is.
  const commit = async () => {
    if (!numeric) return;
    setBusy(true);
    try {
      await onValue(row.edit_percent ? Number(draft) / 100 : Number(draft));
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="border-b border-cb-divider px-3 py-2 last:border-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="cb-press min-w-0 flex-1 text-left font-cb-sans text-[11px] text-cb-body"
        >
          {row.label}
          {row.derived && (
            <span
              title="Read from the bill or worked out from it — shown so you can see what the model concluded, not so it can be adjusted."
              className="ml-1.5 font-cb-mono text-[7.5px] font-semibold tracking-cb-chip text-cb-navy"
            >
              DERIVED
            </span>
          )}
        </button>
        {editing ? (
          <span className="flex flex-none items-baseline gap-1">
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void commit();
                if (e.key === "Escape") setEditing(false);
              }}
              className={cx(
                "w-[84px] rounded-cb-chip border bg-cb-warm px-1.5 py-[1px] text-right font-cb-mono text-[10px] text-cb-ink-text",
                numeric ? "border-cb-brass-line" : "border-cb-bad",
              )}
            />
            {row.edit_percent && <span className="font-cb-mono text-[8px] text-cb-faint">%</span>}
            <button
              type="button"
              disabled={busy || !numeric}
              onClick={() => void commit()}
              className="cb-press font-cb-mono text-[8px] font-semibold text-cb-brass-text disabled:text-cb-disabled"
            >
              SET
            </button>
          </span>
        ) : row.edit_path ? (
          <button
            type="button"
            title={`Type over this and the whole model recomputes — it writes ${row.edit_path}.`}
            onClick={() => {
              setDraft(String(row.edit_percent ? "" : ""));
              setEditing(true);
            }}
            className="cb-press flex-none border-b border-dashed border-cb-brass-line font-cb-mono text-[10px] font-semibold text-cb-ink-text"
          >
            {row.value}
          </button>
        ) : (
          <span className="flex-none font-cb-mono text-[10px] font-semibold text-cb-ink-text">
            {row.value}
          </span>
        )}
        <span
          className={cx(
            "flex-none rounded-cb-chip px-1.5 py-[1px] font-cb-mono text-[7.5px] font-semibold tracking-cb-chip",
            row.confidence === "Low"
              ? "bg-cb-brass-tint text-cb-brass-text"
              : "text-cb-faint",
          )}
        >
          {row.confidence.toUpperCase()}
        </span>
        <span className="flex flex-none gap-1">
          {VERDICTS.map((verdict) => (
            <button
              key={verdict}
              type="button"
              onClick={() => onVerdict(row.status === verdict ? "" : verdict)}
              className={cx(
                "cb-press rounded-cb-chip border px-1.5 py-[1px] font-cb-mono text-[8px] font-semibold",
                row.status === verdict
                  ? "border-cb-ok bg-cb-ok-tint text-cb-ok-dark"
                  : "border-cb-border bg-white text-cb-muted",
              )}
            >
              {verdict.slice(0, 3).toUpperCase()}
            </button>
          ))}
        </span>
      </div>
      {open && (
        <p className="mt-1 max-w-[760px] font-cb-serif text-[11px] leading-[1.55] text-cb-body">
          {row.basis}
          {row.edit_path && (
            <span className="ml-2 font-cb-mono text-[9px] text-cb-faint">
              writes {row.edit_path} — the programme, the rig curve and every rate follow
            </span>
          )}
          {row.reviewed_by && (
            <span className="ml-2 font-cb-mono text-[9px] text-cb-faint">
              {row.status} · {row.reviewed_by}
            </span>
          )}
        </p>
      )}
    </div>
  );
}

function Banner({ tone, children }: { tone: "warn"; children: React.ReactNode }) {
  return (
    <div
      className={cx(
        "mt-3 rounded-cb-card border px-3 py-2 font-cb-sans text-[10.5px] leading-[1.55]",
        tone === "warn" && "border-cb-brass-line bg-cb-brass-tint text-cb-brass-text",
      )}
    >
      {children}
    </div>
  );
}
