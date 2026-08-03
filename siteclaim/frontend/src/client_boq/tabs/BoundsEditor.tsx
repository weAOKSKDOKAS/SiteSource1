// The manifest's page-bound editor — the human half of gate 1.
//
// The backend has accepted an edited `parts` list since the gate was built (`ManifestApproval.parts`
// replaces the draft, is validated against the real page count, and has its measured text-layer
// facts re-stamped). Nothing was ever wired to it, so the only way to correct a boundary was to
// POST the manifest by hand — which is exactly how a 26-page bill that ingested as one 1-page part
// got repaired, over PowerShell, at night.
//
// Two deliberate shapes here:
//
// * Saving and approving are SEPARATE. "Save bounds" posts `approved: false`, so the corrected
//   manifest comes back through the same coverage maths the gate refuses on and the person reads
//   the real figure before locking anything. An editor that saved and approved in one click would
//   be asking someone to approve a number they have not seen.
// * The coverage bar is recomputed HERE, live, from the same rules as the server's `coverage()`.
//   It is a preview, never the verdict: the server validates again on save and its errors are what
//   the screen reports.

import { useMemo, useState } from "react";

import type { Manifest, PartSpec } from "../types";
import { Button, Chip, Modal, SectionLabel, cx } from "../ui";

/** The page spans no part claims, and the ones claimed twice — the same head/interior/tail walk
 *  `pdfops.coverage` does, so the preview and the gate cannot disagree about what is wrong. */
function breaks(parts: PartSpec[], pages: number) {
  const ordered = [...parts].sort((a, b) => a.start - b.start);
  const gaps: { start: number; end: number }[] = [];
  const overlaps: { start: number; end: number }[] = [];
  if (ordered.length && pages > 0 && ordered[0].start > 1) {
    gaps.push({ start: 1, end: Math.min(ordered[0].start - 1, pages) });
  }
  for (let i = 0; i + 1 < ordered.length; i++) {
    const a = ordered[i];
    const b = ordered[i + 1];
    if (b.start > a.end + 1) gaps.push({ start: a.end + 1, end: b.start - 1 });
    else if (b.start <= a.end) overlaps.push({ start: b.start, end: Math.min(a.end, b.end) });
  }
  // The furthest end, not the last to begin: the list is ordered by START, so a part that opens
  // earlier can still close later.
  const lastEnd = ordered.reduce((m, p) => Math.max(m, p.end), 0);
  if (ordered.length && pages > 0 && lastEnd < pages) gaps.push({ start: lastEnd + 1, end: pages });

  const claimed = new Set<number>();
  for (const p of ordered) {
    for (let n = Math.max(1, p.start); n <= Math.min(p.end, pages); n++) claimed.add(n);
  }
  return { gaps, overlaps, coveredPages: claimed.size };
}

/** Mirrors `pdfops.MIN_COVERAGE_SHARE`. Duplicated rather than fetched because it is a preview:
 *  the server's own check is what actually refuses, and this only decides whether to warn early. */
const MIN_COVERAGE_SHARE = 0.6;

export function BoundsEditor({
  manifest,
  open,
  onClose,
  onSave,
}: {
  manifest: Manifest;
  open: boolean;
  onClose: () => void;
  onSave: (parts: PartSpec[]) => Promise<void>;
}) {
  const [draft, setDraft] = useState<PartSpec[]>(() => manifest.parts.map((p) => ({ ...p })));
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState("");

  // Only the parts cut out of the binder are measured against its page count; a loose annex
  // uploaded alongside carries its own pagination and is shown but not judged.
  const binder = useMemo(
    () => draft.filter((p) => !p.source_doc || p.source_doc === manifest.source_doc),
    [draft, manifest.source_doc],
  );
  const state = useMemo(() => breaks(binder, manifest.pages), [binder, manifest.pages]);
  const share = manifest.pages > 0 ? state.coveredPages / manifest.pages : 1;
  const tooThin = share < MIN_COVERAGE_SHARE;
  const outOfBounds = binder.filter(
    (p) => p.start < 1 || p.end > manifest.pages || p.end < p.start,
  );

  const set = (index: number, patch: Partial<PartSpec>) =>
    setDraft((cur) => cur.map((p, i) => (i === index ? { ...p, ...patch } : p)));

  const num = (raw: string) => {
    const n = Number.parseInt(raw, 10);
    return Number.isFinite(n) ? n : 0;
  };

  async function save() {
    setBusy(true);
    setFailed("");
    try {
      // Renumbered in page order before it goes, because `part_id` is `NN-abbr` and the server
      // renumbers too — sending them in the order they happen to sit in the list would make the
      // ids jump around for no reason the person did anything to cause.
      const ordered = [...draft].sort((a, b) => a.start - b.start || a.end - b.end);
      await onSave(ordered.map((p, i) => ({ ...p, n: i + 1 })));
      onClose();
    } catch (e: unknown) {
      setFailed(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Edit page bounds" wide>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <SectionLabel>{manifest.source_doc} · {manifest.pages} PAGES</SectionLabel>
          <Chip
            className={cx(
              "ml-auto",
              // Amber is border + text in this palette; it has no fill token and one is not
              // invented here. Red = the server will refuse, amber = it will warn, green = clean.
              tooThin || outOfBounds.length
                ? "bg-cb-bad-tint text-cb-bad-dark"
                : state.gaps.length || state.overlaps.length
                  ? "border border-cb-amber text-cb-amber"
                  : "bg-cb-ok-tint text-cb-ok-dark",
            )}
          >
            {state.coveredPages}/{manifest.pages} PAGES · {state.gaps.length} GAPS ·{" "}
            {state.overlaps.length} OVERLAPS
          </Chip>
        </div>

        <div className="max-h-[46vh] overflow-y-auto rounded-cb-card border border-cb-border">
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-cb-panel">
              <tr className="border-b border-cb-divider">
                {["#", "Title", "First page", "Last page", "Pages", "From"].map((h) => (
                  <th
                    key={h}
                    className="px-2.5 py-1.5 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {draft.map((part, i) => {
                const bad = part.end < part.start || part.start < 1
                  || ((!part.source_doc || part.source_doc === manifest.source_doc)
                      && part.end > manifest.pages);
                return (
                  <tr
                    key={`${part.part_id}-${i}`}
                    className={cx("border-b border-cb-divider last:border-0", bad && "bg-cb-bad-tint")}
                  >
                    <td className="px-2.5 py-1.5 font-cb-mono text-[10px] text-cb-muted">{i + 1}</td>
                    <td className="px-2.5 py-1.5">
                      <input
                        value={part.title}
                        onChange={(e) => set(i, { title: e.target.value })}
                        className="w-full rounded-cb-btn border border-cb-border bg-white px-2 py-1 font-cb-sans text-[11px] text-cb-ink-text"
                      />
                    </td>
                    {(["start", "end"] as const).map((field) => (
                      <td key={field} className="px-2.5 py-1.5">
                        <input
                          type="number"
                          min={1}
                          max={manifest.pages}
                          value={part[field]}
                          onChange={(e) => set(i, { [field]: num(e.target.value) })}
                          className="w-[76px] rounded-cb-btn border border-cb-border bg-white px-2 py-1 font-cb-mono text-[11px] text-cb-ink-text"
                        />
                      </td>
                    ))}
                    <td className="px-2.5 py-1.5 font-cb-mono text-[10px] text-cb-muted">
                      {Math.max(0, part.end - part.start + 1)}
                    </td>
                    <td className="px-2.5 py-1.5 font-cb-sans text-[10px] text-cb-faint">
                      {part.source_doc && part.source_doc !== manifest.source_doc
                        ? part.source_doc
                        : "binder"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {(state.gaps.length > 0 || state.overlaps.length > 0) && (
          <p className="font-cb-sans text-[10.5px] leading-[1.45] text-cb-bad-dark">
            {state.gaps.length > 0 && (
              <>Belonging to no part: {state.gaps.map((g) => `pp. ${g.start}-${g.end}`).join(", ")}. </>
            )}
            {state.overlaps.length > 0 && (
              <>Claimed twice: {state.overlaps.map((o) => `pp. ${o.start}-${o.end}`).join(", ")}.</>
            )}
          </p>
        )}
        {outOfBounds.length > 0 && (
          <p className="font-cb-sans text-[10.5px] text-cb-bad-dark">
            {outOfBounds.length} part(s) fall outside 1-{manifest.pages}, or end before they start.
            The server will refuse these.
          </p>
        )}
        {tooThin && outOfBounds.length === 0 && (
          <p className="font-cb-sans text-[10.5px] text-cb-bad-dark">
            These parts account for {Math.round(share * 100)}% of the document. A split must cover
            at least {Math.round(MIN_COVERAGE_SHARE * 100)}%; the server will refuse this.
          </p>
        )}
        {failed && (
          <p className="font-cb-sans text-[10.5px] text-cb-bad-dark">{failed}</p>
        )}

        <div className="flex items-center gap-3">
          <Button variant="brass" onClick={save} disabled={busy || !draft.length}>
            {busy ? "Saving…" : "Save bounds"}
          </Button>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <span className="font-cb-sans text-[10px] leading-[1.45] text-cb-muted">
            Saving does not approve. The corrected manifest comes back through the same coverage
            check, and you approve it from the gate once you have read the figure.
          </span>
        </div>
      </div>
    </Modal>
  );
}
