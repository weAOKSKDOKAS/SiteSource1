// The criteria library — what the register measures a contract against, finally editable.
// Not in the drawn frames (the handoff lists only its entry point), so this screen follows the
// handoff's own rules: serif carries the argument (the acceptable position), mono carries ids,
// editing stamps the editor, and disabling states its consequence before it happens.

import { useMemo, useState } from "react";
import { api } from "../api";
import type { CriteriaResponse, CriterionRow } from "../types";
import { Button, SectionLabel, cx } from "../ui";

const CATEGORY_ORDER = ["TP", "PS", "SQD", "LR", "SGA", "OK"];

export function CriteriaLibrary({
  criteria,
  onChanged,
  onError,
}: {
  criteria: CriteriaResponse | null;
  onChanged: () => void;
  onError: (msg: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null); // category_id

  const grouped = useMemo(() => {
    const rows = criteria?.rows ?? [];
    const byCat = new Map<string, CriterionRow[]>();
    for (const row of rows) {
      const list = byCat.get(row.category_id) ?? [];
      list.push(row);
      byCat.set(row.category_id, list);
    }
    return [...byCat.entries()].sort(
      (a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]),
    );
  }, [criteria]);

  if (!criteria) {
    return (
      <div className="p-[18px] font-cb-sans text-[11px] text-cb-muted">Loading the library…</div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[860px] p-[18px]">
        <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">
          Criteria library
        </h1>
        <p className="mt-1 max-w-[640px] font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          The acceptable-terms library every review is measured against — {criteria.count}{" "}
          criteria across six areas. Edits apply to <em>future</em> reviews; registers already on
          file keep the positions they were measured against. Every change records who made it.
        </p>

        {grouped.map(([categoryId, rows]) => (
          <section key={categoryId} className="mt-6">
            <SectionLabel>
              {rows[0]?.category ?? categoryId} · {rows.filter((r) => r.enabled).length} active
            </SectionLabel>
            <div className="mt-2 flex flex-col gap-2">
              {rows.map((row) =>
                editing === row.id ? (
                  <CriterionEditor
                    key={row.id}
                    row={row}
                    onDone={() => {
                      setEditing(null);
                      onChanged();
                    }}
                    onCancel={() => setEditing(null)}
                    onError={onError}
                  />
                ) : (
                  <CriterionCard
                    key={row.id}
                    row={row}
                    onEdit={() => setEditing(row.id)}
                    onToggle={async () => {
                      try {
                        await api.updateCriterion(row.id, { enabled: !row.enabled });
                        onChanged();
                      } catch (e) {
                        onError(e instanceof Error ? e.message : String(e));
                      }
                    }}
                  />
                ),
              )}
              {adding === categoryId ? (
                <CriterionEditor
                  categoryId={categoryId}
                  onDone={() => {
                    setAdding(null);
                    onChanged();
                  }}
                  onCancel={() => setAdding(null)}
                  onError={onError}
                />
              ) : (
                <button
                  type="button"
                  onClick={() => setAdding(categoryId)}
                  className="cb-press self-start rounded-cb-btn border border-dashed border-cb-border-strong px-3 py-1.5 font-cb-sans text-[10.5px] font-medium text-cb-muted"
                >
                  + Add a criterion to {rows[0]?.category ?? categoryId}
                </button>
              )}
            </div>
          </section>
        ))}

        {/* Threshold rules — read-only, and the reason is stated. */}
        <section className="mt-8 border-t border-cb-border pt-4">
          <SectionLabel>Deterministic threshold checks · read-only</SectionLabel>
          <p className="mt-1 max-w-[640px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            These {criteria.thresholds.length} rules are wired into the rules engine — the code
            extracts the named field and applies the rule as written. Text you could edit here
            but code would not obey would be a lie on the screen, so they change with the code,
            not with the library.
          </p>
          <div className="mt-2 overflow-x-auto rounded-cb-card border border-cb-border bg-cb-page">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-cb-border">
                  <th className="px-3 py-2 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint">ID</th>
                  <th className="px-3 py-2 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint">RULE (FLAG WHEN TRUE)</th>
                  <th className="px-3 py-2 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint">EXTRACTED FIELD</th>
                </tr>
              </thead>
              <tbody>
                {criteria.thresholds.map((t) => (
                  <tr key={t.id} className="border-b border-cb-divider last:border-0">
                    <td className="px-3 py-1.5 font-cb-mono text-[10px] font-semibold text-cb-navy">{t.id}</td>
                    <td className="px-3 py-1.5 font-cb-sans text-[10.5px] text-cb-body">{t.rule}</td>
                    <td className="px-3 py-1.5 font-cb-mono text-[9.5px] text-cb-muted">{t.extract_field}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}

function CriterionCard({
  row,
  onEdit,
  onToggle,
}: {
  row: CriterionRow;
  onEdit: () => void;
  onToggle: () => void;
}) {
  return (
    <div
      className={cx(
        "cb-row rounded-cb-card border border-cb-border bg-cb-page p-[12px_13px]",
        !row.enabled && "opacity-60",
      )}
    >
      <div className="flex items-baseline gap-2.5">
        <span className="font-cb-mono text-[10.5px] font-semibold text-cb-navy">{row.id}</span>
        <span className="min-w-0 flex-1 truncate font-cb-sans text-[12px] font-semibold text-cb-ink-text">
          {row.clause_area}
        </span>
        {!row.enabled && (
          <span className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">
            DISABLED — NOT CHECKED IN NEW REVIEWS
          </span>
        )}
        {row.updated_by && (
          <span
            className="font-cb-mono text-[8px] text-cb-faint"
            title={row.updated_at ?? undefined}
          >
            edited · {row.updated_by}
          </span>
        )}
        <button type="button" onClick={onEdit} className="cb-press font-cb-sans text-[10px] font-medium text-cb-brass-text underline underline-offset-2">
          Edit
        </button>
        <button type="button" onClick={onToggle} className="cb-press font-cb-sans text-[10px] font-medium text-cb-muted underline underline-offset-2">
          {row.enabled ? "Disable" : "Enable"}
        </button>
      </div>
      {row.is_placeholder ? (
        <p className="mt-1.5 font-cb-sans text-[10.5px] italic text-cb-faint">
          A placeholder — no acceptable position defined yet. Edit it to bring it into the checks.
        </p>
      ) : (
        <div className="mt-1.5 grid grid-cols-[92px_1fr] gap-x-3 gap-y-1">
          <span className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-ok-dark">WE ACCEPT</span>
          <span className="font-cb-serif text-[11.5px] leading-[1.5] text-cb-body">{row.acceptable_position}</span>
          <span className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-bad-dark">RED FLAG</span>
          <span className="font-cb-serif text-[11px] leading-[1.5] text-cb-muted">{row.red_flag}</span>
          {row.why_it_matters && (
            <>
              <span className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">WHY</span>
              <span className="font-cb-sans text-[10.5px] leading-[1.5] text-cb-muted">{row.why_it_matters}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** One editor for both add and edit — which one it is depends on whether `row` exists. */
function CriterionEditor({
  row,
  categoryId,
  onDone,
  onCancel,
  onError,
}: {
  row?: CriterionRow;
  categoryId?: string;
  onDone: () => void;
  onCancel: () => void;
  onError: (msg: string) => void;
}) {
  const [clauseArea, setClauseArea] = useState(row?.clause_area ?? "");
  const [acceptable, setAcceptable] = useState(row?.acceptable_position ?? "");
  const [redFlag, setRedFlag] = useState(row?.red_flag ?? "");
  const [why, setWhy] = useState(row?.why_it_matters ?? "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      if (row) {
        await api.updateCriterion(row.id, {
          clause_area: clauseArea,
          acceptable_position: acceptable,
          red_flag: redFlag,
          why_it_matters: why,
        });
      } else {
        await api.addCriterion({
          category_id: categoryId ?? "",
          clause_area: clauseArea,
          acceptable_position: acceptable,
          red_flag: redFlag,
          why_it_matters: why,
        });
      }
      onDone();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const field =
    "w-full rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-serif text-[11.5px] leading-[1.5] text-cb-ink-text placeholder:font-cb-sans placeholder:text-cb-faint";

  return (
    <div className="rounded-cb-card border border-cb-brass-line bg-cb-warm p-[13px]">
      <div className="flex items-baseline gap-2.5">
        <span className="font-cb-mono text-[10.5px] font-semibold text-cb-navy">
          {row?.id ?? `${categoryId}-next`}
        </span>
        <input
          value={clauseArea}
          onChange={(e) => setClauseArea(e.target.value)}
          placeholder="Clause area (e.g. Security (Retention))"
          className="min-w-0 flex-1 rounded-cb-btn border border-cb-border bg-cb-page px-2.5 py-1 font-cb-sans text-[12px] font-semibold text-cb-ink-text placeholder:font-normal placeholder:text-cb-faint"
        />
      </div>
      <div className="mt-2 grid grid-cols-[92px_1fr] items-start gap-x-3 gap-y-2">
        <span className="pt-1.5 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-ok-dark">WE ACCEPT</span>
        <textarea rows={2} value={acceptable} onChange={(e) => setAcceptable(e.target.value)} className={field}
          placeholder="The position we accept — this is the argument, written to be read." />
        <span className="pt-1.5 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-bad-dark">RED FLAG</span>
        <textarea rows={2} value={redFlag} onChange={(e) => setRedFlag(e.target.value)} className={field}
          placeholder="What in a contract makes this a departure." />
        <span className="pt-1.5 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">WHY</span>
        <textarea rows={2} value={why} onChange={(e) => setWhy(e.target.value)} className={field}
          placeholder="Why it matters commercially (optional)." />
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button variant="brass" onClick={() => void save()} disabled={busy || !clauseArea.trim()}>
          {row ? "Save — stamps your name" : "Add to the library"}
        </Button>
        <button type="button" onClick={onCancel} className="cb-press font-cb-sans text-[10.5px] text-cb-muted underline underline-offset-2">
          Cancel
        </button>
        <span className="ml-auto max-w-[260px] text-right font-cb-sans text-[9.5px] leading-[1.4] text-cb-faint">
          Applies to future reviews. Registers already on file keep the position they were
          measured against.
        </span>
      </div>
    </div>
  );
}
