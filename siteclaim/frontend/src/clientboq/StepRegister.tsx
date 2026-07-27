// Step 2 — the departure register. The module's decision surface, and the screen the whole
// section is built around.
//
// The design problem here is not density, it is *authorship*. A register line arrives
// carrying a threshold breach the rules engine computed, a match Claude proposed, a quote a
// deterministic check verified — and a verdict that only a person may write. Reading it
// without knowing which is which is how a machine's guess becomes a company's contract
// position. So the ledger puts provenance on the left edge of every line, names it in words
// beside the status, and keeps the verdict controls visually separate from everything the
// machine produced.
//
// Nothing is pre-decided. A register that opened with verdicts already filled in would be
// exactly the failure the module is built to prevent.

import { useMemo, useState } from "react";

import { Pill, StepHeading } from "../components";
import { Button, Card, Collapse, Docket, Drawer, InfoNotice, LayerBadge, SectionHeader, StatCallout, cx } from "../ui";
import { CashflowChart } from "./Cashflow";
import {
  AuthorChip,
  Field,
  FilterChips,
  GateSeal,
  ProvenanceBar,
  ProvenanceLegend,
  Quote,
  SourceChip,
  STATUS_META,
  humanise,
  money,
} from "./boqUi";
import type { DepartureItem, HumanVerdict, RegisterView } from "./types";

type FilterKey = "all" | "undecided" | "rule_flagged" | "candidate" | "citation_failed" | "decided";

// The one-line body a register line leads with. Criteria lines carry an extracted value —
// the actual term found in the contract. The s04/s05/s06 findings carry no value, so their
// rationale is the statement.
function leadText(item: DepartureItem): string {
  return item.extracted_value || item.rationale || item.cited_text || "—";
}

function LedgerRow({
  item,
  verdict,
  onVerdict,
  onOpen,
}: {
  item: DepartureItem;
  verdict: HumanVerdict | null;
  onVerdict: (v: HumanVerdict) => void;
  onOpen: () => void;
}) {
  const meta = STATUS_META[item.status];
  const decided = !meta.actionable;
  const citationFailed = item.status === "citation_failed";
  const heading = item.clause_area ? humanise(item.clause_area) : humanise(item.kind) || "Finding";

  return (
    <li className={cx("flex gap-3 px-4 py-3.5 transition-colors", verdict && "bg-paper-soft/60")}>
      {/* The provenance gutter: the bar says who wrote this line's state, the number is its
          stable identity in the register the client will read. */}
      <div className="flex shrink-0 flex-col items-center gap-1.5 pt-0.5">
        <ProvenanceBar status={item.status} className="h-full min-h-[2.5rem] flex-1" />
      </div>
      <button
        type="button"
        onClick={onOpen}
        title="Open the full register record"
        className="tabular shrink-0 pt-0.5 text-xs font-semibold text-ink-faint hover:text-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright"
      >
        {String(item.item).padStart(2, "0")}
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <AuthorChip status={item.status} />
          <SourceChip source={item.source} kind={item.kind} />
        </div>

        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-semibold text-ink">{heading}</span>
          {item.clause && (
            <span className="tabular rounded border border-line px-1.5 py-px text-[11px] text-ink-soft" title="Cited clause in the document set">
              Clause {item.clause}
            </span>
          )}
          {item.criterion_id && (
            <span className="tabular text-[11px] text-ink-faint" title={item.category || "Criteria library reference"}>
              {item.criterion_id}
            </span>
          )}
        </div>

        <p className="mt-1 text-sm leading-relaxed text-ink">{leadText(item)}</p>

        {item.cited_text && (
          <div className="mt-2">
            <Quote failed={citationFailed}>{item.cited_text}</Quote>
          </div>
        )}

        {citationFailed && (
          <p className="mt-2 rounded-lg border border-bad/30 bg-bad-bg px-3 py-1.5 text-xs text-bad">
            {item.citation_note || "The cited text could not be verified against the document set."} Re-review the
            clause before this line can be confirmed.
          </p>
        )}

        {item.extracted_value && item.rationale && (
          <p className="mt-2 text-xs leading-relaxed text-ink-soft">{item.rationale}</p>
        )}

        {item.proposed_position && (
          <div className="mt-2 rounded-lg border border-brand/20 bg-brand-bg/50 px-3 py-2">
            <div className="tabular text-[10.5px] font-semibold uppercase tracking-[0.06em] text-brand">
              Proposed position · Claude draft
            </div>
            <p className="mt-0.5 text-sm text-ink">{item.proposed_position}</p>
            {item.amendment_proposal && item.amendment_proposal !== item.proposed_position && (
              <p className="mt-1 text-xs text-ink-soft">{item.amendment_proposal}</p>
            )}
          </div>
        )}
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1.5">
        {decided ? (
          // The verdict column stays scannable down the page, but as a mark rather than the
          // word — the author chip on the left already says "confirmed" in full.
          <span
            title={meta.label}
            aria-label={meta.label}
            className={cx(
              "flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold",
              item.status === "confirmed" ? "bg-ok-bg text-ok" : "bg-line-soft text-ink-faint",
            )}
          >
            {item.status === "confirmed" ? "✓" : "✕"}
          </span>
        ) : (
          <>
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={() => onVerdict("confirmed")}
                disabled={citationFailed}
                title={
                  citationFailed
                    ? "A line whose citation failed cannot be confirmed until it is re-reviewed."
                    : "Accept this departure — it carries into the estimate scope and Appendix A"
                }
                className={cx(
                  "pressable inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright disabled:cursor-not-allowed",
                  verdict === "confirmed"
                    ? "border-ok bg-ok text-white"
                    : citationFailed
                      ? "border-line bg-card text-ink-faint/60"
                      : "border-line bg-card text-ink-soft hover:border-ok/50 hover:text-ok",
                )}
              >
                <span aria-hidden>✓</span> Confirm
              </button>
              <button
                type="button"
                onClick={() => onVerdict("dismissed")}
                title="Reject this departure — it is never carried into the estimate"
                className={cx(
                  "pressable inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright",
                  verdict === "dismissed"
                    ? "border-ink-faint bg-ink-faint text-white"
                    : "border-line bg-card text-ink-soft hover:border-ink-faint hover:text-ink",
                )}
              >
                <span aria-hidden>✕</span> Dismiss
              </button>
            </div>
            {!verdict && <span className="text-[10.5px] uppercase tracking-eyebrow text-warn">awaiting you</span>}
          </>
        )}
      </div>
    </li>
  );
}

function RecordDrawer({ item, onClose }: { item: DepartureItem | null; onClose: () => void }) {
  const meta = item ? STATUS_META[item.status] : null;
  const tone = meta?.tone === "neutral" ? "ink" : (meta?.tone ?? "brand");
  return (
    <Drawer
      open={item != null}
      onClose={onClose}
      eyebrow="Register record"
      tone={tone as "bad" | "brand" | "ok" | "ink"}
      title={item ? `Item ${String(item.item).padStart(2, "0")}` : ""}
      subtitle={item && <span>{item.clause_area ? humanise(item.clause_area) : humanise(item.kind)}</span>}
      footer="The register is the decision record. Only the approve gate writes a verdict — no stage and no model can."
    >
      {item && meta && (
        <div className="space-y-3">
          <Docket label="Cited clause" code={item.clause || "no clause — this finding is an absence"} />
          <div className="rounded-xl border border-line-soft bg-paper-soft px-4 py-3">
            <div className="tabular text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Written by</div>
            <div className="mt-1 flex items-center gap-2">
              <ProvenanceBar status={item.status} className="h-4" />
              <span className="text-sm font-semibold text-ink">{meta.author}</span>
              <Pill tone={meta.tone === "neutral" ? "neutral" : (meta.tone as "ok" | "bad" | "brand")}>{meta.label}</Pill>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">{meta.note}</p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Field label="Check">{humanise(item.source)}</Field>
            <Field label="Finding type">{humanise(item.kind) || "—"}</Field>
            <Field label="Criterion">{item.criterion_id || "—"}</Field>
            <Field label="Category">{item.category || "—"}</Field>
            <Field label="Rule reference">{item.rule_ref || "—"}</Field>
            <Field label="Register status">{humanise(item.register_status)}</Field>
          </div>

          <div>
            <Collapse title="Extracted value" defaultOpen={!!item.extracted_value}>
              <p className="text-xs leading-relaxed text-ink-soft">{item.extracted_value || "No value extracted for this finding."}</p>
            </Collapse>
            <Collapse title="Cited text" defaultOpen={!!item.cited_text}>
              {item.cited_text ? (
                <Quote failed={item.status === "citation_failed"}>{item.cited_text}</Quote>
              ) : (
                <p className="text-xs text-ink-faint">No quotation — this finding rests on an absence in the set.</p>
              )}
              {item.citation_note && <p className="mt-1.5 text-xs text-bad">{item.citation_note}</p>}
            </Collapse>
            <Collapse title="Rationale" defaultOpen={!!item.rationale}>
              <p className="text-xs leading-relaxed text-ink-soft">{item.rationale || "—"}</p>
            </Collapse>
            <Collapse title="Amendment proposal" defaultOpen={!!item.amendment_proposal}>
              <p className="text-xs leading-relaxed text-ink-soft">{item.amendment_proposal || "—"}</p>
              {item.proposed_position && (
                <p className="mt-1.5 text-xs font-semibold text-ink">Position: {item.proposed_position}</p>
              )}
            </Collapse>
            <Collapse title="Negotiation">
              <Field label="Client response">{item.client_response || "—"}</Field>
              <Field label="Contractor response" className="mt-2">
                {item.contractor_response || "—"}
              </Field>
              <p className="mt-2 text-[11px] text-ink-faint">
                Filled in when the register goes back and forth with the client.
              </p>
            </Collapse>
          </div>
        </div>
      )}
    </Drawer>
  );
}

export function StepRegister({
  register,
  reviewApproved,
  verdicts,
  busy,
  onVerdict,
  onBulkVerdict,
  onClearVerdicts,
  onClose,
  onReopen,
  onBack,
  onContinue,
}: {
  register: RegisterView;
  reviewApproved: boolean;
  verdicts: Record<number, HumanVerdict>;
  busy: boolean;
  onVerdict: (item: number, v: HumanVerdict) => void;
  onBulkVerdict: (items: number[], v: HumanVerdict) => void;
  onClearVerdicts: () => void;
  onClose: () => void;
  onReopen: () => void;
  onBack: () => void;
  onContinue: () => void;
}) {
  const [filter, setFilter] = useState<FilterKey>("all");
  const [record, setRecord] = useState<DepartureItem | null>(null);

  const lines = register.line_items;
  const actionable = useMemo(() => lines.filter((l) => STATUS_META[l.status].actionable), [lines]);
  const outstanding = actionable.filter((l) => !verdicts[l.item]);
  const ruleFlaggedUndecided = outstanding.filter((l) => l.status === "rule_flagged");

  const counts = useMemo(
    () => ({
      all: lines.length,
      undecided: outstanding.length,
      rule_flagged: lines.filter((l) => l.status === "rule_flagged").length,
      candidate: lines.filter((l) => l.status === "candidate").length,
      citation_failed: lines.filter((l) => l.status === "citation_failed").length,
      decided: lines.filter((l) => verdicts[l.item] || !STATUS_META[l.status].actionable).length,
    }),
    [lines, outstanding.length, verdicts],
  );

  const shown = lines.filter((l) => {
    switch (filter) {
      case "undecided":
        return STATUS_META[l.status].actionable && !verdicts[l.item];
      case "decided":
        return !!verdicts[l.item] || !STATUS_META[l.status].actionable;
      case "all":
        return true;
      default:
        return l.status === filter;
    }
  });

  const confirmedCount = lines.filter(
    (l) => verdicts[l.item] === "confirmed" || l.status === "confirmed",
  ).length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <StepHeading
          title="Rule on every departure"
          lead="One register holds every check: the criteria match, scope alignment, the programme and cash flow. The rules engine pre-flags the numeric breaches and Claude proposes the qualitative matches — but a departure only exists once you say it does."
        />
        <LayerBadge layer="L4" />
      </div>

      <GateSeal
        title="Register gate"
        closed={reviewApproved}
        outstanding={outstanding.length}
        outstandingLabel={outstanding.length === 1 ? "line awaiting you" : "lines awaiting you"}
        detail={
          reviewApproved ? (
            <>
              Closed with <span className="tabular font-semibold text-ink">{confirmedCount}</span> confirmed
              departure{confirmedCount === 1 ? "" : "s"}. They carry into the estimate scope and into Appendix A of
              the offer letter. Reopening the register clears the estimate built on it.
            </>
          ) : (
            <>Every line needs a verdict before the register closes — a register with open lines is not a position.</>
          )
        }
        secondary={
          reviewApproved ? undefined : (
            <Button variant="subtle" onClick={onClearVerdicts} disabled={busy || !Object.keys(verdicts).length}>
              Clear verdicts
            </Button>
          )
        }
        action={
          reviewApproved ? (
            <div className="flex gap-2">
              <Button variant="ghost" onClick={onReopen} loading={busy}>
                Reopen
              </Button>
              <Button onClick={onContinue}>Draft the scope →</Button>
            </div>
          ) : (
            <Button onClick={onClose} loading={busy} disabled={outstanding.length > 0}>
              Close the register →
            </Button>
          )
        }
      />

      {/* Before the gate closes the useful reading is what is still to do; after it closes
          those counts are all zero by definition, so the row switches to what was decided. */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {reviewApproved ? (
          <>
            <StatCallout label="Departures confirmed" value={confirmedCount} tone="ok" hint="carried into the price" />
            <StatCallout
              label="Dismissed"
              value={lines.filter((l) => l.status === "dismissed").length}
              hint="never carried"
            />
            <StatCallout label="Resolved and acceptable" value={register.aligned.length} tone="ink" />
            <StatCallout
              label="Criteria unresolved"
              value={register.unresolved.count}
              tone="ink"
              hint="nothing in the set answers them"
            />
          </>
        ) : (
          <>
            <StatCallout label="Lines to rule on" value={actionable.length} />
            <StatCallout label="Rule-flagged breaches" value={counts.rule_flagged} tone="ink" hint="numeric thresholds" />
            <StatCallout label="Claude proposals" value={counts.candidate} tone="brand" hint="drafts, no verdicts" />
            <StatCallout
              label="Criteria unresolved"
              value={register.unresolved.count}
              tone="ink"
              hint="nothing in the set answers them"
            />
          </>
        )}
      </div>

      <Card className="overflow-hidden">
        <div className="space-y-3 border-b border-line-soft px-4 py-3">
          <ProvenanceLegend statuses={lines.map((l) => l.status)} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <FilterChips
              value={filter}
              onChange={setFilter}
              options={[
                { key: "all", label: "All lines", count: counts.all },
                { key: "undecided", label: "Awaiting you", count: counts.undecided },
                { key: "rule_flagged", label: "Rule-flagged", count: counts.rule_flagged },
                { key: "candidate", label: "Proposed", count: counts.candidate },
                { key: "citation_failed", label: "Citation failed", count: counts.citation_failed },
                { key: "decided", label: "Decided", count: counts.decided },
              ]}
            />
            {!reviewApproved && ruleFlaggedUndecided.length > 0 && (
              <Button
                variant="ghost"
                className="ml-auto"
                onClick={() => onBulkVerdict(ruleFlaggedUndecided.map((l) => l.item), "confirmed")}
                title="A rule-flagged line is a stated threshold breached — confirming them together is a decision you can still change per line."
              >
                Confirm {ruleFlaggedUndecided.length} rule-flagged
              </Button>
            )}
          </div>
        </div>

        {shown.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-ink-faint">No lines match this filter.</p>
        ) : (
          <ul className="divide-y divide-line-soft">
            {shown.map((item) => (
              <LedgerRow
                key={item.item}
                item={item}
                verdict={verdicts[item.item] ?? null}
                onVerdict={(v) => onVerdict(item.item, v)}
                onOpen={() => setRecord(item)}
              />
            ))}
          </ul>
        )}
      </Card>

      {register.cashflow && <CashflowPanel cashflow={register.cashflow} />}

      {register.aligned.length > 0 && (
        <Card className="p-4">
          <SectionHeader
            title="Resolved and acceptable"
            lead="Numeric criteria the rules engine checked and found within the acceptable position. No departure — recorded so a resolved term is never mistaken for an unanswered one."
            right={<Pill tone="ok">{register.aligned.length}</Pill>}
          />
          <ul className="mt-3 divide-y divide-line-soft">
            {register.aligned.map((a) => (
              <li key={a.criterion_id} className="flex gap-3 py-2.5">
                <span aria-hidden className="mt-0.5 shrink-0 text-ok">✓</span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm font-semibold text-ink">{a.clause_area}</span>
                    <span className="tabular text-[11px] text-ink-faint">
                      {a.criterion_id}
                      {a.clause ? ` · Clause ${a.clause}` : ""}
                    </span>
                  </div>
                  <p className="text-sm text-ink-soft">{a.extracted_value}</p>
                  <p className="text-xs text-ink-faint">{a.why}</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {register.unresolved.count > 0 && (
        <Card className="p-4">
          <SectionHeader
            title="Criteria the set does not answer"
            lead="Acceptable-terms criteria no clause in the document set resolves. They are coverage, not departures — there is nothing to rule on until the client supplies the missing terms."
            right={<Pill tone="warn">{register.unresolved.count}</Pill>}
          />
          <div className="mt-3 flex flex-wrap gap-1.5">
            {register.unresolved.criteria.map((c) => (
              <span
                key={c.item}
                title={`Item ${c.item} — ${c.clause_area}`}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-paper-soft px-2.5 py-1 text-xs text-ink-soft"
              >
                <span className="tabular font-semibold text-ink-faint">{c.criterion_id}</span>
                {c.clause_area}
              </span>
            ))}
          </div>
        </Card>
      )}

      <div className="flex items-center justify-between gap-3 pt-1">
        <Button variant="ghost" onClick={onBack}>
          ← Documents
        </Button>
        {reviewApproved && <Button onClick={onContinue}>Draft the scope →</Button>}
      </div>

      <RecordDrawer item={record} onClose={() => setRecord(null)} />
    </div>
  );
}

function CashflowPanel({ cashflow }: { cashflow: NonNullable<RegisterView["cashflow"]> }) {
  const peak = cashflow.working_capital_peak;
  return (
    <Card className="p-4">
      <SectionHeader
        title="Cash flow on these terms"
        lead="Computed from the payment, retention and programme terms as written — the money the package would need before it starts paying for itself."
        right={<LayerBadge layer="L1" />}
      />
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <StatCallout
          label="Peak funding requirement"
          value={money(Math.abs(peak))}
          tone="ink"
          hint="the most negative cumulative position"
        />
        <StatCallout label="Months cash-negative" value={cashflow.negative_periods.length} tone="ink" />
        <StatCallout label="Periods modelled" value={cashflow.points.length} tone="ink" />
      </div>
      <div className="mt-4">
        <CashflowChart cashflow={cashflow} />
      </div>
      {cashflow.findings.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-ink-soft">
          {cashflow.findings.map((f, i) => (
            <li key={i} className="flex gap-2">
              <span aria-hidden className="text-ink-faint">·</span>
              {f}
            </li>
          ))}
        </ul>
      )}
      {cashflow.assumptions.length > 0 && (
        <div className="mt-3">
          <InfoNotice>
            <span className="font-semibold">Assumptions behind the curve.</span>{" "}
            {cashflow.assumptions.join(" ")}
          </InfoNotice>
        </div>
      )}
    </Card>
  );
}
