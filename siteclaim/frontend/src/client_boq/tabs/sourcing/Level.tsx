// Sourcing step 3 — level & compare. Ported from StepLevel, restyled, behaviour unchanged.
//
// The one sentence this screen exists to make true: THE CORRECTED TOTAL IS OURS. A firm's claimed
// total is what they wrote; the corrected total is what the deterministic rules engine recomputed
// as qty × rate. The gap between them is the finding, and it is shown beside every figure rather
// than folded silently into a single number. Claude parses a return; it never prices one.
//
// Two other rules carried over intact:
//
//  * A MISSING RATE IS A SCOPE GAP, NOT A ZERO. A bid that priced nothing for an item is not the
//    cheapest bid — it is an incomplete one, and it says so.
//  * NOTHING IS DELETED. A superseded or withdrawn reply is kept as history; withdrawing re-levels
//    the comparison without it, and the drawer still lists it.

import { useRef, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";

import type {
  AwaitingFirm,
  AwaitingPackage,
  BidReply,
  LevelledBid,
  MisdirectedHint,
  ReplyStatus,
  TenderReplies,
  TenderReplyInfo,
} from "../../types";
import {
  Button,
  Card,
  Chip,
  Collapse,
  Drawer,
  ScanLine,
  SectionLabel,
  SeverityTag,
  cx,
  money,
} from "../../ui";

const hkd = (v: number) => money(v);

function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}

export function Level(props: {
  sections: Record<string, LevelledBid[]>;
  replies: BidReply[];
  stale: boolean;
  xlsxUrl: string;
  loading: boolean;
  onEditRate: (firmId: string, itemRef: string, rate: number | null) => void;
  onRecompute: () => void;
  // Live run: sections come from real priced returns, not a fixture.
  live?: boolean;
  awaiting?: AwaitingPackage[];
  onUploadReturn?: (trade: string, firmId: string, files: File[]) => Promise<MisdirectedHint | null>;
  tenderReplies?: TenderReplies | null;
  comparisonUrl?: string;
  onRefreshReplies?: () => void;
  onWithdrawReply?: (firmId: string, packageKey: string) => Promise<void>;
}) {
  const { sections, replies, stale, xlsxUrl, loading, onEditRate, onRecompute } = props;
  const [detail, setDetail] = useState<LevelledBid | null>(null);
  const trades = Object.keys(sections);
  const claimedOf = new Map(replies.map((r) => [`${r.trade}:${r.firm_id}`, r.claimed_total ?? 0]));

  if (props.live)
    return (
      <LiveLevel
        sections={sections}
        awaiting={props.awaiting ?? []}
        onUploadReturn={props.onUploadReturn}
        xlsxUrl={xlsxUrl}
        tenderReplies={props.tenderReplies ?? null}
        comparisonUrl={props.comparisonUrl ?? ""}
        onRefreshReplies={props.onRefreshReplies}
        onWithdrawReply={props.onWithdrawReply}
      />
    );

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-[12px] leading-relaxed text-cb-muted">
        The rules engine recomputes every amount as qty × rate, sums the corrected total, flags
        arithmetic errors, treats a missing rate or provisional sum as a scope gap, and keeps
        exclusions as non-comparable. Each package is levelled only against its own bids. Edit a rate
        and recompute to see the ranking move.
      </p>

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
        <div className="flex items-center justify-between gap-3 rounded-cb-card border border-cb-brass-line bg-cb-warm px-4 py-2.5 text-[12px]">
          <span className="text-cb-ink-text">A rate changed — the corrected totals are stale.</span>
          <Button variant="brass" onClick={onRecompute} disabled={loading}>
            {loading ? "Recomputing…" : "Recompute"}
          </Button>
        </div>
      )}

      <a
        href={xlsxUrl}
        className="inline-flex items-center gap-2 rounded-cb-btn border border-cb-border-strong bg-white px-4 py-2 font-cb-sans text-[11px] font-semibold text-cb-ink-text hover:bg-cb-panel"
      >
        ⤓ Download Excel comparison{trades.length > 1 ? " — one sheet per package" : ""}
      </a>

      <BidDrawer
        bid={detail}
        claimed={detail ? claimedOf.get(`${detail.trade}:${detail.firm_id}`) ?? 0 : 0}
        onClose={() => setDetail(null)}
      />
    </div>
  );
}

/** One package's full leveling block: claimed-vs-corrected, the editable rate matrix, and that
 *  package's corrections / gaps / exclusions. Never mixes another package's items. */
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
  const items = replies[0]?.line_items.map((l) => ({ ref: l.item_ref, description: l.description })) ?? [];
  const line = (firmId: string, ref: string) =>
    replies.find((r) => r.firm_id === firmId)?.line_items.find((l) => l.item_ref === ref);
  const cheapest = levelled.length ? Math.min(...levelled.map((b) => b.corrected_total)) : 0;

  return (
    <section className="space-y-3">
      <Card flush className="relative overflow-hidden">
        <ScanLine active={loading} />
        <h3 className="border-b border-cb-divider px-3 py-2 font-cb-sans text-[10px] font-semibold uppercase tracking-cb-chip text-cb-muted">
          {tradeLabel(trade)} — claimed vs corrected
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-cb-divider text-left font-cb-sans text-[9px] uppercase tracking-cb-chip text-cb-faint">
                <th className="px-3 py-2 font-semibold">Firm</th>
                <th className="px-3 py-2 text-right font-semibold">Claimed</th>
                <th className="px-3 py-2 text-right font-semibold">Corrected</th>
                <th className="px-3 py-2 text-right font-semibold">Normalised</th>
                <th className="px-3 py-2 font-semibold">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-cb-divider">
              {[...levelled]
                .sort((a, b) => a.corrected_total - b.corrected_total)
                .map((b) => {
                  const claimed = claimedOf.get(`${b.trade}:${b.firm_id}`) ?? 0;
                  const delta = b.corrected_total - claimed;
                  return (
                    <tr
                      key={b.firm_id}
                      onClick={() => onOpenDetail(b)}
                      title="Open the levelled-bid record"
                      className={cx(
                        "cursor-pointer",
                        b.corrected_total === cheapest ? "bg-cb-ok-tint/50" : "hover:bg-cb-panel/70",
                      )}
                    >
                      <td className="px-3 py-2 text-cb-ink-text">
                        <span className="font-medium">{b.firm_name}</span>{" "}
                        <span className="font-cb-mono text-[10px] text-cb-faint">{b.firm_id}</span>
                      </td>
                      <td className="px-3 py-2 text-right font-cb-mono text-cb-body">{hkd(claimed)}</td>
                      <td className="px-3 py-2 text-right font-cb-mono font-semibold text-cb-ink-text">
                        {hkd(b.corrected_total)}
                        {/* The correction, stated. Red because a figure had to be changed — not a
                            style choice, the whole point of the screen. */}
                        {Math.abs(delta) > 0.5 && (
                          <span className="ml-1 text-[10px] text-cb-bad-dark">
                            ({delta > 0 ? "+" : ""}
                            {hkd(delta)})
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-cb-mono text-cb-body">
                        {hkd(b.normalized_total)}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {b.arithmetic_findings.length > 0 && (
                            <Chip className="bg-cb-bad-tint text-cb-bad-dark">
                              {b.arithmetic_findings.length} corrected
                            </Chip>
                          )}
                          {b.scope_gaps.length > 0 && (
                            <Chip className="border border-cb-brass-line text-cb-amber">
                              {b.scope_gaps.length} scope gap
                            </Chip>
                          )}
                          {b.exclusions.length > 0 && (
                            <Chip className="bg-cb-panel text-cb-muted">
                              {b.exclusions.length} exclusion
                            </Chip>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card flush className="overflow-x-auto">
        <h3 className="border-b border-cb-divider px-3 py-2 font-cb-sans text-[10px] font-semibold uppercase tracking-cb-chip text-cb-muted">
          {tradeLabel(trade)} — rates by item (edit a rate to re-level)
        </h3>
        <table className="w-full min-w-[640px] text-[12px]">
          <thead>
            <tr className="border-b border-cb-divider text-left font-cb-sans text-[9px] uppercase tracking-cb-chip text-cb-faint">
              <th className="px-3 py-2 font-semibold">Item</th>
              {firms.map((f) => (
                <th key={f} className="px-3 py-2 text-right font-cb-mono font-semibold">
                  {f}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-cb-divider">
            {items.map(({ ref, description }) => (
              <tr key={ref}>
                <td className="px-3 py-2">
                  <div className="font-cb-mono text-[10px] font-semibold text-cb-ink-text">{ref}</div>
                  <div className="text-[10px] text-cb-faint">{description}</div>
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
                        onChange={(e) =>
                          onEditRate(f, ref, e.target.value === "" ? null : Number(e.target.value))
                        }
                        className="w-24 rounded-cb-chip border border-cb-border-strong bg-white px-2 py-1 text-right font-cb-mono text-[10px] text-cb-ink-text"
                      />
                      {/* "scope gap", never HK$0 — an unpriced item is an incomplete bid, not a
                          cheap one, and the two must never render alike. */}
                      <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">
                        {corrected != null ? hkd(corrected) : "scope gap"}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="border-t-2 border-cb-border-strong bg-cb-panel">
              <td className="px-3 py-2 font-cb-sans text-[9px] font-semibold uppercase tracking-cb-chip text-cb-muted">
                Corrected total
              </td>
              {firms.map((f) => (
                <td key={f} className="px-3 py-2 text-right font-cb-mono text-[12px] font-bold text-cb-ink-text">
                  {hkd(correctedOf.get(f) ?? 0)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </Card>

      <div className="grid gap-3 md:grid-cols-3">
        <CalloutCard title="Arithmetic corrections" accent="text-cb-bad-dark">
          {levelled.flatMap((b) =>
            b.arithmetic_findings.map((f, i) => (
              <li key={`${b.firm_id}-${i}`} className="py-1">
                <span className="font-medium text-cb-ink-text">{nameOf.get(b.firm_id)}</span>
                <span className="font-cb-mono text-[10px] text-cb-faint"> · {f.location}</span>
                <div className="text-[10px] text-cb-body">
                  {f.issue} → {hkd(f.corrected_value)}
                </div>
              </li>
            )),
          )}
        </CalloutCard>
        <CalloutCard title="Scope gaps" accent="text-cb-amber">
          {levelled.flatMap((b) =>
            b.scope_gaps.map((g, i) => (
              <li key={`${b.firm_id}-${i}`} className="py-1">
                <span className="font-medium text-cb-ink-text">{nameOf.get(b.firm_id)}</span>
                <div className="text-[10px] text-cb-body">{g}</div>
              </li>
            )),
          )}
        </CalloutCard>
        <CalloutCard title="Exclusions (non-comparable)" accent="text-cb-muted">
          {levelled.flatMap((b) =>
            b.exclusions.map((x, i) => (
              <li key={`${b.firm_id}-${i}`} className="py-1">
                <span className="font-medium text-cb-ink-text">{nameOf.get(b.firm_id)}</span>
                <div className="text-[10px] text-cb-body">{x}</div>
              </li>
            )),
          )}
        </CalloutCard>
      </div>
    </section>
  );
}

function CalloutCard({
  title,
  accent,
  children,
}: {
  title: string;
  accent: string;
  children: ReactNode;
}) {
  const arr = Array.isArray(children) ? (children as ReactNode[]).flat() : [children];
  const empty = arr.filter(Boolean).length === 0;
  return (
    <Card flush className="overflow-hidden">
      <h4
        className={cx(
          "border-b border-cb-divider px-3 py-2 font-cb-sans text-[9px] font-semibold uppercase tracking-cb-chip",
          accent,
        )}
      >
        {title}
      </h4>
      {empty ? (
        <p className="px-3 py-2 text-[10px] text-cb-faint">None.</p>
      ) : (
        <ul className="divide-y divide-cb-divider px-3">{children}</ul>
      )}
    </Card>
  );
}

/** The levelled-bid record. Every figure here was computed by the rules engine, so the drawer is
 *  navy-accented: nothing in it was written by a model. */
function BidDrawer({
  bid,
  claimed,
  onClose,
}: {
  bid: LevelledBid | null;
  claimed: number;
  onClose: () => void;
}) {
  const delta = bid ? bid.corrected_total - claimed : 0;
  return (
    <Drawer
      open={bid != null}
      onClose={onClose}
      eyebrow="Levelled bid record"
      accent="bg-cb-navy"
      title={bid?.firm_name ?? ""}
      subtitle={
        bid && (
          <span className="font-cb-mono">
            {bid.firm_id} · {bid.trade}
          </span>
        )
      }
      footer="Every corrected figure is recomputed by the deterministic rules engine as qty × rate — Claude parses the reply, it never prices."
    >
      {bid && (
        <div className="space-y-3">
          <div>
            <SectionLabel className="mb-1.5">Claimed vs corrected</SectionLabel>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-cb-card border border-cb-border bg-cb-panel px-3 py-2">
                <SectionLabel>Claimed</SectionLabel>
                <div className="mt-0.5 font-cb-mono text-[13px] font-semibold text-cb-body">
                  {hkd(claimed)}
                </div>
              </div>
              <div className="rounded-cb-card border border-cb-border bg-cb-panel px-3 py-2">
                <SectionLabel>Corrected</SectionLabel>
                <div className="mt-0.5 font-cb-mono text-[13px] font-semibold text-cb-ink-text">
                  {hkd(bid.corrected_total)}
                  {Math.abs(delta) > 0.5 && (
                    <span className="ml-1 text-[10px] text-cb-bad-dark">
                      ({delta > 0 ? "+" : ""}
                      {hkd(delta)})
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="mt-1.5 font-cb-mono text-[10px] text-cb-faint">
              Normalised (exclusions held out): {hkd(bid.normalized_total)}
            </div>
          </div>

          <div className="space-y-1.5">
            <Collapse
              title="Arithmetic corrections"
              count={bid.arithmetic_findings.length}
              defaultOpen={bid.arithmetic_findings.length > 0}
            >
              {bid.arithmetic_findings.length > 0 ? (
                <ul className="space-y-2">
                  {bid.arithmetic_findings.map((f, i) => (
                    <li key={i} className="text-[11px] leading-relaxed text-cb-body">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <SeverityTag severity={f.severity} />
                        <span className="font-cb-mono text-[10px] text-cb-faint">{f.location}</span>
                      </div>
                      <div className="mt-0.5">
                        {f.issue} →{" "}
                        <span className="font-cb-mono font-semibold text-cb-ink-text">
                          {hkd(f.corrected_value)}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-cb-faint">The bid sheet's arithmetic checks out.</p>
              )}
            </Collapse>

            <Collapse
              title="Scope gaps"
              count={bid.scope_gaps.length}
              defaultOpen={bid.scope_gaps.length > 0}
            >
              {bid.scope_gaps.length > 0 ? (
                <ul className="space-y-1 text-[11px] text-cb-body">
                  {bid.scope_gaps.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-cb-faint">Every scheduled item is priced.</p>
              )}
            </Collapse>

            <Collapse title="Exclusions (non-comparable)" count={bid.exclusions.length}>
              {bid.exclusions.length > 0 ? (
                <ul className="space-y-1 text-[11px] text-cb-body">
                  {bid.exclusions.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-cb-faint">No exclusions declared.</p>
              )}
            </Collapse>
          </div>
        </div>
      )}
    </Drawer>
  );
}

// --- Live run: what actually arrived -----------------------------------------------------------
// A unit's enquiry counts answered when an ACTIVE reply is aligned to it (the inbound loop) or a
// return is uploaded here. No demo bids are ever shown on a live run.
function LiveLevel({
  sections,
  awaiting,
  onUploadReturn,
  xlsxUrl,
  tenderReplies,
  comparisonUrl,
  onRefreshReplies,
  onWithdrawReply,
}: {
  sections: Record<string, LevelledBid[]>;
  awaiting: AwaitingPackage[];
  onUploadReturn?: (trade: string, firmId: string, files: File[]) => Promise<MisdirectedHint | null>;
  xlsxUrl: string;
  tenderReplies: TenderReplies | null;
  comparisonUrl: string;
  onRefreshReplies?: () => void;
  onWithdrawReply?: (firmId: string, packageKey: string) => Promise<void>;
}) {
  const [detail, setDetail] = useState<LevelledBid | null>(null);
  const [drawerUnit, setDrawerUnit] = useState<string | null>(null);

  const records = tenderReplies?.replies ?? [];
  const unitTotals = tenderReplies?.unit_totals ?? {};
  const recordsForUnit = (unit: string) => records.filter((r) => r.trade === unit);
  const activeReply = (unit: string, firmId: string) =>
    records.find((r) => r.trade === unit && r.firm_id === firmId && r.status === "active") ?? null;

  const totalReceived = awaiting.reduce((n, pkg) => n + pkg.firms.filter((f) => f.received).length, 0);
  const totalSent = awaiting.reduce((n, pkg) => n + pkg.firms.length, 0);
  const downloadUrl = (tenderReplies?.comparison_available && comparisonUrl) || xlsxUrl;

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-[12px] leading-relaxed text-cb-muted">
        Live run — each dispatched enquiry waits for its priced return. A return counts as received
        when it aligns to the enquiry's routed unit or is uploaded here; the rules engine levels it
        and the unit's comparison activates. No demo bids are ever shown on a live run.
      </p>

      {awaiting.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[11px] text-cb-body">
            {totalReceived} of {totalSent} enquir{totalSent === 1 ? "y" : "ies"} answered
            {tenderReplies?.last_received
              ? ` · last reply ${new Date(tenderReplies.last_received).toLocaleString()}`
              : ""}
          </p>
          {onRefreshReplies && (
            <Button variant="ghost" onClick={onRefreshReplies}>
              Refresh replies
            </Button>
          )}
        </div>
      )}

      {awaiting.length === 0 && (
        <Card className="text-[12px] text-cb-body">
          No dispatched packages yet — dispatch a package's enquiries first.
        </Card>
      )}

      {awaiting.map((pkg) => {
        const bids = sections[pkg.trade] ?? [];
        const received = pkg.firms.filter((f) => f.received).length;
        const unitRecords = recordsForUnit(pkg.trade);
        const total = unitTotals[pkg.trade] ?? 0;
        return (
          <section key={pkg.trade} className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-cb-serif text-[13px] font-semibold text-cb-ink-text">
                {tradeLabel(pkg.trade)}
              </h3>
              <div className="flex items-center gap-2">
                <Chip
                  className={received > 0 ? "bg-cb-ok-tint text-cb-ok-dark" : "bg-cb-panel text-cb-muted"}
                >
                  {pkg.firms.length} enquir{pkg.firms.length === 1 ? "y" : "ies"} sent · {received}{" "}
                  priced return{received === 1 ? "" : "s"} received
                </Chip>
                {unitRecords.length > 0 && (
                  <Button variant="ghost" onClick={() => setDrawerUnit(pkg.trade)}>
                    View replies ({unitRecords.length})
                  </Button>
                )}
              </div>
            </div>

            {bids.length > 0 && <LiveComparison bids={bids} onOpenDetail={setDetail} />}

            <Card flush className="divide-y divide-cb-divider">
              {pkg.firms.map((f) => (
                <ReturnRow
                  key={f.firm_id}
                  trade={pkg.trade}
                  firm={f}
                  reply={activeReply(pkg.trade, f.firm_id)}
                  unitTotal={total}
                  onUploadReturn={onUploadReturn}
                />
              ))}
            </Card>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <p className="text-[10px] text-cb-faint">
                Replies quoting the enquiry's <span className="font-cb-mono">[SiteSource Ref]</span>{" "}
                attach automatically; upload a return above to add one by hand.
              </p>
              {tenderReplies?.comparison_available && comparisonUrl && (
                <a
                  className="text-[10px] font-semibold text-cb-brass-text underline"
                  href={comparisonUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open this tender's comparison ↗
                </a>
              )}
            </div>
          </section>
        );
      })}

      {totalReceived > 0 && (
        <a
          href={downloadUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 rounded-cb-btn border border-cb-border-strong bg-white px-4 py-2 font-cb-sans text-[11px] font-semibold text-cb-ink-text hover:bg-cb-panel"
        >
          ⤓ Download Excel comparison
        </a>
      )}

      <BidDrawer bid={detail} claimed={0} onClose={() => setDetail(null)} />
      <RepliesDrawer
        unit={drawerUnit}
        records={drawerUnit ? recordsForUnit(drawerUnit) : []}
        unitTotal={drawerUnit ? unitTotals[drawerUnit] ?? 0 : 0}
        comparisonUrl={tenderReplies?.comparison_available ? comparisonUrl : ""}
        onWithdraw={onWithdrawReply}
        onClose={() => setDrawerUnit(null)}
      />
    </div>
  );
}

function statusChip(s: ReplyStatus): string {
  // active = in the comparison; withdrawn = a person pulled it; superseded/migrated = history.
  return s === "active"
    ? "bg-cb-ok-tint text-cb-ok-dark"
    : s === "withdrawn"
      ? "bg-cb-bad-tint text-cb-bad-dark"
      : "bg-cb-panel text-cb-muted";
}

/** Every reply on file for one routed unit — active AND history — with the human withdraw gate. */
function RepliesDrawer({
  unit,
  records,
  unitTotal,
  comparisonUrl,
  onWithdraw,
  onClose,
}: {
  unit: string | null;
  records: TenderReplyInfo[];
  unitTotal: number;
  comparisonUrl: string;
  onWithdraw?: (firmId: string, packageKey: string) => Promise<void>;
  onClose: () => void;
}) {
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showEarlier, setShowEarlier] = useState(false);

  const ordered = [...records].sort((a, b) => {
    if ((a.status === "active") !== (b.status === "active")) return a.status === "active" ? -1 : 1;
    return (b.received_at ?? "").localeCompare(a.received_at ?? "");
  });
  const activeCount = records.filter((r) => r.status === "active").length;
  // HISTORY IS KEPT AND COLLAPSED, never deleted. Observed live: "2 active · 7 on file" rendered
  // all seven, with the two genuine returns buried among five of our OWN outbound RFQs — ingested
  // before the `X-SiteSource-Outbound` guard existed. The reply was there and could not be seen.
  //
  // A price that once entered a comparison must stay traceable, so the DEFAULT VIEW changes and
  // the data does not: active first, the rest one click away, and the count line unchanged.
  const earlier = ordered.filter((r) => r.status !== "active");
  const shown = showEarlier ? ordered : ordered.filter((r) => r.status === "active");

  const withdraw = async (firmId: string) => {
    if (!unit || !onWithdraw) return;
    setBusyKey(firmId);
    setError(null);
    try {
      await onWithdraw(firmId, unit);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <Drawer
      open={unit != null}
      onClose={onClose}
      eyebrow="Replies to this enquiry"
      accent="bg-cb-navy"
      title={unit ? tradeLabel(unit) : ""}
      subtitle={
        <span className="font-cb-mono">
          {activeCount} active · {records.length} on file
        </span>
      }
      footer="A superseded or withdrawn reply is kept as history — nothing is deleted. Withdraw re-levels the comparison without that firm's return."
    >
      {unit && (
        <div className="space-y-3">
          {error && <div className="text-[11px] text-cb-bad-dark">{error}</div>}
          {ordered.length === 0 && (
            <p className="text-[11px] text-cb-faint">No replies have landed for this enquiry yet.</p>
          )}
          {ordered.length > 0 && shown.length === 0 && (
            <p className="text-[11px] text-cb-faint">
              Nothing active for this enquiry — every reply on file has been superseded or
              withdrawn.
            </p>
          )}
          <ul className="space-y-2">
            {shown.map((r, i) => (
              <li
                key={`${r.firm_id}-${r.status}-${i}`}
                className="rounded-cb-card border border-cb-border bg-cb-panel px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-medium text-cb-ink-text">{r.firm_id}</span>
                  <Chip className={statusChip(r.status)}>{r.status}</Chip>
                  <span className="ml-auto font-cb-mono text-[10px] text-cb-faint">
                    {unitTotal > 0 ? `${r.line_items}/${unitTotal}` : `${r.line_items}`} items priced
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[10px] text-cb-faint">
                    {r.received_at
                      ? `received ${new Date(r.received_at).toLocaleString()}`
                      : "received time unknown"}
                  </span>
                  {r.status === "active" && onWithdraw && (
                    <Button
                      variant="ghost"
                      disabled={busyKey === r.firm_id}
                      onClick={() => withdraw(r.firm_id)}
                    >
                      {busyKey === r.firm_id ? "Withdrawing…" : "Withdraw from comparison"}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {earlier.length > 0 && (
            <button
              type="button"
              className="text-[11px] font-medium text-cb-brass-text underline"
              onClick={() => setShowEarlier((v) => !v)}
            >
              {showEarlier
                ? `Hide ${earlier.length} earlier version${earlier.length === 1 ? "" : "s"}`
                : `Show ${earlier.length} earlier version${earlier.length === 1 ? "" : "s"}`}
            </button>
          )}
          {comparisonUrl && (
            <a
              className="inline-block text-[10px] font-semibold text-cb-brass-text underline"
              href={comparisonUrl}
              target="_blank"
              rel="noreferrer"
            >
              Open this unit's comparison ↗
            </a>
          )}
        </div>
      )}
    </Drawer>
  );
}

/** Read-only comparison for a package's received returns — the returns are the source of truth and
 *  the engine's corrections are shown as findings, so there is no editable matrix here. */
function LiveComparison({
  bids,
  onOpenDetail,
}: {
  bids: LevelledBid[];
  onOpenDetail: (b: LevelledBid) => void;
}) {
  const cheapest = bids.length ? Math.min(...bids.map((b) => b.corrected_total)) : 0;
  return (
    <Card flush className="overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-cb-divider text-left font-cb-sans text-[9px] uppercase tracking-cb-chip text-cb-faint">
            <th className="px-3 py-2 font-semibold">Firm</th>
            <th className="px-3 py-2 text-right font-semibold">Corrected</th>
            <th className="px-3 py-2 text-right font-semibold">Normalised</th>
            <th className="px-3 py-2 font-semibold">Notes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-cb-divider">
          {[...bids]
            .sort((a, b) => a.corrected_total - b.corrected_total)
            .map((b) => (
              <tr
                key={b.firm_id}
                onClick={() => onOpenDetail(b)}
                title="Open the levelled-bid record"
                className={cx(
                  "cursor-pointer",
                  b.corrected_total === cheapest ? "bg-cb-ok-tint/50" : "hover:bg-cb-panel/70",
                )}
              >
                <td className="px-3 py-2 text-cb-ink-text">
                  <span className="font-medium">{b.firm_name}</span>{" "}
                  <span className="font-cb-mono text-[10px] text-cb-faint">{b.firm_id}</span>
                </td>
                <td className="px-3 py-2 text-right font-cb-mono font-semibold text-cb-ink-text">
                  {hkd(b.corrected_total)}
                </td>
                <td className="px-3 py-2 text-right font-cb-mono text-cb-body">
                  {hkd(b.normalized_total)}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {b.arithmetic_findings.length > 0 && (
                      <Chip className="bg-cb-bad-tint text-cb-bad-dark">
                        {b.arithmetic_findings.length} corrected
                      </Chip>
                    )}
                    {b.scope_gaps.length > 0 && (
                      <Chip className="border border-cb-brass-line text-cb-amber">
                        {b.scope_gaps.length} scope gap
                      </Chip>
                    )}
                    {b.exclusions.length > 0 && (
                      <Chip className="bg-cb-panel text-cb-muted">{b.exclusions.length} exclusion</Chip>
                    )}
                  </div>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </Card>
  );
}

/** One dispatched firm awaiting its return, with the manual-intake affordance. A misdirected upload
 *  is HELD and reported, never filed under the wrong package — the operator confirms the move. */
function ReturnRow({
  trade,
  firm,
  reply,
  unitTotal,
  onUploadReturn,
}: {
  trade: string;
  firm: AwaitingFirm;
  reply?: TenderReplyInfo | null;
  unitTotal: number;
  onUploadReturn?: (trade: string, firmId: string, files: File[]) => Promise<MisdirectedHint | null>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [misdirect, setMisdirect] = useState<MisdirectedHint | null>(null);
  const [retained, setRetained] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const onPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!picked.length || !onUploadReturn) return;
    setBusy(true);
    setError(null);
    setMisdirect(null);
    try {
      const hint = await onUploadReturn(trade, firm.firm_id, picked);
      if (hint) {
        setMisdirect(hint);
        setRetained(picked);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const reattach = async () => {
    if (!misdirect || !onUploadReturn || !retained.length) return;
    setBusy(true);
    setError(null);
    try {
      await onUploadReturn(misdirect.matched_unit, firm.firm_id, retained);
      setMisdirect(null);
      setRetained([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const coverage = reply
    ? `${unitTotal > 0 ? `${reply.line_items}/${unitTotal}` : `${reply.line_items}`} items priced`
    : null;

  return (
    <div className="flex flex-wrap items-center gap-3 px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] font-medium text-cb-ink-text">{firm.firm_name}</span>
          <span className="font-cb-mono text-[10px] text-cb-faint">{firm.firm_id}</span>
          {firm.received ? (
            <Chip className="bg-cb-ok-tint text-cb-ok-dark">return received</Chip>
          ) : (
            <Chip className="bg-cb-panel text-cb-muted">
              {firm.status === "sent_mock"
                ? "in outbox · awaiting"
                : firm.status === "recorded"
                  ? "enquiry recorded · awaiting"
                  : "awaiting reply"}
            </Chip>
          )}
        </div>
        {coverage && (
          <div className="mt-0.5 text-[10px] text-cb-body">
            {coverage}
            {reply?.received_at ? ` · received ${new Date(reply.received_at).toLocaleString()}` : ""}
          </div>
        )}
        {firm.ref && <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">Ref {firm.ref}</div>}
        {misdirect && (
          <div className="mt-1.5 rounded-cb-card border border-cb-brass-line bg-cb-warm px-2.5 py-2 text-[11px] text-cb-ink-text">
            This return prices{" "}
            <span className="font-semibold">{tradeLabel(misdirect.matched_unit)}</span> items (
            {misdirect.matched_items}
            {misdirect.unit_total ? ` of ${misdirect.unit_total}` : ""}) — it looks like that
            enquiry's return, not {tradeLabel(trade)}'s. It was NOT attached here.
            <div className="mt-1.5 flex flex-wrap gap-2">
              <Button variant="ghost" disabled={busy} onClick={reattach}>
                Attach to {tradeLabel(misdirect.matched_unit)} instead
              </Button>
              <button
                type="button"
                className="text-[10px] font-semibold text-cb-faint hover:text-cb-ink-text"
                onClick={() => {
                  setMisdirect(null);
                  setRetained([]);
                }}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}
        {error && <div className="mt-1 text-[11px] text-cb-bad-dark">{error}</div>}
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".xlsx,application/pdf,image/*"
        className="sr-only"
        onChange={onPick}
      />
      <Button variant="ghost" disabled={busy} onClick={() => inputRef.current?.click()}>
        {busy ? "Uploading…" : firm.received ? "Replace return" : "Upload a priced return"}
      </Button>
    </div>
  );
}
