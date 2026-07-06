import { useRef, useState } from "react";
import type { ChangeEvent } from "react";
import type { AwaitingFirm, AwaitingPackage, BidReply, LevelledBid } from "../types";
import { Pill, StepHeading, StepNav } from "../components";
import { Button, Card, Collapse, Drawer, MonoLabel, ScanLine, SeverityTag, cx } from "../ui";
import { hkd, tradeLabel } from "../format";

// Per-section leveling: one labelled comparison block PER SUBLET TRADE — a trade's bids
// are levelled only against each other, and two trades' items are never merged into one
// table. The rate edits and recompute operate within a trade (the recompute re-levels
// every section so the totals stay consistent).
export function StepLevel({
  sections,
  replies,
  stale,
  xlsxUrl,
  onEditRate,
  onRecompute,
  onBack,
  onNext,
  loading,
  live = false,
  awaiting = [],
  onUploadReturn,
}: {
  sections: Record<string, LevelledBid[]>;
  replies: BidReply[];
  stale: boolean;
  xlsxUrl: string;
  onEditRate: (firmId: string, itemRef: string, rate: number | null) => void;
  onRecompute: () => void;
  onBack: () => void;
  onNext: () => void;
  loading: boolean;
  // Live run: sections come from real priced returns, not a fixture. Packages still
  // waiting show the awaiting state with a manual-intake affordance.
  live?: boolean;
  awaiting?: AwaitingPackage[];
  onUploadReturn?: (trade: string, firmId: string, files: File[]) => Promise<void>;
}) {
  const [detail, setDetail] = useState<LevelledBid | null>(null);
  const trades = Object.keys(sections);
  const claimedOf = new Map(replies.map((r) => [`${r.trade}:${r.firm_id}`, r.claimed_total ?? 0]));

  if (live)
    return (
      <LiveLevel sections={sections} awaiting={awaiting} onUploadReturn={onUploadReturn} xlsxUrl={xlsxUrl} onBack={onBack} onNext={onNext} loading={loading} />
    );

  return (
    <div className="space-y-6">
      <StepHeading
        title="Level & compare"
        lead="Claude parses each returned Schedule of Rates; the rules engine recomputes every amount as qty × rate, sums the corrected total, flags arithmetic errors, treats a missing rate or provisional sum as a scope gap, and keeps exclusions as non-comparable. Each sublet trade is levelled only against its own bids — one comparison section per trade. Edit a rate and recompute to see the ranking move."
      />

      {trades.map((trade, i) => (
        <TradeSection
          key={trade}
          trade={trade}
          levelled={sections[trade]}
          replies={replies.filter((r) => r.trade === trade)}
          claimedOf={claimedOf}
          loading={loading && i === 0}
          onEditRate={onEditRate}
          onOpenDetail={setDetail}
        />
      ))}

      {stale && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-warn/40 bg-warn-bg px-4 py-2.5 text-sm">
          <span className="text-ink">A rate changed — the corrected totals are stale.</span>
          <Button onClick={onRecompute} loading={loading}>Recompute</Button>
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <a
          href={xlsxUrl}
          className="inline-flex items-center gap-2 rounded-lg border border-line bg-card px-4 py-2.5 text-sm font-semibold text-ink hover:bg-line-soft"
        >
          ⤓ Download Excel comparison{trades.length > 1 ? " — one sheet per trade" : ""}
        </a>
      </div>

      <StepNav onBack={onBack} onNext={onNext} nextLabel="Recommend an award →" loading={loading} nextDisabled={stale} />

      <BidDrawer
        bid={detail}
        claimed={detail ? claimedOf.get(`${detail.trade}:${detail.firm_id}`) ?? 0 : 0}
        onClose={() => setDetail(null)}
      />
    </div>
  );
}

// One sublet trade's full leveling block: claimed-vs-corrected, the editable rate matrix,
// and that trade's corrections/gaps/exclusions. Never mixes another trade's items.
function TradeSection({
  trade,
  levelled,
  replies,
  claimedOf,
  loading,
  onEditRate,
  onOpenDetail,
}: {
  trade: string;
  levelled: LevelledBid[];
  replies: BidReply[];
  claimedOf: Map<string, number>;
  loading: boolean;
  onEditRate: (firmId: string, itemRef: string, rate: number | null) => void;
  onOpenDetail: (bid: LevelledBid) => void;
}) {
  const firms = replies.map((r) => r.firm_id);
  const nameOf = new Map(levelled.map((b) => [b.firm_id, b.firm_name]));
  const correctedOf = new Map(levelled.map((b) => [b.firm_id, b.corrected_total]));

  // Item order from the first reply; qty/rate per (firm,item) from the replies.
  const items = replies[0]?.line_items.map((l) => ({ ref: l.item_ref, description: l.description })) ?? [];
  const line = (firmId: string, ref: string) =>
    replies.find((r) => r.firm_id === firmId)?.line_items.find((l) => l.item_ref === ref);

  const cleanCorrected = levelled.map((b) => b.corrected_total);
  const cheapest = cleanCorrected.length ? Math.min(...cleanCorrected) : 0;

  return (
    <section className="space-y-4">
      {/* Summary: claimed vs corrected */}
      <Card className="relative overflow-hidden">
        <ScanLine active={loading} />
        <h2 className="border-b border-line-soft px-4 py-2.5 text-xs font-semibold uppercase tracking-eyebrow text-ink-soft">
          {tradeLabel(trade)} — claimed vs corrected
        </h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line-soft text-left text-xs uppercase tracking-eyebrow text-ink-faint">
              <th className="px-4 py-2 font-semibold">Firm</th>
              <th className="px-4 py-2 text-right font-semibold">Claimed</th>
              <th className="px-4 py-2 text-right font-semibold">Corrected</th>
              <th className="px-4 py-2 text-right font-semibold">Normalised</th>
              <th className="px-4 py-2 font-semibold">Notes</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-soft">
            {[...levelled]
              .sort((a, b) => a.corrected_total - b.corrected_total)
              .map((b) => {
                const claimed = claimedOf.get(`${b.trade}:${b.firm_id}`) ?? 0;
                const delta = b.corrected_total - claimed;
                const isCheapest = b.corrected_total === cheapest;
                return (
                  <tr
                    key={b.firm_id}
                    onClick={() => onOpenDetail(b)}
                    title="Open the levelled-bid record"
                    className={cx("cursor-pointer transition-colors", isCheapest ? "bg-ok-bg/30" : "hover:bg-paper-soft/70")}
                  >
                    <td className="px-4 py-2.5 text-ink">
                      <span className="font-medium hover:text-brand">{b.firm_name}</span>{" "}
                      <span className="tabular text-xs text-ink-faint">{b.firm_id}</span>
                    </td>
                    <td className="tabular px-4 py-2.5 text-right text-ink-soft">{hkd(claimed)}</td>
                    <td className="tabular px-4 py-2.5 text-right font-semibold text-ink">
                      {hkd(b.corrected_total)}
                      {Math.abs(delta) > 0.5 && (
                        <span className="ml-1 text-xs text-bad">({delta > 0 ? "+" : ""}{hkd(delta)})</span>
                      )}
                    </td>
                    <td className="tabular px-4 py-2.5 text-right text-ink-soft">{hkd(b.normalized_total)}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {b.arithmetic_findings.length > 0 && <Pill tone="bad">{b.arithmetic_findings.length} corrected</Pill>}
                        {b.scope_gaps.length > 0 && <Pill tone="brand">{b.scope_gaps.length} scope gap</Pill>}
                        {b.exclusions.length > 0 && <Pill>{b.exclusions.length} exclusion</Pill>}
                      </div>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </Card>

      {/* Editable rate matrix */}
      <Card className="overflow-x-auto">
        <h2 className="border-b border-line-soft px-4 py-2.5 text-xs font-semibold uppercase tracking-eyebrow text-ink-soft">
          {tradeLabel(trade)} — rates by item (edit a rate to re-level)
        </h2>
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-line-soft text-left text-xs uppercase tracking-eyebrow text-ink-faint">
              <th className="px-3 py-2 font-semibold">Item</th>
              {firms.map((f) => (
                <th key={f} className="tabular px-3 py-2 text-right font-semibold">{f}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line-soft">
            {items.map(({ ref, description }) => (
              <tr key={ref}>
                <td className="px-3 py-2">
                  <div className="tabular text-xs font-semibold text-ink">{ref}</div>
                  <div className="text-xs text-ink-faint">{description}</div>
                </td>
                {firms.map((f) => {
                  const l = line(f, ref);
                  const corrected = l && l.rate != null ? l.qty * l.rate : null;
                  return (
                    <td key={f} className="px-3 py-2 text-right align-top">
                      <input
                        type="number"
                        value={l?.rate ?? ""}
                        placeholder="—"
                        onChange={(e) => onEditRate(f, ref, e.target.value === "" ? null : Number(e.target.value))}
                        className="tabular w-24 rounded border border-line bg-card px-2 py-1 text-right text-xs text-ink focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                      />
                      <div className="tabular mt-0.5 text-[11px] text-ink-faint">
                        {corrected != null ? hkd(corrected) : "scope gap"}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="border-t-2 border-line bg-paper/40">
              <td className="px-3 py-2 text-xs font-semibold uppercase tracking-eyebrow text-ink-soft">Corrected total</td>
              {firms.map((f) => (
                <td key={f} className="tabular px-3 py-2 text-right text-sm font-bold text-ink">
                  {hkd(correctedOf.get(f) ?? 0)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </Card>

      {/* Called-out corrections, gaps, exclusions — this trade only */}
      <div className="grid gap-4 md:grid-cols-3">
        <CalloutCard title="Arithmetic corrections" tone="bad">
          {levelled.flatMap((b) =>
            b.arithmetic_findings.map((f, i) => (
              <li key={`${b.firm_id}-${i}`} className="py-1">
                <span className="font-medium text-ink">{nameOf.get(b.firm_id)}</span>
                <span className="tabular text-xs text-ink-faint"> · {f.location}</span>
                <div className="text-xs text-ink-soft">{f.issue} → {hkd(f.corrected_value)}</div>
              </li>
            )),
          )}
        </CalloutCard>
        <CalloutCard title="Scope gaps" tone="brand">
          {levelled.flatMap((b) =>
            b.scope_gaps.map((g, i) => (
              <li key={`${b.firm_id}-${i}`} className="py-1">
                <span className="font-medium text-ink">{nameOf.get(b.firm_id)}</span>
                <div className="text-xs text-ink-soft">{g}</div>
              </li>
            )),
          )}
        </CalloutCard>
        <CalloutCard title="Exclusions (non-comparable)" tone="neutral">
          {levelled.flatMap((b) =>
            b.exclusions.map((x, i) => (
              <li key={`${b.firm_id}-${i}`} className="py-1">
                <span className="font-medium text-ink">{nameOf.get(b.firm_id)}</span>
                <div className="text-xs text-ink-soft">{x}</div>
              </li>
            )),
          )}
        </CalloutCard>
      </div>
    </section>
  );
}

// The levelled-bid record: claimed vs corrected up top, then the engine's findings —
// every value already computed by the rules engine and shown in the tables above.
function BidDrawer({ bid, claimed, onClose }: { bid: LevelledBid | null; claimed: number; onClose: () => void }) {
  const delta = bid ? bid.corrected_total - claimed : 0;
  return (
    <Drawer
      open={bid != null}
      onClose={onClose}
      eyebrow="Levelled bid record"
      tone="ink"
      title={bid?.firm_name ?? ""}
      subtitle={bid && <span className="tabular">{bid.firm_id} · {bid.trade}</span>}
      footer="Every corrected figure is recomputed by the deterministic rules engine as qty × rate — Claude (Layer 2) parses the reply, it never prices."
    >
      {bid && (
        <div className="space-y-3">
          <div>
            <MonoLabel className="mb-1.5">Claimed vs corrected</MonoLabel>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-xl border border-line-soft bg-paper-soft px-4 py-3">
                <MonoLabel>Claimed</MonoLabel>
                <div className="tabular mt-0.5 text-base font-semibold text-ink-soft">{hkd(claimed)}</div>
              </div>
              <div className="rounded-xl border border-line-soft bg-paper-soft px-4 py-3">
                <MonoLabel>Corrected</MonoLabel>
                <div className="tabular mt-0.5 text-base font-semibold text-ink">
                  {hkd(bid.corrected_total)}
                  {Math.abs(delta) > 0.5 && (
                    <span className="ml-1 text-xs text-bad">({delta > 0 ? "+" : ""}{hkd(delta)})</span>
                  )}
                </div>
              </div>
            </div>
            <div className="tabular mt-1.5 text-[11px] text-ink-faint">Normalised (exclusions held out): {hkd(bid.normalized_total)}</div>
          </div>

          <div>
            <Collapse title="Arithmetic corrections" count={bid.arithmetic_findings.length} defaultOpen={bid.arithmetic_findings.length > 0}>
              {bid.arithmetic_findings.length > 0 ? (
                <ul className="space-y-2">
                  {bid.arithmetic_findings.map((f, i) => (
                    <li key={i} className="text-xs leading-relaxed text-ink-soft">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <SeverityTag severity={f.severity} />
                        <span className="tabular text-ink-faint">{f.location}</span>
                      </div>
                      <div className="mt-0.5">{f.issue} → <span className="tabular font-semibold text-ink">{hkd(f.corrected_value)}</span></div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-ink-faint">The bid sheet's arithmetic checks out.</p>
              )}
            </Collapse>

            <Collapse title="Scope gaps" count={bid.scope_gaps.length} defaultOpen={bid.scope_gaps.length > 0}>
              {bid.scope_gaps.length > 0 ? (
                <ul className="space-y-1 text-xs text-ink-soft">
                  {bid.scope_gaps.map((g, i) => <li key={i}>{g}</li>)}
                </ul>
              ) : (
                <p className="text-xs text-ink-faint">Every scheduled item is priced.</p>
              )}
            </Collapse>

            <Collapse title="Exclusions (non-comparable)" count={bid.exclusions.length}>
              {bid.exclusions.length > 0 ? (
                <ul className="space-y-1 text-xs text-ink-soft">
                  {bid.exclusions.map((x, i) => <li key={i}>{x}</li>)}
                </ul>
              ) : (
                <p className="text-xs text-ink-faint">No exclusions declared.</p>
              )}
            </Collapse>
          </div>
        </div>
      )}
    </Drawer>
  );
}

function CalloutCard({ title, tone, children }: { title: string; tone: "bad" | "brand" | "neutral"; children: React.ReactNode }) {
  const arr = Array.isArray(children) ? children.flat() : [children];
  const empty = arr.filter(Boolean).length === 0;
  const accent = tone === "bad" ? "text-bad" : tone === "brand" ? "text-brand" : "text-ink-soft";
  return (
    <Card className="overflow-hidden">
      <h3 className={cx("border-b border-line-soft px-3 py-2 text-xs font-semibold uppercase tracking-eyebrow", accent)}>{title}</h3>
      {empty ? (
        <p className="px-3 py-2 text-xs text-ink-faint">None.</p>
      ) : (
        <ul className="divide-y divide-line-soft px-3">{children}</ul>
      )}
    </Card>
  );
}

// --- Live run: awaiting returns + per-firm manual intake ---------------------
// One block per dispatched sublet package. A package with returns shows the read-only
// levelled comparison (the raw reply and its editable rate matrix belong to the demo path);
// every dispatched firm shows its status and the [SiteSource Ref] its enquiry carries, with
// an "Upload a priced return" affordance that levels one firm's SoR into this section.
function LiveLevel({
  sections,
  awaiting,
  onUploadReturn,
  xlsxUrl,
  onBack,
  onNext,
  loading,
}: {
  sections: Record<string, LevelledBid[]>;
  awaiting: AwaitingPackage[];
  onUploadReturn?: (trade: string, firmId: string, files: File[]) => Promise<void>;
  xlsxUrl: string;
  onBack: () => void;
  onNext: () => void;
  loading: boolean;
}) {
  const [detail, setDetail] = useState<LevelledBid | null>(null);
  const totalReceived = Object.values(sections).reduce((n, bids) => n + bids.length, 0);

  return (
    <div className="space-y-6">
      <StepHeading
        title="Level & compare"
        lead="Live run — each dispatched package waits for its priced returns. As a return lands (via the inbound loop, or uploaded here) the rules engine levels it and that package's comparison activates. No demo bids are ever shown on a live run."
      />

      {awaiting.length === 0 && (
        <Card className="p-6 text-sm text-ink-soft">
          No dispatched sublet packages yet — route a package to sublet and dispatch its enquiries first.
        </Card>
      )}

      {awaiting.map((pkg) => {
        const bids = sections[pkg.trade] ?? [];
        const received = pkg.firms.filter((f) => f.received).length;
        return (
          <section key={pkg.trade} className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-display text-base font-semibold tracking-display text-ink">{tradeLabel(pkg.trade)}</h2>
              <Pill tone={received > 0 ? "ok" : "neutral"}>
                {pkg.firms.length} enquir{pkg.firms.length === 1 ? "y" : "ies"} sent · {received} priced return{received === 1 ? "" : "s"} received
              </Pill>
            </div>

            {bids.length > 0 && <LiveComparison bids={bids} onOpenDetail={setDetail} />}

            <Card className="divide-y divide-line-soft">
              {pkg.firms.map((f) => (
                <ReturnRow key={f.firm_id} trade={pkg.trade} firm={f} onUploadReturn={onUploadReturn} />
              ))}
            </Card>
            <p className="text-xs text-ink-faint">
              Replies quoting the enquiry's <span className="tabular">[SiteSource Ref]</span> attach automatically once the inbound loop is wired; upload a return above in the meantime.
            </p>
          </section>
        );
      })}

      {totalReceived > 0 && (
        <a
          href={xlsxUrl}
          className="inline-flex items-center gap-2 rounded-lg border border-line bg-card px-4 py-2.5 text-sm font-semibold text-ink hover:bg-line-soft"
        >
          ⤓ Download Excel comparison
        </a>
      )}

      <StepNav onBack={onBack} onNext={onNext} nextLabel="Recommend an award →" loading={loading} nextDisabled={totalReceived === 0} />
      <BidDrawer bid={detail} claimed={0} onClose={() => setDetail(null)} />
    </div>
  );
}

// The read-only levelled comparison for a package's received returns (no editable matrix —
// the returns are the source of truth; the engine's corrections are shown as findings).
function LiveComparison({ bids, onOpenDetail }: { bids: LevelledBid[]; onOpenDetail: (b: LevelledBid) => void }) {
  const cheapest = bids.length ? Math.min(...bids.map((b) => b.corrected_total)) : 0;
  return (
    <Card className="overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line-soft text-left text-xs uppercase tracking-eyebrow text-ink-faint">
            <th className="px-4 py-2 font-semibold">Firm</th>
            <th className="px-4 py-2 text-right font-semibold">Corrected</th>
            <th className="px-4 py-2 text-right font-semibold">Normalised</th>
            <th className="px-4 py-2 font-semibold">Notes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-soft">
          {[...bids]
            .sort((a, b) => a.corrected_total - b.corrected_total)
            .map((b) => (
              <tr
                key={b.firm_id}
                onClick={() => onOpenDetail(b)}
                title="Open the levelled-bid record"
                className={cx("cursor-pointer transition-colors", b.corrected_total === cheapest ? "bg-ok-bg/30" : "hover:bg-paper-soft/70")}
              >
                <td className="px-4 py-2.5 text-ink">
                  <span className="font-medium hover:text-brand">{b.firm_name}</span> <span className="tabular text-xs text-ink-faint">{b.firm_id}</span>
                </td>
                <td className="tabular px-4 py-2.5 text-right font-semibold text-ink">{hkd(b.corrected_total)}</td>
                <td className="tabular px-4 py-2.5 text-right text-ink-soft">{hkd(b.normalized_total)}</td>
                <td className="px-4 py-2.5">
                  <div className="flex flex-wrap gap-1">
                    {b.arithmetic_findings.length > 0 && <Pill tone="bad">{b.arithmetic_findings.length} corrected</Pill>}
                    {b.scope_gaps.length > 0 && <Pill tone="brand">{b.scope_gaps.length} scope gap</Pill>}
                    {b.exclusions.length > 0 && <Pill>{b.exclusions.length} exclusion</Pill>}
                  </div>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </Card>
  );
}

// One dispatched firm awaiting its return, with the manual-intake affordance.
function ReturnRow({
  trade,
  firm,
  onUploadReturn,
}: {
  trade: string;
  firm: AwaitingFirm;
  onUploadReturn?: (trade: string, firmId: string, files: File[]) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const onPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!picked.length || !onUploadReturn) return;
    setBusy(true);
    setError(null);
    try {
      await onUploadReturn(trade, firm.firm_id, picked);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ink">{firm.firm_name}</span>
          <span className="tabular text-xs text-ink-faint">{firm.firm_id}</span>
          {firm.received ? (
            <Pill tone="ok">return received</Pill>
          ) : (
            <Pill tone="neutral">{firm.status === "sent_mock" ? "in outbox · awaiting" : "awaiting reply"}</Pill>
          )}
        </div>
        {firm.ref && <div className="tabular mt-0.5 text-[11px] text-ink-faint">Ref {firm.ref}</div>}
        {error && <div className="mt-1 text-xs text-bad">{error}</div>}
      </div>
      <input ref={inputRef} type="file" multiple accept=".xlsx,application/pdf,image/*" className="sr-only" onChange={onPick} />
      <Button variant="ghost" loading={busy} onClick={() => inputRef.current?.click()}>
        {firm.received ? "Replace return" : "Upload a priced return"}
      </Button>
    </div>
  );
}
