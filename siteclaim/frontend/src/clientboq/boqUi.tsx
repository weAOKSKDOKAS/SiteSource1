// Module-local presentation primitives for Client → BOQ.
//
// Everything here is built from Atlas tokens (src/index.css) — no new colours. What the
// module adds is one idea the rest of the app does not need: **provenance**. Every value on a
// register line was written by something, and the module's hard constraint is that the AI is
// never the thing that writes a decision. So authorship is not a footnote here; it is the
// left edge of every line.
//
// The mapping, and why each colour:
//   rule_flagged     bad     a stated numeric threshold is breached — deterministic, the
//                            strongest pre-flag the module can raise
//   citation_failed  bad + hatch   also serious, but a *trust* failure rather than a breach:
//                            the quote could not be found in the documents. The hatch (not a
//                            second hue) carries the difference, and the backend refuses to
//                            let this line be confirmed until it is re-reviewed.
//   candidate        brand   Claude proposed the match — Layer 2, the app's AI accent
//   uncovered        teal    a clause no criterion covers. Atlas leaves teal unreserved; a
//                            coverage gap is exactly the kind of "look here" that is neither
//                            a breach nor a proposal
//   unresolved       neutral an absence, not a finding
//   confirmed        ok      a human accepted it — green is reserved for exactly this
//   dismissed        neutral a human rejected it
// Amber stays what it is everywhere else in Atlas: the human gate itself.

import type { ReactNode } from "react";
import { Pill } from "../components";
import { Button, Card, cx } from "../ui";
import type { DepartureSource, DepartureStatus } from "./types";

// ---------------------------------------------------------------------------
// Numbers. The rate book is HKD, so in-app readouts are HK$; cents appear only when
// the figure actually has them (a price does, a rate rarely does).
// ---------------------------------------------------------------------------
export function money(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const hasCents = Math.abs(n % 1) > 0.004;
  return "HK$" + n.toLocaleString("en-HK", {
    minimumFractionDigits: hasCents ? 2 : 0,
    maximumFractionDigits: 2,
  });
}

export function num(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-HK", { maximumFractionDigits: 3 });
}

// "responsibility_creep" -> "Responsibility creep"
export function humanise(key: string): string {
  if (!key) return "";
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// The provenance system
// ---------------------------------------------------------------------------
export type BoqTone = "bad" | "brand" | "teal" | "ok" | "neutral";

interface StatusMeta {
  /** The line's state, named the way an estimator would say it. */
  label: string;
  /** Who wrote this state — the sentence the gutter is making. */
  author: string;
  /** The one-line explanation behind the legend and the hover. */
  note: string;
  tone: BoqTone;
  /** A trust failure is drawn hatched rather than given a second hue. */
  hatched?: boolean;
  /** True while the line still needs a verdict. */
  actionable: boolean;
}

export const STATUS_META: Record<DepartureStatus, StatusMeta> = {
  rule_flagged: {
    label: "Rule-flagged",
    author: "Rules engine",
    note: "A numeric threshold in the criteria library is breached. The rule raised it; you still decide it.",
    tone: "bad",
    actionable: true,
  },
  citation_failed: {
    label: "Citation failed",
    author: "Citation check",
    note: "The quote this line rests on was not found in the document set. It cannot be confirmed until it is re-reviewed.",
    tone: "bad",
    hatched: true,
    actionable: true,
  },
  candidate: {
    label: "Proposed",
    author: "Claude",
    note: "Claude matched this clause to a criterion and drafted a position. A proposal only — it carries no verdict.",
    tone: "brand",
    actionable: true,
  },
  uncovered: {
    label: "Uncovered",
    author: "Criteria match",
    note: "This clause matched no criterion in the library. Surfaced so you can place it rather than lose it.",
    tone: "teal",
    actionable: true,
  },
  unresolved: {
    label: "Unresolved",
    author: "Criteria match",
    note: "A criterion no clause in the document set resolves. Grouped as coverage, not as a line to decide.",
    tone: "neutral",
    actionable: false,
  },
  confirmed: {
    label: "Confirmed",
    author: "You",
    note: "You accepted this departure. It carries into the estimate scope and into Appendix A of the offer letter.",
    tone: "ok",
    actionable: false,
  },
  dismissed: {
    label: "Dismissed",
    author: "You",
    note: "You rejected this departure. It is never carried into the estimate.",
    tone: "neutral",
    actionable: false,
  },
};

const TONE_TEXT: Record<BoqTone, string> = {
  bad: "text-bad",
  brand: "text-brand",
  teal: "text-teal",
  ok: "text-ok",
  neutral: "text-ink-faint",
};

const TONE_CHIP: Record<BoqTone, string> = {
  bad: "bg-bad-bg text-bad",
  brand: "bg-brand-bg text-brand",
  teal: "bg-teal-bg text-teal",
  ok: "bg-ok-bg text-ok",
  neutral: "bg-line-soft text-ink-soft",
};

const TONE_HEX: Record<BoqTone, string> = {
  bad: "#e5484d",
  brand: "#1f6feb",
  teal: "#0fb5a6",
  ok: "#2ea56a",
  neutral: "#8a98ab",
};

/**
 * The provenance bar — the module's signature mark. A 4px rule down the left edge of a
 * register line, coloured by who wrote the line's state and hatched when the line's
 * citation did not hold. It is the only place the app draws an edge stripe, and it earns
 * the exception by carrying meaning rather than decoration.
 */
export function ProvenanceBar({ status, className }: { status: DepartureStatus; className?: string }) {
  const meta = STATUS_META[status];
  const hex = TONE_HEX[meta.tone];
  return (
    <span
      aria-hidden
      title={`${meta.label} — written by ${meta.author}`}
      className={cx("block w-1 shrink-0 rounded-full", className)}
      style={
        meta.hatched
          ? { backgroundImage: `repeating-linear-gradient(135deg, ${hex} 0 3px, ${hex}33 3px 6px)` }
          : { backgroundColor: hex }
      }
    />
  );
}

/** The status + author chip that sits in a line's header, naming the bar in words. */
export function AuthorChip({ status }: { status: DepartureStatus }) {
  const meta = STATUS_META[status];
  return (
    <span
      title={meta.note}
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-eyebrow",
        TONE_CHIP[meta.tone],
      )}
    >
      {meta.label}
      <span className="font-medium normal-case tracking-normal opacity-70">· {meta.author}</span>
    </span>
  );
}

/** The legend that makes the gutter readable without a hover. */
export function ProvenanceLegend({ statuses }: { statuses: DepartureStatus[] }) {
  const seen = statuses.filter((s, i) => statuses.indexOf(s) === i);
  if (!seen.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-eyebrow text-ink-faint">Written by</span>
      {seen.map((s) => {
        const meta = STATUS_META[s];
        return (
          <span key={s} className="flex items-center gap-1.5 text-xs" title={meta.note}>
            <ProvenanceBar status={s} className="h-3.5" />
            <span className={cx("font-semibold", TONE_TEXT[meta.tone])}>{meta.author}</span>
            <span className="text-ink-faint">{meta.label.toLowerCase()}</span>
          </span>
        );
      })}
    </div>
  );
}

// Which check produced a line — orthogonal to who wrote its status.
const SOURCE_LABEL: Record<DepartureSource, string> = {
  criteria: "Criteria match",
  scope_alignment: "Scope alignment",
  program: "Programme",
  cashflow: "Cash flow",
};

export function SourceChip({ source, kind }: { source: DepartureSource | string; kind?: string }) {
  const label = SOURCE_LABEL[source as DepartureSource] ?? humanise(source);
  return (
    <span className="text-[11px] text-ink-faint">
      {label}
      {kind ? <span className="text-ink-faint/80"> · {humanise(kind)}</span> : null}
    </span>
  );
}

// ---------------------------------------------------------------------------
// The gate seal — the module's other structural device.
// ---------------------------------------------------------------------------
/**
 * A workflow gate, drawn as a seal that is either open (amber, counting what is still
 * undecided) or closed (green, stating what it locked). Amber is Atlas's human-gate colour
 * and this is the app's most literal human gate: nothing downstream runs until it closes.
 */
export function GateSeal({
  title,
  closed,
  outstanding,
  outstandingLabel,
  detail,
  action,
  secondary,
}: {
  title: string;
  closed: boolean;
  outstanding?: number;
  outstandingLabel?: string;
  detail: ReactNode;
  action?: ReactNode;
  secondary?: ReactNode;
}) {
  return (
    <Card
      className={cx(
        "flex flex-wrap items-center gap-x-5 gap-y-3 px-5 py-4",
        closed ? "border-ok/30 tint-ok" : "border-warn/40",
      )}
    >
      <span
        aria-hidden
        className={cx(
          "flex h-11 w-11 shrink-0 items-center justify-center rounded-full border-2 text-base",
          closed ? "border-ok text-ok" : "border-warn text-warn",
        )}
      >
        {closed ? "✓" : "◌"}
      </span>
      {/* A basis floor keeps the explanation readable: without it the count and the actions
          squeeze the sentence into a four-word column. */}
      <div className="min-w-0 flex-1 basis-80">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-display text-base font-semibold tracking-display text-ink">{title}</h3>
          <Pill tone={closed ? "ok" : "warn"}>{closed ? "closed" : "open"}</Pill>
        </div>
        <p className="mt-0.5 text-sm text-ink-soft">{detail}</p>
      </div>
      {/* The counter reaching zero is the moment the gate becomes closable, so it stops being
          amber at exactly that point — the colour is the signal, not the label. */}
      {!closed && outstanding !== undefined && (
        <div className="shrink-0 text-right">
          <div className={cx("tabular text-3xl font-bold leading-none", outstanding === 0 ? "text-ok" : "text-warn")}>
            {outstanding}
          </div>
          <div className="mt-1 text-[11px] font-medium uppercase tracking-eyebrow text-ink-faint">
            {outstanding === 0 ? "ready to close" : (outstandingLabel ?? "outstanding")}
          </div>
        </div>
      )}
      <div className="flex items-center gap-2">
        {secondary}
        {action}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Small shared bits
// ---------------------------------------------------------------------------
/** A labelled block inside a record: mono uppercase label over its value. */
export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="tabular text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-faint">{label}</div>
      <div className="mt-0.5 text-sm text-ink-soft">{children}</div>
    </div>
  );
}

/**
 * A quotation lifted from the document set. Set apart as a quote because that is what it is —
 * the words the line rests on, and the thing the citation check verifies.
 */
export function Quote({ children, failed = false }: { children: ReactNode; failed?: boolean }) {
  return (
    <blockquote
      className={cx(
        "border-l-2 pl-3 text-sm italic leading-relaxed",
        failed ? "border-bad/50 text-ink-soft" : "border-line text-ink-soft",
      )}
    >
      “{children}”
    </blockquote>
  );
}

/**
 * A hand-recomputable arithmetic trace. Mono, one line, exactly the numbers the rules engine
 * used — so an estimator can check the machine with a calculator instead of trusting it.
 */
export function Trace({ children }: { children: ReactNode }) {
  return (
    <div className="tabular rounded-lg bg-paper-soft px-2.5 py-1.5 text-[11.5px] leading-relaxed text-ink-soft">
      {children}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <Card className="px-5 py-8 text-center">
      <p className="font-display text-base font-semibold text-ink">{title}</p>
      {children && <p className="mx-auto mt-1.5 max-w-md text-sm text-ink-soft">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </Card>
  );
}

/** A filter chip row — one row, above the thing it filters. */
export function FilterChips<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { key: T; label: string; count: number }[];
  value: T;
  onChange: (key: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          aria-pressed={value === o.key}
          className={cx(
            "pressable inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright",
            value === o.key ? "bg-ink text-white" : "bg-card text-ink-soft hover:bg-line-soft",
            o.count === 0 && value !== o.key && "opacity-50",
          )}
        >
          {o.label}
          <span className="tabular opacity-70">{o.count}</span>
        </button>
      ))}
    </div>
  );
}

/** A download affordance for a generated file, styled as a ghost button but a real link. */
export function DownloadLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Button variant="ghost" className="no-underline" onClick={() => window.open(href, "_blank", "noopener")}>
      {children}
    </Button>
  );
}
