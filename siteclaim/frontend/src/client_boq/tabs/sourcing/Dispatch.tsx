// Sourcing step 2 — dispatch. Ported from StepDispatch, restyled, behaviour unchanged.
//
// The approve-before-send gate. What matters here and is preserved exactly:
//
//  * EACH FIRM GETS ONLY ITS OWN PACKAGE'S DOCUMENTS. The electrical firm receives the electrical
//    scope, not the whole tender. The assembled set is shown before anything is drafted, and a
//    person can remove a document or expand a slice to the whole file.
//  * A GMAIL FAILURE IS PARTIAL SUCCESS, NOT A DEAD END. The backend returns per-firm reasons and
//    the enquiries stay in the outbox; the panel shows the aggregate AND every firm's outcome.
//  * NOTHING IS SENT. Drafts are prepared in Gmail for a person to review and send. Saying that
//    plainly is more honest than a disabled Send button.
//
// Its fetching has been LIFTED OUT: in the wizard this screen fetched the attachment plan itself,
// breaking the presentational contract every other step kept. Here the tab owns it, the way every
// other cb tab owns its own, and the plan arrives as a prop.

import { useEffect, useState } from "react";

import type {
  Candidate,
  DispatchDraftsResponse,
  DispatchSet,
  DispatchStatus,
  SectionPlan,
  ShortlistSet,
} from "../../types";
import { Button, Card, Chip, LoadingDots, Modal, SectionLabel, cx } from "../../ui";

export type Draft = { subject: string; body: string };
export type SectionOverride = { removed: string[]; whole: string[] };

const STATUS_LABEL: Record<DispatchStatus, string> = {
  drafted: "Draft",
  approved: "Approved",
  sent_mock: "In outbox",
  sent: "Sent",
  send_failed: "Send failed",
  drafted_gmail: "In Gmail drafts",
};

function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}

/** "1-3, 7" from [1,2,3,7] — a page range a person can check against the original. */
function formatPages(pages: number[]): string {
  if (!pages.length) return "—";
  const sorted = [...pages].sort((a, b) => a - b);
  const runs: string[] = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (const p of sorted.slice(1)) {
    if (p === prev + 1) {
      prev = p;
      continue;
    }
    runs.push(start === prev ? `${start}` : `${start}-${prev}`);
    start = p;
    prev = p;
  }
  runs.push(start === prev ? `${start}` : `${start}-${prev}`);
  return runs.join(", ");
}

export function Dispatch({
  shortlist,
  approvals,
  dispatch,
  drafts,
  demoMode,
  plans,
  plansError,
  loading,
  onToggleApprove,
  onEditDraft,
  onComposeDrafts,
  onPrepareDrafts,
  onSend,
}: {
  shortlist: ShortlistSet;
  approvals: Record<string, string[]>;
  dispatch: DispatchSet | null;
  drafts: Record<string, Draft>;
  demoMode: boolean;
  /** Lifted to the tab container — this screen no longer fetches. null = still loading. */
  plans: SectionPlan[] | null;
  plansError: string;
  loading: boolean;
  onToggleApprove: (trade: string, firmId: string) => void;
  onEditDraft: (trade: string, firmId: string, value: Draft) => void;
  onComposeDrafts: () => Promise<DispatchSet>;
  onPrepareDrafts?: (overrides: { package_key: string; removed: string[]; whole: string[] }[]) => Promise<DispatchDraftsResponse>;
  onSend: () => void;
}) {
  const [reviewOpen, setReviewOpen] = useState(false);
  const trades = Object.keys(shortlist.per_trade).sort((a, b) => a.localeCompare(b));
  const approvedCount = Object.values(approvals).reduce((n, ids) => n + ids.length, 0);
  const editedCount = Object.keys(drafts).filter((key) => {
    const [trade, fid] = key.split(":");
    return (approvals[trade] ?? []).includes(fid);
  }).length;

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-[12px] leading-relaxed text-cb-muted">
        The approve-before-send gate: review the selected firms and their enquiry emails, edit any
        draft, then confirm. Each firm receives only its package's documents. Confirming prepares
        each enquiry in the outbox with exactly your edited text.
      </p>

      <Card flush>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-cb-divider px-3 py-2">
          <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
            Selected for enquiry
          </h3>
          <span className="font-cb-mono text-[10px] text-cb-faint">
            {approvedCount} firm{approvedCount === 1 ? "" : "s"}
            {editedCount > 0 ? ` · ${editedCount} draft${editedCount === 1 ? "" : "s"} edited` : ""}
          </span>
        </div>
        <div className="space-y-1.5 px-3 py-2">
          {trades.map((trade) => {
            const picked = (approvals[trade] ?? [])
              .map((fid) => shortlist.per_trade[trade].find((c) => c.firm.firm_id === fid))
              .filter((c): c is Candidate => c != null);
            return (
              <div key={trade} className="flex flex-wrap items-center gap-1.5">
                <SectionLabel className="w-40 shrink-0">{tradeLabel(trade)}</SectionLabel>
                {picked.length === 0 && (
                  <span className="text-[11px] italic text-cb-faint">
                    none selected — pick on the shortlist or in the review pop-up
                  </span>
                )}
                {picked.map((c) => (
                  <Chip
                    key={c.firm.firm_id}
                    className={
                      c.recommended_against
                        ? "bg-cb-bad-tint text-cb-bad-dark"
                        : "bg-cb-panel text-cb-body"
                    }
                  >
                    {c.firm.name}
                    {c.recommended_against ? " ⚠" : ""}
                  </Chip>
                ))}
              </div>
            );
          })}
        </div>
        <div className="flex justify-end border-t border-cb-divider px-3 py-2">
          <Button variant="brass" onClick={() => setReviewOpen(true)} disabled={loading}>
            Review &amp; edit enquiries →
          </Button>
        </div>
      </Card>

      {dispatch?.notice && (
        // Brass, because a run-level notice is not a failure and not a register fact — and this
        // one is the difference between "the enquiries went to the firms" and "they went to your
        // own inbox". It reads before the outbox list for that reason.
        <div className="rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2 font-cb-sans text-[11px] font-medium text-cb-brass-text">
          {dispatch.notice}
        </div>
      )}
      {dispatch && (
        <Card flush>
          <div className="flex items-center justify-between border-b border-cb-divider bg-cb-ok-tint px-3 py-2">
            <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
              Outbox — {dispatch.bundles.length} enquir
              {dispatch.bundles.length === 1 ? "y" : "ies"} prepared
            </h3>
            <Chip className="bg-white text-cb-ok-dark">{dispatch.bundles.length} ready</Chip>
          </div>
          <ul className="divide-y divide-cb-divider">
            {dispatch.bundles.map((b) => (
              <li key={`${b.trade}-${b.firm_id}`} className="px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-semibold text-cb-ink-text">{b.firm_name}</span>
                  <span className="font-cb-mono text-[10px] text-cb-faint">{b.firm_id}</span>
                  <Chip className="bg-cb-panel text-cb-body">{tradeLabel(b.trade)}</Chip>
                  <span className="ml-auto">
                    <Chip
                      className={
                        b.status === "sent_mock" || b.status === "drafted_gmail"
                          ? "bg-cb-ok-tint text-cb-ok-dark"
                          : "bg-cb-panel text-cb-muted"
                      }
                    >
                      {STATUS_LABEL[b.status]}
                    </Chip>
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] font-medium text-cb-muted">Documents enclosed:</span>
                  {b.bundle_doc_refs.map((d) => (
                    <span
                      key={d}
                      className="rounded-cb-chip bg-cb-panel px-1.5 py-0.5 font-cb-mono text-[10px] text-cb-body"
                    >
                      {d}
                    </span>
                  ))}
                </div>
                <div className="mt-2 rounded-cb-card border border-cb-border bg-cb-panel p-3">
                  <div className="text-[11px] font-semibold text-cb-ink-text">{b.email_subject}</div>
                  <p className="mt-1 whitespace-pre-line text-[11px] leading-relaxed text-cb-body">
                    {b.email_body}
                  </p>
                </div>
              </li>
            ))}
          </ul>
          <p className="border-t border-cb-divider px-3 py-2 text-[10px] text-cb-faint">
            Nothing is sent from here — enquiries are prepared with their package-only bundles, ready
            for a person to send.
          </p>
        </Card>
      )}

      <ReviewModal
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
        plans={plans}
        plansError={plansError}
        onPrepareDrafts={onPrepareDrafts}
      />
    </div>
  );
}

/** The assembled relevant-document set, per package. Controlled: the removals and expansions are
 *  lifted to the modal so "Prepare Gmail drafts" assembles exactly what is shown. */
function AttachmentPlan({
  plans,
  error,
  overrides,
  onOverridesChange,
}: {
  plans: SectionPlan[] | null;
  error: string;
  overrides: Record<string, SectionOverride>;
  onOverridesChange: (next: Record<string, SectionOverride>) => void;
}) {
  const ovFor = (key: string): SectionOverride => overrides[key] ?? { removed: [], whole: [] };
  const toggle = (key: string, field: keyof SectionOverride, doc: string) => {
    const cur = ovFor(key);
    const list = cur[field];
    const next = list.includes(doc) ? list.filter((d) => d !== doc) : [...list, doc];
    onOverridesChange({ ...overrides, [key]: { ...cur, [field]: next } });
  };

  if (error) return <p className="text-[11px] text-cb-bad-dark">{error}</p>;
  if (!plans) return <LoadingDots label="Assembling the relevant documents" />;
  if (plans.length === 0) return null;

  return (
    <div className="space-y-3">
      <SectionLabel>Relevant documents per package (assembled)</SectionLabel>
      <p className="text-[10px] text-cb-faint">
        Remove anything a firm doesn’t need, or expand a slice to the whole file — the Gmail drafts
        carry exactly this set.
      </p>
      {plans.map((plan) => {
        const ov = ovFor(plan.package_key);
        return (
          <div key={plan.package_key} className="rounded-cb-card border border-cb-border bg-cb-panel p-3">
            <div className="mb-1.5 text-[11px] font-semibold text-cb-ink-text">
              {tradeLabel(plan.package_key)}
            </div>
            <ul className="space-y-1">
              {plan.attachments.map((a, i) => {
                const removed = ov.removed.includes(a.source_doc);
                const priced = a.flags.includes("priced_return");
                const expanded = a.mode === "sliced" && ov.whole.includes(a.source_doc);
                const removable = a.mode !== "generated" && !priced;
                return (
                  <li
                    key={i}
                    className={cx(
                      "flex flex-wrap items-baseline gap-1.5 text-[11px]",
                      removed && "opacity-45",
                    )}
                  >
                    <span className={cx("font-medium text-cb-ink-text", removed && "line-through")}>
                      {a.out_filename || a.source_doc}
                    </span>
                    <Chip className="bg-white text-cb-body">
                      {a.mode === "sliced"
                        ? expanded
                          ? "whole file"
                          : `pp. ${formatPages(a.pages)}`
                        : a.mode === "generated"
                          ? "SoR sheet"
                          : "whole file"}
                    </Chip>
                    {priced && <Chip className="bg-cb-ok-tint text-cb-ok-dark">priced return</Chip>}
                    {a.clauses.length > 0 && !expanded && (
                      <span className="font-cb-mono font-medium text-cb-body">
                        {a.clauses.join(", ")}
                      </span>
                    )}
                    {/* Amber: a degradation to report, not a failure. cb has no amber tint, so
                        these are bordered rather than filled. */}
                    {a.flags.includes("scanned_whole") && (
                      <Chip className="border border-cb-brass-line text-cb-amber">scanned</Chip>
                    )}
                    {a.flags.includes("whole_clause_not_located") && (
                      <Chip className="border border-cb-brass-line text-cb-amber">
                        clause not located
                      </Chip>
                    )}
                    {a.flags.includes("whole_section_not_located") && (
                      <Chip className="border border-cb-brass-line text-cb-amber">
                        section not located
                      </Chip>
                    )}
                    <span className="text-cb-faint">{a.reason}</span>
                    <span className="ml-auto flex items-center gap-2">
                      {a.mode === "sliced" && !removed && !priced && (
                        <button
                          type="button"
                          className="font-medium text-cb-brass-text underline"
                          onClick={() => toggle(plan.package_key, "whole", a.source_doc)}
                        >
                          {expanded ? "use slice" : "expand to whole file"}
                        </button>
                      )}
                      {removable && (
                        <button
                          type="button"
                          className={cx(
                            "font-medium underline",
                            removed ? "text-cb-brass-text" : "text-cb-faint hover:text-cb-bad-dark",
                          )}
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
              <div className="mt-2 rounded-cb-chip border border-cb-brass-line px-2 py-1 text-[10px] text-cb-amber">
                Referenced but not supplied:{" "}
                <span className="font-semibold">
                  {plan.missing_specs.map((m) => m.spec).join(", ")}
                </span>{" "}
                — chase it or dispatch without.
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** The centred review pop-up (a Modal, never a Drawer): the selected firms grouped by package with
 *  add/remove, and for EACH selected firm an editable subject + body. The confirm writes the outbox
 *  with exactly the edited text. */
function ReviewModal({
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
  live,
  plans,
  plansError,
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
  live: boolean;
  plans: SectionPlan[] | null;
  plansError: string;
  onPrepareDrafts?: (overrides: { package_key: string; removed: string[]; whole: string[] }[]) => Promise<DispatchDraftsResponse>;
}) {
  const [composed, setComposed] = useState<Record<string, Draft>>({});
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState("");
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftResult, setDraftResult] = useState<DispatchDraftsResponse | null>(null);
  const [draftError, setDraftError] = useState("");
  const [overrides, setOverrides] = useState<Record<string, SectionOverride>>({});

  const approvedCount = Object.values(approvals).reduce((n, ids) => n + ids.length, 0);

  // A changed selection, draft or attachment set invalidates the last Gmail result — it described
  // a different bundle.
  useEffect(() => {
    setDraftResult(null);
    setDraftError("");
  }, [approvals, drafts, overrides]);

  useEffect(() => {
    if (!open) return;
    let stale = false;
    setComposing(true);
    setError("");
    onComposeDrafts()
      .then((set) => {
        if (stale) return;
        setComposed(
          Object.fromEntries(
            set.bundles.map((b) => [
              `${b.trade}:${b.firm_id}`,
              { subject: b.email_subject, body: b.email_body },
            ]),
          ),
        );
      })
      .catch((e: unknown) => !stale && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !stale && setComposing(false));
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, approvals]);

  const prepareGmailDrafts = () => {
    if (!onPrepareDrafts) return;
    setDraftBusy(true);
    setDraftError("");
    onPrepareDrafts(
      Object.entries(overrides).map(([package_key, ov]) => ({
        package_key,
        removed: ov.removed,
        whole: ov.whole,
      })),
    )
      .then(setDraftResult)
      .catch((e: unknown) => setDraftError(e instanceof Error ? e.message : String(e)))
      .finally(() => setDraftBusy(false));
  };

  const shown = (trade: string, fid: string): Draft =>
    drafts[`${trade}:${fid}`] ?? composed[`${trade}:${fid}`] ?? { subject: "", body: "" };

  return (
    <Modal open={open} onClose={onClose} title="Review & edit enquiries (approve-before-send)" wide>
      <div className="space-y-4">
        {error && (
          <p className="rounded-cb-card bg-cb-bad-tint px-3 py-2 text-[11px] text-cb-bad-dark">
            {error}
          </p>
        )}

        {trades.map((trade) => {
          const candidates = shortlist.per_trade[trade];
          const picked = approvals[trade] ?? [];
          return (
            <section key={trade}>
              <SectionLabel className="mb-1.5">{tradeLabel(trade)}</SectionLabel>
              <div className="mb-2 flex flex-wrap gap-1.5">
                {candidates.map((c) => {
                  const selected = picked.includes(c.firm.firm_id);
                  return (
                    <button
                      key={c.firm.firm_id}
                      type="button"
                      onClick={() => onToggleApprove(trade, c.firm.firm_id)}
                      className={cx(
                        "cb-press rounded-cb-pill border px-2.5 py-1 font-cb-sans text-[10px] font-medium",
                        selected && c.recommended_against && "border-cb-bad bg-cb-bad-tint text-cb-bad-dark",
                        selected && !c.recommended_against && "border-cb-ink bg-cb-ink text-white",
                        !selected && "border-cb-border-strong bg-white text-cb-muted hover:bg-cb-panel",
                      )}
                    >
                      {c.firm.name}
                      {c.recommended_against ? " ⚠" : ""}
                      {selected ? " ✓" : ""}
                    </button>
                  );
                })}
              </div>
              {picked.some(
                (fid) => candidates.find((c) => c.firm.firm_id === fid)?.recommended_against,
              ) && (
                <p className="mb-2 rounded-cb-card border border-cb-bad bg-cb-bad-tint px-3 py-1.5 text-[11px] text-cb-bad-dark">
                  A selected firm is recommended against — sending it an enquiry is allowed, but the
                  flag stands.
                </p>
              )}
              <div className="space-y-3">
                {picked.map((fid) => {
                  const cand = candidates.find((c) => c.firm.firm_id === fid);
                  if (!cand) return null;
                  const value = shown(trade, fid);
                  const edited = drafts[`${trade}:${fid}`] != null;
                  return (
                    <div key={fid} className="rounded-cb-card border border-cb-border bg-cb-panel p-3">
                      <div className="mb-1.5 flex flex-wrap items-center gap-2">
                        <span className="text-[11px] font-semibold text-cb-ink-text">
                          {cand.firm.name}
                        </span>
                        <span className="font-cb-mono text-[10px] text-cb-faint">{fid}</span>
                        {/* A person's edit outranks the model's draft, and says so. */}
                        {edited && <Chip className="bg-cb-ok-tint text-cb-ok-dark">edited</Chip>}
                        {composing && !edited && <LoadingDots label="composing" />}
                      </div>
                      <input
                        value={value.subject}
                        onChange={(e) => onEditDraft(trade, fid, { ...value, subject: e.target.value })}
                        placeholder="Subject"
                        className="mb-1.5 w-full rounded-cb-btn border border-cb-border-strong bg-white px-2.5 py-1.5 font-cb-mono text-[11px] text-cb-ink-text"
                      />
                      <textarea
                        value={value.body}
                        onChange={(e) => onEditDraft(trade, fid, { ...value, body: e.target.value })}
                        placeholder="Email body"
                        rows={6}
                        className="w-full rounded-cb-btn border border-cb-border-strong bg-white px-2.5 py-1.5 text-[11px] leading-relaxed text-cb-ink-text"
                      />
                    </div>
                  );
                })}
                {picked.length === 0 && (
                  <p className="text-[11px] italic text-cb-faint">
                    No firm selected for this package.
                  </p>
                )}
              </div>
            </section>
          );
        })}

        {live && approvedCount > 0 && (
          <div className="border-t border-cb-divider pt-3">
            <AttachmentPlan
              plans={plans}
              error={plansError}
              overrides={overrides}
              onOverridesChange={setOverrides}
            />
          </div>
        )}

        {/* The Gmail hand-off, surfaced honestly: aggregate AND per firm. A failure is a warning
            with an actionable reason, never a dead "Failed to fetch" — the backend returns partial
            success and the enquiries stay safe in the outbox. */}
        {draftError && (
          <p className="rounded-cb-card bg-cb-bad-tint px-3 py-2 text-[11px] text-cb-bad-dark">
            {draftError}
          </p>
        )}
        {draftResult && draftResult.message && (
          <div className="rounded-cb-card border border-cb-brass-line bg-cb-warm px-3 py-2 text-[11px] text-cb-amber">
            {draftResult.message}
          </div>
        )}
        {draftResult && (draftResult.drafted.length > 0 || draftResult.failed.length > 0) && (
          <div className="rounded-cb-card border border-cb-ok bg-cb-ok-tint px-3 py-2 text-[11px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-cb-ink-text">
                {draftResult.drafted.length} Gmail draft
                {draftResult.drafted.length === 1 ? "" : "s"} prepared
                {draftResult.failed.length > 0 && ` · ${draftResult.failed.length} failed`}
              </span>
              <a
                className="ml-auto font-semibold text-cb-brass-text underline"
                href="https://mail.google.com/mail/u/0/#drafts"
                target="_blank"
                rel="noreferrer"
              >
                Open Gmail drafts ↗
              </a>
            </div>
            <ul className="mt-1.5 divide-y divide-cb-divider">
              {draftResult.bundles.map((b) => {
                const failure = draftResult.failed.find((f) => f.firm_id === b.firm_id);
                const ok = draftResult.drafted.includes(b.firm_id);
                const to = draftResult.recipients.find((r) => r.firm_id === b.firm_id)?.to;
                return (
                  <li
                    key={`${b.trade}-${b.firm_id}`}
                    className="flex flex-wrap items-center gap-2 py-1"
                  >
                    <span className="text-cb-ink-text">{b.firm_name}</span>
                    <Chip className="bg-white text-cb-body">{tradeLabel(b.trade)}</Chip>
                    {to && <span className="font-cb-mono text-cb-faint">→ {to}</span>}
                    {ok && <Chip className="bg-white text-cb-ok-dark">Draft created</Chip>}
                    {failure && (
                      <Chip className="border border-cb-brass-line text-cb-amber">not drafted</Chip>
                    )}
                    {failure && <span className="text-cb-amber">{failure.reason}</span>}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 border-t border-cb-divider pt-3">
          <span className="text-[10px] text-cb-faint">
            Confirming prepares each enquiry in the outbox with exactly the text above — the human
            gate before anything leaves.
          </span>
          <div className="flex items-center gap-2">
            {live && onPrepareDrafts && (
              <Button
                variant="outline"
                onClick={prepareGmailDrafts}
                disabled={draftBusy || approvedCount === 0 || composing}
              >
                {draftBusy ? "Preparing…" : "Prepare Gmail drafts"}
              </Button>
            )}
            <Button
              variant="brass"
              onClick={onConfirm}
              disabled={sending || approvedCount === 0 || composing}
            >
              {sending
                ? "Writing…"
                : `Confirm — write ${approvedCount} enquir${approvedCount === 1 ? "y" : "ies"} →`}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
