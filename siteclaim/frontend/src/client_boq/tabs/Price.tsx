// The Price tab — the priced estimate, and the trace behind every number.
//
// Not in the drawn frames (the handoff says "Not designed yet" for this step and the next), so it
// follows the handoff's own rules rather than inventing new ones. Three carry real weight here:
//
//  * MONO FOR EVERY FIGURE. This is the screen where numbers are compared digit by digit, and the
//    type roles exist precisely so a machine-produced number never wears the same face as prose.
//  * THE PRICE IS ARITHMETIC, NOT A VERDICT. `margin_amount` is a readout — price minus cost —
//    and the backend deliberately refuses to say "profitable" or "thin". Neither does this screen.
//  * A FLAG IS SURFACED, NEVER SUPPRESSED, AND NEVER BLOCKS. The rule layer raises five kinds;
//    each one names its item and says what it means for the number beside it. A missing rate is
//    priced at ZERO and flagged rather than guessed, which is only safe if it is impossible to
//    miss on screen.

import { useCallback, useEffect, useMemo, useState } from "react";
import type { SetData } from "../App";
import { api, runJob } from "../api";
import { Divider, DocTab, Rail, RailFolded, TAB_FOR_JOB, usePanes } from "../chrome";
import { PageView } from "../PageView";
import type {
  CompanySettings,
  CostActivity,
  CostLine,
  EstimateFlag,
  EstimateResponse,
  EstimateScheduleInput,
  JobState,
  RateRowFull,
} from "../types";
import { Button, Chip, SectionLabel, Segmented, WaitingOn, cx, money } from "../ui";
import { Costing } from "./Costing";
import { EMPTY_SCHEDULE, ScheduleEditor, useScheduleDraft } from "./ScheduleEditor";

/** What each rule flag means for the number standing next to it. The backend sends `kind` and a
 *  message about the item; this is the consequence, which is what a reader actually needs. */
const FLAG_COPY: Record<string, { label: string; tone: "bad" | "warn"; consequence: string }> = {
  missing_rate: {
    label: "MISSING RATE",
    tone: "bad",
    consequence: "Priced at zero. The rate book has no id for this resource, and a guessed rate is worse than a visible hole.",
  },
  zero_or_negative_qty: {
    label: "QUANTITY ≤ 0",
    tone: "bad",
    consequence: "Contributes nothing to the total. Either the take-off is wrong or the line does not belong.",
  },
  empty_activity: {
    label: "NO RESOURCE LINES",
    tone: "warn",
    consequence: "An activity that costs nothing. Usually a line somebody meant to fill in.",
  },
  rate_outlier: {
    label: "RATE OUTLIER",
    tone: "warn",
    consequence: "Far from the book rate for its category. Priced as given — this is a prompt to check it, not a correction.",
  },
  unclassified_item: {
    label: "UNCLASSIFIED",
    tone: "warn",
    consequence: "Neither direct nor indirect, so it is priced in neither. Never guessed into one.",
  },
};

function flagCopy(kind: string) {
  return (
    FLAG_COPY[kind] ?? {
      label: kind.toUpperCase().replace(/_/g, " "),
      tone: "warn" as const,
      consequence: "",
    }
  );
}

type PriceView = "costing" | "estimate";

/**
 * Two engines behind one step, while the older one is retired.
 *
 * **Costing** is the current one: it prices the client's bill from a bottom-up build-up and hands
 * back a live Excel model. It needs only the bill, so it deliberately sits OUTSIDE the register and
 * scope gates — reading a bill and costing it is not downstream of either.
 *
 * **Estimate** is the earlier resource-schedule engine, kept until it is deleted so no work in
 * progress is stranded.
 */
export function PriceTab(props: {
  data: SetData;
  /** The run in flight anywhere in this set, from the shell — threaded to the estimate view so
   *  its Run button honours a job it did not start. */
  job?: JobState | null;
  railOpen: boolean;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
  onProgress?: (job: JobState | null) => void;
  /** The shell's job tracker — `keep` in the estimate view runs through it when present. */
  onTrack?: <T>(label: string, run: () => Promise<T>) => Promise<T>;
}) {
  const [view, setView] = useState<PriceView>("costing");
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <div className="flex flex-none items-center gap-2 border-b border-cb-border bg-cb-surface px-4 py-2">
        <Segmented
          value={view}
          options={[
            { value: "costing" as PriceView, label: "COSTING" },
            { value: "estimate" as PriceView, label: "ESTIMATE (OLD)" },
          ]}
          onChange={setView}
        />
        <span className="font-cb-mono text-[9px] text-cb-faint">
          {view === "costing"
            ? "prices the client's bill · needs no gate"
            : "the earlier resource-schedule engine, being retired"}
        </span>
      </div>
      {view === "costing" ? (
        <Costing setId={props.data.setId} onError={props.onError} />
      ) : (
        <EstimateView {...props} />
      )}
    </div>
  );
}

function EstimateView({
  data,
  job,
  railOpen,
  onRefresh,
  onError,
  onProgress,
  onTrack,
}: {
  data: SetData;
  /** The run in flight anywhere in this set, from the shell. A tab's own `busy` flag dies
   *  with the component, so a run started here and navigated away from left this tab able to
   *  offer its Run button again — over a job that was still going, which the server then
   *  refused with a 409 the UI had invited. `busy` covers work THIS mount started; `job`
   *  covers work the set is doing at all. */
  job?: JobState | null;
  railOpen: boolean;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
  onProgress?: (job: JobState | null) => void;
  /** Hand long work to the shell so it stays visible after this tab unmounts. */
  onTrack?: <T,>(label: string, run: () => Promise<T>) => Promise<T>;
}) {
  const [result, setResult] = useState<EstimateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // The shell's job, narrowed to work that belongs to THIS tab. `TAB_FOR_JOB` is the one
  // place that translates a workflow name into a tab, so this cannot drift from the chips.
  const jobRunning =
    !!job &&
    (job.status === "queued" || job.status === "running") &&
    TAB_FOR_JOB[job.kind] === "price";
  // Everything that used to gate on `busy` gates on this instead.
  const running = busy || jobRunning;
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [flagFilter, setFlagFilter] = useState<string | null>(null);
  const [partId, setPartId] = useState<string | null>(null);
  // The schedule is the estimate's INPUT; the estimate is its output. One tab, two modes, because
  // they are the same subject at two stages — and in LIVE you cannot have the second without
  // building the first.
  const [loaded, setLoaded] = useState<{ schedule: EstimateScheduleInput; margin: number } | null>(null);
  const [savedMeta, setSavedMeta] = useState<{ at: string | null; by: string }>({ at: null, by: "" });
  const [rates, setRates] = useState<RateRowFull[]>([]);
  const [company, setCompany] = useState<CompanySettings | null>(null);
  const [mode, setMode] = useState<"estimate" | "schedule">("estimate");
  const { draft, setDraft, margin, setMargin, dirty } = useScheduleDraft(loaded);
  const panes = usePanes("price", 236, 620, railOpen);

  /** The shell's tracker when it was supplied, a pass-through otherwise, so this tab still works
   *  if it is ever rendered outside the desk shell. */
  const keep = <T,>(label: string, run: () => Promise<T>) =>
    onTrack ? onTrack(label, run) : run();

  useEffect(() => {
    let live = true;
    setLoading(true);
    api
      .estimate(data.setId)
      .then((r) => live && setResult(r))
      .catch(() => live && setResult(null)) // 404 = not run yet, which is a state, not an error
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [data.setId, data.hasEstimate]);

  // The schedule, the rate book the editor picks from, and the letterhead the run stamps on.
  useEffect(() => {
    let live = true;
    void api
      .schedule(data.setId)
      .then((r) => {
        if (!live) return;
        setLoaded({ schedule: r.schedule, margin: r.margin_pct });
        setSavedMeta({ at: r.updated_at, by: r.updated_by });
        // Never priced and never scheduled: open on the editor, because that is the only thing
        // there is to do here.
        if (!r.saved) setMode("schedule");
      })
      .catch(() => live && setLoaded({ schedule: EMPTY_SCHEDULE, margin: 0 }));
    void api.rates().then((r) => live && setRates(r.rows.filter((x) => !x.archived)));
    void api.settings().then((s) => live && setCompany(s.company));
    return () => {
      live = false;
    };
  }, [data.setId]);

  // Open on a document, the same as every other tab — the estimate is read beside the tender.
  useEffect(() => {
    const parts = data.parts?.parts ?? [];
    if (!parts.length) return;
    if (!partId || !parts.some((p) => p.part_id === partId)) setPartId(parts[0].part_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.parts]);

  const save = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api.saveSchedule(data.setId, draft, margin);
      setLoaded({ schedule: r.schedule, margin: r.margin_pct });
      setSavedMeta({ at: r.updated_at, by: r.updated_by });
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [data.setId, draft, margin, onError]);

  const run = useCallback(async () => {
    setBusy(true);
    // A new run makes the previous refusal history: clear the shell banner at the START,
    // before the work, so it can never describe a run that has been superseded.
    onError("");
    try {
      // Save first when there are unsaved edits: pricing something the server has not been told
      // about would produce a figure nobody can reproduce from what is stored.
      if (dirty) {
        const r = await api.saveSchedule(data.setId, draft, margin);
        setLoaded({ schedule: r.schedule, margin: r.margin_pct });
        setSavedMeta({ at: r.updated_at, by: r.updated_by });
      }
      // DEMO runs inline and returns the estimate; LIVE queues a job. `runJob` covers both, and
      // `keep` owns it in the shell so navigation does not orphan it. DEMO ignores what is sent
      // and prices its fixture; LIVE requires margin + schedule (it used to 422 because nothing
      // sent them). The letter header is code-injected: the company from app settings, the client
      // and project from THIS tender's desk card, the date today.
      await keep("Pricing the estimate", () =>
        runJob(
          () =>
            api.runEstimate(data.setId, {
              margin_pct: margin,
              schedule: draft,
              letter: {
                ...(company ?? {}),
                project: data.name,
                client_name: data.meta?.client || "the Client",
                date: new Date().toISOString().slice(0, 10),
              },
            }),
          api.estimateStatus,
          onProgress,
        ));
      onProgress?.(null);
      setResult(await api.estimate(data.setId));
      setMode("estimate");
      await onRefresh();
    } catch (e: unknown) {
      onProgress?.(null);
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [company, data, dirty, draft, margin, onError, onProgress, onRefresh]);

  const estimate = result?.estimate ?? null;
  const totals = result?.totals ?? null;

  const flagsByItem = useMemo(() => {
    const map = new Map<string, EstimateFlag[]>();
    (estimate?.flags ?? []).forEach((f) => {
      const list = map.get(f.item_id) ?? [];
      list.push(f);
      map.set(f.item_id, list);
    });
    return map;
  }, [estimate]);

  const shown = useMemo(() => {
    const acts = estimate?.activities ?? [];
    if (!flagFilter) return acts;
    return acts.filter((a) =>
      (flagsByItem.get(a.item_id) ?? []).some((f) => f.kind === flagFilter),
    );
  }, [estimate, flagFilter, flagsByItem]);

  const flagCounts = result?.flag_counts ?? {};
  const totalFlags = Object.values(flagCounts).reduce((n, c) => n + c, 0);

  // --- gates and empty states ----------------------------------------------
  if (!data.gates.review || !data.gates.scope) {
    return (
      <WaitingOn title="The price waits on two gates">
        {!data.gates.review
          ? "The register is not approved yet, so nothing downstream of it can be priced. Approve it on the Register tab."
          : "The scope is not frozen yet. Freezing is what turns every unanswered query into an answer or a stated priced assumption — approve it on the Scope tab."}
      </WaitingOn>
    );
  }

  if (loading) return <WaitingOn title="Reading the estimate…">Loading the cost build-up.</WaitingOn>;

  return (
    <div ref={panes.container} className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      {/* ---------------- pane 1 — the totals, and the flag index ---------------- */}
      {panes.railOpen ? (
        <Rail width={panes.railWidth} onResize={panes.dragRail}>
          <div className="border-b border-cb-border p-3">
            <SectionLabel>THE PRICE</SectionLabel>
            {totals ? (
              <>
                <div className="mt-1.5 font-cb-mono text-[21px] font-semibold leading-none text-cb-ink-text">
                  {money(totals.price)}
                </div>
                <div className="mt-1 font-cb-mono text-[9px] text-cb-faint">
                  COST {money(totals.total_cost)} + {totals.margin_pct}% MARGIN
                </div>
              </>
            ) : (
              <div className="mt-1.5 font-cb-mono text-[15px] text-cb-faint">not run</div>
            )}
          </div>

          {totals && (
            <div className="border-b border-cb-border p-3">
              <SectionLabel>THE BUILD-UP</SectionLabel>
              <dl className="mt-1.5 flex flex-col gap-1">
                <Money label="Direct" value={totals.total_direct} />
                <Money label="Indirect" value={totals.total_indirect} />
                <Money label="Total cost" value={totals.total_cost} strong />
                <Money label={`Margin · ${totals.margin_pct}%`} value={totals.margin_amount} />
                <Money label="Price" value={totals.price} strong />
              </dl>
              {/* The backend refuses to call a margin good or bad. So does this. */}
              <p className="mt-2 font-cb-sans text-[9.5px] leading-[1.45] text-cb-faint">
                Margin is a readout — price less cost. Nothing here judges whether it is enough;
                that is the estimator's call, not arithmetic's.
              </p>
            </div>
          )}

          {totalFlags > 0 && (
            <div className="border-b border-cb-border p-3">
              <SectionLabel>FLAGS · {totalFlags}</SectionLabel>
              <div className="mt-1.5 flex flex-col gap-1">
                {Object.entries(flagCounts).map(([kind, count]) => {
                  const copy = flagCopy(kind);
                  const active = flagFilter === kind;
                  return (
                    <button
                      key={kind}
                      type="button"
                      onClick={() => setFlagFilter(active ? null : kind)}
                      className={cx(
                        "cb-row flex items-center justify-between rounded-cb-btn border px-2 py-1.5 text-left",
                        active ? "border-cb-brass bg-cb-selected" : "border-transparent",
                      )}
                    >
                      <span className="flex items-center gap-1.5">
                        <span
                          className={cx(
                            "h-2 w-2 flex-none rounded-[1px]",
                            copy.tone === "bad" ? "bg-cb-bad" : "bg-cb-amber",
                          )}
                        />
                        <span className="font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-body">
                          {copy.label}
                        </span>
                      </span>
                      <span className="font-cb-mono text-[10px] font-semibold text-cb-ink-text">
                        {count}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 font-cb-sans text-[9.5px] leading-[1.45] text-cb-faint">
                Flags never block a price. They mark the numbers a person should look at before
                signing one.
              </p>
            </div>
          )}

          {estimate?.duration_weeks != null && (
            <div className="p-3">
              <SectionLabel>PROGRAMME</SectionLabel>
              <div className="mt-1 font-cb-mono text-[11px] text-cb-body">
                {estimate.duration_weeks} weeks
              </div>
              <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.45] text-cb-faint">
                What the per-week indirects are multiplied by.
              </p>
            </div>
          )}
        </Rail>
      ) : (
        <RailFolded
          lines={[
            { value: totals ? money(totals.price).replace("HK$", "") : "—", label: "PRICE" },
            { value: String(estimate?.activities.length ?? 0), label: "ITEMS" },
            { value: String(totalFlags), label: "FLAGS" },
          ]}
        />
      )}

      {/* ---------------- pane 2 — the build-up ---------------- */}
      <section
        style={panes.docCollapsed ? undefined : { width: panes.midWidth }}
        className={cx(
          "flex min-w-0 flex-col overflow-hidden border-r border-cb-border bg-cb-surface",
          panes.docCollapsed ? "flex-1" : "flex-none",
        )}
      >
        <header className="flex flex-none flex-wrap items-center gap-2 border-b border-cb-border px-4 py-3">
          <div className="min-w-0 flex-1">
            <SectionLabel>{mode === "schedule" ? "PRICING SCHEDULE" : "PRICED ESTIMATE"}</SectionLabel>
            <h2 className="mt-0.5 font-cb-serif text-[17px] font-semibold text-cb-ink-text">
              {mode === "schedule"
                ? `${draft.items.filter((i) => i.category === "direct").length} activities, ${draft.items.filter((i) => i.category === "indirect").length} indirect${draft.items.filter((i) => i.category === "indirect").length === 1 ? "" : "s"}`
                : estimate
                  ? `${estimate.activities.length} activities, ${estimate.indirects.length} indirect${estimate.indirects.length === 1 ? "" : "s"}`
                  : "Not priced yet"}
            </h2>
          </div>

          {/* Input and output of the same thing — so one control, not two screens. */}
          <div className="flex flex-none rounded-cb-btn border border-cb-border-strong">
            {(["schedule", "estimate"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={cx(
                  "cb-press px-2.5 py-1 font-cb-sans text-[10.5px] font-medium first:rounded-l-cb-btn last:rounded-r-cb-btn",
                  mode === m ? "bg-cb-ink text-white" : "bg-white text-cb-body",
                )}
              >
                {m === "schedule" ? `Schedule${dirty ? " •" : ""}` : "Estimate"}
              </button>
            ))}
          </div>

          {mode === "estimate" && estimate && (
            <a
              href={api.workbookUrl(data.setId)}
              className="cb-press flex-none rounded-cb-btn border border-cb-border-strong bg-white px-3 py-1.5 font-cb-sans text-[10.5px] font-medium text-cb-ink-text"
            >
              Workbook (.xlsx)
            </a>
          )}
          {mode === "estimate" && (
            <Button variant={estimate ? "outline" : "brass"} onClick={() => void run()} disabled={running}>
              {busy ? "Pricing…" : estimate ? "Re-run" : "Run the estimate"}
            </Button>
          )}
        </header>

        {mode === "schedule" ? (
          <ScheduleEditor
            schedule={draft}
            marginPct={margin}
            rates={rates}
            savedAt={savedMeta.at}
            savedBy={savedMeta.by}
            dirty={dirty}
            busy={busy}
            onChange={setDraft}
            onMargin={setMargin}
            onSave={() => void save()}
            onRun={() => void run()}
          />
        ) : !estimate && running ? (
          <div className="p-5">
            <WaitingOn title="The estimate is running">
              Building the cost spine. It keeps going if you navigate away — the strip above
              follows it, and stops it.
            </WaitingOn>
          </div>
        ) : !estimate ? (
          <div className="p-5">
            <WaitingOn title="The estimate has not been run">
              Both gates are passed, so it can run now. The cost spine is deterministic — quantities
              × rates from the book, indirects by their stated basis, then the margin. No model
              touches a number.
              {!loaded?.schedule.items.length && (
                <>
                  {" "}
                  Offline it prices a sample schedule; against a real tender it needs yours, which
                  you build under <strong>Schedule</strong>.
                </>
              )}
            </WaitingOn>
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto">
            {flagFilter && (
              <div className="flex items-center gap-2 border-b border-cb-brass-line bg-cb-brass-tint px-4 py-2">
                <span className="font-cb-mono text-[9px] font-semibold tracking-cb-chip text-cb-brass-text">
                  SHOWING {flagCopy(flagFilter).label} ONLY
                </span>
                <button
                  type="button"
                  onClick={() => setFlagFilter(null)}
                  className="cb-press ml-auto font-cb-sans text-[10px] text-cb-brass-text underline underline-offset-2"
                >
                  show everything
                </button>
              </div>
            )}

            {shown.map((activity) => (
              <ActivityRow
                key={activity.item_id}
                activity={activity}
                flags={flagsByItem.get(activity.item_id) ?? []}
                expanded={open.has(activity.item_id)}
                onToggle={() =>
                  setOpen((cur) => {
                    const next = new Set(cur);
                    if (next.has(activity.item_id)) next.delete(activity.item_id);
                    else next.add(activity.item_id);
                    return next;
                  })
                }
              />
            ))}

            {!shown.length && (
              <p className="px-4 py-6 font-cb-sans text-[11px] text-cb-muted">
                No activity carries that flag.
              </p>
            )}

            {/* indirects */}
            {!flagFilter && estimate.indirects.length > 0 && (
              <div className="border-t-[3px] border-cb-border-strong">
                <div className="px-4 pb-1 pt-3">
                  <SectionLabel>INDIRECTS</SectionLabel>
                </div>
                {estimate.indirects.map((line) => (
                  <div
                    key={line.item_id || line.label}
                    className="flex items-baseline gap-3 border-b border-cb-divider px-4 py-2.5"
                  >
                    <span className="w-[64px] flex-none font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint">
                      {line.basis.toUpperCase().replace(/_/g, " ")}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block font-cb-sans text-[11.5px] text-cb-ink-text">
                        {line.label}
                      </span>
                      {/* The backend writes this so the number can be recomputed by hand. */}
                      <span className="block font-cb-mono text-[9.5px] text-cb-muted">
                        {line.detail}
                      </span>
                    </span>
                    <span className="flex-none font-cb-mono text-[12px] font-semibold text-cb-ink-text">
                      {money(line.amount)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* the footer — where the price actually comes from */}
            {!flagFilter && totals && (
              <div className="border-t-[3px] border-cb-border-strong bg-cb-panel px-4 py-3">
                <dl className="flex flex-col gap-1">
                  <Money label="Direct" value={totals.total_direct} />
                  <Money label="Indirect" value={totals.total_indirect} />
                  <Money label="Total cost" value={totals.total_cost} strong />
                  <Money label={`Margin · ${totals.margin_pct}%`} value={totals.margin_amount} />
                </dl>
                <div className="mt-2 flex items-baseline justify-between border-t border-cb-border-strong pt-2">
                  <span className="font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-faint">
                    PRICE
                  </span>
                  <span className="font-cb-mono text-[19px] font-semibold text-cb-ink-text">
                    {money(totals.price)}
                  </span>
                </div>
                {/* Consequence is capped at 180px by design — it belongs beside a gate button.
                    Here the note runs the width of the column. */}
                <p className="mt-2 font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
                  This is the figure the offer letter carries. Editing it means changing a quantity,
                  a rate or the margin and re-running — never typing over the total.
                </p>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ---------------- pane 3 — the document ---------------- */}
      {panes.docCollapsed ? (
        <DocTab onOpen={panes.openDoc} label="DOCUMENT" />
      ) : (
        <>
          <Divider onDrag={panes.dragMiddle} />
          <PageView
            setId={data.setId}
            parts={data.parts?.parts ?? []}
            partId={partId}
            page={null}
            onPartChange={setPartId}
          />
        </>
      )}
    </div>
  );
}

/** One priced activity, with its resource lines behind a disclosure. Collapsed by default: a
 *  reader wants the shape of the estimate first and the arithmetic on demand. */
function ActivityRow({
  activity,
  flags,
  expanded,
  onToggle,
}: {
  activity: CostActivity;
  flags: EstimateFlag[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const worst = flags.some((f) => flagCopy(f.kind).tone === "bad");
  return (
    <div className={cx("border-b border-cb-border", worst && "bg-cb-bad-tint/40")}>
      <button
        type="button"
        onClick={onToggle}
        className="cb-row flex w-full items-baseline gap-3 px-4 py-2.5 text-left"
      >
        <span className="w-[52px] flex-none font-cb-mono text-[10px] font-semibold text-cb-muted">
          {activity.item_id}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-cb-sans text-[11.5px] text-cb-ink-text">
            {activity.description}
          </span>
          {flags.length > 0 && (
            <span className="mt-0.5 flex flex-wrap gap-1">
              {flags.map((f, i) => {
                const copy = flagCopy(f.kind);
                return (
                  <span
                    key={i}
                    title={f.message}
                    className={cx(
                      "rounded-cb-chip px-1.5 py-[1px] font-cb-mono text-[8px] font-semibold tracking-cb-chip",
                      copy.tone === "bad"
                        ? "bg-cb-bad-tint text-cb-bad-dark"
                        : "bg-cb-brass-tint text-cb-brass-text",
                    )}
                  >
                    {copy.label}
                  </span>
                );
              })}
            </span>
          )}
        </span>
        <span className="flex-none font-cb-mono text-[12px] font-semibold text-cb-ink-text">
          {money(activity.activity_total)}
        </span>
        <span className="w-3 flex-none font-cb-mono text-[10px] text-cb-faint">
          {expanded ? "−" : "+"}
        </span>
      </button>

      <div className="cb-expand" data-open={expanded}>
        <div>
          <div className="px-4 pb-3">
            {flags.map((f, i) => {
              const copy = flagCopy(f.kind);
              return copy.consequence ? (
                <p
                  key={i}
                  className={cx(
                    "mb-1.5 rounded-cb-btn px-2 py-1.5 font-cb-sans text-[10px] leading-[1.45]",
                    copy.tone === "bad"
                      ? "bg-cb-bad-tint text-cb-bad-dark"
                      : "bg-cb-brass-tint text-cb-brass-text",
                  )}
                >
                  <span className="font-cb-mono text-[8px] font-semibold tracking-cb-chip">
                    {copy.label}
                  </span>{" "}
                  — {copy.consequence}
                </p>
              ) : null;
            })}
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-cb-divider">
                  {["RESOURCE", "QTY", "RATE", "FROM", "AMOUNT"].map((h, i) => (
                    <th
                      key={h}
                      className={cx(
                        "pb-1 font-cb-mono text-[7.5px] font-semibold tracking-cb-chip text-cb-faint",
                        i > 0 && "text-right",
                      )}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {activity.lines.map((line, i) => (
                  <LineRow key={`${line.resource_ref}-${i}`} line={line} />
                ))}
                {!activity.lines.length && (
                  <tr>
                    <td colSpan={5} className="py-2 font-cb-sans text-[10px] text-cb-muted">
                      No resource lines — this activity costs nothing.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

/** One resource line. The whole row is the trace: qty (converted through productivity when there
 *  is one), the rate, WHERE the rate came from, and the amount. */
function LineRow({ line }: { line: CostLine }) {
  const missing = line.rate_source === "missing";
  return (
    <tr className="border-b border-cb-divider last:border-0">
      <td className="py-1.5">
        <span className="block font-cb-sans text-[10.5px] text-cb-body">{line.description}</span>
        {line.resource_ref && (
          <span className="block font-cb-mono text-[8.5px] text-cb-faint">{line.resource_ref}</span>
        )}
      </td>
      <td className="py-1.5 text-right font-cb-mono text-[10px] text-cb-body">
        {line.qty.toLocaleString("en-US")}
        {line.unit && <span className="ml-1 text-[8.5px] text-cb-faint">{line.unit}</span>}
        {/* qty ÷ productivity = hours. Shown because the hours are what the rate multiplies. */}
        {line.hours != null && (
          <span className="block text-[8.5px] text-cb-muted">
            ÷ {line.productivity} = {line.hours.toLocaleString("en-US")} hr
          </span>
        )}
      </td>
      <td className="py-1.5 text-right font-cb-mono text-[10px] text-cb-body">
        {missing ? "—" : line.rate.toLocaleString("en-US")}
      </td>
      <td className="py-1.5 text-right">
        <Chip
          className={cx(
            "font-cb-mono text-[7.5px]",
            missing
              ? "bg-cb-bad-tint text-cb-bad-dark"
              : line.rate_source === "inline"
                ? "bg-cb-info-fill text-cb-navy"
                : "bg-cb-panel text-cb-muted",
          )}
          title={
            missing
              ? "No rate with this id in the book — priced at zero rather than guessed."
              : line.rate_source === "inline"
                ? "A rate given on the line itself, overriding the book."
                : "From the rate book."
          }
        >
          {missing ? "MISSING" : line.rate_source === "inline" ? "INLINE" : "BOOK"}
        </Chip>
      </td>
      <td
        className={cx(
          "py-1.5 text-right font-cb-mono text-[10.5px] font-semibold",
          missing ? "text-cb-bad-dark" : "text-cb-ink-text",
        )}
      >
        {money(line.amount)}
      </td>
    </tr>
  );
}

function Money({ label, value, strong }: { label: string; value: number; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt
        className={cx(
          "font-cb-sans text-[10.5px]",
          strong ? "font-semibold text-cb-ink-text" : "text-cb-muted",
        )}
      >
        {label}
      </dt>
      <dd
        className={cx(
          "font-cb-mono tabular-nums",
          strong ? "text-[12px] font-semibold text-cb-ink-text" : "text-[11px] text-cb-body",
        )}
      >
        {money(value)}
      </dd>
    </div>
  );
}
