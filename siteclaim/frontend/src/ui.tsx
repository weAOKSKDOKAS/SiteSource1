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

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-xl border border-line bg-card", className)}>{children}</div>;
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
