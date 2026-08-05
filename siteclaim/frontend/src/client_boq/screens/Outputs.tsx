// Outputs and norms — the rate book's sibling. Rates say what a crew costs an hour; these say how
// many hours the work takes. Both are the company's, not a job's.
//
// There is no "add a norm". A rate id is the company's own code and can be anything; an output only
// means something because the engine reads it, so the book declares the list (boq/outputs.py NORMS)
// and the backend refuses a key it does not know. A number nobody consults, sitting on a screen
// looking authoritative, is worse than no number.

import { useState } from "react";
import { api } from "../api";
import type { OutputRow, OutputsResponse } from "../types";
import { Button, SectionLabel, cx, formatNorm } from "../ui";

export function Outputs({
  outputs,
  onChanged,
  onError,
}: {
  outputs: OutputsResponse | null;
  onChanged: () => void;
  onError: (msg: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);

  if (!outputs) {
    return <div className="p-[18px] font-cb-sans text-[11px] text-cb-muted">Loading the book…</div>;
  }

  const edited = outputs.blocks.flatMap((b) => b.rows).filter((r) => r.source === "you").length;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[760px] p-[18px]">
        <div className="flex items-baseline gap-3">
          <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">
            Outputs and norms
          </h1>
          <span className="font-cb-mono text-[10px] text-cb-muted">
            {outputs.count} norms
            {edited > 0 && ` · ${edited} set by you`}
          </span>
        </div>
        <p className="mt-1 max-w-[620px] font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          What your crews actually achieve. Every tender starts from these and may differ from
          them — where it does, the tender says so and shows both numbers. Editing one changes
          every future estimate; it never rewrites one already run.
        </p>

        {outputs.blocks.map((block) => (
          <section key={block.id} className="mt-5">
            <SectionLabel>{block.title}</SectionLabel>
            <div className="mt-2 rounded-cb-card border border-cb-border bg-cb-page">
              {block.rows.map((row) =>
                editing === row.key ? (
                  <NormEditor
                    key={row.key}
                    row={row}
                    onDone={() => {
                      setEditing(null);
                      onChanged();
                    }}
                    onCancel={() => setEditing(null)}
                    onError={onError}
                  />
                ) : (
                  <NormRow
                    key={row.key}
                    row={row}
                    onEdit={() => setEditing(row.key)}
                  />
                ),
              )}
            </div>
          </section>
        ))}

        <p className="mt-6 max-w-[620px] border-t border-cb-divider pt-3 font-cb-sans text-[9.5px] leading-[1.65] text-cb-faint">
          Nothing here is a fact about a tender. It is what your company knows, and it is the thing
          worth arguing about once rather than every bid.
        </p>
      </div>
    </div>
  );
}

function NormRow({ row, onEdit }: { row: OutputRow; onEdit: () => void }) {
  const moved = row.source === "you" && row.value !== row.default;
  return (
    <div className="cb-row flex items-baseline gap-3 border-b border-cb-divider px-3 py-[7px] last:border-0">
      <div className="min-w-0 flex-1">
        <span className="font-cb-sans text-[11.5px] text-cb-body">{row.label}</span>
        {row.source === "you" && row.updated_by && (
          <span
            className="ml-2 font-cb-mono text-[8px] text-cb-faint"
            title={row.updated_at ?? undefined}
          >
            set · {row.updated_by}
          </span>
        )}
        {row.note && (
          // The `⌞` line. A norm that needs explaining says so here rather than in a tooltip
          // nobody opens — the reasoning is the useful half of the number.
          <div className="mt-[1px] font-cb-sans text-[9.5px] leading-[1.5] text-cb-faint">
            <span className="mr-1 font-cb-mono">⌞</span>
            {row.note}
          </div>
        )}
      </div>
      <span className="w-[80px] flex-none text-right font-cb-mono text-[14px] font-semibold text-cb-ink-text">
        {formatNorm(row.value)}
      </span>
      <span className="w-[54px] flex-none font-cb-mono text-[9.5px] text-cb-faint">{row.unit}</span>
      <button
        type="button"
        onClick={onEdit}
        title={moved ? `Ships at ${formatNorm(row.default)}` : "Edit"}
        className="cb-press flex-none font-cb-sans text-[11px] text-cb-brass-text"
      >
        ✎
      </button>
    </div>
  );
}

function NormEditor({
  row,
  onDone,
  onCancel,
  onError,
}: {
  row: OutputRow;
  onDone: () => void;
  onCancel: () => void;
  onError: (msg: string) => void;
}) {
  const [value, setValue] = useState(String(row.value));
  const [busy, setBusy] = useState(false);
  const numeric = value.trim() !== "" && !Number.isNaN(Number(value));

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      onDone();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-b border-cb-divider bg-cb-warm px-3 py-[9px] last:border-0">
      <div className="flex items-baseline gap-3">
        <span className="min-w-0 flex-1 font-cb-sans text-[11.5px] text-cb-body">{row.label}</span>
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && numeric) void run(() => api.setOutputNorm(row.key, Number(value)));
            if (e.key === "Escape") onCancel();
          }}
          title={numeric ? undefined : "A norm must be a number — a bad one never silently becomes 0."}
          className={cx(
            "w-[80px] flex-none rounded-cb-chip border bg-cb-page px-2 py-1 text-right font-cb-mono text-[13px] text-cb-ink-text",
            numeric ? "border-cb-border" : "border-[1.5px] border-cb-bad",
          )}
        />
        <span className="w-[54px] flex-none font-cb-mono text-[9.5px] text-cb-faint">{row.unit}</span>
      </div>
      <div className="mt-2 flex items-center gap-3">
        <Button
          variant="brass"
          disabled={busy || !numeric}
          onClick={() => void run(() => api.setOutputNorm(row.key, Number(value)))}
          className="px-3 py-1 text-[10.5px]"
        >
          Save
        </Button>
        <button
          type="button"
          onClick={onCancel}
          className="cb-press font-cb-sans text-[10px] text-cb-muted underline underline-offset-2"
        >
          Cancel
        </button>
        {row.source === "you" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => api.resetOutputNorm(row.key))}
            title="Forgets your value. A norm cannot be removed — the engine reads it whatever happens."
            className="cb-press ml-auto font-cb-sans text-[10px] text-cb-muted underline underline-offset-2"
          >
            Back to {formatNorm(row.default)}
          </button>
        )}
      </div>
    </div>
  );
}
