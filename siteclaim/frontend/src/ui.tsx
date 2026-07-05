import { useEffect, useState } from "react";
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
    <span className={cx("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold uppercase tracking-eyebrow", s.classes)}>
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
    // Primary CTA: the brand→violet accent gradient + brand glow (the prototype's emphasis).
    primary:
      "bg-brand-violet text-white shadow-glow transition hover:brightness-110 disabled:bg-none disabled:bg-ink-faint disabled:shadow-none",
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

// Atlas card: set apart by a soft hairline + the ported deep card shadow + 16px radius,
// never an edge stripe.
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-card border border-line-soft bg-card shadow-card", className)}>{children}</div>;
}

// A single instrument reading — the "real visual element" every Atlas view carries. A faint
// tone-matched tint wash lifts it off the panel (neutral depth, signal colours stay reserved).
export function StatCallout({ label, value, hint, tone = "ink" }: { label: string; value: ReactNode; hint?: string; tone?: "ink" | "brand" | "ok" | "violet" }) {
  const accent = { ink: "text-ink", brand: "text-brand", ok: "text-ok", violet: "text-violet" }[tone];
  const tint = { ink: "", brand: "tint-brand", ok: "tint-ok", violet: "tint-violet" }[tone];
  return (
    <Card className={cx("px-4 py-3", tint)}>
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
        <h2 className="font-display text-lg font-semibold tracking-display text-ink">{title}</h2>
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
  return <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-eyebrow", map.cls)}>{map.label}</span>;
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

// --- Drawer (detail-on-click) -----------------------------------------------
// The V2 slide-in record panel: right-anchored, scrim with a light blur, eased
// slide (it stays mounted so the transition runs both ways). Escape / scrim / ✕
// close it. `eyebrow` is the record-type line ("Firm record", "Variance record");
// `footer` is the closing microcopy line, centred and faint.
const DRAWER_TONES = {
  brand: { chip: "bg-brand", text: "text-brand" },
  violet: { chip: "bg-violet", text: "text-violet" },
  ok: { chip: "bg-ok", text: "text-ok" },
  warn: { chip: "bg-warn", text: "text-warn" },
  bad: { chip: "bg-bad", text: "text-bad" },
  ink: { chip: "bg-ink", text: "text-ink-soft" },
} as const;
export type DrawerTone = keyof typeof DRAWER_TONES;

export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  eyebrow = "Detail record",
  tone = "brand",
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: ReactNode;
  eyebrow?: string;
  tone?: DrawerTone;
  children: ReactNode;
  footer?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const t = DRAWER_TONES[tone];
  return (
    <div className={cx("fixed inset-0 z-[80]", open ? "pointer-events-auto" : "pointer-events-none")} aria-hidden={!open}>
      <div
        className={cx(
          "absolute inset-0 bg-ink/45 backdrop-blur-[2px] transition-opacity duration-300",
          open ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cx(
          "absolute right-0 top-0 h-full w-[432px] max-w-[92vw] overflow-y-auto bg-card",
          "shadow-[-30px_0_60px_-30px_rgba(15,27,45,0.5)]",
          "transition-transform duration-300 ease-[cubic-bezier(.3,.8,.25,1)]",
          open ? "translate-x-0" : "translate-x-[105%]",
        )}
      >
        <div className="p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className={cx("flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.12em]", t.text)}>
              <span className={cx("flex h-6 w-6 items-center justify-center rounded-md text-[11px] text-white", t.chip)}>§</span>
              {eyebrow}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-paper text-sm text-ink-soft hover:text-ink"
            >
              ✕
            </button>
          </div>
          <h3 className="font-display text-xl font-bold tracking-display text-ink">{title}</h3>
          {subtitle && <div className="mt-1 text-xs text-ink-soft">{subtitle}</div>}
          <div className="mt-4">{children}</div>
          {footer && <p className="mb-1 mt-5 text-center text-[11.5px] leading-relaxed text-ink-faint">{footer}</p>}
        </div>
      </aside>
    </div>
  );
}

// The mono uppercase field label used inside detail records ("Reference / docket",
// "Record summary", "Issuing register").
export function MonoLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cx("tabular text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-faint", className)}>
      {children}
    </div>
  );
}

// The "Reference / docket" tile — a citable code set in mono on a soft panel.
export function Docket({ label = "Reference / docket", code, className }: { label?: string; code: ReactNode; className?: string }) {
  return (
    <div className={cx("rounded-xl border border-line-soft bg-paper-soft px-4 py-3", className)}>
      <MonoLabel className="mb-1">{label}</MonoLabel>
      <div className="tabular text-base font-semibold text-ink">{code}</div>
    </div>
  );
}

// A collapsible section inside a detail view. Chevron rotates; closed by default
// unless the section is load-bearing (pass defaultOpen).
export function Collapse({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-line-soft py-2.5 first:border-t-0 first:pt-0">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 text-left" aria-expanded={open}>
        <span className={cx("text-[10px] text-ink-faint transition-transform duration-200", open && "rotate-90")} aria-hidden>
          ▶
        </span>
        <MonoLabel>{title}</MonoLabel>
        {count != null && <span className="tabular text-[10.5px] text-ink-faint">· {count}</span>}
      </button>
      {open && <div className="pt-2">{children}</div>}
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
