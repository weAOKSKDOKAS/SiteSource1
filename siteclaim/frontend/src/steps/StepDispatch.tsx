import type { DispatchSet, DispatchStatus, ShortlistSet } from "../types";
import { Pill, StepHeading, StepNav } from "../components";
import { Button, Card, cx } from "../ui";
import { tradeLabel } from "../format";

const STATUS_LABEL: Record<DispatchStatus, string> = {
  drafted: "Draft",
  approved: "Approved",
  sent_mock: "Sent (mock)",
};

export function StepDispatch({
  shortlist,
  heroTrade,
  approvals,
  dispatch,
  onToggleApprove,
  onSend,
  onBack,
  onNext,
  loading,
}: {
  shortlist: ShortlistSet;
  heroTrade: string;
  approvals: Record<string, string[]>;
  dispatch: DispatchSet | null;
  onToggleApprove: (trade: string, firmId: string) => void;
  onSend: () => void;
  onBack: () => void;
  onNext: () => void;
  loading: boolean;
}) {
  const trades = Object.keys(shortlist.per_trade).sort((a, b) =>
    a === heroTrade ? -1 : b === heroTrade ? 1 : a.localeCompare(b),
  );
  const approvedCount = Object.values(approvals).reduce((n, ids) => n + ids.length, 0);

  return (
    <div className="space-y-6">
      <StepHeading
        title="Dispatch enquiries"
        lead="Approve which firms to invite (the human gate). Each firm receives only its trade's documents — the electrical firm gets the electrical scope, not the whole tender — and a composed enquiry email. Nothing is actually sent: this writes to a mock outbox."
      />

      {trades.map((trade) => {
        const approved = approvals[trade] ?? [];
        return (
          <Card key={trade} className="overflow-hidden">
            <div className="border-b border-line-soft px-4 py-2.5 text-sm font-semibold text-ink">{tradeLabel(trade)}</div>
            <ul className="divide-y divide-line-soft">
              {shortlist.per_trade[trade].map((c) => {
                const checked = approved.includes(c.firm.firm_id);
                return (
                  <li key={c.firm.firm_id} className="flex items-center gap-3 px-4 py-2.5">
                    <input
                      id={`ap-${c.firm.firm_id}`}
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggleApprove(trade, c.firm.firm_id)}
                      className="h-4 w-4 accent-[var(--color-brand)]"
                    />
                    <label htmlFor={`ap-${c.firm.firm_id}`} className="flex flex-1 flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-ink">{c.firm.name}</span>
                      <span className="tabular text-xs text-ink-faint">{c.firm.firm_id}</span>
                      {c.recommended_against && <Pill tone="bad">recommended against</Pill>}
                    </label>
                  </li>
                );
              })}
            </ul>
          </Card>
        );
      })}

      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-ink-soft">
          {approvedCount} firm{approvedCount === 1 ? "" : "s"} approved.
        </span>
        <Button onClick={onSend} loading={loading} disabled={approvedCount === 0}>
          Send to approved firms (mock) →
        </Button>
      </div>

      {dispatch && (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line-soft bg-ok-bg/40 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-ink">Mock outbox</h2>
            <Pill tone="ok">{dispatch.bundles.length} sent</Pill>
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

      <StepNav onBack={onBack} onNext={onNext} nextLabel="Level the bids →" loading={loading} nextDisabled={!dispatch} />
    </div>
  );
}
