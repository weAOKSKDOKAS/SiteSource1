// Frame 07 — Scope. What the register decided, what the client has not answered, and what the
// addenda changed, turned into the scope of record: the words that go into the offer letter
// verbatim.
//
// This is the freeze gate. Two rules do all the work:
//
//  * **Nothing walks into the scope on its own.** A source stays on the left rail until someone
//    maps it. That is what makes every line in the offer letter somebody's decision.
//  * **A machine's number must not be able to look priced.** An unreviewed AI fallback sits under
//    a brass rule labelled "not yours until you accept it"; only accepting moves it under the
//    green "PRICED ON THIS ASSUMPTION" rule. Approve is disabled while any remains.
//
// The disabled Approve is a deliberate departure from the drawn frame, which shows it live with
// two fallbacks still active. Reason: locked decision 8 makes freeze the point where an
// unanswered query becomes an answer or a stated priced assumption, so approving over an
// unaccepted fallback would let a guess into the price — which this frame's own rule forbids.
// It follows the same pattern the design uses for a citation-failed row: disable the control and
// put the reason where the button is, instead of catching a 409 afterwards.

import { useCallback, useEffect, useState } from "react";
import type { SetData } from "../App";
import { api, runJob } from "../api";
import { Rail } from "../chrome";
import type { JobState, ScopeItem, ScopeSection, ScopeSource, ScopeSourcesResponse } from "../types";
import { Button, Chip, SectionLabel, WaitingOn, cx, money } from "../ui";

const SECTIONS: { id: ScopeSection; label: string }[] = [
  { id: "qualifications", label: "QUALIFICATIONS & EXCLUSIONS" },
  { id: "fallbacks", label: "OPEN RFI PRICING FALLBACKS & ASSUMPTIONS" },
  { id: "logistics", label: "LOGISTICS & EXECUTION BOUNDARIES" },
];

const GROUPS: { id: ScopeSource["group"]; label: string; head: string; badge: string }[] = [
  {
    id: "departure",
    label: "CONFIRMED DEPARTURES",
    head: "text-cb-navy",
    badge: "bg-cb-info text-cb-navy",
  },
  {
    id: "rfi",
    label: "OPEN RFIS & QUERIES",
    head: "text-cb-brass-text",
    badge: "bg-cb-brass-tint text-cb-brass-text",
  },
  {
    id: "addendum",
    label: "ADDENDA SCOPE DELTAS",
    head: "text-cb-blue",
    badge: "bg-cb-info text-cb-blue",
  },
];

export function ScopeTab({
  data,
  railOpen,
  onRefresh,
  onError,
  onProgress,
}: {
  data: SetData;
  railOpen: boolean;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
  onProgress?: (job: JobState | null) => void;
}) {
  const [state, setState] = useState<ScopeSourcesResponse | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [justMapped, setJustMapped] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      api
        .scopeSources(data.setId)
        .then(setState)
        .catch((e: unknown) => onError(e instanceof Error ? e.message : String(e))),
    [data.setId, onError],
  );

  useEffect(() => {
    if (data.scope) void load();
  }, [data.scope, load]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const map = (source: ScopeSource) =>
    run(async () => {
      const result = await api.mapScope(data.setId, source.source_ref);
      setJustMapped((cur) => new Set(cur).add(result.item.item_id));
    });

  const save = (item: ScopeItem, accept?: boolean) =>
    run(async () => {
      await api.updateScopeItem(data.setId, item.item_id, { text: draft, accept });
      setEditing(null);
    });

  const approve = () =>
    run(async () => {
      await api.approveScope(data.setId, true);
      await onRefresh();
    });

  /** Draft the scope. A background job in LIVE, inline in DEMO — runJob covers both. */
  async function runScope() {
    setBusy(true);
    try {
      await runJob(
        () => api.runScope(data.setId),
        api.estimateStatus,
        (s) => onProgress?.(s),
      );
      onProgress?.(null);
      await onRefresh();
    } catch (e: unknown) {
      onProgress?.(null);
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!data.scope) {
    return (
      <WaitingOn
        title="The scope has not been drafted yet"
        action={
          data.gates.review ? (
            <Button variant="brass" onClick={runScope} disabled={busy}>
              Draft the scope
            </Button>
          ) : undefined
        }
      >
        {data.gates.review
          ? "The register is closed. Drafting the scope reads the confirmed positions back out of it and proposes the scope statement the price will rest on."
          : "The scope waits on the register — it is built from what the register decided, so there is nothing to assemble until those verdicts exist."}
      </WaitingOn>
    );
  }

  const items = state?.items ?? [];
  const blocked = (state?.fallbacks_active ?? 0) > 0;
  const locked = data.gates.scope;

  return (
    <div className="flex min-h-0 flex-1">
      {/* ---------------- pane 1 — scope sources ---------------- */}
      {railOpen && (
        <Rail width={266}>
          <div className="border-b border-cb-border px-3 py-3">
            <SectionLabel>SCOPE SOURCES</SectionLabel>
            <p className="mt-0.5 font-cb-sans text-[10px] text-cb-muted">
              from ingest &amp; the register
            </p>
          </div>

          {GROUPS.map((group) => {
            const rows = (state?.sources ?? []).filter((s) => s.group === group.id);
            return (
              <div key={group.id} className="border-b border-cb-border px-2 py-2">
                <div className="flex items-center gap-2 px-1 pb-1">
                  <span
                    className={cx(
                      "font-cb-mono text-[8.5px] font-semibold tracking-cb-label",
                      group.head,
                    )}
                  >
                    {group.label}
                  </span>
                  <span
                    className={cx(
                      "ml-auto flex-none rounded-cb-chip px-1.5 font-cb-mono text-[9px] font-semibold",
                      group.badge,
                    )}
                  >
                    {rows.length}
                  </span>
                </div>
                {rows.length === 0 ? (
                  <p className="px-1 py-1 font-cb-sans text-[10px] text-cb-faint">None.</p>
                ) : (
                  rows.map((source) => (
                    <div
                      key={source.source_ref}
                      className={cx(
                        "cb-row mb-1 rounded-cb-btn px-2 py-1.5",
                        source.mapped && "bg-cb-panel",
                      )}
                    >
                      <p className="font-cb-sans text-[11px] font-medium leading-[1.35] text-cb-ink-text">
                        {source.label}
                      </p>
                      <div className="mt-1 flex items-center gap-2">
                        <span className="flex-1 truncate font-cb-mono text-[9px] text-cb-faint">
                          {source.meta}
                        </span>
                        {source.mapped ? (
                          <span className="flex-none rounded-cb-chip border border-cb-border-strong px-1.5 py-0.5 font-cb-mono text-[8.5px] tracking-cb-chip text-cb-faint">
                            IN SCOPE
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => map(source)}
                            disabled={busy || locked}
                            className="cb-press flex-none rounded-cb-chip bg-cb-brass px-2 py-0.5 font-cb-sans text-[9.5px] font-semibold text-cb-on-brass disabled:opacity-40"
                          >
                            + Map to scope
                          </button>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            );
          })}

          <p className="mt-auto px-3 py-3 font-cb-sans text-[10px] leading-[1.5] text-cb-faint">
            A source stays here until you map it — nothing walks into the scope on its own.
          </p>
        </Rail>
      )}

      {/* ---------------- pane 2 — the scope workspace ---------------- */}
      <section className="flex min-w-0 flex-1 flex-col bg-cb-desk/40">
        {/* the gate banner */}
        <div className="flex flex-none flex-wrap items-center gap-3 border-b border-cb-border bg-cb-selected px-[18px] py-3">
          <div className="min-w-0 flex-1">
            <SectionLabel className={locked ? "text-cb-ok-dark" : undefined}>
              GATE 3 · SCOPE OF RECORD{locked ? " · LOCKED" : ""}
            </SectionLabel>
            <div className="font-cb-serif text-[15px] font-semibold text-cb-ink-text">
              {state?.baseline ?? 0} baseline item
              {(state?.baseline ?? 0) === 1 ? "" : "s"} established
              {(state?.fallbacks_active ?? 0) > 0 && (
                <>
                  {" · "}
                  {state?.fallbacks_active} pre-filled AI fallback
                  {state?.fallbacks_active === 1 ? "" : "s"} active
                </>
              )}
            </div>
          </div>

          {locked ? (
            <Chip className="flex-none bg-cb-ok-tint text-cb-ok-dark">
              ✓ SCOPE LOCKED · PRICING UNLOCKED
            </Chip>
          ) : (
            <div className="flex flex-none items-center gap-3">
              {blocked && (
                <p className="max-w-[260px] text-right font-cb-sans text-[10px] leading-[1.4] text-cb-brass-text">
                  {state?.fallbacks_active} fallback
                  {state?.fallbacks_active === 1 ? "" : "s"} still pre-filled. Accept or rewrite
                  each one — a price cannot rest on a suggestion nobody agreed to.
                </p>
              )}
              <Button
                variant="brass"
                onClick={approve}
                disabled={busy}
                disabledReason={
                  blocked
                    ? `${state?.fallbacks_active} pre-filled fallback(s) have not been accepted.`
                    : undefined
                }
              >
                Approve scope &amp; unlock pricing
              </Button>
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto py-4">
          {items.length === 0 && (
            <p className="mx-[18px] rounded-cb-card border border-dashed border-cb-border-strong bg-white p-5 text-center font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
              The scope is empty. Map a confirmed departure, an open query or an applied addendum
              from the left to start building it — every line you map is written into the offer
              letter word for word.
            </p>
          )}

          {SECTIONS.map((section) => {
            const rows = items.filter((i) => i.section === section.id);
            if (!rows.length) return null;
            return (
              <div key={section.id} className="mb-4">
                <SectionLabel className="mb-2 px-[18px]">{section.label}</SectionLabel>
                {rows.map((item) => (
                  <ScopeCard
                    key={item.item_id}
                    item={item}
                    justMapped={justMapped.has(item.item_id)}
                    editing={editing === item.item_id}
                    draft={draft}
                    busy={busy}
                    locked={locked}
                    onEdit={() => {
                      setEditing(item.item_id);
                      setDraft(item.text);
                    }}
                    onCustom={() => {
                      setEditing(item.item_id);
                      setDraft("");
                    }}
                    onDraft={setDraft}
                    onCancel={() => setEditing(null)}
                    onSave={(accept) => save(item, accept)}
                    onAccept={() =>
                      run(() =>
                        api.updateScopeItem(data.setId, item.item_id, { accept: true }),
                      )
                    }
                    onConvert={() =>
                      run(() =>
                        api.updateScopeItem(data.setId, item.item_id, { convert_to_user: true }),
                      )
                    }
                    onUnmap={() => run(() => api.unmapScope(data.setId, item.item_id))}
                  />
                ))}
              </div>
            );
          })}

          {items.length > 0 && (
            <p className="mx-[18px] mt-2 font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
              Every line here is written into the offer letter word for word — AI lines are marked
              so you can see whose words they are.
            </p>
          )}
        </div>

        <div className="flex-none border-t border-cb-border bg-cb-surface px-[18px] py-2.5">
          <p className="font-cb-sans text-[10px] leading-[1.45] text-cb-muted">
            Approving the gate freezes these words as the basis of the price. Reopening the scope
            drops the estimate built on it.
          </p>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// One scope line
// ---------------------------------------------------------------------------
function ScopeCard({
  item,
  justMapped,
  editing,
  draft,
  busy,
  locked,
  onEdit,
  onCustom,
  onDraft,
  onCancel,
  onSave,
  onAccept,
  onConvert,
  onUnmap,
}: {
  item: ScopeItem;
  justMapped: boolean;
  editing: boolean;
  draft: string;
  busy: boolean;
  locked: boolean;
  onEdit: () => void;
  onCustom: () => void;
  onDraft: (t: string) => void;
  onCancel: () => void;
  onSave: (accept?: boolean) => void;
  onAccept: () => void;
  onConvert: () => void;
  onUnmap: () => void;
}) {
  const fallback = item.is_fallback;
  const priced = !fallback || item.accepted;

  return (
    <div
      className={cx(
        "mx-[18px] mb-2.5 rounded-cb-card border p-[12px_13px]",
        fallback ? "border-cb-brass-line bg-cb-warm" : "border-cb-border bg-white",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-cb-sans text-[12.5px] font-semibold text-cb-ink-text">
          {item.title || "Untitled"}
        </span>
        <AuthorshipBadge badge={item.badge} />
        {justMapped && <Chip className="bg-cb-ok-tint text-cb-ok-dark">JUST MAPPED</Chip>}
        {fallback && !item.accepted && (
          <Chip className="bg-cb-brass-tint text-cb-brass-text">PENDING CLIENT REPLY</Chip>
        )}
      </div>

      {editing ? (
        <div className="mt-2">
          <textarea
            value={draft}
            onChange={(e) => onDraft(e.target.value)}
            rows={4}
            autoFocus
            className={cx(
              "min-h-[66px] w-full resize-y rounded-cb-btn border border-cb-brass p-[9px_10px] font-cb-serif text-[12px] leading-[1.6] text-cb-ink-text",
              fallback ? "bg-white" : "bg-cb-warm",
            )}
          />
          <div className="mt-2 flex items-center gap-2">
            <Button variant="dark" onClick={() => onSave(fallback ? true : undefined)} disabled={busy}>
              Save
            </Button>
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <span className="font-cb-sans text-[10px] text-cb-muted">
              Saving stamps this line <strong className="font-semibold">USER</strong> — you edited
              it, you own it.
            </span>
          </div>
        </div>
      ) : (
        <>
          {/* The rule under the text IS the state. Brass = a suggestion, not yours yet.
              Green = priced on this. An unreviewed suggestion never gets the green rule. */}
          <div
            className={cx(
              "mt-2 border-l-2 pl-[9px]",
              fallback ? (priced ? "border-cb-ok" : "border-cb-brass") : "border-transparent pl-0",
            )}
          >
            {fallback && (
              <SectionLabel className={priced ? "text-cb-ok-dark" : "text-cb-brass-text"}>
                {priced
                  ? "PRICED ON THIS ASSUMPTION"
                  : "PRE-FILLED FALLBACK · not yours until you accept it"}
              </SectionLabel>
            )}
            <p className="mt-1 font-cb-serif text-[12px] leading-[1.6] text-cb-body">
              {item.text || (
                <span className="text-cb-faint">
                  No wording yet — write what the price assumes.
                </span>
              )}
            </p>
          </div>

          {!locked && (
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-dashed border-cb-border pt-2">
              {fallback && !item.accepted ? (
                <>
                  <Button variant="dark" onClick={onAccept} disabled={busy || !item.text.trim()}>
                    Accept AI fallback
                  </Button>
                  <Button variant="outline" onClick={onCustom} disabled={busy}>
                    Write custom assumption
                  </Button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={onEdit}
                    className="cb-press font-cb-sans text-[10.5px] text-cb-brass-text underline underline-offset-2"
                  >
                    Edit prose
                  </button>
                  {item.badge === "ai" && (
                    <button
                      type="button"
                      onClick={onConvert}
                      title="Take ownership of these words without changing them"
                      className="cb-press font-cb-sans text-[10.5px] text-cb-brass-text underline underline-offset-2"
                    >
                      Convert to user
                    </button>
                  )}
                </>
              )}
              <button
                type="button"
                onClick={onUnmap}
                disabled={busy}
                title="Return this to the sources rail"
                className="cb-press ml-auto font-cb-sans text-[10px] text-cb-muted underline underline-offset-2"
              >
                Remove from scope
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** `AI` and `USER` are visually distinct on purpose: a model's suggestion and a person's
 *  decision must never be mistakable for one another on a page that becomes a contract. */
function AuthorshipBadge({ badge }: { badge: "ai" | "user" }) {
  return (
    <span
      title={
        badge === "ai"
          ? "Drafted by the model. You can edit it or take ownership of it."
          : "Your words. You wrote or edited this line."
      }
      className={cx(
        "inline-flex flex-none items-center rounded-cb-chip border px-1.5 py-0.5 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip",
        badge === "ai"
          ? "border-cb-disabled bg-cb-info text-cb-navy"
          : "border-cb-brass-line bg-cb-brass-tint text-cb-brass-text",
      )}
    >
      {badge.toUpperCase()}
    </span>
  );
}

export { money };
