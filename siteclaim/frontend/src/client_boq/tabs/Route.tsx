// The Route tab — where one tender forks, package by package, into "we build this" or "someone
// quotes us for this".
//
// Three things about this screen are load-bearing, and each of them is a rule the product already
// lives by rather than a decision taken here:
//
//  * THE BILL IS CHOSEN BY A PERSON. Which document produces every priced row is proposed from a
//    part's `category`, and that category was written by an AI interpretation stage. So the screen
//    PROPOSES a set and a human CONFIRMS it. It is a SET, not one document: a bill of quantities
//    and a separate daywork or provisional-items schedule are both priceable.
//  * THE ROUTE IS ADVISORY UNTIL A PERSON SETS IT. Every card shows the recommendation as a
//    recommendation — never pre-applied, never styled like a decision already taken — and the
//    toggle beside it is the decision. The coverage signal underneath is deterministic Layer 1,
//    which is why it is stated as counts rather than as a verdict.
//  * A GATE IS AN EXPLANATION, NOT A DEAD END. Routing sits behind the review gate, so the
//    analysis 409s until the register is approved. The tab opens anyway and says which gate
//    refused and how to clear it, in the backend's own sentence — the same no-padlock rule the
//    step chips follow.
//
// Vocabulary note: the bridge's bill split is NEVER called "scope" here. That word already means
// client_boq's estimate scope on this desk, and one tab strip cannot carry two unrelated things
// under one name.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { SetData } from "../App";
import { api } from "../api";
import { sectionOfKey } from "./Sourcing";
import type {
  BqCandidates,
  BridgeRouteDecisions,
  BridgeRoutePackage,
  BridgeRouteProposalRead,
  JobState,
  ScopePackages,
  SorItem,
} from "../types";
import {
  OpenTab,
  Button,
  Card,
  Chip,
  Collapse,
  Drawer,
  ErrorNote,
  LoadingDots,
  Pill,
  ScanLine,
  SectionLabel,
  WaitingOn,
  cx,
} from "../ui";

export const ROUTE_LABEL: Record<string, string> = {
  self_perform: "Self-perform",
  sublet: "Sublet",
};

// Local rather than imported from procurement's format.ts, for the same reason the bridge types
// are copied rather than imported: this product keeps its own helpers, and a cross-import is the
// beginning of a tangle.
function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}

/** A section header title is stored upper-case (DRILLING); show it in title case. */
function titleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
}

/** The bill lines behind a routing card — for a section sub-package just that section's items.
 *
 *  Reads the section from the KEY when the server did not resolve one: a `trade:SECTION` key with
 *  no section is a contradiction, and treating it as "the whole trade" is what put 145 bill lines
 *  under a card captioned "Section 1 — General and Preliminaries (30 items)". `find` is also
 *  `filter` now, because the split can produce two packages that normalise to one trade. */
function itemsFor(p: BridgeRoutePackage, split: ScopePackages | null): SorItem[] {
  const all = (split?.packages ?? []).filter((x) => x.trade === p.trade)
    .flatMap((x) => x.sor_items ?? []);
  const section = p.section ?? sectionOfKey(p.package_key);
  return section ? all.filter((it) => (it.section ?? "") === section) : all;
}

/** The deterministic coverage signal. Counts, never a verdict — Layer 1 says how many firms exist,
 *  it does not say what to do about it. Neutral panel chips, because a coloured chip here would
 *  imply an authorship or a judgement that these numbers do not carry. */
export function SignalChips({ signals }: { signals: Record<string, number | boolean | string> }) {
  const chip = (label: string, key: string) =>
    signals[key] !== undefined ? (
      <Chip key={key} className="bg-cb-panel text-cb-body">{`${label}: ${String(signals[key])}`}</Chip>
    ) : null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {chip("register firms", "trade_firm_count")}
      {chip("assessable", "assessable_firm_count")}
      {chip("in-house", "in_house_history")}
      {signals.thin_pool ? (
        <Chip className="border border-cb-brass-line text-cb-amber">thin pool</Chip>
      ) : null}
    </div>
  );
}

function Stage({
  n,
  title,
  done,
  children,
}: {
  n: number;
  title: string;
  done?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <span
          className={cx(
            "flex h-5 w-5 items-center justify-center rounded-full font-cb-mono text-[10px]",
            done ? "bg-cb-ok text-white" : "bg-cb-panel text-cb-muted",
          )}
          aria-hidden
        >
          {done ? "✓" : n}
        </span>
        <h3 className="font-cb-serif text-sm font-semibold text-cb-ink-text">{title}</h3>
      </div>
      <div className="pl-7">{children}</div>
    </section>
  );
}

export function RouteTab({
  data,
  onError,
  onRefresh,
  onTrack,
}: {
  data: SetData;
  onError: (message: string) => void;
  onRefresh: () => Promise<void>;
  /** Hand long work to the shell. This tab is where the symptom was reported: the bridge split
   *  is a BLOCKING endpoint with no job id, so `busy` below was the only record it was running —
   *  and `busy` is local state that dies with the tab. The work never stopped; the evidence did. */
  onTrack?: <T,>(label: string, run: () => Promise<T>) => Promise<T>;
}) {
  const setId = data.setId;

  const [candidates, setCandidates] = useState<BqCandidates | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [split, setSplit] = useState<ScopePackages | null>(null);
  const [splitNotes, setSplitNotes] = useState<string[]>([]);
  /** The live split job, while one is running. Null in DEMO, where the split answers inline. */
  const [splitJob, setSplitJob] = useState<JobState | null>(null);
  const [proposal, setProposal] = useState<BridgeRouteProposalRead | null>(null);
  const [decisions, setDecisions] = useState<BridgeRouteDecisions | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  /** The package keys whose toggle a PERSON pressed since the last load/analyze. The confirm
   *  records `chosen` wholesale — defaults included — and the walkthrough (F7) showed that one
   *  click could therefore record the machine's whole proposal as the human's decision with
   *  nothing on screen saying so. This set is what lets the confirm state that honestly. Reset
   *  whenever the toggles are re-seeded, because a re-seed is not a person deciding. */
  const [touched, setTouched] = useState<Set<string>>(new Set());

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "bill" | "split" | "analyze" | "confirm">("");
  const [gate, setGate] = useState("");
  /** Warnings the bridge returned alongside a SUCCESSFUL call — today, the soft review
   *  gate's unread-terms notice. Distinct from `gate` (a refusal) and `error` (a failure):
   *  this is work that went ahead and needs saying so. */
  const [routeNotes, setRouteNotes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<BridgeRoutePackage | null>(null);

  // One load for everything this tab reads back. The proposal and decisions endpoints are pure
  // reads — they never re-run the analysis — so this is safe to call on mount and after each step.
  const load = useCallback(async () => {
    setLoading(true);
    const [cand, spl, prop, dec] = await Promise.all([
      api.bridge.candidates(setId).catch(() => null), // 404 = the set has no parts yet
      api.bridge.split(setId).catch(() => null), // 404 = the split has not been run
      api.bridge.proposal(setId).catch(() => null),
      api.bridge.decisions(setId).catch(() => null),
    ]);
    setCandidates(cand);
    setSplit(spl?.scope ?? null);
    setProposal(prop);
    setDecisions(dec);
    if (cand) setPicked(cand.confirmed.length ? cand.confirmed : cand.proposed);
    if (dec?.decisions.length) {
      setChosen(Object.fromEntries(dec.decisions.map((d) => [d.package_key, d.chosen_route])));
    } else if (prop?.packages.length) {
      // Default the toggles to what was recommended. This is a DEFAULT, not a decision: nothing is
      // recorded until Confirm, and every card still reads "Recommended: …" beside the toggle.
      setChosen(Object.fromEntries(prop.packages.map((p) => [p.package_key, p.recommended_route])));
    }
    setTouched(new Set());
    setLoading(false);
  }, [setId]);

  useEffect(() => {
    void load();
  }, [load]);

  const LABEL: Record<Exclude<typeof busy, "">, string> = {
    bill: "Confirming the priced bill",
    split: "Splitting the bill into packages",
    analyze: "Proposing a route per package",
    confirm: "Recording the routing decisions",
  };

  const run = async (kind: typeof busy, fn: () => Promise<void>) => {
    setBusy(kind);
    setError("");
    // The shell banner too, not just this tab's own: a 409 raised here was reaching
    // `onError` and then outliving the condition it described.
    onError("");
    try {
      await (onTrack ? onTrack(LABEL[kind as Exclude<typeof busy, "">] ?? "Working", fn) : fn());
    } catch (e: unknown) {
      const err = e as Error & { status?: number };
      // A 409 from the review gate is not a failure — it is the gate saying it has not been
      // cleared. Show its own sentence in place, and leave the tab open.
      if (err.status === 409) setGate(err.message);
      else {
        setError(err.message);
        onError(err.message);
      }
    } finally {
      setBusy("");
    }
  };

  const confirmBill = () =>
    run("bill", async () => {
      const next = await api.bridge.confirmBillParts(setId, picked);
      setCandidates(next);
      await onRefresh();
    });

  // Live, the split is a job: it reads every part's pdf and indexes each one, which on a real pack
  // is ~170 documents and minutes of work. So the stage and the per-document count are shown while
  // it runs, and STOP is offered — the same treatment ingest and review already get, rather than a
  // button that goes quiet and a request that never comes back.
  const runSplit = () =>
    run("split", async () => {
      const res = await api.bridge.runSplitToCompletion(setId, setSplitJob);
      setSplitJob(null);
      if (!res) return;            // cancelled — the operator's decision, not a failure
      setSplit(res.scope);
      setSplitNotes(res.notes);
      await onRefresh();
    });

  const cancelSplit = async () => {
    if (splitJob?.job_id) await api.cancelJob(splitJob.job_id).catch(() => undefined);
  };

  const analyze = () =>
    run("analyze", async () => {
      setGate("");
      const res = await api.bridge.analyzeRoutes(setId);
      setProposal({
        set_id: res.set_id,
        run_ref: res.run_ref,
        packages: res.packages,
        // A fresh analysis recomputes BOTH sides from the same split, so nothing can be stale.
        stale_packages: [],
        notes: res.notes ?? [],
        open_queries: res.open_queries,
        review_approved: true,
        has_split: true,
      });
      setChosen(Object.fromEntries(res.packages.map((p) => [p.package_key, p.recommended_route])));
      setTouched(new Set());
      // In soft mode the analyze call SUCCEEDS on an unapproved register and says so in `notes`.
      // That sentence is the entire safety of the soft gate — a bypass nobody is told about is a
      // gate that has silently stopped existing — so it is rendered, never swallowed.
      setRouteNotes(res.notes ?? []);
      await onRefresh();
    });

  const confirmRoutes = () =>
    run("confirm", async () => {
      const body = (proposal?.packages ?? []).map((p) => ({
        package_key: p.package_key,
        chosen_route: chosen[p.package_key] ?? p.recommended_route,
      }));
      const recorded = await api.bridge.confirmRoutes(setId, body);
      setDecisions(recorded);
      // The same warning on the act, not just the advice: confirming a route on unread terms is
      // the moment that matters.
      setRouteNotes(recorded.notes ?? []);
      await onRefresh();
    });

  const billConfirmed = Boolean(candidates?.confirmed.length);

  /** Show every part, not just the ones that could be the bill. */
  const [showAllParts, setShowAllParts] = useState(false);

  /** Which parts this gate actually renders.
   *
   *  A whole-pack archive extract makes this list 206 rows, and the question on screen is "which
   *  document is the priced bill?" — a question 200 drawings and specification appendices do not
   *  help answer. So the default is the parts the interpreter categorised `pricing`, plus anything
   *  already confirmed, plus whatever is currently ticked (a selection must never vanish under the
   *  person making it, which is why `picked` is in here and not just the server's two lists).
   *
   *  The backend is untouched: `candidates_on` still returns everything, because other consumers
   *  read it and a display problem is not a reason to narrow an API.
   *
   *  The honest-degrade case is the important one. When NOTHING is proposed and nothing is
   *  confirmed, the interpreter found no pricing part — the backend's own `message` says so — and
   *  filtering to an empty list would stand the operator in front of a gate with nothing to pick.
   *  There the full list IS the answer, so it renders automatically. */
  const visibleParts = useMemo(() => {
    const all = candidates?.parts ?? [];
    const anyKnown = all.some((p) => p.proposed || p.confirmed);
    if (showAllParts || !anyKnown) return all;
    return all.filter((p) => p.proposed || p.confirmed || picked.includes(p.part_id));
  }, [candidates, showAllParts, picked]);
  const hiddenCount = (candidates?.parts.length ?? 0) - visibleParts.length;
  const decided = Boolean(decisions?.decisions.length);
  const packages = proposal?.packages ?? [];
  const counts = useMemo(() => {
    const self = packages.filter((p) => (chosen[p.package_key] ?? p.recommended_route) === "self_perform").length;
    return { self, sublet: packages.length - self };
  }, [packages, chosen]);

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <LoadingDots label="Reading the bill, the split and any routing already recorded…" />
      </div>
    );
  }

  if (!candidates) {
    return (
      <WaitingOn
        title="Nothing to route yet"
        action={<OpenTab setId={data.setId} tab="documents">Open Documents</OpenTab>}
      >
        This tender has no parts. Upload the documents and approve the split manifest first — the
        bill has to exist before it can be routed.
      </WaitingOn>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-6 p-6">
        {error && <ErrorNote message={error} onDismiss={() => setError("")} />}

        {/* 1 — the human bill gate */}
        <Stage n={1} title="Which document is the priced bill?" done={billConfirmed}>
          <p className="mb-2 text-[12px] text-cb-muted">{candidates.message}</p>
          {candidates.stale_confirmed.length > 0 && (
            <p className="mb-2 text-[11px] text-cb-amber">
              {candidates.stale_confirmed.length} previously confirmed part(s) no longer exist in
              this set: {candidates.stale_confirmed.join(", ")}.
            </p>
          )}
          <div className="space-y-1.5">
            {visibleParts.map((p) => {
              const on = picked.includes(p.part_id);
              return (
                <Card key={p.part_id} selected={on} className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() =>
                      setPicked((cur) =>
                        cur.includes(p.part_id) ? cur.filter((x) => x !== p.part_id) : [...cur, p.part_id],
                      )
                    }
                    className="mt-0.5 accent-[var(--color-cb-brass)]"
                    aria-label={`Use ${p.title} as a priced bill`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
                        {p.title || p.part_id}
                      </span>
                      <Chip className="bg-cb-panel text-cb-muted">{p.category}</Chip>
                      {p.proposed && (
                        // Brass: a model's reading proposed this. Never "confirmed".
                        <Chip className="bg-cb-brass-tint text-cb-brass-text">proposed</Chip>
                      )}
                      {p.confirmed && <Chip className="bg-cb-ok-tint text-cb-ok-dark">confirmed</Chip>}
                      {p.scanned && (
                        <Chip className="border border-cb-brass-line text-cb-amber">scanned</Chip>
                      )}
                      {!p.has_pdf && (
                        <Chip className="bg-cb-bad-tint text-cb-bad-dark">no file — yields nothing</Chip>
                      )}
                    </div>
                    <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">
                      {/* No page count for a workbook: an xlsx has none, and the archive's
                          placeholder bound rendered "1 pages" as though it were measured. */}
                      {p.part_id}
                      {p.pages != null ? ` · ${p.pages} pages` : ""}
                      {p.source_doc ? ` · ${p.source_doc}` : ""}
                    </div>
                    {/* The reason, in words. A bare `scanned` chip reads as "needs OCR" when the
                        real answer is usually "needs the Excel reader" — a different problem with
                        a different answer, and the operator was left to guess which. */}
                    {p.unreadable_reason && (
                      <div className="mt-0.5 font-cb-sans text-[10px] text-cb-amber">
                        {p.unreadable_reason}
                      </div>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
          {(hiddenCount > 0 || showAllParts) && (
            <button
              type="button"
              onClick={() => setShowAllParts((v) => !v)}
              className="cb-press mt-2 font-cb-sans text-[11px] text-cb-navy underline"
            >
              {showAllParts
                ? `Show only the likely bill${candidates.parts.length ? ` (hide ${candidates.parts.length - (candidates.parts.filter((p) => p.proposed || p.confirmed || picked.includes(p.part_id)).length)})` : ""}`
                : `Show all ${candidates.parts.length} parts`}
            </button>
          )}
          <div className="mt-2 flex items-center gap-2">
            <Button
              variant="brass"
              onClick={confirmBill}
              disabled={busy !== "" || picked.length === 0}
              disabledReason={picked.length === 0 ? "Choose at least one part — the bill is what produces every priced line." : undefined}
            >
              {busy === "bill" ? "Confirming…" : billConfirmed ? "Re-confirm bill" : "Confirm bill"}
            </Button>
            <span className="text-[11px] text-cb-faint">
              {picked.length} selected — every confirmed part yields priced lines; the rest become
              context only.
            </span>
          </div>
        </Stage>

        {/* 2 — the split */}
        <Stage n={2} title="Split the bill into trade packages" done={Boolean(split)}>
          {!billConfirmed ? (
            <p className="text-[12px] text-cb-faint">Waits on the bill above.</p>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Button variant={split ? "outline" : "brass"} onClick={runSplit} disabled={busy !== ""}>
                  {busy === "split" ? "Splitting…" : split ? "Re-run the split" : "Run the split"}
                </Button>
                {splitJob && splitJob.status !== "done" && (
                  <>
                    <span className="text-[11px] uppercase tracking-wide text-cb-muted">
                      {splitJob.stage || splitJob.status}
                      {(splitJob.total ?? 0) > 0 && ` · ${splitJob.done}/${splitJob.total} documents`}
                    </span>
                    <Button variant="outline" onClick={cancelSplit} disabled={splitJob.cancel_requested}>
                      {splitJob.cancel_requested ? "Stopping…" : "Stop"}
                    </Button>
                  </>
                )}
                {split && !splitJob && (
                  <span className="text-[11px] text-cb-muted">
                    {split.packages.length} packages ·{" "}
                    {split.packages.reduce((n, p) => n + p.sor_items.length, 0)} priced lines
                  </span>
                )}
              </div>
              {splitNotes.length > 0 && (
                <div className="mt-2">
                  <Collapse title="What the split reported" count={splitNotes.length}>
                    <ul className="space-y-1">
                      {splitNotes.map((n, i) => (
                        <li key={i} className="text-[11px] leading-relaxed text-cb-body">
                          {n}
                        </li>
                      ))}
                    </ul>
                  </Collapse>
                </div>
              )}
            </>
          )}
        </Stage>

        {/* 3 — the proposal, behind the review gate */}
        <Stage n={3} title="Route each package" done={decided}>
          {/* The soft gate's voice. In V1 an unapproved register no longer refuses this step — it
              warns — and this is where the warning has to land, beside the decision it qualifies.
              Amber border and text, no fill: it is not a failure and not a finding, it is the
              condition the work below was done under. Rendered ABOVE the proposal deliberately;
              read after choosing a route it would be an epitaph rather than a warning. */}
          {routeNotes.length > 0 && (
            <div className="mb-3 border border-cb-amber px-3 py-2">
              <div className="font-cb-mono text-[10px] font-semibold tracking-cb-label text-cb-amber">
                READ THIS BEFORE RELYING ON THE ROUTING
              </div>
              {routeNotes.map((n) => (
                <p key={n} className="mt-1 font-cb-sans text-[11px] leading-[1.5] text-cb-amber">
                  {n}
                </p>
              ))}
            </div>
          )}
          {gate ? (
            // The no-padlock rule: the tab stays open and states the gate in the backend's own
            // words, because that sentence names which gate refused and why.
            <Card className="border-cb-brass-line bg-cb-warm">
              <SectionLabel>Waiting on the review gate</SectionLabel>
              <p className="mt-1 text-[12px] leading-relaxed text-cb-body">{gate}</p>
            </Card>
          ) : !split ? (
            <p className="text-[12px] text-cb-faint">Waits on the split above.</p>
          ) : (
            <div className="space-y-3">
              <div className="relative flex flex-wrap items-center justify-between gap-2">
                <ScanLine active={busy === "analyze" || busy === "confirm"} />
                <p className="text-[12px] text-cb-muted">
                  {packages.length ? (
                    <>
                      <span className="font-cb-mono">{proposal?.run_ref}</span> · {packages.length}{" "}
                      packages · {counts.self} self-perform / {counts.sublet} sublet
                    </>
                  ) : (
                    "No routing proposed yet."
                  )}
                </p>
                <div className="flex items-center gap-2">
                  <Button variant="outline" onClick={analyze} disabled={busy !== ""}>
                    {busy === "analyze"
                      ? "Proposing…"
                      : packages.length
                        ? "Re-propose routing"
                        : "Propose routing"}
                  </Button>
                  {packages.length > 0 && (
                    <Button variant="brass" onClick={confirmRoutes} disabled={busy !== ""}>
                      {busy === "confirm" ? "Recording…" : decided ? "Re-confirm routing" : "Confirm routing"}
                    </Button>
                  )}
                </div>
                {/* WHAT THE CONFIRM RECORDS, said before the click (F7). Confirm writes every
                    toggle — the ones a person pressed AND the ones still sitting on the machine's
                    recommendation. Recording the machine's whole proposal in one click is allowed;
                    doing it without saying so is how brass quietly becomes "the human decided". */}
                {packages.length > 0 && (
                  <p className="mt-1.5 font-cb-sans text-[10.5px] text-cb-muted">
                    {(() => {
                      const pressed = packages.filter((p) => touched.has(p.package_key)).length;
                      const defaulted = packages.length - pressed;
                      // After a reload the toggles are seeded from the RECORDED decisions — the
                      // person's own, not the machine's — and the sentence must not confuse the
                      // two: brass is only brass the first time round.
                      const rest = decided ? "as already recorded" : "still on the machine's recommendation";
                      const sentence = defaulted === 0
                        ? `Records ${packages.length} route${packages.length === 1 ? "" : "s"} — every one set by you this visit.`
                        : pressed === 0
                          ? `Records ${packages.length} route${packages.length === 1 ? "" : "s"} — ${rest}, none changed this visit.`
                          : `Records ${packages.length} routes — ${pressed} changed by you this visit, ${defaulted} ${rest}.`;
                      return `${sentence} Re-confirming later replaces these in place.`;
                    })()}
                  </p>
                )}
              </div>

              {/* THE PROPOSAL PREDATES THE SPLIT. Re-running the split rewrites `bridge_scopes`
                  and touches `package_routes` not at all, so a stored row can name a package the
                  current split no longer produces. The backend refuses to confirm one; this says
                  so before the button is pressed, and names them. */}
              {(proposal?.stale_packages?.length ?? 0) > 0 && (
                <Card className="border-cb-brass-line bg-cb-selected">
                  <SectionLabel>This routing predates the current split</SectionLabel>
                  <p className="mt-1 text-[12px] leading-relaxed text-cb-body">
                    {proposal!.stale_packages.length} package(s) below are not in the current scope
                    split — <span className="font-cb-mono">{proposal!.stale_packages.join(", ")}</span>.
                    Re-propose the routing before confirming; confirming is refused until you do.
                  </p>
                </Card>
              )}

              {proposal && proposal.open_queries > 0 && (
                <p className="text-[11px] text-cb-amber">
                  {proposal.open_queries} client question(s) still open — shown, not blocking: an
                  unanswered query does not move the submission deadline.
                </p>
              )}

              {packages.map((p) => {
                const pick = chosen[p.package_key] ?? p.recommended_route;
                const items = itemsFor(p, split);
                const section = p.section ?? sectionOfKey(p.package_key);
                const heading = section
                  ? `${tradeLabel(p.trade)} · ${p.section_title ? titleCase(p.section_title) : `Section ${section}`}`
                  : tradeLabel(p.trade);
                return (
                  <Card key={p.package_key}>
                    <div className="flex flex-wrap items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setDetail(p)}
                            title="Open the routing record"
                            className="text-balance text-left font-cb-sans text-[12px] font-semibold text-cb-ink-text hover:text-cb-brass-text"
                          >
                            {heading}
                          </button>
                          {/* The key ALWAYS renders. It was gated on `p.section`, so the one card
                              whose section failed to resolve was also the one card that did not say
                              which package it was. */}
                          <span className="font-cb-mono text-[10px] text-cb-faint">{p.package_key}</span>
                          {p.stale && (
                            <Chip className="bg-cb-negotiated text-cb-amber">not in the current split</Chip>
                          )}
                          {/* Brass says a model proposed this. It is a RECOMMENDATION and the word
                              stays on the chip, so it can never read as a decision already taken. */}
                          <Chip className="bg-cb-brass-tint text-cb-brass-text">
                            {`Recommended: ${ROUTE_LABEL[p.recommended_route] ?? p.recommended_route}`}
                          </Chip>
                          {/* Navy says a deterministic rule wrote it — the fallback path uses no
                              model at all, so claiming brass here would be a lie. */}
                          {p.source === "fallback" && (
                            <Chip className="bg-cb-info-fill text-cb-navy">rule-based</Chip>
                          )}
                        </div>
                        {p.rationale && (
                          <p className="mt-1 text-[12px] leading-relaxed text-cb-body">{p.rationale}</p>
                        )}
                        {p.scope_summary && (
                          <p className="mt-1 text-[11px] text-cb-faint">{p.scope_summary}</p>
                        )}
                        <div className="mt-2">
                          <SignalChips signals={p.signals} />
                        </div>
                        {items.length > 0 && (
                          <div className="mt-2">
                            <Collapse
                              title={section ? `Section ${section} lines` : "Bill lines"}
                              count={items.length}
                            >
                              <ul className="space-y-1">
                                {items.map((it) => (
                                  <li key={it.item_ref} className="flex gap-2 text-[11px] leading-relaxed">
                                    <span className="shrink-0 font-cb-mono font-semibold text-cb-ink-text">
                                      {it.item_ref}
                                    </span>
                                    <span className="text-cb-body">{it.description}</span>
                                  </li>
                                ))}
                              </ul>
                            </Collapse>
                          </div>
                        )}
                      </div>
                      <div className="flex overflow-hidden rounded-cb-btn border border-cb-border-strong">
                        {["self_perform", "sublet"].map((r) => (
                          <button
                            key={r}
                            onClick={() => {
                              setChosen((cur) => ({ ...cur, [p.package_key]: r }));
                              setTouched((cur) => new Set(cur).add(p.package_key));
                            }}
                            className={cx(
                              "px-3 py-1.5 font-cb-sans text-[11px] font-semibold transition-colors",
                              pick === r
                                ? "bg-cb-ink text-white"
                                : "bg-white text-cb-muted hover:bg-cb-panel",
                            )}
                          >
                            {ROUTE_LABEL[r]}
                          </button>
                        ))}
                      </div>
                    </div>
                  </Card>
                );
              })}

              {decided && (
                <p className="text-[11px] text-cb-ok-dark">
                  Routing recorded. {decisions?.self_perform_packages.length ?? 0} self-perform,{" "}
                  {decisions?.sublet_packages.length ?? 0} sublet — the sublet packages are what the
                  Sourcing tab works from. No estimate is created by this decision on either side.
                </p>
              )}
            </div>
          )}
        </Stage>
      </div>

      <PackageDrawer pkg={detail} decided={decisions} onClose={() => setDetail(null)} />
    </div>
  );
}

/** The routing record for one package: what was recommended, the deterministic signal behind it,
 *  and the human decision once made. */
function PackageDrawer({
  pkg,
  decided,
  onClose,
}: {
  pkg: BridgeRoutePackage | null;
  decided: BridgeRouteDecisions | null;
  onClose: () => void;
}) {
  const decision = pkg
    ? decided?.decisions.find((d) => d.package_key === pkg.package_key) ?? null
    : null;
  return (
    <Drawer
      open={pkg != null}
      onClose={onClose}
      eyebrow="Routing record"
      accent="bg-cb-brass"
      title={pkg ? tradeLabel(pkg.trade) : ""}
      subtitle={pkg && <span className="font-cb-mono">{pkg.package_key}</span>}
      footer="The recommendation is advisory — the record of truth is the human decision, who made it and when."
    >
      {pkg && (
        <div className="space-y-2">
          {pkg.scope_summary && (
            <p className="text-[11px] leading-relaxed text-cb-body">{pkg.scope_summary}</p>
          )}
          <Collapse title="Recommendation (advisory)" defaultOpen>
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip className="bg-cb-brass-tint text-cb-brass-text">
                {ROUTE_LABEL[pkg.recommended_route] ?? pkg.recommended_route}
              </Chip>
              <Chip className="bg-cb-info-fill text-cb-navy">
                {pkg.source === "fallback" ? "rule-based" : pkg.source}
              </Chip>
            </div>
            {pkg.rationale && (
              <p className="mt-1.5 text-[11px] leading-relaxed text-cb-body">{pkg.rationale}</p>
            )}
          </Collapse>

          <Collapse title="Coverage signal (Layer 1)" defaultOpen>
            <SignalChips signals={pkg.signals} />
          </Collapse>

          <Collapse title="Human decision" defaultOpen={Boolean(decision)}>
            {decision ? (
              <div className="text-[11px] leading-relaxed text-cb-body">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Pill className="bg-cb-ok-tint text-cb-ok-dark">
                    {ROUTE_LABEL[decision.chosen_route] ?? decision.chosen_route}
                  </Pill>
                  {decision.chosen_route !== pkg.recommended_route && (
                    <Pill className="border border-cb-brass-line text-cb-amber">override</Pill>
                  )}
                </div>
                <SectionLabel className="mt-2">Decided by</SectionLabel>
                <div className="font-cb-mono text-cb-ink-text">
                  {decision.decided_by}
                  {decision.decided_at ? ` · ${decision.decided_at.slice(0, 10)}` : ""}
                </div>
              </div>
            ) : (
              <p className="text-[11px] text-cb-faint">
                Not decided yet — set the toggle and confirm routing.
              </p>
            )}
          </Collapse>
        </div>
      )}
    </Drawer>
  );
}
