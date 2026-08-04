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
  AwaitingPackage,
  BidReply,
  BridgeRouteProposalRead,
  Coverage,
  DispatchSet,
  GmailIntegrationStatus,
  LevelledBid,
  MisdirectedHint,
  Recommendation,
  ScopePackages,
  SectionPlan,
  ShortlistSet,
  TenderReplies,
} from "../types";
import { Button, ErrorNote, LoadingDots, WaitingOn, cx } from "../ui";
import { Dispatch, type Draft } from "./sourcing/Dispatch";
import { Level } from "./sourcing/Level";
import { Recommend } from "./sourcing/Recommend";
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

  // Level & award.
  const [levelled, setLevelled] = useState<Record<string, LevelledBid[]> | null>(null);
  // The raw replies behind the editable rate matrix. The desk has no demo-case loader (the wizard
  // got these from one), so in DEMO the summary tables populate from the levelled sections while
  // the matrix stays empty; on the live path rates are corrected by re-uploading a return, which
  // is the real workflow anyway.
  const [replies, setReplies] = useState<BidReply[]>([]);
  const [levelStale, setLevelStale] = useState(false);
  const [tenderReplies, setTenderReplies] = useState<TenderReplies | null>(null);
  /** FIX 4 — the Gmail transport's own state. `polling_enabled` defaults FALSE on the server, so a
   *  default install is not watching for replies at all and this screen is otherwise
   *  indistinguishable from an inbox with nothing in it. The endpoint already returned every field
   *  needed; none of it was shown where the operator is actually waiting. */
  const [gmail, setGmail] = useState<GmailIntegrationStatus | null>(null);
  /** FIX 5 — the active-reply count at the last look, so an INCREASE can be noticed. Written and
   *  read only inside the poll's own setter, so it never triggers a render of its own. */
  const [, setReplyMark] = useState<number | null>(null);
  const [landed, setLanded] = useState(0);
  const [recommendations, setRecommendations] = useState<Record<string, Recommendation> | null>(null);
  const [awards, setAwards] = useState<Record<string, string>>({});

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

  // --- level & award -------------------------------------------------------
  const refreshReplies = () =>
    void api.sourcing
      .tenderReplies(setId)
      .then(setTenderReplies)
      .catch(() => setTenderReplies(null)); // 404 = nothing has landed yet, which is a state

  // FIX 4 — the transport's own state, read once when the tab opens. Cheap (no network call on
  // the server side: token_state is checked without one) and it never fails the screen.
  useEffect(() => {
    if (demoMode) return; // DEMO reports "demo" and there is no inbox to describe
    void api.sourcing.gmailStatus().then(setGmail).catch(() => setGmail(null));
  }, [demoMode]);

  // FIX 5 — while Level & compare is VISIBLE and the server is actually polling, re-read the
  // tender's replies on the server's own cadence. `api.ts` said it outright: refreshed on demand,
  // no polling loop — so the poller could file a reply while this screen still showed "awaiting".
  //
  // Bounded deliberately: it stops on unmount and when the step is not visible, and there is no
  // always-on timer in the shell. Polling a screen nobody is looking at buys nothing.
  //
  // It NEVER calls runLevel(). A comparison must not silently recompute under someone
  // mid-decision — a new arrival is offered, and the re-level is theirs to press.
  const pollSeconds = Math.max(15, gmail?.poll_seconds ?? 120);
  const watching = step === "level" && !demoMode && Boolean(gmail?.polling_enabled);
  useEffect(() => {
    if (!watching) return;
    let live = true;
    const tick = () => {
      void api.sourcing
        .tenderReplies(setId)
        .then((next) => {
          if (!live) return;
          setTenderReplies(next);
          const n = next.replies.filter((r) => r.status === "active").length;
          setReplyMark((mark) => {
            if (mark !== null && n > mark) setLanded(n - mark);
            return n;
          });
        })
        .catch(() => undefined); // a 404 is "nothing yet", and a blip is not worth a banner
    };
    tick();
    const timer = window.setInterval(tick, pollSeconds * 1000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [watching, setId, pollSeconds]);

  const runLevel = () =>
    run(async () => {
      const res = await api.sourcing.levelAll(replies, scope);
      setLevelled(Object.fromEntries(res.sections.map((s2) => [s2.trade, s2.levelled])));
      setLevelStale(false);
      if (!demoMode) refreshReplies();
    });

  const editRate = (firmId: string, itemRef: string, rate: number | null) => {
    setReplies((cur) =>
      cur.map((r) =>
        r.firm_id === firmId
          ? {
              ...r,
              line_items: r.line_items.map((l) => (l.item_ref === itemRef ? { ...l, rate } : l)),
            }
          : r,
      ),
    );
    setLevelStale(true); // the corrected totals no longer match the rates on screen
  };

  const uploadReturn = async (
    trade: string,
    firmId: string,
    files: File[],
  ): Promise<MisdirectedHint | null> => {
    const res = await api.sourcing.levelUpload(files, firmId, trade, setId);
    // A misdirected return is NOT filed — it comes back as a hint for the operator to confirm.
    if (res.misdirected) return res.misdirected;
    await runLevel();
    return null;
  };

  const withdrawReply = async (firmId: string, packageKey: string) => {
    await api.sourcing.withdrawReply(setId, firmId, packageKey);
    await runLevel();
  };

  const runRecommend = () =>
    run(async () => {
      const flat = Object.values(levelled ?? {}).flat();
      const res = await api.sourcing.recommendAll(flat, {}, scope);
      setRecommendations(Object.fromEntries(res.sections.map((s2) => [s2.trade, s2.recommendation])));
    });

  // What was dispatched, and whether each firm's return has landed — by EITHER path (an active
  // reply aligned to the unit, or a manual upload that levelled into its section).
  const awaiting: AwaitingPackage[] = useMemo(() => {
    if (!dispatch) return [];
    const byUnit = new Map<string, AwaitingPackage>();
    for (const b of dispatch.bundles) {
      const received =
        (tenderReplies?.replies ?? []).some(
          (r) => r.trade === b.trade && r.firm_id === b.firm_id && r.status === "active",
        ) || (levelled?.[b.trade] ?? []).some((l) => l.firm_id === b.firm_id);
      const pkg = byUnit.get(b.trade) ?? { trade: b.trade, firms: [] };
      pkg.firms.push({
        firm_id: b.firm_id,
        firm_name: b.firm_name,
        ref: (b.email_subject.match(/\[SiteSource Ref:\s*([^\]]+)\]/) ?? [])[1]?.trim() ?? "",
        received,
        status: b.status,
      });
      byUnit.set(b.trade, pkg);
    }
    return [...byUnit.values()];
  }, [dispatch, tenderReplies, levelled]);

  const awaitingTrades = useMemo(
    () => Object.entries(recommendations ?? {}).filter(([, r]) => r.awaiting_valid_return).map(([t]) => t),
    [recommendations],
  );

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
              <>
              {/* FIX 9 — the priced-return document is not always the artifact the design intends.
                  The design sends the ORIGINAL Schedule of Rates sliced to this unit's section
                  pages, because a subcontractor returns what they were sent. On the real pack the
                  draft carried SoR_ground-investigation-4.xlsx instead — correctly, since the bill
                  arrived as a workbook and there was no PDF to slice — and nothing said so.
                  Stated here, BEFORE drafting, from the flag the plan already carries. */}
              {(plans ?? []).some((pl) =>
                (pl.attachments ?? []).some((a) => (a.flags ?? []).includes("substituted_priced_return")),
              ) && (
                <div className="mb-3 border border-cb-amber px-3 py-2">
                  <div className="font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-amber">
                    PRICED-RETURN DOCUMENT SUBSTITUTED
                  </div>
                  {(plans ?? []).flatMap((pl) =>
                    (pl.attachments ?? [])
                      .filter((a) => (a.flags ?? []).includes("substituted_priced_return"))
                      .map((a) => (
                        <p
                          key={`${pl.package_key}:${a.source_doc}`}
                          className="mt-1 font-cb-sans text-[11px] leading-[1.5] text-cb-amber"
                        >
                          <strong>{pl.package_key}</strong> — {a.reason}
                        </p>
                      )),
                  )}
                </div>
              )}
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
              </>
            ) : (
              <WaitingOn title="Waits on the shortlist">
                Run the shortlist first — dispatch sends enquiries to the firms selected there.
              </WaitingOn>
            )
          ) : step === "level" ? (
            <>
              {/* FIX 4 — one status line, from the endpoint that already returned all of this.
                  `polling_enabled` defaults false, so a default install watches nothing and this
                  screen looks exactly like an empty inbox. Amber border and text when it is off,
                  because that is a condition to act on rather than a failure that happened. */}
              {gmail && !gmail.polling_enabled && (
                <p className="mb-3 border border-cb-amber px-3 py-2 font-cb-sans text-[11px] leading-[1.5] text-cb-amber">
                  Replies are <strong>not being watched</strong>. Returns have to be uploaded by
                  hand on each package below. Set <code>GMAIL_POLLING_ENABLED=true</code> in
                  backend/.env and restart to have them collected automatically.
                  {gmail.last_error ? ` Last transport error: ${gmail.last_error}` : ""}
                </p>
              )}
              {gmail?.polling_enabled && (
                <p className="mb-3 font-cb-sans text-[11px] leading-[1.5] text-cb-muted">
                  Watching for replies
                  {gmail.last_poll_at ? ` — last checked ${new Date(gmail.last_poll_at).toLocaleTimeString()}` : ""}
                  {` · ${gmail.replies_processed} processed, ${gmail.replies_unmatched} unmatched this run`}
                  {gmail.last_error ? ` · ${gmail.last_error}` : ""}
                </p>
              )}
              {/* FIX 5 — an arrival is ANNOUNCED, never acted on: re-levelling under someone
                  mid-decision would move numbers they are reading. */}
              {landed > 0 && (
                <p className="mb-3 flex items-center gap-2 border border-cb-amber px-3 py-2 font-cb-sans text-[11px] text-cb-amber">
                  {landed} new return{landed === 1 ? "" : "s"} landed — re-level to include{" "}
                  {landed === 1 ? "it" : "them"}.
                  <button
                    type="button"
                    onClick={() => setLanded(0)}
                    className="cb-press ml-auto underline"
                  >
                    dismiss
                  </button>
                </p>
              )}
            {levelled ? (
              <Level
                sections={levelled}
                replies={replies}
                stale={levelStale}
                xlsxUrl={api.sourcing.levelingXlsxUrl()}
                loading={busy}
                onEditRate={editRate}
                onRecompute={runLevel}
                live={!demoMode}
                awaiting={awaiting}
                onUploadReturn={uploadReturn}
                tenderReplies={tenderReplies}
                comparisonUrl={api.sourcing.tenderComparisonUrl(setId)}
                onRefreshReplies={refreshReplies}
                onWithdrawReply={withdrawReply}
              />
            ) : (
              <div className="space-y-3">
                <p className="max-w-3xl text-[12px] leading-relaxed text-cb-muted">
                  Level the priced returns: the rules engine recomputes every amount as qty × rate,
                  flags arithmetic errors, and treats a missing rate as a scope gap rather than a
                  cheap bid.
                </p>
                <Button variant="brass" onClick={runLevel} disabled={busy || !scope}>
                  {busy ? "Levelling…" : "Level the returns"}
                </Button>
              </div>
            )}
            </>
          ) : recommendations ? (
            <Recommend
              sections={recommendations}
              awards={awards}
              awaitingTrades={awaitingTrades}
              onSetAward={(trade, firmId) => setAwards((cur) => ({ ...cur, [trade]: firmId }))}
              onSkip={(trade) => setAwards((cur) => ({ ...cur, [trade]: "" }))}
            />
          ) : levelled ? (
            <div className="space-y-3">
              <p className="max-w-3xl text-[12px] leading-relaxed text-cb-muted">
                The engine ranks each package by corrected price, read against the firm database — a
                fatal flag demotes a firm regardless of price. Claude narrates; you award.
              </p>
              <Button variant="brass" onClick={runRecommend} disabled={busy}>
                {busy ? "Ranking…" : "Recommend an award"}
              </Button>
            </div>
          ) : (
            <WaitingOn title="Waits on the levelling">
              Level the returns first — the ranking is computed from the corrected totals.
            </WaitingOn>
          )}
        </div>
      </div>
    </div>
  );
}
