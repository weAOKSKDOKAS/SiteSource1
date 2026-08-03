// Sourcing step 1 — the shortlist. Ported from StepShortlist, restyled, behaviour unchanged.
//
// This is the screen the whole database exists for, so two things are stated rather than implied:
// the ranking is DETERMINISTIC (a firm with a fatal flag is demoted below every clean firm
// regardless of price or match — Layer 1, never a model), and an absent closeout record is said
// out loud instead of rendering as a misleading 0% match.
//
// Selecting a recommended-against firm is ALLOWED and visibly flagged. The gate is human: the
// product's job is to make the consequence unmissable, not to remove the choice.

import { useState } from "react";

import { FirmRecord, RiskFlagList } from "../../firm";
import type { Candidate, Coverage, ShortlistSet } from "../../types";
import { Card, Chip, Collapse, Drawer, MatchChip, Pill, SectionLabel, cx } from "../../ui";

function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}

export function Shortlist({
  shortlist,
  coverage,
  approvals,
  onToggleApprove,
}: {
  shortlist: ShortlistSet;
  coverage: Coverage | null;
  approvals: Record<string, string[]>;
  onToggleApprove: (trade: string, firmId: string) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [detail, setDetail] = useState<Candidate | null>(null);
  const [focusTrade, setFocusTrade] = useState(""); // "" = show every package
  const trades = Object.keys(shortlist.per_trade).sort((a, b) => a.localeCompare(b));
  const shown = focusTrade ? trades.filter((t) => t === focusTrade) : trades;

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-[12px] leading-relaxed text-cb-muted">
        For each sublet package the database returns firms scored by how well their closeout history
        matches the scope, each with cited evidence and risk flags. The ranking is deterministic — a
        firm with a fatal flag is demoted below every clean firm regardless of price or match.
      </p>

      {coverage && (
        <Card className="bg-cb-info text-[11px] text-cb-body">
          Screening against{" "}
          <span className="font-cb-mono font-semibold text-cb-ink-text">
            {coverage.total_firms.toLocaleString("en-HK")}
          </span>{" "}
          firms sourced from official Hong Kong registers —{" "}
          <span className="font-cb-mono font-semibold text-cb-ink-text">
            {coverage.flagged_firms.toLocaleString("en-HK")}
          </span>{" "}
          carry verified public risk flags, each linked to its government source. Only firms with an
          assessable closeout record are shortlisted below.
        </Card>
      )}

      {trades.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <SectionLabel>Focus a package</SectionLabel>
          <select
            value={focusTrade}
            onChange={(e) => setFocusTrade(e.target.value)}
            className="rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1 font-cb-sans text-[11px] text-cb-body"
          >
            <option value="">All packages ({trades.length})</option>
            {trades.map((t) => (
              <option key={t} value={t}>
                {tradeLabel(t)}
              </option>
            ))}
          </select>
        </div>
      )}

      {shown.map((trade) => {
        const candidates = shortlist.per_trade[trade];
        const open = expanded[trade] ?? true;
        const flagged = candidates.filter((c) => c.recommended_against).length;
        const picked = (approvals[trade] ?? []).length;
        return (
          <Card key={trade} className="p-0">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-cb-divider px-3 py-2">
              <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
                {tradeLabel(trade)}
              </h3>
              <div className="flex items-center gap-2">
                {flagged > 0 && (
                  <Chip className="bg-cb-bad-tint text-cb-bad-dark">{flagged} flagged</Chip>
                )}
                <Chip className="bg-cb-panel text-cb-muted">{candidates.length} firms</Chip>
                {picked > 0 && (
                  <Chip className="bg-cb-ok-tint text-cb-ok-dark">{picked} selected</Chip>
                )}
                <button
                  type="button"
                  onClick={() => setExpanded((e) => ({ ...e, [trade]: !open }))}
                  className="font-cb-sans text-[10px] font-semibold text-cb-brass-text hover:underline"
                >
                  {open ? "Hide" : "Show"}
                </button>
              </div>
            </div>

            {open ? (
              <>
                {candidates.every((c) => !c.firm.closeout_summary && c.match_score <= 0) && (
                  <p className="border-b border-cb-divider bg-cb-panel px-3 py-2 text-[10px] text-cb-faint">
                    No closeout evidence for these firms yet — ordered by trade specialty and the
                    public risk screen (alphabetical among equals). Match ranking activates once
                    closeout (EOS) records are loaded.
                  </p>
                )}
                <ol className="divide-y divide-cb-divider">
                  {candidates.map((c, i) => (
                    <CandidateRow
                      key={c.firm.firm_id}
                      candidate={c}
                      rank={i + 1}
                      top={i === 0}
                      selected={(approvals[trade] ?? []).includes(c.firm.firm_id)}
                      onToggleSelect={() => onToggleApprove(trade, c.firm.firm_id)}
                      onOpen={() => setDetail(c)}
                    />
                  ))}
                </ol>
              </>
            ) : (
              <div className="px-3 py-2 text-[11px] text-cb-body">
                Top pick:{" "}
                <span className="font-semibold text-cb-ink-text">{candidates[0]?.firm.name}</span>
              </div>
            )}
          </Card>
        );
      })}

      <FirmDrawer candidate={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

function CandidateRow({
  candidate,
  rank,
  top,
  selected,
  onToggleSelect,
  onOpen,
}: {
  candidate: Candidate;
  rank: number;
  top: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  onOpen: () => void;
}) {
  const { firm } = candidate;
  const against = candidate.recommended_against;
  const fatal = candidate.risk_flags.filter((f) => f.severity === "fatal");
  const warnings = candidate.risk_flags.filter((f) => f.severity !== "fatal");

  return (
    <li className={cx("px-3 py-2.5", against ? "bg-cb-bad-tint/40" : "hover:bg-cb-panel/60")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-cb-border font-cb-mono text-[10px] text-cb-muted">
          {rank}
        </span>
        <button
          type="button"
          onClick={onOpen}
          title="Open the firm record"
          className="text-left font-cb-sans text-[12px] font-semibold text-cb-ink-text hover:text-cb-brass-text"
        >
          {firm.name}
        </button>
        <span className="font-cb-mono text-[10px] text-cb-faint">{firm.firm_id}</span>
        <MatchChip score={candidate.match_score} assessed={!!firm.closeout_summary} />
        {top && !against && <Chip className="bg-cb-ok-tint text-cb-ok-dark">Top pick</Chip>}
        {against && (
          <Chip className="bg-cb-bad-tint text-cb-bad-dark">⛔ Recommend against</Chip>
        )}
        <span className="ml-auto flex items-center gap-2">
          <span className="text-[10px] text-cb-faint">
            {firm.registered_grade} · {firm.value_band.replace(/_/g, " ")}
          </span>
          {/* The enquiry selection. Selecting a recommended-against firm is allowed but visibly
              warned — the gate is human, and removing the choice would hide the judgement. */}
          <button
            type="button"
            onClick={onToggleSelect}
            title={
              against && !selected
                ? "This firm is recommended against — selecting it is allowed but flagged"
                : "Toggle enquiry selection"
            }
            className={cx(
              "cb-press rounded-cb-btn border px-2.5 py-1 font-cb-sans text-[10px] font-semibold",
              selected && against && "border-cb-bad bg-cb-bad-tint text-cb-bad-dark",
              selected && !against && "border-cb-ink bg-cb-ink text-white",
              !selected && "border-cb-border-strong bg-white text-cb-muted hover:bg-cb-panel",
            )}
          >
            {selected ? (against ? "Selected — flagged ⚠" : "Selected ✓") : "Select for enquiry"}
          </button>
        </span>
      </div>

      {firm.closeout_summary && (
        <p className="mt-1.5 text-[11px] text-cb-body">{firm.closeout_summary}</p>
      )}

      {against && (
        <div className="mt-2 rounded-cb-card border border-cb-bad bg-white p-3">
          <p className="mb-2 font-cb-sans text-[10px] font-semibold uppercase tracking-cb-chip text-cb-bad-dark">
            Disqualifying — do not award regardless of price
          </p>
          <RiskFlagList flags={fatal} />
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mt-2">
          <RiskFlagList flags={warnings} />
        </div>
      )}
    </li>
  );
}

/** The firm record drawer — the full fused profile already delivered with the shortlist, so no
 *  extra fetch. Scope evidence is candidate-specific; the raw public flags are the browse view. */
function FirmDrawer({ candidate, onClose }: { candidate: Candidate | null; onClose: () => void }) {
  const firm = candidate?.firm;
  return (
    <Drawer
      open={candidate != null}
      onClose={onClose}
      eyebrow="Firm record"
      // Red when the record itself disqualifies; navy otherwise, because everything in this drawer
      // is register data and deterministic scoring — nothing here was written by a model.
      accent={candidate?.recommended_against ? "bg-cb-bad" : "bg-cb-navy"}
      title={firm?.name ?? ""}
      subtitle={
        firm && candidate ? (
          <span className="flex flex-wrap items-center gap-2">
            <MatchChip score={candidate.match_score} assessed={!!firm.closeout_summary} />
            {candidate.recommended_against && (
              <Pill className="bg-cb-bad-tint text-cb-bad-dark">⛔ Recommend against</Pill>
            )}
          </span>
        ) : undefined
      }
      footer="SiteSource asserts nothing without a record — every flag above carries its issuing source and reference."
    >
      {candidate && firm && (
        <FirmRecord firm={firm} flags={candidate.risk_flags} flagsLabel="Risk flags">
          <Collapse title="Scope evidence" count={candidate.evidence.length}>
            {candidate.evidence.length > 0 ? (
              <ul className="space-y-2">
                {candidate.evidence.map((e, i) => (
                  <li key={i} className="text-[11px] leading-relaxed text-cb-body">
                    <span className="font-semibold text-cb-ink-text">{e.source}</span>
                    <span className="font-cb-mono text-cb-faint"> · {e.reference}</span>
                    <div>{e.snippet}</div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[11px] text-cb-faint">No matched closeout evidence.</p>
            )}
          </Collapse>
        </FirmRecord>
      )}
    </Drawer>
  );
}
