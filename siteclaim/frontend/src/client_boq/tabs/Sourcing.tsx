// The Sourcing tab — everything that happens to the packages we decided to SUBLET.
//
// Four steps behind one tab rather than four more tabs, because they were already a wizard with a
// stepper of their own: shortlist → dispatch → level → recommend.
//
// Three things this container is responsible for, each of them a rule rather than a convenience:
//
//  * ONLY SUBLET PACKAGES REACH HERE. The route decision is the filter, read from the bridge. A
//    self-perform package is priced in-house and has no business on a shortlist.
//  * THE TAB OWNS ITS FETCHING. In the wizard, StepDispatch fetched its own attachment plan,
//    breaking the presentational contract every other step kept. Here the container fetches and
//    the steps take props — the way every other cb tab works.
//  * THE SOURCING SCOPE IS A PROJECTION, NOT A FACT. It is derived client-side from the split plus
//    the decisions: sublet units re-keyed so `trade` becomes `package_key`, items filtered by
//    section, so a split tender sources each section as its own package with its own shortlist.
//    There is deliberately no endpoint for it.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { SetData } from "../App";
import { api } from "../api";
import type {
  BridgeRouteProposalRead,
  DispatchSet,
  ScopePackages,
  SectionPlan,
  ShortlistSet,
  Coverage,
} from "../types";
import { Button, ErrorNote, LoadingDots, WaitingOn, cx } from "../ui";
import { Dispatch, type Draft } from "./sourcing/Dispatch";
import { Shortlist } from "./sourcing/Shortlist";

type StepId = "shortlist" | "dispatch" | "level" | "recommend";

const STEPS: { id: StepId; label: string }[] = [
  { id: "shortlist", label: "Shortlist" },
  { id: "dispatch", label: "Dispatch" },
  { id: "level", label: "Level & compare" },
  { id: "recommend", label: "Award" },
];

/** The sublet-only scope, re-keyed for sourcing.
 *
 *  Ported verbatim in behaviour from the wizard: a section sub-package carries its `package_key`
 *  as its trade (the sourcing key) and only its own section's items; a whole package is unchanged.
 *  That is what lets one tender run a separate shortlist, dispatch and award per section. */
export function sourcingScope(
  split: ScopePackages | null,
  proposal: BridgeRouteProposalRead | null,
  subletKeys: string[],
): ScopePackages | null {
  if (!split || !proposal) return null;
  const wanted = new Set(subletKeys);
  const packages = proposal.packages
    .filter((p) => wanted.has(p.package_key))
    .map((p) => {
      const parent = split.packages.find((x) => x.trade === p.trade);
      const items = p.section
        ? (parent?.sor_items ?? []).filter((it) => (it.section ?? "") === p.section)
        : (parent?.sor_items ?? []);
      return {
        trade: p.package_key,
        scope_summary: p.scope_summary,
        sor_items: items,
        source_refs: parent?.source_refs ?? [],
        sections: parent?.sections ?? [],
      };
    });
  return { project_name: split.project_name, packages };
}

export function SourcingTab({
  data,
  demoMode,
  onError,
}: {
  data: SetData;
  demoMode: boolean;
  onError: (message: string) => void;
}) {
  const setId = data.setId;

  const [step, setStep] = useState<StepId>("shortlist");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [split, setSplit] = useState<ScopePackages | null>(null);
  const [proposal, setProposal] = useState<BridgeRouteProposalRead | null>(null);
  const [sublet, setSublet] = useState<string[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);

  // The state the wizard held in App.tsx, lifted here so the tab owns its own.
  const [shortlist, setShortlist] = useState<ShortlistSet | null>(null);
  const [approvals, setApprovals] = useState<Record<string, string[]>>({});
  const [dispatch, setDispatch] = useState<DispatchSet | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});

  // Lifted out of StepDispatch, which used to fetch this itself.
  const [plans, setPlans] = useState<SectionPlan[] | null>(null);
  const [plansError, setPlansError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const [spl, prop, dec, cov] = await Promise.all([
      api.bridge.split(setId).catch(() => null),
      api.bridge.proposal(setId).catch(() => null),
      api.bridge.decisions(setId).catch(() => null),
      api.sourcing.coverage().catch(() => null),
    ]);
    setSplit(spl?.scope ?? null);
    setProposal(prop);
    setSublet(dec?.sublet_packages ?? []);
    setCoverage(cov);
    setLoading(false);
  }, [setId]);

  useEffect(() => {
    void load();
  }, [load]);

  const scope = useMemo(
    () => sourcingScope(split, proposal, sublet),
    [split, proposal, sublet],
  );

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  };

  const runShortlist = () =>
    run(async () => {
      if (!scope) return;
      const result = await api.sourcing.shortlist(
        scope,
        demoMode ? undefined : { includePublic: true, k: 8 },
      );
      setShortlist(result);
      // Default the enquiry selection to the top clean firm per package. A default, not a
      // decision: every row still shows its flags and the person can change any of it.
      setApprovals(
        Object.fromEntries(
          Object.entries(result.per_trade).map(([trade, cands]) => {
            const first = cands.find((c) => !c.recommended_against) ?? cands[0];
            return [trade, first ? [first.firm.firm_id] : []];
          }),
        ),
      );
    });

  // The attachment plan follows the selection, and is fetched HERE rather than inside the step.
  useEffect(() => {
    if (demoMode || !scope || step !== "dispatch") return;
    let stale = false;
    setPlans(null);
    setPlansError("");
    api.sourcing
      .dispatchPlan(scope, approvals, scope.project_name)
      .then((p) => !stale && setPlans(p))
      .catch((e: unknown) => !stale && setPlansError(e instanceof Error ? e.message : String(e)));
    return () => {
      stale = true;
    };
  }, [demoMode, scope, approvals, step]);

  const toggleApprove = (trade: string, firmId: string) =>
    setApprovals((cur) => {
      const ids = cur[trade] ?? [];
      return {
        ...cur,
        [trade]: ids.includes(firmId) ? ids.filter((f) => f !== firmId) : [...ids, firmId],
      };
    });

  const dispatchBody = (send: boolean) => ({
    shortlist,
    approvals,
    scope,
    project_name: scope?.project_name ?? "",
    send,
    ...(send
      ? {
          draft_overrides: Object.entries(drafts).map(([key, value]) => {
            const [trade, firm_id] = key.split(":");
            return { trade, firm_id, subject: value.subject, body: value.body };
          }),
        }
      : {}),
  });

  const composeDrafts = () => api.sourcing.dispatch(dispatchBody(false));

  const sendDispatch = () =>
    run(async () => {
      setDispatch(await api.sourcing.dispatch(dispatchBody(true)));
    });

  const prepareDrafts = (
    overrides: { package_key: string; removed: string[]; whole: string[] }[],
  ) =>
    api.sourcing.dispatchDrafts({
      ...dispatchBody(false),
      attachment_overrides: overrides,
    });

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <LoadingDots label="Reading the routing decision…" />
      </div>
    );
  }

  // No decision yet, or nothing sublet. Both open and explain rather than locking.
  if (!sublet.length) {
    return (
      <WaitingOn title={proposal?.packages.length ? "Nothing routed to sublet" : "Waits on the route"}>
        {proposal?.packages.length
          ? "Every package on this tender is routed self-perform, so there is nobody to source. Change a route on the Route tab if that is wrong."
          : "Sourcing works from the packages routed to sublet. Propose and confirm the routing on the Route tab first — that decision is what says which packages arrive here."}
      </WaitingOn>
    );
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {/* The internal stepper. Like the tab strip above it, no step is disabled — a step that
          cannot run yet opens and says what it waits on. */}
      <nav className="flex flex-none items-center gap-1 border-b border-cb-divider bg-cb-panel px-4 py-1.5">
        {STEPS.map((s, i) => (
          <div key={s.id} className="flex items-center">
            {i > 0 && <span className="px-1 text-cb-border-strong">›</span>}
            <button
              type="button"
              onClick={() => setStep(s.id)}
              className={cx(
                "cb-press rounded-cb-btn px-2.5 py-1 font-cb-sans text-[11px]",
                step === s.id
                  ? "bg-white font-semibold text-cb-ink-text shadow-[inset_0_-2px_0_var(--color-cb-brass)]"
                  : "font-medium text-cb-muted hover:text-cb-body",
              )}
            >
              {s.label}
            </button>
          </div>
        ))}
        <span className="ml-auto font-cb-mono text-[10px] text-cb-faint">
          {sublet.length} sublet package{sublet.length === 1 ? "" : "s"}
        </span>
      </nav>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-4 p-6">
          {error && <ErrorNote message={error} onDismiss={() => setError("")} />}

          {step === "shortlist" ? (
            shortlist ? (
              <Shortlist
                shortlist={shortlist}
                coverage={coverage}
                approvals={approvals}
                onToggleApprove={toggleApprove}
              />
            ) : (
              <div className="space-y-3">
                <p className="max-w-3xl text-[12px] leading-relaxed text-cb-muted">
                  {sublet.length} package{sublet.length === 1 ? "" : "s"} routed to sublet. The
                  shortlist cross-references each against the firm database — closeout history,
                  public risk flags and registered trades — and ranks deterministically.
                </p>
                <Button variant="brass" onClick={runShortlist} disabled={busy || !scope}>
                  {busy ? "Cross-referencing…" : "Run the shortlist"}
                </Button>
              </div>
            )
          ) : step === "dispatch" ? (
            shortlist ? (
              <Dispatch
                shortlist={shortlist}
                approvals={approvals}
                dispatch={dispatch}
                drafts={drafts}
                demoMode={demoMode}
                plans={plans}
                plansError={plansError}
                loading={busy}
                onToggleApprove={toggleApprove}
                onEditDraft={(trade, firmId, value) =>
                  setDrafts((cur) => ({ ...cur, [`${trade}:${firmId}`]: value }))
                }
                onComposeDrafts={composeDrafts}
                onPrepareDrafts={demoMode ? undefined : prepareDrafts}
                onSend={sendDispatch}
              />
            ) : (
              <WaitingOn title="Waits on the shortlist">
                Run the shortlist first — dispatch sends enquiries to the firms selected there.
              </WaitingOn>
            )
          ) : (
            <WaitingOn title={`${step === "level" ? "Level & compare" : "Award"} — screen not built yet`}>
              {step === "level"
                ? "The priced returns, with every amount recomputed and every arithmetic error, scope gap and exclusion flagged. Ported next."
                : "The risk-adjusted recommendation and the human award. Ported next — the recommendation is advisory and the award stays a person's."}
            </WaitingOn>
          )}
        </div>
      </div>
    </div>
  );
}
