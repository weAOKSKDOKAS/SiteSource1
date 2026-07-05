import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Severity } from "./types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// --- Severity --------------------------------------------------------------
const SEVERITY: Record<Severity, { label: string; classes: string; dot: string }> = {
  fatal: { label: "Fatal", classes: "bg-bad-bg text-bad", dot: "bg-bad" },
  warning: { label: "Warning", classes: "bg-warn-bg text-warn", dot: "bg-warn" },
  info: { label: "Info", classes: "bg-brand-bg text-brand", dot: "bg-brand" },
};

export function SeverityTag({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity];
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold uppercase tracking-wide", s.classes)}>
      <span className={cx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

// --- Match score (semantic relevance of closeout history to the scope) -----
export function MatchChip({ score }: { score: number }) {
  const value = Math.round(score * 100);
  const tier = score >= 0.7 ? "bg-ok-bg text-ok" : score >= 0.5 ? "bg-brand-bg text-brand" : "bg-line-soft text-ink-soft";
  return (
    <span
      className={cx("tabular inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tier)}
      title="Semantic match of the firm's closeout history to this scope"
    >
      {value}% match
    </span>
  );
}

// --- Button ----------------------------------------------------------------
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "subtle";
  loading?: boolean;
};

export function Button({ variant = "primary", loading, children, className, disabled, ...rest }: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright focus-visible:ring-offset-2 disabled:cursor-not-allowed";
  const variants = {
    primary: "bg-brand text-white hover:bg-brand-bright disabled:bg-ink-faint",
    ghost: "border border-line bg-card text-ink hover:bg-line-soft disabled:text-ink-faint",
    subtle: "text-ink-soft hover:text-ink disabled:text-ink-faint",
  };
  return (
    <button className={cx(base, variants[variant], className)} disabled={disabled || loading} {...rest}>
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner() {
  return <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" aria-hidden />;
}

// Atlas card: set apart by a soft hairline + subtle shadow, never an edge stripe.
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-xl border border-line-soft bg-card shadow-sm", className)}>{children}</div>;
}

// A single instrument reading — the "real visual element" every Atlas view carries.
export function StatCallout({ label, value, hint, tone = "ink" }: { label: string; value: ReactNode; hint?: string; tone?: "ink" | "brand" | "ok" | "violet" }) {
  const accent = { ink: "text-ink", brand: "text-brand", ok: "text-ok", violet: "text-violet" }[tone];
  return (
    <Card className="px-4 py-3">
      <div className={cx("tabular text-2xl font-bold leading-none", accent)}>{value}</div>
      <div className="mt-1 text-xs font-medium text-ink-faint">{label}</div>
      {hint && <div className="mt-0.5 text-[11px] text-ink-faint">{hint}</div>}
    </Card>
  );
}

// Section header — display type, left-aligned, no accent underline (Atlas rule).
export function SectionHeader({ title, lead, right }: { title: string; lead?: string; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="font-display text-lg font-semibold tracking-tight text-ink">{title}</h2>
        {lead && <p className="mt-0.5 max-w-2xl text-sm text-ink-soft">{lead}</p>}
      </div>
      {right}
    </div>
  );
}

// Layer badge — the architecture colour convention (L2 brand blue, L3 violet, L4 amber).
export function LayerBadge({ layer }: { layer: "L1" | "L2" | "L3" | "L4" }) {
  const map = {
    L1: { label: "Layer 1 · rules", cls: "bg-line-soft text-ink-soft" },
    L2: { label: "Layer 2 · Claude", cls: "bg-brand-bg text-brand" },
    L3: { label: "Layer 3 · database", cls: "bg-violet-bg text-violet" },
    L4: { label: "Layer 4 · human gate", cls: "bg-warn-bg text-warn" },
  }[layer];
  return <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide", map.cls)}>{map.label}</span>;
}

// A lightweight centered modal (pop-up forms per Section 8). Escape/backdrop closes.
export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4" onClick={onClose}>
      <Card className="w-full max-w-lg p-5" >
        <div className="mb-3 flex items-center justify-between" onClick={(e) => e.stopPropagation()}>
          <h3 className="font-display text-base font-semibold text-ink">{title}</h3>
          <button className="text-ink-faint hover:text-ink" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div onClick={(e) => e.stopPropagation()}>{children}</div>
      </Card>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-bad/30 bg-bad-bg px-4 py-3 text-sm text-bad">
      <span className="font-semibold">Something went wrong.</span> {message}
    </div>
  );
}

export function InfoNotice({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-warn/30 bg-warn-bg px-4 py-2.5 text-sm text-ink">{children}</div>;
}

// A hover/focus "ⓘ" carrying context as its tooltip. Keyboard-focusable.
export function InfoDot({ title }: { title: string }) {
  return (
    <span
      tabIndex={0}
      role="note"
      aria-label={title}
      title={title}
      className="ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-line text-[10px] font-bold text-ink-faint align-middle focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright"
    >
      i
    </span>
  );
}
