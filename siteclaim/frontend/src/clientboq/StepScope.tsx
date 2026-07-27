// Step 3 — the scope of record.
//
// Two things meet on this screen and they must not look alike. Claude drafts a scope
// statement and sorts what it read into inclusions, exclusions, ambiguities, conflicts and
// assumptions. Separately, code injects one assumption per departure the human confirmed on
// the register — verbatim, no model involved. So the notes are grouped by kind, and the
// register-sourced ones are pulled out into their own block with the register named: this is
// the point where a decision made two screens ago becomes something the price rests on.
//
// The gate is an edit box, not a checkbox. Approving is where the human either accepts
// Claude's sentence or writes their own — and whichever is in the box becomes the scope of
// record the estimate and the offer letter are built from.

import { useEffect, useState } from "react";

import { Pill, StepHeading } from "../components";
import { Button, Card, LayerBadge, LoadingDots, ScanLine, SectionHeader, cx } from "../ui";
import { EmptyState, Field, GateSeal } from "./boqUi";
import type { ScopeReviewNote, ScopeResult } from "./types";

// The five note kinds, in the order an estimator reads them: what we are doing, what we are
// not, then the three flavours of "this is not nailed down".
const KIND_ORDER = ["inclusion", "exclusion", "ambiguity", "conflict", "assumption"] as const;

const KIND_META: Record<string, { label: string; tone: "ok" | "neutral" | "warn" | "bad" | "brand"; note: string }> = {
  inclusion: { label: "Included", tone: "ok", note: "In the price." },
  exclusion: { label: "Excluded", tone: "neutral", note: "Not in the price — stated so the client cannot assume it." },
  ambiguity: { label: "Ambiguous", tone: "warn", note: "The documents do not settle it; the price carries an allowance." },
  conflict: { label: "Conflicting", tone: "bad", note: "Two documents disagree. Resolve before award." },
  assumption: { label: "Assumed", tone: "brand", note: "What the price is built on." },
};

function NoteList({ notes }: { notes: ScopeReviewNote[] }) {
  return (
    <ul className="space-y-1.5">
      {notes.map((n, i) => (
        <li key={i} className="flex gap-2 text-sm leading-relaxed text-ink-soft">
          <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-faint" />
          {n.text}
        </li>
      ))}
    </ul>
  );
}

const CARRIED_PREVIEW = 5;

/**
 * The register's confirmed departures, injected verbatim. On a busy set this runs to a dozen
 * or more, which would swamp the screen the estimator actually came here to read — so it
 * previews and expands. Nothing is hidden permanently; the count is always stated.
 */
function CarriedFromRegister({ notes }: { notes: ScopeReviewNote[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? notes : notes.slice(0, CARRIED_PREVIEW);
  const hidden = notes.length - shown.length;
  return (
    <Card className="p-4">
      <SectionHeader
        title="Carried from the register"
        lead="One assumption per departure you confirmed, injected by code — never re-worded by a model. This is where the register's decisions become part of the price."
        right={<Pill tone="ok">{notes.length}</Pill>}
      />
      <ul className="mt-3 space-y-2">
        {shown.map((n, i) => (
          <li key={i} className="flex gap-2.5 rounded-lg border border-ok/25 bg-ok-bg/40 px-3 py-2">
            <span aria-hidden className="mt-0.5 shrink-0 text-ok">✓</span>
            <span className="text-sm leading-relaxed text-ink">{n.text}</span>
          </li>
        ))}
      </ul>
      {(hidden > 0 || expanded) && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-2 text-xs font-semibold text-brand hover:underline"
        >
          {expanded ? "Show fewer" : `Show all ${notes.length} carried assumptions`}
        </button>
      )}
    </Card>
  );
}

export function StepScope({
  scope,
  running,
  stage,
  busy,
  onRun,
  onApprove,
  onReopen,
  onBack,
  onContinue,
}: {
  scope: ScopeResult | null;
  running: boolean;
  stage: string;
  busy: boolean;
  onRun: () => void;
  onApprove: (amendedSummary: string) => void;
  onReopen: () => void;
  onBack: () => void;
  onContinue: () => void;
}) {
  const [summary, setSummary] = useState("");
  const draftSummary = scope?.scope.summary ?? "";
  const recordSummary = scope?.summary_of_record ?? "";

  useEffect(() => {
    setSummary(recordSummary);
  }, [recordSummary]);

  if (!scope) {
    return (
      <div className="space-y-5">
        <StepHeading
          title="Agree what is being priced"
          lead="With the register closed, Claude reads the same documents again — this time for scope — and the confirmed departures are wired in as priced assumptions."
        />
        {running ? (
          <Card className="relative p-6">
            <ScanLine active />
            <LoadingDots label={stage ? `Drafting the scope — ${stage}` : "Drafting the scope"} />
          </Card>
        ) : (
          <EmptyState
            title="No scope draft yet"
            action={<Button onClick={onRun}>Draft the scope →</Button>}
          >
            The draft is a starting point. You edit the statement before approving it, and what you approve is
            what the estimate and the offer letter are built from.
          </EmptyState>
        )}
        <Button variant="ghost" onClick={onBack}>
          ← Register
        </Button>
      </div>
    );
  }

  const fromRegister = scope.scope.notes.filter((n) => n.source === "register");
  const drafted = scope.scope.notes.filter((n) => n.source !== "register");
  const edited = summary.trim() !== draftSummary.trim() && summary.trim().length > 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <StepHeading
          title="Agree what is being priced"
          lead="Claude drafts the scope statement and sorts what it read; the departures you confirmed are injected verbatim as priced assumptions. Approve the statement — amended or as drafted — and it becomes the scope of record."
        />
        <LayerBadge layer="L2" />
      </div>

      <GateSeal
        title="Scope gate"
        closed={scope.scope_approved}
        detail={
          scope.scope_approved ? (
            <>The scope of record is locked. The cost build-up and the offer letter are written against it.</>
          ) : (
            <>The pricing run refuses until this is approved — nothing gets priced against a scope nobody agreed.</>
          )
        }
        secondary={
          scope.scope_approved ? undefined : (
            <Button variant="subtle" onClick={() => setSummary(draftSummary)} disabled={!edited}>
              Reset to draft
            </Button>
          )
        }
        action={
          scope.scope_approved ? (
            <div className="flex gap-2">
              <Button variant="ghost" onClick={onReopen} loading={busy}>
                Reopen
              </Button>
              <Button onClick={onContinue}>Price it →</Button>
            </div>
          ) : (
            <Button onClick={() => onApprove(edited ? summary.trim() : "")} loading={busy} disabled={!summary.trim()}>
              Approve the scope →
            </Button>
          )
        }
      />

      <Card className="p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className="font-display text-base font-semibold tracking-display text-ink">Scope of record</h3>
          {scope.scope_approved ? (
            <Pill tone="ok">approved</Pill>
          ) : edited ? (
            <Pill tone="warn">amended — yours, not the draft</Pill>
          ) : (
            <Pill tone="brand">as drafted by Claude</Pill>
          )}
        </div>
        <textarea
          className={cx(
            "h-28 w-full resize-y rounded-lg border px-3 py-2 text-sm leading-relaxed focus:outline-none",
            scope.scope_approved ? "border-line-soft bg-paper-soft text-ink-soft" : "border-line focus:border-brand",
          )}
          value={summary}
          readOnly={scope.scope_approved}
          onChange={(e) => setSummary(e.target.value)}
        />
        {edited && !scope.scope_approved && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-ink-faint hover:text-ink">Show Claude's original draft</summary>
            <p className="mt-1.5 rounded-lg bg-paper-soft px-3 py-2 text-xs leading-relaxed text-ink-soft">{draftSummary}</p>
          </details>
        )}
      </Card>

      {fromRegister.length > 0 && <CarriedFromRegister notes={fromRegister} />}

      <Card className="p-4">
        <SectionHeader
          title="What Claude read"
          lead="Drafted from the document set and grouped by what each note does to the price."
          right={<LayerBadge layer="L2" />}
        />
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {KIND_ORDER.map((kind) => {
            const notes = drafted.filter((n) => n.kind === kind);
            if (!notes.length) return null;
            const meta = KIND_META[kind];
            return (
              <div key={kind}>
                <div className="mb-1.5 flex items-center gap-2">
                  <Pill tone={meta.tone}>{meta.label}</Pill>
                  <span className="text-[11px] text-ink-faint">{meta.note}</span>
                </div>
                <NoteList notes={notes} />
              </div>
            );
          })}
          {drafted.filter((n) => !KIND_ORDER.includes(n.kind as (typeof KIND_ORDER)[number])).length > 0 && (
            <div>
              <div className="mb-1.5">
                <Pill>Other</Pill>
              </div>
              <NoteList notes={drafted.filter((n) => !KIND_ORDER.includes(n.kind as (typeof KIND_ORDER)[number]))} />
            </div>
          )}
        </div>
      </Card>

      {scope.scope.clarifying_questions.length > 0 && (
        <Card className="p-4">
          <SectionHeader
            title="Ask the client"
            lead="Questions the documents leave open. Answering them before award is cheaper than pricing around them."
            right={<Pill tone="warn">{scope.scope.clarifying_questions.length}</Pill>}
          />
          <ol className="mt-3 space-y-1.5">
            {scope.scope.clarifying_questions.map((q, i) => (
              <li key={i} className="flex gap-2.5 text-sm text-ink-soft">
                <span className="tabular shrink-0 text-xs font-semibold text-ink-faint">{i + 1}</span>
                {q}
              </li>
            ))}
          </ol>
        </Card>
      )}

      <div className="flex items-center justify-between gap-3 pt-1">
        <Button variant="ghost" onClick={onBack}>
          ← Register
        </Button>
        <div className="flex items-center gap-3">
          <Field label="Set">{scope.set_id}</Field>
          {scope.scope_approved && <Button onClick={onContinue}>Price it →</Button>}
        </div>
      </div>
    </div>
  );
}
