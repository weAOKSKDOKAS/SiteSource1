// Shared primitives for client_boq. Everything here is small, unstyled-by-default and takes its
// colour from the caller, because the palette carries meaning: a chip that picks its own colour
// would eventually say the wrong thing.

import { useEffect, useState } from "react";
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
        "inline-flex flex-none items-center gap-1.5 whitespace-nowrap font-cb-mono text-[10px] font-semibold tracking-cb-chip",
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
        "font-cb-mono text-[10px] font-semibold tracking-cb-chip",
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

/**
 * Where a number came from: the company's book, this tender, or nowhere.
 *
 * The library/tender rule made visible. A tender inherits every norm the output book holds and may
 * override any of them — and the override is always shown, because an inherited number and a chosen
 * one are different claims even when the digits match. Only the person who chose one can be asked why.
 *
 * `MISSING` is the important case and the reason this is a chip rather than a bit of styling: it is a
 * number named by something that prices, that nothing stands behind. It renders red and carries 0 —
 * flagged, never quietly defaulted, exactly as an archived rate resolves on a re-run.
 *
 * The backend decides which of the three this is (`boq/outputs.py: resolve`). This never works it out
 * from the value — two code paths that can disagree about provenance are worse than no mark at all.
 */
export type Source = "book" | "yours" | "missing";

const SOURCE_STYLE: Record<Source, string> = {
  book: "bg-cb-info text-cb-navy border border-cb-disabled",
  yours: "bg-cb-brass-tint text-cb-brass-text border border-cb-brass-line",
  missing: "bg-cb-bad-tint text-cb-bad-dark border border-cb-bad",
};

const SOURCE_TITLE: Record<Source, string> = {
  book: "Inherited from the output library. Changing it there changes every future tender.",
  yours: "Typed on this tender, for this job only. The library is untouched.",
  missing: "Nothing in the library defines this. It prices at zero until somebody sets it.",
};

export function SourceChip({
  source,
  bookValue,
  className,
}: {
  source: Source;
  /** The book's number, shown beside an override so `⟨BOOK 20⟩` sits next to your 9. */
  bookValue?: number | null;
  className?: string;
}) {
  const showBook = source === "yours" && bookValue !== null && bookValue !== undefined;
  return (
    <span className={cx("inline-flex flex-none items-center gap-1", className)}>
      {showBook && (
        <Chip className={SOURCE_STYLE.book} title={SOURCE_TITLE.book}>
          BOOK {formatNorm(bookValue)}
        </Chip>
      )}
      <Chip className={SOURCE_STYLE[source]} title={SOURCE_TITLE[source]}>
        {source.toUpperCase()}
      </Chip>
    </span>
  );
}

/** A norm, printed the way it is said: `0.33`, `20`, `1.23` — never `20.00` and never `0.3300`. */
export function formatNorm(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
}

/** The all-caps mono section label that heads a block of content. */
export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cx(
        "font-cb-mono text-[10px] font-semibold uppercase tracking-cb-label text-cb-faint",
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

/**
 * A small exclusive choice, shown in full — `⟨A⟩ B C`.
 *
 * A select would hide the alternatives behind a click, and on Site › Holes the alternatives are the
 * decision: you are choosing between three classes of access whose meanings matter, ninety-one
 * times. Every option carries its own `title`, because "B" on its own tells you nothing.
 *
 * Nothing is pre-selected. `value=""` is a legitimate state — a hole nobody has judged yet — and it
 * has to look different from a hole somebody judged as A.
 */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  className,
}: {
  value: T | "";
  options: { value: T; label: string; title?: string; tone?: "normal" | "warn" }[];
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "inline-flex flex-none overflow-hidden rounded-cb-btn border border-cb-border-strong",
        className,
      )}
    >
      {options.map((option) => {
        const on = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cx(
              "cb-press border-r border-cb-border-strong px-2 py-[3px] font-cb-mono text-[10px] font-semibold last:border-r-0",
              on && option.tone === "warn"
                ? "bg-cb-amber text-cb-on-brass"
                : on
                  ? "bg-cb-ink text-white"
                  : "bg-white text-cb-muted",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * A window of a drawing sheet, centred on one station.
 *
 * One render per sheet, cropped N ways in CSS. There is no image pipeline and none is needed: the
 * browser downloads the sheet once, and ninety-one tiles are ninety-one transforms of that same
 * cached image.
 *
 * The scaling looks like it stretches and does not. A window that is square *in metres* covers
 * different fractions of the page horizontally and vertically whenever the page is not square — so
 * setting width and height independently from those two fractions is exactly the uniform scale, not
 * a distortion of it. That holds only while the registration is isotropic, which is why
 * `georef.SheetRegistration.problems()` refuses a sheet whose two axes disagree by more than 2%.
 *
 * With no registration there is no honest picture to draw, so it says so rather than showing a
 * plausible-looking placeholder somebody might classify a hole from.
 */
export function MapCrop({
  src,
  box,
  size = 96,
  className,
}: {
  src: string | null;
  /** Fractions of the page. Null when the sheet has not been located yet. */
  box: { x0: number; y0: number; x1: number; y1: number; clipped?: boolean } | null;
  size?: number;
  className?: string;
}) {
  const span = box ? { x: box.x1 - box.x0, y: box.y1 - box.y0 } : null;
  if (!src || !span || span.x <= 0 || span.y <= 0) {
    return (
      <div
        style={{ width: size, height: size }}
        title="This sheet has no grid marks yet — read the coordinates beside any two grid crosses and every station on it follows."
        className={cx(
          "flex flex-none items-center justify-center rounded-cb-chip border border-dashed border-cb-border-strong bg-cb-panel p-1 text-center font-cb-mono text-[10px] leading-[1.35] text-cb-faint",
          className,
        )}
      >
        NO GRID MARKS ON THIS SHEET YET
      </div>
    );
  }
  return (
    <div
      style={{ width: size, height: size }}
      className={cx(
        "relative flex-none overflow-hidden rounded-cb-chip border bg-cb-page",
        box?.clipped ? "border-cb-amber" : "border-cb-border",
        className,
      )}
    >
      <img
        src={src}
        alt=""
        draggable={false}
        style={{
          position: "absolute",
          width: size / span.x,
          height: size / span.y,
          left: -(box!.x0 * size) / span.x,
          top: -(box!.y0 * size) / span.y,
          maxWidth: "none",
        }}
      />
      {/* The station is the centre of the window by construction, so the crosshair needs no
          coordinates of its own — it marks the middle, and the middle is the hole. */}
      <span className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 font-cb-mono text-[13px] font-semibold text-cb-bad">
        ✛
      </span>
      {box?.clipped && (
        <span
          title="This station is near the edge of the sheet, so part of the window is off the paper."
          className="absolute bottom-0 right-0 bg-cb-amber px-1 font-cb-mono text-[10px] font-semibold text-cb-on-brass"
        >
          EDGE
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cards & consequences
// ---------------------------------------------------------------------------
/** `flush` drops the card's own padding, for a card whose child is a table or a divided list and
 *  must reach the border. It is a PROP rather than a `className="p-0"` because `cx` concatenates,
 *  it does not resolve: `p-0` and `p-[12px_13px]` are both plain `padding` at equal specificity,
 *  so which one wins is decided by the order Tailwind happens to emit them in the bundle — and it
 *  emits `.p-0` first, so every `<Card className="p-0">` in this app was silently rendering
 *  padded. Measured in the built CSS on 2026-08-03, then fixed here rather than at 13 call sites. */
export function Card({
  children,
  className,
  selected,
  flush,
}: {
  children: ReactNode;
  className?: string;
  selected?: boolean;
  flush?: boolean;
}) {
  return (
    <div
      className={cx(
        "cb-row rounded-cb-card border border-cb-border",
        flush ? null : "p-[12px_13px]",
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
/** The way out of a blocked state, offered where the blockage is explained.
 *
 *  Every WAITS-ON screen names the tab that unlocks it; this is that sentence's missing half —
 *  a sentence that says "do it on the Route tab" and then makes you find the Route tab yourself
 *  is only half an explanation. Navigation only: it never performs the unlocking action itself,
 *  so no gate is weakened by it.
 */
export function OpenTab({ setId, tab, children }: { setId: string; tab: string; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={() => {
        window.location.hash = `#/tender/s/${encodeURIComponent(setId)}/${tab}`;
      }}
      className="cb-press rounded-cb-btn border border-cb-brass-line bg-cb-brass-tint px-3 py-1.5 font-cb-sans text-[11.5px] font-semibold text-cb-brass-text"
    >
      {children} →
    </button>
  );
}

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

// ---------------------------------------------------------------------------
// The team (named profiles)
// ---------------------------------------------------------------------------
/** The avatar colour set — brass-adjacent tones from the palette, assigned round-robin when a
 *  member has none stored. Initials, never photos: this is a desk tool, not a social app. */
export const AVATAR_COLOURS = ["#1E3A52", "#BD9A5F", "#2F6E8A", "#3C8A63", "#856636", "#8A3826"];

export function avatarColour(member: { colour?: string; member_id?: string } | null): string {
  if (member?.colour) return member.colour;
  if (!member?.member_id) return "#8A97A3";
  let hash = 0;
  for (const ch of member.member_id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLOURS[hash % AVATAR_COLOURS.length];
}

/** A team member as a circle of initials. `title` carries the full name — the design's rule. */
export function Avatar({
  member,
  size = 22,
  ring,
}: {
  member: { name?: string; initials?: string; colour?: string; member_id?: string } | null;
  size?: number;
  /** Overlapping stacks ring each avatar in ink so they read as separate circles. */
  ring?: boolean;
}) {
  const initials = member?.initials || (member?.name ?? "?").slice(0, 1).toUpperCase();
  return (
    <span
      title={member?.name ?? "Nobody identified"}
      style={{
        width: size,
        height: size,
        background: avatarColour(member),
        fontSize: Math.round(size * 0.38),
      }}
      className={cx(
        "flex flex-none select-none items-center justify-center rounded-full font-cb-sans font-semibold text-white",
        ring && "border-[1.5px] border-cb-ink",
      )}
    >
      {initials}
    </span>
  );
}

// ===========================================================================
// Primitives the ported procurement screens need
// ===========================================================================
// Built once, here, rather than invented inline four times — four inconsistent drawers is a
// worse outcome than one that is slightly wrong everywhere.
//
// TWO RULES THEY ALL FOLLOW:
//
// 1. Colour carries meaning, so these take it from the caller wherever it is semantic (the same
//    reason `Pill` and `Chip` above do). Atlas's `tone="brand" | "violet" | …` enums are NOT
//    translated by name — Atlas blue means "Claude wrote this" and cb blue means "an uncovered
//    clause", so a mechanical swap would silently invert them. Where a tone is genuinely a
//    magnitude and not an authorship claim (a match score), a fixed scale is used and says so.
//
// 2. They must work INSIDE `[data-app="cboq"]` without depending on it. `.cb-press` and the
//    `--cb-*` motion variables only apply under that attribute (set at App.tsx), so nothing here
//    uses them for anything load-bearing — every open/closed state is real conditional rendering
//    or a plain Tailwind transition, never a CSS class that might not be loaded.

/** A tiny spinner for a control that is working. */
export function Spinner() {
  return (
    <span
      className="inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent"
      aria-hidden
    />
  );
}

/** Three pulsing dots plus an optional label — for a region that is loading, not a control. */
export function LoadingDots({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[11px] text-cb-faint" role="status" aria-live="polite">
      <span className="flex gap-1" aria-hidden>
        {[0, 160, 320].map((delay) => (
          <span
            key={delay}
            className="h-1.5 w-1.5 animate-pulse rounded-full bg-cb-faint"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
      {label}
    </span>
  );
}

/** A hairline that sweeps a card while work is in flight. Purely an affordance — it says
 *  "something is happening here", never what the result is. */
export function ScanLine({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 h-[2px] overflow-hidden rounded-t-[inherit]" aria-hidden>
      <div
        className="h-full w-1/3 animate-[cbSweep_1.4s_ease-in-out_infinite]"
        style={{ background: "linear-gradient(90deg, transparent, var(--color-cb-brass), transparent)" }}
      />
    </div>
  );
}

/** How bad a finding is. `warning` uses `cb-amber`, whose token comment already names warning as
 *  one of its meanings; there is deliberately no amber FILL because cb has no amber tint token and
 *  inventing a hex would put an unowned colour in the palette. */
export type Severity = "fatal" | "warning" | "info";

const SEVERITY: Record<Severity, { label: string; cls: string; dot: string }> = {
  fatal: { label: "Fatal", cls: "bg-cb-bad-tint text-cb-bad-dark", dot: "bg-cb-bad" },
  warning: { label: "Warning", cls: "border border-cb-brass-line text-cb-amber", dot: "bg-cb-amber" },
  info: { label: "Info", cls: "bg-cb-info-fill text-cb-muted", dot: "bg-cb-muted" },
};

export function SeverityTag({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-cb-chip px-2 py-0.5 font-cb-sans text-[10px] font-semibold uppercase tracking-cb-chip",
        s.cls,
      )}
    >
      <span className={cx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

/** Semantic match of a firm's closeout history to this scope.
 *
 *  The tiers are a MAGNITUDE, not an authorship claim, so they use the ok/muted/faint scale rather
 *  than brass or navy — a brass chip here would say "a model decided this", and the score is
 *  deterministic cross-reference. `assessed` false with a zero score is "nothing to score
 *  against", which is not the same as a measured zero and must not read as one. */
export function MatchChip({ score, assessed = true }: { score: number; assessed?: boolean }) {
  if (!assessed && score <= 0) {
    return (
      <span
        className="inline-flex items-center rounded-cb-pill bg-cb-panel px-2 py-0.5 font-cb-sans text-[10px] font-medium text-cb-faint"
        title="No closeout record yet — there is nothing to score against. Firms are ordered by trade/specialty and the public risk screen; match ranking activates once closeout (EOS) evidence exists."
      >
        unassessed — no closeout yet
      </span>
    );
  }
  const value = Math.round(score * 100);
  const tier =
    score >= 0.7 ? "bg-cb-ok-tint text-cb-ok-dark" : score >= 0.5 ? "bg-cb-panel text-cb-body" : "bg-cb-panel text-cb-faint";
  return (
    <span
      className={cx("inline-flex items-center rounded-cb-pill px-2 py-0.5 font-cb-mono text-[10px] font-medium", tier)}
      title="Semantic match of the firm's closeout history to this scope"
    >
      {value}% match
    </span>
  );
}

/** A titled, collapsible block. Children render only when open — the same behaviour as the screen
 *  this was ported from, and it means the block does not depend on `.cb-expand` being loaded. */
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
    <div className="rounded-cb-card border border-cb-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left font-cb-sans text-[11px] font-medium text-cb-ink-text"
      >
        <span>
          {title}
          {count != null && <span className="ml-1.5 font-cb-mono text-[10px] text-cb-faint">{count}</span>}
        </span>
        <span className="text-cb-faint" aria-hidden>{open ? "−" : "+"}</span>
      </button>
      {open && <div className="border-t border-cb-divider px-3 py-2">{children}</div>}
    </div>
  );
}

/** A centred overlay for a decision that needs the whole screen's attention. */
export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-cb-ink/40 px-4"
      onClick={onClose}
    >
      <div
        className={cx(
          "flex max-h-[88vh] w-full flex-col rounded-cb-card border border-cb-border bg-cb-surface p-5 shadow-cb-card",
          wide ? "max-w-3xl" : "max-w-lg",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-cb-serif text-base font-semibold text-cb-ink-text">{title}</h3>
          <button className="text-cb-faint hover:text-cb-ink-text" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

/** The right-anchored detail record. Stays mounted so the slide runs both ways; escape, scrim and
 *  ✕ all close it.
 *
 *  `accent` is a className, not a tone enum — the caller says what the record MEANS (brass for a
 *  model's proposal, navy for a deterministic result, bad for a failure) instead of picking from a
 *  list of names whose colours mean something different in the other design system. */
export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  eyebrow = "Detail record",
  accent = "bg-cb-brass",
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: ReactNode;
  eyebrow?: string;
  accent?: string;
  children: ReactNode;
  footer?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div
      className={cx("fixed inset-0 z-[80]", open ? "pointer-events-auto" : "pointer-events-none")}
      aria-hidden={!open}
    >
      <div
        className={cx(
          "absolute inset-0 bg-cb-ink/45 transition-opacity duration-300",
          open ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cx(
          "absolute right-0 top-0 h-full w-[432px] max-w-[92vw] overflow-y-auto bg-cb-surface",
          "shadow-[-30px_0_60px_-30px_rgba(12,26,40,0.5)]",
          "transition-transform duration-300 ease-[cubic-bezier(.3,.8,.25,1)]",
          open ? "translate-x-0" : "translate-x-[105%]",
        )}
      >
        <header className="flex items-start justify-between gap-3 border-b border-cb-border px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className={cx("h-2 w-2 rounded-full", accent)} aria-hidden />
              <SectionLabel>{eyebrow}</SectionLabel>
            </div>
            <h3 className="mt-1 font-cb-serif text-base font-semibold text-cb-ink-text">{title}</h3>
            {subtitle && <div className="mt-0.5 text-[11px] text-cb-muted">{subtitle}</div>}
          </div>
          <button className="text-cb-faint hover:text-cb-ink-text" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="px-5 py-4">{children}</div>
        {footer && <p className="px-5 pb-5 text-center text-[10px] text-cb-faint">{footer}</p>}
      </aside>
    </div>
  );
}

/** The heading above a step's body. */
export function StepHeading({ title, lead }: { title: string; lead: string }) {
  return (
    <div>
      <h2 className="font-cb-serif text-lg font-semibold text-cb-ink-text">{title}</h2>
      <p className="mt-0.5 max-w-2xl text-[12px] text-cb-muted">{lead}</p>
    </div>
  );
}

/** A section heading with optional lead and a right-hand slot. */
export function SectionHeader({ title, lead, right }: { title: string; lead?: string; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="font-cb-serif text-base font-semibold text-cb-ink-text">{title}</h2>
        {lead && <p className="mt-0.5 max-w-2xl text-[12px] text-cb-muted">{lead}</p>}
      </div>
      {right}
    </div>
  );
}

/** Back / continue for a step. `loading` disables forward travel while work is in flight. */
export function StepNav({
  onBack,
  onNext,
  nextLabel = "Continue →",
  loading = false,
  nextDisabled = false,
}: {
  onBack?: () => void;
  onNext?: () => void;
  nextLabel?: string;
  loading?: boolean;
  nextDisabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-cb-divider pt-3">
      {onBack ? (
        <Button variant="ghost" onClick={onBack}>
          ← Back
        </Button>
      ) : (
        <span />
      )}
      {onNext && (
        <Button variant="brass" onClick={onNext} disabled={loading || nextDisabled}>
          {loading ? (
            <span className="inline-flex items-center gap-2">
              <Spinner /> Working…
            </span>
          ) : (
            nextLabel
          )}
        </Button>
      )}
    </div>
  );
}

/** One headline number with its label. `accent` is a className so the caller says what the number
 *  means rather than choosing from a palette of tone names. */
export function StatCallout({
  label,
  value,
  hint,
  accent = "text-cb-ink-text",
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  accent?: string;
  className?: string;
}) {
  return (
    <Card className={className}>
      <div className={cx("font-cb-mono text-2xl font-bold leading-none", accent)}>{value}</div>
      <div className="mt-1 text-[11px] font-medium text-cb-faint">{label}</div>
      {hint && <div className="mt-0.5 text-[10px] text-cb-faint">{hint}</div>}
    </Card>
  );
}

/** A reference / docket block — a code that must be quoted back exactly. */
export function Docket({
  label = "Reference / docket",
  code,
  className,
}: {
  label?: string;
  code: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("rounded-cb-card border border-cb-border bg-cb-panel px-4 py-3", className)}>
      <SectionLabel className="mb-1">{label}</SectionLabel>
      <div className="font-cb-mono text-sm font-semibold text-cb-ink-text">{code}</div>
    </div>
  );
}
