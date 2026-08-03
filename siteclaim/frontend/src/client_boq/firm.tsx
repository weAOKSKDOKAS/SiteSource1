// The firm record — the fused subcontractor profile, restyled for the tender desk.
//
// This is the product's whole argument rendered as a component, so the rules it follows are not
// cosmetic:
//
//  * NOTHING IS ASSERTED WITHOUT A RECORD. Every risk flag carries its issuing source and its
//    reference, and the reference is shown, not summarised. That is what separates this from a
//    chatbot's opinion about a company.
//  * SEVERITY IS DETERMINISTIC. `fatal` comes from Layer 1's risk scoring, never from a model, so
//    it is styled as a finding rather than as a suggestion.
//  * AN ABSENT RECORD IS SAID PLAINLY. "No assessable closeout record" is a different statement
//    from a zero, and the screen must not let them look alike.

import type { ReactNode } from "react";

import type { Evidence, FirmProfile, RiskFlag } from "./types";
import { Chip, Collapse, Docket, SectionLabel, SeverityTag, cx } from "./ui";

/** Display-only: a usable enquiry e-mail, or null when it is blank, has no "@", or is the
 *  source's redaction. The stored value stays faithful — this only decides what to show. */
export function shownEmail(email: string | null | undefined): string | null {
  const e = (email || "").trim();
  if (!e || !e.includes("@") || e.toLowerCase().includes("[email")) return null;
  return e;
}

function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}

/** The citations under a flag. The reference chip is the point of the whole component. */
export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) return null;
  return (
    <ul className="mt-1.5 space-y-1">
      {evidence.map((e, j) => (
        <li key={j} className="text-[11px] leading-relaxed text-cb-body">
          <span className="font-semibold text-cb-ink-text">{e.source}</span>
          <span
            className="ml-1.5 inline-flex cursor-help items-center rounded-cb-chip border border-cb-border px-1.5 py-px font-cb-mono text-[10px] text-cb-body"
            title={`${e.source} — reference ${e.reference}`}
          >
            {e.reference}
          </span>
          <div className="text-cb-body">{e.snippet}</div>
        </li>
      ))}
    </ul>
  );
}

export function RiskFlagList({ flags }: { flags: RiskFlag[] }) {
  if (!flags.length) return null;
  return (
    <ul className="space-y-2">
      {flags.map((f, i) => (
        <li
          key={i}
          className={cx(
            "rounded-cb-card border px-3 py-2",
            // A fatal flag is a deterministic finding, so it gets the failure colour outright.
            // A warning is amber — cb has no amber tint, so it is a border and not a fill.
            f.severity === "fatal"
              ? "border-cb-bad bg-cb-bad-tint"
              : f.severity === "warning"
                ? "border-cb-brass-line bg-cb-warm"
                : "border-cb-border bg-white",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <SeverityTag severity={f.severity} />
            <span className="text-[12px] font-semibold text-cb-ink-text">{f.label}</span>
            <span className="font-cb-mono text-[10px] text-cb-faint">{f.rule_ref}</span>
          </div>
          <EvidenceList evidence={f.evidence} />
        </li>
      ))}
    </ul>
  );
}

export function FirmRecord({
  firm,
  flags = firm.public_flags,
  flagsLabel = "Public flags",
  children,
}: {
  firm: FirmProfile;
  flags?: RiskFlag[];
  flagsLabel?: string;
  children?: ReactNode;
}) {
  const email = shownEmail(firm.enquiry_email);
  return (
    <div className="space-y-3">
      <Docket label="Firm reference" code={firm.firm_id} />
      {firm.description && (
        <p className="text-[11px] leading-relaxed text-cb-body">{firm.description}</p>
      )}

      <div>
        <SectionLabel className="mb-1">Registration</SectionLabel>
        <div className="text-[11px] text-cb-body">
          {firm.registered_grade || "—"} · {firm.value_band.replace(/_/g, " ") || "unbanded"}
        </div>
        {(firm.reg_date || firm.expiry_date) && (
          <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">
            {firm.reg_date || "—"}
            {firm.expiry_date ? ` → ${firm.expiry_date}` : ""}
          </div>
        )}
        {firm.br_no && (
          <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">BR {firm.br_no}</div>
        )}
      </div>

      {(email || firm.address) && (
        <div>
          <SectionLabel className="mb-1">Contact</SectionLabel>
          {email && (
            <a
              href={`mailto:${email}`}
              className="block font-cb-mono text-[11px] text-cb-brass-text hover:underline"
            >
              ✉ {email}
            </a>
          )}
          {firm.address && (
            <div className="mt-0.5 text-[11px] leading-snug text-cb-body">{firm.address}</div>
          )}
        </div>
      )}

      {firm.trades.length > 0 && (
        <div>
          <SectionLabel className="mb-1.5">Registered trades</SectionLabel>
          <div className="flex flex-wrap gap-1.5">
            {firm.trades.map((t) => (
              // A registration is a fact from the register — deterministic, so navy rather than
              // brass. Nothing here was proposed by a model.
              <Chip key={t} className="bg-cb-info-fill text-cb-navy">
                {tradeLabel(t)}
              </Chip>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1.5">
        <Collapse title="Closeout record" defaultOpen>
          <p className="text-[11px] leading-relaxed text-cb-body">
            {firm.closeout_summary || "No assessable closeout record."}
          </p>
        </Collapse>
        <Collapse title={flagsLabel} count={flags.length} defaultOpen={flags.length > 0}>
          {flags.length > 0 ? (
            <RiskFlagList flags={flags} />
          ) : (
            <p className="text-[11px] text-cb-faint">No flags on record for this firm.</p>
          )}
        </Collapse>
        <Collapse title="Award history" count={firm.award_history.length}>
          {firm.award_history.length > 0 ? (
            <ul className="space-y-1 text-[11px] text-cb-body">
              {firm.award_history.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-cb-faint">No recorded public awards.</p>
          )}
        </Collapse>
        {children}
      </div>
    </div>
  );
}
