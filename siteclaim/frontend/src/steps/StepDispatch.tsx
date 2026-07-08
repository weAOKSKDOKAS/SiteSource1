import { useEffect, useState } from "react";

import { api } from "../api";
import type { AttachmentOverride, Candidate, DispatchDraftsResponse, DispatchSet, DispatchStatus, ScopePackages, SectionPlan, ShortlistSet, TenderReplies } from "../types";
import { Pill, StepHeading, StepNav } from "../components";
import { Button, Card, LoadingDots, Modal, cx } from "../ui";
import { tradeLabel } from "../format";

// "12,13,14,31" -> "12–14, 31" for a sliced page list.
function formatPages(pages: number[]): string {
  const sorted = [...pages].sort((a, b) => a - b);
  const runs: string[] = [];
  let start = sorted[0], prev = sorted[0];
  for (const p of sorted.slice(1)) {
    if (p === prev + 1) { prev = p; continue; }
    runs.push(start === prev ? `${start}` : `${start}–${prev}`);
    start = prev = p;
  }
  if (start !== undefined) runs.push(start === prev ? `${start}` : `${start}–${prev}`);
  return runs.join(", ");
}

// One section's remove/expand decisions, keyed by source_doc.
type SectionOverride = { removed: string[]; whole: string[] };

// The relevant-only attachment plan per dispatched section — the human gate before a draft is
// prepared. Read from /dispatch/plan; live only (in demo there are no real uploads). Interactive:
// each document can be removed, and any sliced document can be expanded to the whole file. The
// decisions are lifted to the modal (controlled) so "Prepare Gmail drafts" assembles exactly this.
function AttachmentPlanPreview({
  scope, approvals, projectName, overrides, onOverridesChange,
}: {
  scope: ScopePackages | null | undefined;
  approvals: Record<string, string[]>;
  projectName: string;
  overrides: Record<string, SectionOverride>;
  onOverridesChange: (next: Record<string, SectionOverride>) => void;
}) {
  const [plans, setPlans] = useState<SectionPlan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stale = false;
    setPlans(null);
    setError(null);
    api
      .dispatchPlan(scope ?? null, approvals, projectName)
      .then((p) => !stale && setPlans(p))
      .catch((e: unknown) => !stale && setError(e instanceof Error ? e.message : String(e)));
    return () => { stale = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectName]);

  const ovFor = (key: string): SectionOverride => overrides[key] ?? { removed: [], whole: [] };
  const toggle = (key: string, field: keyof SectionOverride, doc: string) => {
    const cur = ovFor(key);
    const list = cur[field];
    const next = list.includes(doc) ? list.filter((d) => d !== doc) : [...list, doc];
    onOverridesChange({ ...overrides, [key]: { ...cur, [field]: next } });
  };

  if (error) return <p className="text-xs text-bad">{error}</p>;
  if (!plans) return <LoadingDots label="Assembling the relevant documents" />;
  if (plans.length === 0) return null;
  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold uppercase tracking-eyebrow text-ink-soft">Relevant documents per section (assembled)</h4>
      <p className="text-[11px] text-ink-faint">Remove anything a firm doesn’t need, or expand a slice to the whole file — the Gmail drafts carry exactly this set.</p>
      {plans.map((plan) => {
        const ov = ovFor(plan.package_key);
        return (
          <div key={plan.package_key} className="rounded-lg border border-line-soft bg-paper-soft/50 p-3">
            <div className="mb-1.5 text-xs font-semibold text-ink">{tradeLabel(plan.package_key)}</div>
            <ul className="space-y-1">
              {plan.attachments.map((a, i) => {
                const removed = ov.removed.includes(a.source_doc);
                const priced = a.flags.includes("priced_return"); // the SoR slice / generated sheet the firm prices
                const expanded = a.mode === "sliced" && ov.whole.includes(a.source_doc);
                const removable = a.mode !== "generated" && !priced; // the priced return is never removable
                return (
                  <li key={i} className={cx("flex flex-wrap items-baseline gap-1.5 text-xs", removed && "opacity-45")}>
                    <span className={cx("font-medium text-ink", removed && "line-through")}>{a.out_filename || a.source_doc}</span>
                    <Pill tone={expanded ? "neutral" : a.mode === "sliced" ? "brand" : a.mode === "generated" ? "ok" : priced ? "ok" : "neutral"}>
                      {a.mode === "sliced" ? (expanded ? "whole file" : `pp. ${formatPages(a.pages)}`) : a.mode === "generated" ? "SoR sheet" : "whole file"}
                    </Pill>
                    {priced && <Pill tone="ok">priced return</Pill>}
                    {a.clauses.length > 0 && !expanded && (
                      <span className="tabular font-medium text-ink-soft">{a.clauses.join(", ")}</span>
                    )}
                    {a.flags.includes("scanned_whole") && <Pill tone="warn">scanned</Pill>}
                    {a.flags.includes("whole_clause_not_located") && <Pill tone="warn">clause not located</Pill>}
                    {a.flags.includes("whole_section_not_located") && <Pill tone="warn">section not located</Pill>}
                    <span className="text-ink-faint">{a.reason}</span>
                    <span className="ml-auto flex items-center gap-2">
                      {a.mode === "sliced" && !removed && !priced && (
                        <button type="button" className="font-medium text-brand underline" onClick={() => toggle(plan.package_key, "whole", a.source_doc)}>
                          {expanded ? "use slice" : "expand to whole file"}
                        </button>
                      )}
                      {removable && (
                        <button
                          type="button"
                          className={cx("font-medium underline", removed ? "text-brand" : "text-ink-faint hover:text-bad")}
                          onClick={() => toggle(plan.package_key, "removed", a.source_doc)}
                        >
                          {removed ? "undo" : "remove"}
                        </button>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
            {plan.missing_specs.length > 0 && (
              <div className="mt-2 rounded border border-warn/40 bg-warn-bg px-2 py-1 text-xs text-warn">
                Referenced but not supplied: <span className="font-semibold">{plan.missing_specs.map((m) => m.spec).join(", ")}</span> — chase it or dispatch without.
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

const STATUS_LABEL: Record<DispatchStatus, string> = {
  drafted: "Draft",
  approved: "Approved",
  sent_mock: "In outbox",
  sent: "Sent",
  send_failed: "Send failed",
  drafted_gmail: "In Gmail drafts",
};

type Draft = { subject: string; body: string };

// Live-mode panel: which replies have accumulated for this tender. Manual refresh only —
// no polling loop. Hidden in demo mode (there is no live reply loop there).
function RepliesPanel({ slug }: { slug: string }) {
  const [data, setData] = useState<TenderReplies | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    setBusy(true);
    setError(null);
    api
      .tenderReplies(slug)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  return (
    <Card>
      <div className="flex items-center justify-between border-b border-line-soft px-4 py-2.5">
        <h2 className="text-sm font-semibold text-ink">Replies received</h2>
        <Button variant="ghost" onClick={refresh} loading={busy}>
          Refresh
        </Button>
      </div>
      <div className="space-y-2 px-4 py-3">
        {error && <p className="text-xs text-bad">{error}</p>}
        {!data && !error && <p className="text-xs text-ink-faint">Refresh to check for replies to this tender.</p>}
        {data && (
          <>
            <p className="text-xs text-ink-soft">
              {data.reply_count} received
              {data.last_received ? ` · last ${new Date(data.last_received).toLocaleString()}` : ""}
              {data.outstanding.length ? ` · ${data.outstanding.length} outstanding` : ""}
            </p>
            {data.replies.length > 0 && (
              <ul className="divide-y divide-line-soft">
                {data.replies.map((r) => (
                  <li key={`${r.trade}-${r.firm_id}`} className="flex items-center gap-2 py-1.5">
                    <span className="text-sm text-ink">{r.firm_id}</span>
                    <Pill tone="brand">{tradeLabel(r.trade)}</Pill>
                    <span className="tabular ml-auto text-xs text-ink-faint">{r.line_items} items</span>
                  </li>
                ))}
              </ul>
            )}
            {data.comparison_available && (
              <a
                className="inline-block text-xs font-semibold text-brand underline"
                href={api.tenderComparisonUrl(slug)}
                target="_blank"
                rel="noreferrer"
              >
                Download comparison.xlsx
              </a>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

export function StepDispatch({
  shortlist,
  heroTrade,
  approvals,
  dispatch,
  demoMode,
  tenderSlug,
  scope,
  projectName,
  drafts,
  onToggleApprove,
  onEditDraft,
  onComposeDrafts,
  onPrepareDrafts,
  onSend,
  onBack,
  onNext,
  loading,
}: {
  shortlist: ShortlistSet;
  heroTrade: string;
  approvals: Record<string, string[]>;
  dispatch: DispatchSet | null;
  demoMode: boolean;
  tenderSlug: string;
  scope?: ScopePackages | null;   // the sourcing scope — for the relevant-doc plan preview (live)
  projectName?: string;
  drafts: Record<string, Draft>;
  onToggleApprove: (trade: string, firmId: string) => void;
  onEditDraft: (trade: string, firmId: string, value: Draft) => void;
  onComposeDrafts: () => Promise<DispatchSet>;
  onPrepareDrafts?: (overrides: AttachmentOverride[]) => Promise<DispatchDraftsResponse>;  // live: hand bundles to n8n Gmail drafts
  onSend: () => void;
  onBack: () => void;
  onNext: () => void;
  loading: boolean;
}) {
  const [reviewOpen, setReviewOpen] = useState(false);
  const trades = Object.keys(shortlist.per_trade).sort((a, b) =>
    a === heroTrade ? -1 : b === heroTrade ? 1 : a.localeCompare(b),
  );
  const approvedCount = Object.values(approvals).reduce((n, ids) => n + ids.length, 0);
  const editedCount = Object.keys(drafts).filter((key) => {
    const [trade, fid] = key.split(":");
    return (approvals[trade] ?? []).includes(fid);
  }).length;

  return (
    <div className="space-y-6">
      <StepHeading
        title="Dispatch enquiries"
        lead="The approve-before-send gate: review the selected firms and their enquiry emails in the pop-up, edit any draft, then confirm. Each firm receives only its trade's documents — the electrical firm gets the electrical scope, not the whole tender. Confirming prepares each enquiry in the outbox with exactly your edited text, ready to send."
      />

      {/* Selection summary per trade — firms are picked on the shortlist or in the pop-up. */}
      <Card className="p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-ink">Selected for enquiry</h2>
          <span className="tabular text-xs text-ink-faint">
            {approvedCount} firm{approvedCount === 1 ? "" : "s"}
            {editedCount > 0 ? ` · ${editedCount} draft${editedCount === 1 ? "" : "s"} edited` : ""}
          </span>
        </div>
        <div className="space-y-2">
          {trades.map((trade) => {
            const picked = (approvals[trade] ?? [])
              .map((fid) => shortlist.per_trade[trade].find((c) => c.firm.firm_id === fid))
              .filter((c): c is Candidate => c != null);
            return (
              <div key={trade} className="flex flex-wrap items-center gap-1.5">
                <span className="w-40 shrink-0 text-xs font-semibold uppercase tracking-eyebrow text-ink-faint">{tradeLabel(trade)}</span>
                {picked.length === 0 && <span className="text-xs italic text-ink-faint">none selected — pick on the shortlist or in the review pop-up</span>}
                {picked.map((c) => (
                  <Pill key={c.firm.firm_id} tone={c.recommended_against ? "bad" : "brand"}>
                    {c.firm.name}{c.recommended_against ? " ⚠" : ""}
                  </Pill>
                ))}
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex justify-end">
          <Button onClick={() => setReviewOpen(true)} disabled={loading}>
            Review &amp; edit enquiries →
          </Button>
        </div>
      </Card>

      {/* Persistent post-confirm summary + the outbox (the audit trail). */}
      {dispatch && (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line-soft bg-ok-bg/40 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-ink">
              Outbox — {dispatch.bundles.length} enquir{dispatch.bundles.length === 1 ? "y" : "ies"} prepared
            </h2>
            <Pill tone="ok">{dispatch.bundles.length} ready</Pill>
          </div>
          <ul className="divide-y divide-line-soft">
            {dispatch.bundles.map((b) => (
              <li key={`${b.trade}-${b.firm_id}`} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">{b.firm_name}</span>
                  <span className="tabular text-xs text-ink-faint">{b.firm_id}</span>
                  <Pill tone="brand">{tradeLabel(b.trade)}</Pill>
                  <span className={cx("ml-auto", "")}>
                    <Pill tone={b.status === "sent_mock" ? "ok" : "neutral"}>{STATUS_LABEL[b.status]}</Pill>
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <span className="text-xs font-medium text-ink-soft">Documents enclosed:</span>
                  {b.bundle_doc_refs.map((d) => (
                    <span key={d} className="tabular rounded bg-line-soft px-1.5 py-0.5 text-xs text-ink-soft">{d}</span>
                  ))}
                </div>
                <div className="mt-2 rounded-lg border border-line-soft bg-paper/40 p-3">
                  <div className="text-xs font-semibold text-ink">{b.email_subject}</div>
                  <p className="mt-1 whitespace-pre-line text-xs leading-relaxed text-ink-soft">{b.email_body}</p>
                </div>
              </li>
            ))}
          </ul>
          <p className="border-t border-line-soft px-4 py-2 text-[11px] text-ink-faint">
            Live sending is wired separately — enquiries are prepared here with their trade-only bundles, ready to send.
          </p>
        </Card>
      )}

      {!demoMode && dispatch && tenderSlug && <RepliesPanel slug={tenderSlug} />}

      <StepNav onBack={onBack} onNext={onNext} nextLabel="Level & compare →" loading={loading} nextDisabled={!dispatch} />

      <DispatchReviewModal
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        shortlist={shortlist}
        trades={trades}
        approvals={approvals}
        drafts={drafts}
        onToggleApprove={onToggleApprove}
        onEditDraft={onEditDraft}
        onComposeDrafts={onComposeDrafts}
        onConfirm={() => {
          onSend();
          setReviewOpen(false);
        }}
        sending={loading}
        live={!demoMode}
        scope={scope}
        projectName={projectName ?? ""}
        onPrepareDrafts={onPrepareDrafts}
      />
    </div>
  );
}

// The centered review pop-up (a Modal, never a Drawer): the selected firms grouped by
// trade with add/remove, and for EACH selected firm the composed enquiry email in an
// editable subject + body. Edits persist (App state) and the confirm writes the outbox
// with exactly the edited text.
function DispatchReviewModal({
  open,
  onClose,
  shortlist,
  trades,
  approvals,
  drafts,
  onToggleApprove,
  onEditDraft,
  onComposeDrafts,
  onConfirm,
  sending,
  live = false,
  scope,
  projectName = "",
  onPrepareDrafts,
}: {
  open: boolean;
  onClose: () => void;
  shortlist: ShortlistSet;
  trades: string[];
  approvals: Record<string, string[]>;
  drafts: Record<string, Draft>;
  onToggleApprove: (trade: string, firmId: string) => void;
  onEditDraft: (trade: string, firmId: string, value: Draft) => void;
  onComposeDrafts: () => Promise<DispatchSet>;
  onConfirm: () => void;
  sending: boolean;
  live?: boolean;
  scope?: ScopePackages | null;
  projectName?: string;
  onPrepareDrafts?: (overrides: AttachmentOverride[]) => Promise<DispatchDraftsResponse>;
}) {
  const [composed, setComposed] = useState<Record<string, Draft>>({});
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftResult, setDraftResult] = useState<DispatchDraftsResponse | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  // The attachment gate's per-section remove/expand decisions, keyed by package_key.
  const [attachmentOverrides, setAttachmentOverrides] = useState<Record<string, SectionOverride>>({});
  const approvedCount = Object.values(approvals).reduce((n, ids) => n + ids.length, 0);

  // Hand the approved bundles to the n8n Gmail-draft workflow, carrying the gate's decisions so
  // the assembled set matches the preview exactly. Result is surfaced honestly: when
  // N8N_DRAFTS_WEBHOOK is unset the backend no-ops and webhook_configured is false.
  const prepareGmailDrafts = () => {
    if (!onPrepareDrafts) return;
    const overrides: AttachmentOverride[] = Object.entries(attachmentOverrides)
      .filter(([, o]) => o.removed.length > 0 || o.whole.length > 0)
      .map(([package_key, o]) => ({ package_key, removed: o.removed, whole: o.whole }));
    setDraftBusy(true);
    setDraftError(null);
    setDraftResult(null);
    onPrepareDrafts(overrides)
      .then(setDraftResult)
      .catch((e: unknown) => setDraftError(e instanceof Error ? e.message : String(e)))
      .finally(() => setDraftBusy(false));
  };

  // Editing the selection or drafts invalidates a prior draft result — clear it so the summary
  // never claims Gmail drafts that no longer match what is on screen.
  useEffect(() => {
    setDraftResult(null);
    setDraftError(null);
  }, [approvals, drafts, attachmentOverrides]);

  // (Re)compose whenever the pop-up opens or the selection changes — the composed text is
  // the default; a person's edit (drafts) always wins and survives reopening.
  useEffect(() => {
    if (!open || approvedCount === 0) return;
    let stale = false;
    setComposing(true);
    setError(null);
    onComposeDrafts()
      .then((set) => {
        if (stale) return;
        setComposed(
          Object.fromEntries(set.bundles.map((b) => [`${b.trade}:${b.firm_id}`, { subject: b.email_subject, body: b.email_body }])),
        );
      })
      .catch((e: unknown) => !stale && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !stale && setComposing(false));
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, approvals]);

  const shown = (trade: string, fid: string): Draft =>
    drafts[`${trade}:${fid}`] ?? composed[`${trade}:${fid}`] ?? { subject: "", body: "" };

  return (
    <Modal open={open} onClose={onClose} title="Review & edit enquiries (approve-before-send)" wide>
      <div className="space-y-4">
        {error && <p className="rounded-lg bg-bad-bg px-3 py-2 text-xs text-bad">{error}</p>}
        {trades.map((trade) => {
          const candidates = shortlist.per_trade[trade];
          const picked = approvals[trade] ?? [];
          return (
            <section key={trade}>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-eyebrow text-ink-soft">{tradeLabel(trade)}</h4>
              {/* add/remove firms (multi-select) */}
              <div className="mb-2 flex flex-wrap gap-1.5">
                {candidates.map((c) => {
                  const selected = picked.includes(c.firm.firm_id);
                  return (
                    <button
                      key={c.firm.firm_id}
                      type="button"
                      onClick={() => onToggleApprove(trade, c.firm.firm_id)}
                      className={cx(
                        "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                        selected && c.recommended_against && "border-bad/50 bg-bad-bg text-bad",
                        selected && !c.recommended_against && "border-brand bg-brand text-white",
                        !selected && "border-line bg-card text-ink-soft hover:bg-line-soft",
                      )}
                    >
                      {c.firm.name}
                      {c.recommended_against ? " ⚠" : ""}
                      {selected ? " ✓" : ""}
                    </button>
                  );
                })}
              </div>
              {picked.some((fid) => candidates.find((c) => c.firm.firm_id === fid)?.recommended_against) && (
                <p className="mb-2 rounded-lg border border-bad/40 bg-bad-bg px-3 py-1.5 text-xs text-bad">
                  A selected firm is recommended against — sending it an enquiry is allowed, but the flag stands.
                </p>
              )}
              {/* one editable draft per selected firm */}
              <div className="space-y-3">
                {picked.map((fid) => {
                  const cand = candidates.find((c) => c.firm.firm_id === fid);
                  if (!cand) return null;
                  const value = shown(trade, fid);
                  const edited = drafts[`${trade}:${fid}`] != null;
                  return (
                    <div key={fid} className="rounded-lg border border-line-soft bg-paper-soft/60 p-3">
                      <div className="mb-1.5 flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold text-ink">{cand.firm.name}</span>
                        <span className="tabular text-[11px] text-ink-faint">{fid}</span>
                        {edited && <Pill tone="brand">edited</Pill>}
                        {composing && !edited && <LoadingDots label="composing" />}
                      </div>
                      <input
                        value={value.subject}
                        onChange={(e) => onEditDraft(trade, fid, { ...value, subject: e.target.value })}
                        placeholder="Subject"
                        className="tabular mb-1.5 w-full rounded-lg border border-line bg-card px-2.5 py-1.5 text-xs text-ink focus:border-brand focus:outline-none"
                      />
                      <textarea
                        value={value.body}
                        onChange={(e) => onEditDraft(trade, fid, { ...value, body: e.target.value })}
                        placeholder="Email body"
                        rows={6}
                        className="w-full rounded-lg border border-line bg-card px-2.5 py-1.5 text-xs leading-relaxed text-ink focus:border-brand focus:outline-none"
                      />
                    </div>
                  );
                })}
                {picked.length === 0 && <p className="text-xs italic text-ink-faint">No firm selected for this trade.</p>}
              </div>
            </section>
          );
        })}

        {live && approvedCount > 0 && (
          <div className="border-t border-line-soft pt-3">
            <AttachmentPlanPreview
              scope={scope}
              approvals={approvals}
              projectName={projectName}
              overrides={attachmentOverrides}
              onOverridesChange={setAttachmentOverrides}
            />
          </div>
        )}

        {/* Gmail-draft hand-off result — surfaced honestly (aggregate + per-firm), incl. the
            "drafting is off" state the backend returns when N8N_DRAFTS_WEBHOOK is unset. */}
        {draftError && <p className="rounded-lg bg-bad-bg px-3 py-2 text-xs text-bad">{draftError}</p>}
        {draftResult && !draftResult.webhook_configured && (
          <div className="rounded-lg border border-warn/40 bg-warn-bg px-3 py-2 text-xs text-warn">
            Drafting is off — set <span className="tabular font-semibold">N8N_DRAFTS_WEBHOOK</span> (and activate the n8n
            workflow) to create Gmail drafts. Nothing was sent; the outbox confirm below still works.
          </div>
        )}
        {draftResult && draftResult.webhook_configured && (
          <div className="rounded-lg border border-ok/40 bg-ok-bg px-3 py-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-ink">
                {draftResult.drafted} Gmail draft{draftResult.drafted === 1 ? "" : "s"} prepared
              </span>
              <a
                className="ml-auto font-semibold text-brand underline"
                href="https://mail.google.com/mail/u/0/#drafts"
                target="_blank"
                rel="noreferrer"
              >
                Open Gmail drafts ↗
              </a>
            </div>
            <ul className="mt-1.5 divide-y divide-line-soft">
              {draftResult.bundles.map((b) => (
                <li key={`${b.trade}-${b.firm_id}`} className="flex flex-wrap items-center gap-2 py-1">
                  <span className="text-ink">{b.firm_name}</span>
                  <Pill tone="brand">{tradeLabel(b.trade)}</Pill>
                  <Pill tone="ok">Draft created</Pill>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 border-t border-line-soft pt-3">
          <span className="text-xs text-ink-faint">
            Confirming prepares each enquiry in the outbox with exactly the text above — the human gate before anything leaves.
          </span>
          <div className="flex items-center gap-2">
            {live && onPrepareDrafts && (
              <Button variant="ghost" onClick={prepareGmailDrafts} loading={draftBusy} disabled={approvedCount === 0 || composing}>
                Prepare Gmail drafts
              </Button>
            )}
            <Button onClick={onConfirm} loading={sending} disabled={approvedCount === 0 || composing}>
              Confirm — write {approvedCount} enquir{approvedCount === 1 ? "y" : "ies"} →
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
