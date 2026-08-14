// Working (§10) — the screen that decides whether he trusts it.
//
// Renders ENGINE B: `price_bill` over the stored build-ups and rates — the engine the sweep's
// spread and the routed loadings actually reach. This is a different engine from the Costing
// view's (`boq_costing.price`), and until this screen existed its entire surface — the priced
// bill, the checks, the rate trace, the sweep — was curl-only, so every number Phase 1 fixed
// was invisible.
//
// Three parts, per the design:
//   the BILL     every item with its build-up, spread share, routed loading, rate and amount —
//                an unpriced row is red, never blank (GP ¶6 makes it work agreed for free)
//   the WORKING  one item's derivation tree — every leaf says whether it came from a document,
//                a person or the library, a failing leaf paints red in place, and the coverage
//                block underneath lists what the rate must carry (the list is a rule's; the
//                ticks are yours, each with a name and a date)
//   the SWEEP    costs with no bill item, each with its route — the app's ONLY hard stop, and
//                the sentences it refuses with are shown BEFORE the button, unrewritten.

import { useCallback, useEffect, useState } from "react";
import { api, isNotYet, readFailure } from "../api";
import type {
  BillChecksResponse,
  CoverageResponse,
  RateTraceResponse,
  SweepResponse,
  TraceNode,
  WorkingBill,
  WorkingItem,
} from "../types";
import { Button, SectionLabel, WaitingOn, cx, money } from "../ui";

export function WorkingView({
  setId,
  onError,
}: {
  setId: string;
  onError: (msg: string) => void;
}) {
  const [bill, setBill] = useState<WorkingBill | null>(null);
  const [checks, setChecks] = useState<BillChecksResponse | null>(null);
  const [sweep, setSweep] = useState<SweepResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [waiting, setWaiting] = useState("");

  const load = useCallback(async () => {
    try {
      const [b, c, s] = await Promise.all([
        api.workingBill(setId),
        api.billChecks(setId),
        api.sweep(setId),
      ]);
      setBill(b);
      setChecks(c);
      setSweep(s);
      setWaiting("");
    } catch (e) {
      if (isNotYet(e)) {
        setWaiting("no bill of quantities has been imported yet — the working prices the "
          + "client's own bill, so there is nothing to show until one is on the Route step");
      } else {
        onError(readFailure(e));
      }
    }
  }, [setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  if (waiting) return <WaitingOn title="No bill yet">{waiting}</WaitingOn>;
  if (!bill) return <WaitingOn title="Pricing the bill…">Running the stored build-ups.</WaitingOn>;

  const leaf = bill.items.filter((i) => i.qty !== null || i.lump);
  const unpriced = bill.items.filter((i) => i.rate_source === "unpriced");

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1120px] p-[18px]">
        <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">Working</h1>
          <span className="font-cb-mono text-[10px] text-cb-muted">
            rev {bill.rev} · tendered {money(bill.tendered_total)} · spread{" "}
            {money(bill.spread_total)} · loadings {money(bill.loading_total)}
          </span>
          {unpriced.length > 0 && (
            <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-bad-dark">
              {unpriced.length} UNPRICED — GP ¶6 DEEMS EACH COVERED BY THE OTHER RATES
            </span>
          )}
        </header>

        {/* The checks strip: every clause-backed guard, counted. This is where Phase 1's
            loading_unapplied and platform_cost_unconsumed become visible to the person who
            typed the money. */}
        {checks && Object.keys(checks.counts).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(checks.counts).map(([kind, n]) => (
              <span
                key={kind}
                title={checks.flags.find((f) => f.kind === kind)?.message ?? ""}
                className="rounded-cb-chip bg-cb-bad-tint px-2 py-0.5 font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-bad-dark"
              >
                {kind.replace(/_/g, " ").toUpperCase()} · {n}
              </span>
            ))}
          </div>
        )}

        <div className="mt-4 grid gap-4 [grid-template-columns:minmax(380px,5fr)_minmax(320px,4fr)]">
          {/* ---- the bill ---- */}
          <div className="min-w-0 overflow-x-auto rounded-cb-card border border-cb-border bg-cb-page">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-cb-border">
                  {["REF", "DESCRIPTION", "QTY", "RATE", "LOADING", "AMOUNT"].map((h, i) => (
                    <th
                      key={h}
                      className={cx(
                        "px-2.5 py-1.5 font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-faint",
                        i >= 2 && "text-right",
                      )}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {leaf.map((item) => (
                  <BillRow
                    key={item.full_ref}
                    item={item}
                    selected={selected === item.full_ref}
                    onSelect={() =>
                      setSelected((s) => (s === item.full_ref ? null : item.full_ref))
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* ---- the working for the selected item ---- */}
          <div className="min-w-0">
            {selected ? (
              <ItemWorking key={selected} setId={setId} fullRef={selected} onError={onError} />
            ) : (
              <p className="mt-2 font-cb-sans text-[10.5px] leading-[1.6] text-cb-muted">
                Pick an item on the left. Its derivation opens here as a tree — every leaf says
                whether it came from a document, a person or the library, and a leaf that cannot
                say is painted red, because a tree with one unattributed number still looks
                complete, and looking complete is the failure this screen exists to prevent.
              </p>
            )}
          </div>
        </div>

        {/* ---- the sweep ---- */}
        {sweep && <SweepBlock setId={setId} sweep={sweep} onChanged={load} onError={onError} />}
      </div>
    </div>
  );
}

function BillRow({
  item,
  selected,
  onSelect,
}: {
  item: WorkingItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const unpriced = item.rate_source === "unpriced";
  return (
    <tr
      onClick={onSelect}
      className={cx(
        "cb-row cursor-pointer border-b border-cb-divider last:border-b-0",
        selected && "bg-cb-selected",
        unpriced && "bg-cb-bad-tint", // red, never blank — an unpriced row is a promise to work free
      )}
    >
      <td className="px-2.5 py-1.5 font-cb-mono text-[10px] font-semibold text-cb-ink-text">
        {item.full_ref}
      </td>
      <td className="max-w-[240px] truncate px-2.5 py-1.5 font-cb-sans text-[10.5px] text-cb-body">
        {item.description}
      </td>
      <td className="px-2.5 py-1.5 text-right font-cb-mono text-[10px] text-cb-muted">
        {item.lump ? "lump" : item.qty ?? "—"} {item.unit}
      </td>
      <td className="px-2.5 py-1.5 text-right font-cb-mono text-[10.5px] text-cb-ink-text">
        {unpriced ? (
          <span className="font-semibold text-cb-bad-dark">UNPRICED</span>
        ) : item.unit_rate === null ? (
          "-"
        ) : (
          money(item.unit_rate)
        )}
      </td>
      <td className="px-2.5 py-1.5 text-right font-cb-mono text-[10px] text-cb-brass-text">
        {item.loading ? money(item.loading) : ""}
      </td>
      <td className="px-2.5 py-1.5 text-right font-cb-mono text-[10.5px] font-semibold text-cb-ink-text">
        {money(item.amount)}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// One item's working: the tree, then what the rate must cover
// ---------------------------------------------------------------------------
function ItemWorking({
  setId,
  fullRef,
  onError,
}: {
  setId: string;
  fullRef: string;
  onError: (msg: string) => void;
}) {
  const [trace, setTrace] = useState<RateTraceResponse | null>(null);
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, c] = await Promise.all([
        api.rateTrace(setId, fullRef),
        api.rateCoverage(setId, fullRef),
      ]);
      setTrace(t);
      setCoverage(c);
    } catch (e) {
      if (!isNotYet(e)) onError(readFailure(e));
    }
  }, [setId, fullRef, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!trace) return <WaitingOn title="Opening the working…">Reading the trace.</WaitingOn>;

  const t = trace.trace;
  return (
    <div className="rounded-cb-card border border-cb-border bg-cb-page p-3">
      <div className="flex items-baseline gap-2 border-b border-cb-ink-text pb-1.5">
        <span className="font-cb-mono text-[10px] tracking-cb-chip text-cb-faint">RATE</span>
        <span className="font-cb-mono text-[20px] font-semibold text-cb-ink-text">
          {t.rate === null ? "—" : money(t.rate)}
        </span>
        {t.unit && <span className="font-cb-sans text-[10px] text-cb-muted">/ {t.unit}</span>}
        <span className="ml-auto">
          {t.checks.length > 0 && (
            <span className="rounded-cb-chip bg-cb-ok-tint px-1.5 py-0.5 font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-ok-dark">
              ✓ EXTENSION CHECKS
            </span>
          )}
        </span>
      </div>

      {trace.waiting_on ? (
        <p className="mt-2 font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
          {trace.waiting_on}
        </p>
      ) : (
        t.root && <TreeNode node={t.root} depth={0} />
      )}

      {t.problems.length > 0 && (
        <div className="mt-2 rounded-cb-chip border border-cb-bad bg-cb-bad-tint px-2 py-1.5">
          {t.problems.map((p) => (
            <p key={p} className="font-cb-sans text-[10px] leading-[1.5] text-cb-bad-dark">
              {p}
            </p>
          ))}
        </div>
      )}

      {coverage && <CoverageBlock setId={setId} coverage={coverage} onChanged={load} onError={onError} />}
    </div>
  );
}

/** One line of the tree. Indented by depth; the authorship triad carries the meaning: a red
 *  line is a failed check, brass affordances mark what a person can change, and the arithmetic
 *  itself is the rule's. */
function TreeNode({ node, depth }: { node: TraceNode; depth: number }) {
  return (
    <>
      <div
        style={{ paddingLeft: depth * 22 }}
        className={cx(
          "border-b border-cb-divider py-1 last:border-b-0",
          node.problem && "bg-cb-bad-tint",
        )}
      >
        <div className="flex flex-wrap items-baseline gap-x-2">
          {node.op && (
            <span className="font-cb-mono text-[10px] text-cb-muted">{node.op}</span>
          )}
          <span className="font-cb-sans text-[10.5px] font-medium text-cb-ink-text">
            {node.label}
          </span>
          {node.value !== null && (
            <span className="font-cb-mono text-[10.5px] font-semibold text-cb-ink-text">
              {Math.abs(node.value) >= 1000 ? money(node.value) : node.value}
              {node.unit ? ` ${node.unit}` : ""}
            </span>
          )}
          {node.formula && (
            <span className="font-cb-mono text-[10px] text-cb-muted">{node.formula}</span>
          )}
          <span className="ml-auto font-cb-sans text-[10px] font-medium text-cb-brass-text">
            {node.origin === "document" && node.cite
              ? `▸ ${node.cite.label || "show me"}`
              : node.origin === "person"
                ? `${node.owner || "?"} · ▸ change`
                : node.origin === "library"
                  ? `${node.source || "book"} · ▸ change`
                  : ""}
          </span>
        </div>
        {node.note && (
          <p className="mt-0.5 max-w-[520px] font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
            {node.note}
          </p>
        )}
        {node.problem && (
          <p className="mt-0.5 font-cb-sans text-[10px] font-medium leading-[1.4] text-cb-bad-dark">
            ✕ {node.problem}
          </p>
        )}
      </div>
      {node.children.map((child, i) => (
        <TreeNode key={`${child.label}-${i}`} node={child} depth={depth + 1} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// WHAT THIS RATE MUST COVER — the list is a rule's; the ticks are yours
// ---------------------------------------------------------------------------
function CoverageBlock({
  setId,
  coverage,
  onChanged,
  onError,
}: {
  setId: string;
  coverage: CoverageResponse;
  onChanged: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const unticked = coverage.entries.filter((e) => !e.ticked);

  const tick = async (headKey: string, ticked: boolean) => {
    setBusy(true);
    try {
      await api.coverageTick(setId, coverage.full_ref, headKey, ticked);
      await onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 border-t border-cb-border pt-2">
      <div className="flex items-baseline gap-2">
        <SectionLabel>WHAT THIS RATE MUST COVER</SectionLabel>
        <span className="font-cb-mono text-[10px] text-cb-muted">
          {coverage.entries.length} heads
        </span>
        {unticked.length > 0 && (
          <span className="rounded-cb-chip bg-cb-bad-tint px-1.5 font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-bad-dark">
            {unticked.length} NOT COVERED
          </span>
        )}
        <span className="ml-auto font-cb-sans text-[10px] text-cb-faint">
          the list is read from the SMM by a rule · the ticks are yours
        </span>
      </div>

      {coverage.waiting_on && (
        <p className="mt-1 font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
          {coverage.waiting_on}
        </p>
      )}

      {coverage.entries.map((entry) => (
        <div
          key={entry.key}
          className={cx(
            "mt-1 flex items-start gap-2 py-0.5",
            !entry.ticked && "rounded-cb-chip bg-cb-bad-tint px-1.5",
          )}
        >
          <button
            type="button"
            disabled={busy}
            title={entry.ticked ? "Untick — my number does not carry this after all" : "Tick — my number carries this"}
            onClick={() => void tick(entry.key, !entry.ticked)}
            className={cx(
              "cb-press flex-none font-cb-mono text-[11px] font-semibold",
              entry.ticked ? "text-cb-ok" : "text-cb-bad",
            )}
          >
            {entry.ticked ? "✓" : "✕"}
          </button>
          <span className="flex-1 font-cb-sans text-[10px] leading-[1.5] text-cb-body">
            {entry.label}
            {entry.clause_ref && (
              <span className="ml-1.5 font-cb-mono text-[10px] text-cb-muted">
                {entry.clause_ref}
              </span>
            )}
          </span>
          {entry.ticked && entry.ticked_by && (
            <span className="flex-none font-cb-mono text-[10px] text-cb-faint">
              {entry.ticked_by} · {entry.ticked_at?.slice(5, 10)}
            </span>
          )}
        </div>
      ))}

      {coverage.partial && (
        <p className="mt-1.5 font-cb-sans text-[10px] leading-[1.5] text-cb-faint">
          Partial by construction: the pack carries this contract's amendments to the SMM, not
          the SMM itself.
        </p>
      )}
      <p className="mt-1 font-cb-sans text-[10px] leading-[1.5] text-cb-faint">
        A machine cannot know what you put in your number. Unticked heads are not an error; each
        is a decision waiting.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The sweep — the app's only hard stop
// ---------------------------------------------------------------------------
function SweepBlock({
  setId,
  sweep,
  onChanged,
  onError,
}: {
  setId: string;
  sweep: SweepResponse;
  onChanged: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [settleRefusal, setSettleRefusal] = useState("");

  const route = async (cost: SweepResponse["costs"][number], routeTo: string, targetRef = "") => {
    setBusy(true);
    try {
      await api.routeSweepCost(setId, {
        key: cost.key, label: cost.label, amount: cost.amount, source: cost.source,
        route: routeTo, target_ref: targetRef,
        // The accept route demands a reason on the backend; prompt for it there and then —
        // a risk somebody took deliberately and one nobody noticed look identical later.
        reason: routeTo === "accept"
          ? (window.prompt("Accepting this cost as a risk. Why? (recorded beside it)") ?? "")
          : cost.reason,
      });
      setSettleRefusal("");
      await onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const settle = async () => {
    setBusy(true);
    try {
      await api.settleSweep(setId);
      setSettleRefusal("");
      await onChanged();
    } catch (e) {
      // The gate's own sentence, unrewritten, where the button is.
      setSettleRefusal(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-6">
      <div className="flex items-baseline gap-3">
        <SectionLabel>THE SWEEP — COSTS WITH NO BILL ITEM</SectionLabel>
        <span className="font-cb-mono text-[10px] text-cb-muted">
          spread pool {money(sweep.spread_total)} · accepted risk {money(sweep.accepted_risk)}
        </span>
        {sweep.settled ? (
          <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-ok-dark">
            ✓ SETTLED
          </span>
        ) : (
          <span className="ml-auto">
            <Button variant="brass" disabled={busy} onClick={() => void settle()}>
              Settle the sweep — every cost has a route
            </Button>
          </span>
        )}
      </div>
      <p className="mt-1 max-w-[720px] font-cb-sans text-[10px] leading-[1.55] text-cb-muted">
        General Preambles ¶6: an item with no rate is deemed covered by the other rates — so an
        unrouted cost is a promise to do that work for nothing. This is the app's only hard stop.
      </p>

      {settleRefusal && (
        <div className="mt-2 rounded-cb-card border border-cb-bad bg-cb-bad-tint px-3 py-2">
          <p className="font-cb-sans text-[10.5px] leading-[1.55] text-cb-bad-dark">
            {settleRefusal}
          </p>
        </div>
      )}

      {sweep.costs.length === 0 && (
        <p className="mt-2 font-cb-sans text-[10.5px] text-cb-muted">
          No costs listed yet. The sweep can only guard what somebody has written on it.
        </p>
      )}

      {sweep.costs.map((cost) => (
        <div
          key={cost.key}
          className={cx(
            "mt-2 flex flex-wrap items-center gap-2 rounded-cb-card border px-3 py-2",
            cost.route ? "border-cb-border bg-cb-page" : "border-cb-bad bg-cb-bad-tint",
          )}
        >
          <span className="font-cb-sans text-[11px] font-medium text-cb-ink-text">
            {cost.label}
          </span>
          <span className="font-cb-mono text-[10.5px] font-semibold text-cb-ink-text">
            {money(cost.amount)}
          </span>
          {cost.route ? (
            <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-ok-dark">
              {cost.route.toUpperCase()}
              {cost.target_ref ? ` → ${cost.target_ref}` : ""}
              {cost.decided_by ? ` · ${cost.decided_by}` : ""}
            </span>
          ) : (
            <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-bad-dark">
              UNROUTED
            </span>
          )}
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            {sweep.routes.map((r) => (
              <button
                key={r}
                type="button"
                disabled={busy}
                title={sweep.route_meaning[r] ?? r}
                onClick={() => {
                  if (r === "load") {
                    const target = window.prompt(
                      "Load onto which bill item? (its reference, e.g. 2.2b)",
                      cost.target_ref || "");
                    if (target) void route(cost, r, target.trim());
                  } else {
                    void route(cost, r);
                  }
                }}
                className={cx(
                  "cb-press rounded-cb-btn border px-2 py-0.5 font-cb-mono text-[10px] font-semibold tracking-cb-chip",
                  cost.route === r
                    ? "border-cb-ink bg-cb-ink text-white"
                    : "border-cb-border bg-cb-page text-cb-body",
                )}
              >
                {r.toUpperCase()}
              </button>
            ))}
          </span>
          {cost.reason && (
            <p className="basis-full font-cb-sans text-[10px] leading-[1.45] text-cb-muted">
              {cost.reason}
            </p>
          )}
        </div>
      ))}

      {sweep.outstanding.length > 0 && (
        <div className="mt-2">
          {sweep.outstanding.map((line) => (
            <p key={line} className="font-cb-sans text-[10px] leading-[1.5] text-cb-bad-dark">
              {line}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
