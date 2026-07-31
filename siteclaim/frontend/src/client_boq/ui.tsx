// Shared primitives for client_boq. Everything here is small, unstyled-by-default and takes its
// colour from the caller, because the palette carries meaning: a chip that picks its own colour
// would eventually say the wrong thing.

import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { DepartureItem, RegisterStatus } from "./types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------------------
// Authorship — the one derivation in the whole UI, written down once
// ---------------------------------------------------------------------------
// The design's five rail swatches are not in the payload; they are read off the fields the
// backend does send. Deriving this per-component would guarantee two components eventually
// disagree about who wrote a finding — the single thing this product exists to keep straight.
// So it lives here and nowhere else.
//
// The subtlety: a human verdict OVERWRITES `status` (`confirmed` / `dismissed` / `query`), so
// authorship cannot be read from status alone or every decided line would lose its author. The
// precedence below leans on fields that survive a verdict:
//
//   1. status == citation_failed  -> red    a check on it failed (never confirmable)
//   2. rule_ref is set            -> navy   the rule layer is the ONLY writer of rule_ref,
//                                           and it is never cleared — so this survives
//   3. status == uncovered        -> blue   a clause no criterion covers
//   4. source == cashflow         -> grey   s06 is arithmetic on the payment terms, no model
//   5. otherwise                  -> brass  s03/s04/s05 are all AI-propose
//
// Rule 5 is the honest default: everything that is not demonstrably deterministic is attributed
// to the model. Over-crediting code would be the dangerous direction of the two.
export type Author = "rule" | "model" | "failed" | "uncovered" | "code";

export const AUTHOR: Record<Author, { label: string; long: string; swatch: string; text: string }> = {
  rule: {
    label: "RULES ENGINE",
    long: "A deterministic rule fired on a measured value. No model was involved in the finding.",
    swatch: "bg-cb-navy",
    text: "text-cb-navy",
  },
  model: {
    label: "CLAUDE",
    long: "Proposed by the model from the document text. A proposal, not a verdict — yours is the verdict.",
    swatch: "border-[1.5px] border-cb-brass",
    text: "text-cb-brass-text",
  },
  failed: {
    label: "CITATION FAILED",
    long: "The quoted words could not be found where this line says they are. Do not rely on it.",
    swatch: "bg-cb-bad",
    text: "text-cb-bad-dark",
  },
  uncovered: {
    label: "UNCOVERED CLAUSE",
    long: "A clause in the contract that no criterion in the library covers.",
    swatch: "bg-cb-blue",
    text: "text-cb-blue",
  },
  code: {
    label: "CODE, NO MODEL",
    long: "Computed arithmetically from the payment terms. Nothing here was written by a model.",
    swatch: "bg-cb-muted",
    text: "text-cb-muted",
  },
};

export function authorOf(item: Pick<DepartureItem, "status" | "source" | "rule_ref">): Author {
  const status = item.status as RegisterStatus;
  if (status === "citation_failed") return "failed";
  if (item.rule_ref) return "rule";
  if (status === "uncovered") return "uncovered";
  if (item.source === "cashflow") return "code";
  return "model";
}

/** The 8×8 swatch used in the rail's FROM: list and beside a register line. */
export function AuthorSwatch({ author, className }: { author: Author; className?: string }) {
  return (
    <span
      title={AUTHOR[author].long}
      aria-label={AUTHOR[author].label}
      className={cx("inline-block h-2 w-2 flex-none rounded-[2px]", AUTHOR[author].swatch, className)}
    />
  );
}

/** Swatch + name, for a register row's meta line. */
export function AuthorBadge({ author }: { author: Author }) {
  return (
    <span
      title={AUTHOR[author].long}
      className={cx(
        "inline-flex flex-none items-center gap-1.5 whitespace-nowrap font-cb-mono text-[8.5px] font-semibold tracking-cb-chip",
        AUTHOR[author].text,
      )}
    >
      <AuthorSwatch author={author} />
      {AUTHOR[author].label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Chips, pills, labels
// ---------------------------------------------------------------------------
/** A small all-caps mono chip. Colour is the caller's, always — see the note at the top. */
export function Chip({
  children,
  className,
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex flex-none items-center gap-1 whitespace-nowrap rounded-cb-chip px-[7px] py-[3px]",
        "font-cb-mono text-[9px] font-semibold tracking-cb-chip",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** A rounded revision pill: `Rev 0 · Original intake`. */
export function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex flex-none items-center whitespace-nowrap rounded-cb-pill px-2 py-1",
        "font-cb-sans text-[10px] font-medium",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** The all-caps mono section label that heads a block of content. */
export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cx(
        "font-cb-mono text-[8.5px] font-semibold uppercase tracking-cb-label text-cb-faint",
        className,
      )}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "brass" | "dark" | "outline" | "amber" | "ghost";
  /** Shown in place of the button when it is disabled — the design's rule for a control that
   *  cannot be used: state the reason where the button is, instead of catching a 409 later. */
  disabledReason?: string;
};

const VARIANT: Record<NonNullable<ButtonProps["variant"]>, string> = {
  brass: "bg-cb-brass text-cb-on-brass font-semibold",
  dark: "bg-cb-ink text-white font-semibold",
  outline: "border border-cb-border-strong bg-white text-cb-ink-text font-medium",
  amber: "bg-cb-amber text-cb-on-brass font-semibold",
  ghost: "text-cb-brass-text-light underline underline-offset-2 font-medium",
};

export function Button({
  variant = "outline",
  disabledReason,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || Boolean(disabledReason);
  return (
    <button
      {...rest}
      disabled={isDisabled}
      title={disabledReason || rest.title}
      className={cx(
        "cb-press rounded-cb-btn font-cb-sans",
        variant === "ghost" ? "" : "px-4 py-2 text-[11px]",
        isDisabled
          ? "cursor-not-allowed border border-dashed border-cb-border-strong bg-transparent text-cb-disabled"
          : VARIANT[variant],
        className,
      )}
    >
      {children}
    </button>
  );
}

/** A 30×28 icon button — re-run OCR, edit bounds. Always needs a title: the glyph alone does
 *  not say what it does, and this tool has no room for labels beside them. */
export function IconButton({
  className,
  children,
  filled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { filled?: boolean }) {
  return (
    <button
      {...rest}
      className={cx(
        "cb-press cb-icon-btn flex h-7 w-[30px] flex-none items-center justify-center rounded-cb-btn text-[12px]",
        filled
          ? "bg-cb-brass text-cb-on-brass"
          : "border border-cb-border-strong bg-white text-cb-muted",
        rest.disabled && "cursor-not-allowed opacity-45",
        className,
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Cards & consequences
// ---------------------------------------------------------------------------
export function Card({
  children,
  className,
  selected,
}: {
  children: ReactNode;
  className?: string;
  selected?: boolean;
}) {
  return (
    <div
      className={cx(
        "cb-row rounded-cb-card border border-cb-border p-[12px_13px]",
        selected ? "border-l-[3px] border-l-cb-brass bg-cb-selected" : "bg-white",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** The sentence beside a gate button saying what passing it costs. Every gate has one; the
 *  design's rule is that a gate states its consequence *before* it is passed, not after. */
export function Consequence({ children }: { children: ReactNode }) {
  return (
    <p className="max-w-[180px] font-cb-sans text-[10px] leading-[1.4] text-cb-muted">{children}</p>
  );
}

/** A step that has not run yet says what it is waiting for. No step is ever disabled — a
 *  locked tab produces a dead end, an open one that explains itself does not. */
export function WaitingOn({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  /** The thing this step is waiting for, when the user can do it from here. A step that says
   *  what it needs and then makes you go elsewhere to do it is only half an explanation. */
  action?: ReactNode;
}) {
  return (
    <div className="flex h-full w-full items-center justify-center p-10">
      <div className="max-w-md text-center">
        <div className="font-cb-serif text-[17px] font-semibold text-cb-ink-text">{title}</div>
        <p className="mt-2 font-cb-sans text-[11.5px] leading-[1.6] text-cb-muted">{children}</p>
        {action && <div className="mt-4 flex justify-center">{action}</div>}
      </div>
    </div>
  );
}

/** An error the backend refused with. Gate 409s arrive here verbatim, because the backend's
 *  own sentence names which gate refused and why. */
export function ErrorNote({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div className="flex items-start gap-3 border border-cb-bad bg-cb-bad-tint px-4 py-[9px]">
      <p className="flex-1 font-cb-sans text-[11px] leading-[1.45] text-cb-bad-dark">{message}</p>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="cb-press flex-none font-cb-mono text-[10px] text-cb-bad-dark"
        >
          ✕
        </button>
      )}
    </div>
  );
}

/** Formats a whole-dollar figure the way the register and risk pane do. */
export function money(value: number, currency = "HK$"): string {
  return `${currency}${Math.round(Math.abs(value)).toLocaleString("en-US")}`;
}
