// Pricing & rates — the book /estimate/run prices from, finally editable. Mono for anything
// compared digit by digit; editing stamps who and disowns the seed; archiving states its
// consequence (missing_rate on re-run) before it happens, never after.

import { useMemo, useState } from "react";
import { api } from "../api";
import type { RateRowFull, RatesResponse } from "../types";
import { Button, SectionLabel, cx } from "../ui";

export function Rates({
  rates,
  onChanged,
  onError,
}: {
  rates: RatesResponse | null;
  onChanged: () => void;
  onError: (msg: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  const grouped = useMemo(() => {
    const rows = (rates?.rows ?? []).filter((r) => showArchived || !r.archived);
    const byCat = new Map<string, RateRowFull[]>();
    for (const row of rows) {
      const key = row.category || "other";
      const list = byCat.get(key) ?? [];
      list.push(row);
      byCat.set(key, list);
    }
    const order = rates?.categories ?? [];
    return [...byCat.entries()].sort(
      (a, b) => (order.indexOf(a[0]) + 99) - (order.indexOf(b[0]) + 99) || a[0].localeCompare(b[0]),
    );
  }, [rates, showArchived]);

  if (!rates) {
    return <div className="p-[18px] font-cb-sans text-[11px] text-cb-muted">Loading the book…</div>;
  }

  const archivedCount = rates.rows.filter((r) => r.archived).length;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[900px] p-[18px]">
        <div className="flex items-baseline gap-3">
          <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">
            Pricing &amp; rates
          </h1>
          <span className="font-cb-mono text-[10px] text-cb-muted">{rates.count} live rates</span>
          {archivedCount > 0 && (
            <button
              type="button"
              onClick={() => setShowArchived((v) => !v)}
              className="cb-press font-cb-sans text-[10px] text-cb-muted underline underline-offset-2"
            >
              {showArchived ? "hide" : "show"} {archivedCount} archived
            </button>
          )}
        </div>
        <p className="mt-1 max-w-[640px] font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          The rate book every estimate prices from. A schedule line names a rate by its id; a
          rate that is archived — or was never here — prices at 0 with a{" "}
          <span className="font-cb-mono text-[10px]">missing_rate</span> flag rather than a
          number nobody stands behind. Edits stamp your name and apply to the next run.
        </p>

        {rates.seed_duplicates.length > 0 && (
          <div className="mt-3 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2 font-cb-sans text-[10.5px] text-cb-brass-text">
            The seed CSV repeated {rates.seed_duplicates.join(", ")} — first occurrence won, the
            rest were dropped at seed time. Worth cleaning at the source.
          </div>
        )}

        {grouped.map(([category, rows]) => (
          <section key={category} className="mt-5">
            <SectionLabel>{category} · {rows.filter((r) => !r.archived).length}</SectionLabel>
            <div className="mt-2 overflow-x-auto rounded-cb-card border border-cb-border bg-cb-page">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-cb-border">
                    {["RATE ID", "DESCRIPTION", "UNIT", "RATE", "", ""].map((h, i) => (
                      <th key={i} className="px-3 py-2 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) =>
                    editing === row.rate_id ? (
                      <RateEditorRow
                        key={row.rate_id}
                        row={row}
                        onDone={() => {
                          setEditing(null);
                          onChanged();
                        }}
                        onCancel={() => setEditing(null)}
                        onError={onError}
                      />
                    ) : (
                      <tr key={row.rate_id} className={cx("cb-row border-b border-cb-divider last:border-0", row.archived && "opacity-50")}>
                        <td className="px-3 py-1.5 font-cb-mono text-[10px] font-semibold text-cb-ink-text">{row.rate_id}</td>
                        <td className="px-3 py-1.5">
                          <span className="font-cb-sans text-[11px] text-cb-body">{row.description}</span>
                          {row.source === "user" && row.updated_by && (
                            <span className="ml-2 font-cb-mono text-[8px] text-cb-faint" title={row.updated_at ?? undefined}>
                              edited · {row.updated_by}
                            </span>
                          )}
                          {row.archived && (
                            <span className="ml-2 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-bad-dark">
                              ARCHIVED — PRICES AS MISSING
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-1.5 font-cb-mono text-[10px] text-cb-muted">{row.unit}</td>
                        <td className="px-3 py-1.5 text-right font-cb-mono text-[11px] font-semibold text-cb-ink-text">
                          {row.rate.toLocaleString("en-US")}
                          {row.currency && <span className="ml-1 text-[8.5px] font-medium text-cb-faint">{row.currency}</span>}
                        </td>
                        <td className="px-2 py-1.5">
                          {!row.archived && (
                            <button type="button" onClick={() => setEditing(row.rate_id)} className="cb-press font-cb-sans text-[10px] font-medium text-cb-brass-text underline underline-offset-2">
                              Edit
                            </button>
                          )}
                        </td>
                        <td className="px-2 py-1.5">
                          {!row.archived && (
                            <button
                              type="button"
                              title="Archives, never deletes — schedule lines that reference it will flag missing_rate."
                              onClick={async () => {
                                try {
                                  await api.archiveRate(row.rate_id);
                                  onChanged();
                                } catch (e) {
                                  onError(e instanceof Error ? e.message : String(e));
                                }
                              }}
                              className="cb-press font-cb-sans text-[10px] font-medium text-cb-muted underline underline-offset-2"
                            >
                              Archive
                            </button>
                          )}
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
          </section>
        ))}

        {adding ? (
          <div className="mt-4">
            <AddRateCard
              categories={rates.categories}
              onDone={() => {
                setAdding(false);
                onChanged();
              }}
              onCancel={() => setAdding(false)}
              onError={onError}
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="cb-press mt-4 rounded-cb-btn border border-dashed border-cb-border-strong px-3 py-1.5 font-cb-sans text-[10.5px] font-medium text-cb-muted"
          >
            + Add a rate
          </button>
        )}
      </div>
    </div>
  );
}

function RateEditorRow({
  row,
  onDone,
  onCancel,
  onError,
}: {
  row: RateRowFull;
  onDone: () => void;
  onCancel: () => void;
  onError: (msg: string) => void;
}) {
  const [description, setDescription] = useState(row.description);
  const [unit, setUnit] = useState(row.unit);
  const [rate, setRate] = useState(String(row.rate));
  const [busy, setBusy] = useState(false);
  const numeric = !Number.isNaN(Number(rate)) && rate.trim() !== "";

  const save = async () => {
    setBusy(true);
    try {
      await api.updateRate(row.rate_id, { description, unit, rate: Number(rate) });
      onDone();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const cell = "rounded-cb-chip border border-cb-border bg-cb-warm px-2 py-1 font-cb-sans text-[11px] text-cb-ink-text";
  return (
    <tr className="border-b border-cb-divider bg-cb-warm last:border-0">
      <td className="px-3 py-2 font-cb-mono text-[10px] font-semibold text-cb-ink-text">{row.rate_id}</td>
      <td className="px-3 py-2">
        <input value={description} onChange={(e) => setDescription(e.target.value)} className={cx(cell, "w-full")} />
      </td>
      <td className="px-3 py-2">
        <input value={unit} onChange={(e) => setUnit(e.target.value)} className={cx(cell, "w-[64px] font-cb-mono text-[10px]")} />
      </td>
      <td className="px-3 py-2 text-right">
        <input
          value={rate}
          onChange={(e) => setRate(e.target.value)}
          className={cx(cell, "w-[92px] text-right font-cb-mono text-[11px]", !numeric && "border-cb-bad")}
          title={numeric ? undefined : "A rate must be a number — a bad rate never silently becomes 0."}
        />
      </td>
      <td className="px-2 py-2">
        <button type="button" onClick={() => void save()} disabled={busy || !numeric} className="cb-press font-cb-sans text-[10px] font-semibold text-cb-brass-text underline underline-offset-2 disabled:text-cb-disabled">
          Save
        </button>
      </td>
      <td className="px-2 py-2">
        <button type="button" onClick={onCancel} className="cb-press font-cb-sans text-[10px] text-cb-muted underline underline-offset-2">
          Cancel
        </button>
      </td>
    </tr>
  );
}

function AddRateCard({
  categories,
  onDone,
  onCancel,
  onError,
}: {
  categories: string[];
  onDone: () => void;
  onCancel: () => void;
  onError: (msg: string) => void;
}) {
  const [rateId, setRateId] = useState("");
  const [category, setCategory] = useState(categories[0] ?? "labour");
  const [description, setDescription] = useState("");
  const [unit, setUnit] = useState("");
  const [rate, setRate] = useState("");
  const [busy, setBusy] = useState(false);
  const numeric = !Number.isNaN(Number(rate)) && rate.trim() !== "";

  const save = async () => {
    setBusy(true);
    try {
      await api.addRate({
        rate_id: rateId.trim().toUpperCase(),
        category,
        description,
        unit,
        rate: Number(rate),
        currency: "HKD",
      });
      onDone();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const cell = "rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[11.5px] text-cb-ink-text placeholder:text-cb-faint";
  return (
    <div className="rounded-cb-card border border-cb-brass-line bg-cb-warm p-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <input value={rateId} onChange={(e) => setRateId(e.target.value)} placeholder="RATE-ID" className={cx(cell, "w-[120px] font-cb-mono uppercase")} />
        <select value={category} onChange={(e) => setCategory(e.target.value)} className={cx(cell, "w-[130px]")}>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" className={cx(cell, "min-w-[200px] flex-1")} />
        <input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="unit" className={cx(cell, "w-[70px] font-cb-mono")} />
        <input value={rate} onChange={(e) => setRate(e.target.value)} placeholder="rate" className={cx(cell, "w-[92px] text-right font-cb-mono")} />
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button variant="brass" onClick={() => void save()} disabled={busy || !rateId.trim() || !numeric}>
          Add to the book
        </Button>
        <button type="button" onClick={onCancel} className="cb-press font-cb-sans text-[10.5px] text-cb-muted underline underline-offset-2">
          Cancel
        </button>
      </div>
    </div>
  );
}
