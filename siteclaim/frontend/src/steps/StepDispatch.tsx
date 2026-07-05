import { useEffect, useState } from "react";

import { api } from "../api";
import type { Candidate, DispatchSet, DispatchStatus, ShortlistSet, TenderReplies } from "../types";
import { Pill, StepHeading, StepNav } from "../components";
import { Button, Card, Modal, cx } from "../ui";
import { tradeLabel } from "../format";

const STATUS_LABEL: Record<DispatchStatus, string> = {
  drafted: "Draft",
  approved: "Approved",
  sent_mock: "Sent (mock)",
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
  drafts,
  onToggleApprove,
  onEditDraft,
  onComposeDrafts,
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
  drafts: Record<string, Draft>;
  onToggleApprove: (trade: string, firmId: string) => void;
  onEditDraft: (trade: string, firmId: string, value: Draft) => void;
  onComposeDrafts: () => Promise<DispatchSet>;
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
        lead="The approve-before-send gate: review the selected firms and their enquiry emails in the pop-up, edit any draft, then confirm. Each firm receives only its trade's documents — the electrical firm gets the electrical scope, not the whole tender. Nothing is actually sent: confirming writes the mock outbox with exactly your edited text."
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

      {/* Persistent post-confirm summary + the mock outbox (the audit trail). */}
      {dispatch && (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line-soft bg-ok-bg/40 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-ink">
              {dispatch.bundles.length} enquir{dispatch.bundles.length === 1 ? "y" : "ies"} prepared — mock outbox
            </h2>
            <Pill tone="ok">{dispatch.bundles.length} written</Pill>
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
        </Card>
      )}

      {!demoMode && dispatch && tenderSlug && <RepliesPanel slug={tenderSlug} />}

      <StepNav onBack={onBack} onNext={onNext} nextLabel="Level the bids →" loading={loading} nextDisabled={!dispatch} />

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
}) {
  const [composed, setComposed] = useState<Record<string, Draft>>({});
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const approvedCount = Object.values(approvals).reduce((n, ids) => n + ids.length, 0);

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
                        {composing && !edited && <span className="text-[11px] italic text-ink-faint">composing…</span>}
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

        <div className="flex items-center justify-between gap-3 border-t border-line-soft pt-3">
          <span className="text-xs text-ink-faint">
            Confirming writes the mock outbox with exactly the text above — the human gate before anything is sent.
          </span>
          <Button onClick={onConfirm} loading={sending} disabled={approvedCount === 0 || composing}>
            Confirm — write {approvedCount} enquir{approvedCount === 1 ? "y" : "ies"} →
          </Button>
        </div>
      </div>
    </Modal>
  );
}
