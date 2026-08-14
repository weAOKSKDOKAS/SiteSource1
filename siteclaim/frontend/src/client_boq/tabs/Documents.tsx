// Frame 01 — Documents. One tender PDF arrives; the app splits it by structure; the reviewer
// confirms the split is right, reads what each part says, and approves the manifest.
//
// Approving freezes the page numbers every later citation depends on, which is why the coverage
// bar and the gaps/overlaps chip are the loudest things on the screen: they are the evidence the
// approval rests on, and a gap has to be *visible* rather than merely reported in a number.

import { useEffect, useMemo, useRef, useState } from "react";
import type { SetData } from "../App";
import { api, runJob } from "../api";
import { BillPicker } from "../BillPicker";
import { Divider, DocTab, Rail, RailFolded, TAB_FOR_JOB, usePanes, usePersisted } from "../chrome";
import { PageView } from "../PageView";
import { BoundsEditor } from "./BoundsEditor";
// `Highlight` is imported explicitly because the DOM lib declares a global of the same name
// (the CSS Custom Highlight API) — without this, TS silently resolves to that one.
import type {
  Highlight,
  JobState,
  PageSpan,
  PartContext,
  PartRow,
  PartSpec,
  StrategyFlag,
} from "../types";
import {
  Button,
  Card,
  Chip,
  Consequence,
  IconButton,
  Pill,
  SectionLabel,
  WaitingOn,
  cx,
} from "../ui";

const CATEGORY_LABEL: Record<string, string> = {
  conditions: "conditions",
  specification: "specification",
  drawings: "drawings",
  boq: "bills of quantities",
  correspondence: "correspondence",
  forms: "forms",
  other: "other",
};

// `why` is the hover sentence — the chip's words are a verdict, and a verdict an estimator
// cannot interrogate is jargon (the walkthrough scored TIER 4 exactly that way).
const TIER_LABEL: Record<number, { text: string; cls: string; why: string }> = {
  1: { text: "TIER 1 · BOOKMARKS VERIFIED",
       cls: "bg-cb-ok-tint text-cb-ok-dark",
       why: "The binder carries its own bookmarks and they matched the pages — the most reliable "
            + "structure a PDF can offer, so the proposed split follows them." },
  2: { text: "TIER 2 · PRINTED CONTENTS, OFFSET VERIFIED",
       cls: "bg-cb-ok-tint text-cb-ok-dark",
       why: "No bookmarks, but a printed contents page was found and its page numbers lined up "
            + "with the document, so the proposed split follows it." },
  3: { text: "TIER 3 · DIVIDERS DETECTED",
       cls: "bg-cb-brass-tint text-cb-brass-text",
       why: "No bookmarks or usable contents page — the split follows divider pages detected in "
            + "the binder. Worth a closer look before approving." },
  4: { text: "TIER 4 · NO STRUCTURE FOUND — SPLIT BY HAND",
       cls: "bg-cb-bad-tint text-cb-bad-dark",
       why: "Nothing in the binder says where one document ends and the next begins — no "
            + "bookmarks, no readable contents, no dividers. The proposal is one single part; "
            + "use Edit page bounds to cut it where you know the boundaries are." },
};

/** How a part was read. A scan that vision managed to read is a different state from one nothing
 *  could read, and the difference decides whether anything downstream may cite it. */
function scanBadge(part: PartRow) {
  if (!part.scanned) return { text: "TEXT", cls: "bg-cb-info-fill text-cb-navy" };
  if (part.readable) return { text: "VISION OCR", cls: "bg-cb-brass-tint text-cb-brass-text" };
  return { text: "NOT READ", cls: "bg-cb-bad text-white" };
}

function segmentColour(part: PartRow, selected: boolean): string {
  if (selected) return "var(--color-cb-brass)";
  if (!part.scanned) return "var(--color-cb-navy)";
  if (part.readable) return "var(--color-cb-amber)";
  return "var(--color-cb-bad)";
}

type Segment =
  | { kind: "part"; spec: PartSpec; pages: number }
  | { kind: "gap"; start: number; end: number; pages: number };

/** The coverage bar in page order, with an explicit segment for every stretch that belongs to
 *  no part. Both lists come from the backend, so this only interleaves them — it does not
 *  recompute where the gaps are, which would risk the bar and the gate disagreeing. */
function segments(parts: PartSpec[], gaps: PageSpan[]): Segment[] {
  const out: Segment[] = [
    ...parts.map((spec) => ({
      kind: "part" as const,
      spec,
      pages: spec.end - spec.start + 1,
      start: spec.start,
    })),
    ...gaps.map((g) => ({
      kind: "gap" as const,
      start: g.start,
      end: g.end,
      pages: g.end - g.start + 1,
    })),
  ].sort((a, b) => a.start - b.start);
  return out;
}

export function DocumentsTab({
  data,
  job,
  railOpen,
  onRefresh,
  onError,
  onProgress,
  onTrack,
  initialTarget,
}: {
  data: SetData;
  /** The run in flight anywhere in this set, from the shell. A tab's own `busy` flag dies
   *  with the component, so a run started here and navigated away from left this tab able to
   *  offer its Run button again — over a job that was still going, which the server then
   *  refused with a 409 the UI had invited. `busy` covers work THIS mount started; `job`
   *  covers work the set is doing at all. */
  job?: JobState | null;
  railOpen: boolean;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
  onProgress?: (job: JobState | null) => void;
  /** Hand long work to the shell so it stays visible after this tab unmounts. */
  onTrack?: <T,>(label: string, run: () => Promise<T>) => Promise<T>;
  /** A deep link from outside the tab — e.g. the desk card's READ FROM COT citation. Opens
   *  that part at that measured page. */
  initialTarget?: { partId: string; page: number } | null;
}) {
  const parts = data.parts?.parts ?? [];
  const manifest = data.manifest;
  const [selected, setSelected] = useState<string | null>(parts[0]?.part_id ?? null);
  const [page, setPage] = useState<number | null>(null);
  const [contexts, setContexts] = useState<Record<string, PartContext>>({});
  const [busy, setBusy] = useState(false);
  // The shell's job, narrowed to work that belongs to THIS tab. `TAB_FOR_JOB` is the one
  // place that translates a workflow name into a tab, so this cannot drift from the chips.
  const jobRunning =
    !!job &&
    (job.status === "queued" || job.status === "running") &&
    TAB_FOR_JOB[job.kind] === "documents";
  // Everything that used to gate on `busy` gates on this instead.
  const running = busy || jobRunning;
  const [reading, setReading] = useState<string | null>(null);
  const [editingCard, setEditingCard] = useState<string | null>(null);
  const [editingBounds, setEditingBounds] = useState(false);
  /** Opt-in, remembered, and off by default. Paired with the shell's STOP: automatic advance
   *  without a way to stop it is worse than clicking. */
  const [chain, setChain] = usePersisted("chainReview", false);
  const [locations, setLocations] = useState<Record<string, LocateResult>>({});
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const panes = usePanes("documents", 244, 560, railOpen);

  /** The shell's tracker when it was supplied, a pass-through otherwise, so this tab still works
   *  if it is ever rendered outside the desk shell. */
  const keep = <T,>(label: string, run: () => Promise<T>) =>
    onTrack ? onTrack(label, run) : run();
  const [sortByPage, setSortByPage] = useState(true);

  // A deep link (the desk card's READ FROM COT) held in a ref, so the first-page effect below
  // can honour its page instead of resetting the freshly selected part to page 1.
  const pendingTarget = useRef<{ partId: string; page: number } | null>(null);

  // Selecting a part shows its first page — never a page from the part before it — UNLESS the
  // selection came from a deep link that names its own measured page.
  useEffect(() => {
    if (!selected) return;
    if (pendingTarget.current?.partId === selected) {
      setPage(pendingTarget.current.page);
      pendingTarget.current = null;
      return;
    }
    const part = parts.find((p) => p.part_id === selected);
    if (part) setPage(parseInt(part.pages.split("-")[0], 10));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  useEffect(() => {
    if (!parts.length) return;
    if (!selected || !parts.some((p) => p.part_id === selected)) setSelected(parts[0].part_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.parts]);

  useEffect(() => {
    if (!initialTarget || !parts.some((p) => p.part_id === initialTarget.partId)) return;
    pendingTarget.current = initialTarget;
    if (selected === initialTarget.partId) {
      // Already on the part — the selection effect will not fire; jump directly.
      setPage(initialTarget.page);
      pendingTarget.current = null;
    } else {
      setSelected(initialTarget.partId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTarget]);

  // The full context card per part — the list payload only carries the summary line.
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      parts
        .filter((p) => !contexts[p.part_id])
        .map((p) => api.part(data.setId, p.part_id).catch(() => null)),
    ).then((loaded) => {
      if (cancelled) return;
      const next: Record<string, PartContext> = {};
      loaded.forEach((d) => d && (next[d.part.part_id] = d.context));
      if (Object.keys(next).length) setContexts((cur) => ({ ...cur, ...next }));
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.parts]);

  const ordered = useMemo(
    () =>
      sortByPage
        ? parts
        : [...parts].sort((a, b) => a.title.localeCompare(b.title)),
    [parts, sortByPage],
  );

  const stats = useMemo(() => {
    const text = parts.filter((p) => !p.scanned).length;
    const vision = parts.filter((p) => p.scanned && p.readable).length;
    const unread = parts.filter((p) => p.scanned && !p.readable).length;
    return { text, vision, unread };
  }, [parts]);

  async function approve() {
    setBusy(true);
    try {
      await api.approveManifest(data.setId);
      await onRefresh();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /** Undo the approval. The gate was one-way, so a boundary noticed after locking meant reopening
   *  the row by hand in SQLite. The approve endpoint has always taken `approved`, so this is the
   *  same single writer moving the same flag the other way — not a second path to the gate. */
  async function reopen() {
    // A new run makes the previous refusal history: clear the shell banner at the START,
    // before the work, so it can never describe a run that has been superseded.
    onError("");
    setBusy(true);
    try {
      await api.approveManifest(data.setId, undefined, false);
      await onRefresh();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /** Save edited page bounds WITHOUT approving. The server validates against the real page count
   *  and refuses a split that does not fit; whatever it says comes straight back to the editor. */
  async function saveBounds(parts: PartSpec[]) {
    await api.approveManifest(data.setId, parts, false);
    await onRefresh();
  }

  async function split() {
    // A new run makes the previous refusal history: clear the shell banner at the START,
    // before the work, so it can never describe a run that has been superseded.
    onError("");
    setBusy(true);
    try {
      // Through runJob, not a bare call: in LIVE this returns `queued` and the work happens on a
      // pool thread. Reading the first response would appear to work offline and do nothing at
      // all with a real key.
      // A TENDER PACK IS EXTRACTED, NOT CUT. `/ingest/split` slices page ranges out of one binder
      // PDF; an archive-planned manifest's "parts" are still zip entries, and unpacking them is
      // `/bridge/archive/extract` — a job on the same pool, reporting through the same strip,
      // stoppable with the same STOP. Both run behind the SAME manifest gate, which is the point:
      // a 232 MB pack passes exactly the gate a single document does.
      const isArchive = data.manifest?.layout === "archive";
      await keep(isArchive ? "Unpacking the tender pack" : "Splitting the binder", async () => {
        const cut = await runJob(
          () => (isArchive ? api.bridge.archiveExtract(data.setId) : api.split(data.setId)),
          api.ingestStatus,
          (s) => onProgress?.(s),
        );
        onProgress?.(null);
        await onRefresh();
        // The ONE hop in this workflow that crosses no human gate. Splitting leaves the parts cut
        // and the manifest gate already passed, which is the whole of what the review needs — so
        // where the person has asked for it, the review starts here instead of after a trip to
        // another tab. Everything downstream of the review DOES cross a gate (the register's
        // verdicts, then the scope, then the bill confirmation, then the routing decision), so
        // there is nothing further to chain: this is not a first step towards auto-running the
        // workflow, it is the only step that can exist.
        if (chain && cut.status !== "cancelled") {
          await runJob(
            () => api.runReview(data.setId, data.name),
            api.reviewStatus,
            (s) => onProgress?.(s),
          );
          onProgress?.(null);
          await onRefresh();
        }
      });
    } catch (e: unknown) {
      onProgress?.(null);
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /** Correct one card. The model's reading is a proposal like everything else it produces; this
   *  is the way to disagree with it, and doing so transfers ownership. */
  async function saveCard(
    partId: string,
    patch: { summary: string; obligations: string[]; commercial_flags: string[] },
  ) {
    setReading(partId);
    try {
      const result = await api.saveContext(data.setId, partId, patch);
      setContexts((cur) => ({ ...cur, [partId]: result.context }));
      setEditingCard(null);
      await onRefresh();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setReading(null);
    }
  }

  /** Prove a quoted claim against the page, and show it. Three outcomes — a quote that is not on
   *  these pages says so rather than quietly scrolling somewhere plausible. */
  async function locateQuote(partId: string, quote: string) {
    setLocations((cur) => ({ ...cur, [quote]: "pending" }));
    try {
      const r = await api.locateQuote(data.setId, partId, quote);
      setLocations((cur) => ({
        ...cur,
        [quote]: { verdict: r.verdict, page: r.page, note: r.note },
      }));
      if (r.verdict === "located" && r.page != null) {
        setSelected(partId);
        setHighlights(r.highlights);
        setPage(r.page);
      } else {
        setHighlights([]);
      }
    } catch (e: unknown) {
      setLocations((cur) => {
        const next = { ...cur };
        delete next[quote];
        return next;
      });
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  /** Read one part again. The retry for a scan vision could not read — and it may honestly
   *  fail again, which is why the outcome is reported rather than assumed. */
  async function reinterpret(partId: string) {
    setReading(partId);
    try {
      const result = await api.reinterpret(data.setId, partId);
      setContexts((cur) => ({ ...cur, [partId]: result.context }));
      // `readable` may have flipped either way, and the parts list carries that badge.
      await onRefresh();
      if (!result.readable) {
        onError(
          `${partId} still could not be read. ${result.context.notes || "Vision returned nothing usable."} Nothing downstream will cite these pages.`,
        );
      }
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setReading(null);
    }
  }

  if (!manifest) {
    return (
      <WaitingOn title="Nothing ingested for this set">
        Upload a tender binder to read its structure and propose a split.
      </WaitingOn>
    );
  }

  const coverage = manifest.coverage_detail;
  const clean = coverage.gaps.length === 0 && coverage.overlaps.length === 0;
  // A folder set has no binder, so page coverage is not a fact about it and the split UI has
  // nothing to describe. The tier chip still carries the reason on hover.
  const isFolder = manifest.layout === "folder";
  const tier = TIER_LABEL[manifest.tier] ?? {
    text: "ORGANISED FOLDER",
    cls: "bg-cb-info text-cb-navy border border-cb-disabled",
    why: "This set arrived as a folder already organised into files — each file became its own "
         + "part, nothing was split, and there was no binder structure to detect.",
  };

  return (
    <div ref={panes.container} className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      {/* ---------------- pane 1 — parts ---------------- */}
      {panes.railOpen ? (
        <Rail width={panes.railWidth} onResize={panes.dragRail}>
          <div className="flex flex-col gap-2 border-b border-cb-border p-3">
            <div className="truncate font-cb-sans text-[12px] font-semibold text-cb-ink-text">
              {manifest.source_doc || "An organised folder"}
            </div>
            <div className="font-cb-mono text-[10px] font-medium text-cb-muted">
              {isFolder
                ? manifest.summary ??
                  `${manifest.file_count ?? manifest.parts.length} files · ${manifest.file_pages ?? 0} pages`
                : `${manifest.pages} pages · one file in, ${manifest.parts.length} parts out`}
            </div>
            <Chip className={tier.cls} title={manifest.tier_reason || tier.why}>
              {tier.text}
            </Chip>
            {isFolder && manifest.auto_approved && (
              // Not a green tick. The gate passed itself because there was nothing to confirm, and
              // saying so is the difference between "approved" and "somebody looked at this".
              <p className="font-cb-sans text-[10px] leading-[1.5] text-cb-faint">
                Nothing was split, so there was no split to approve — this step passed
                automatically and nobody reviewed it.
              </p>
            )}
            <a
              href={api.downloadUrl(data.setId)}
              className={cx(
                "cb-press w-full rounded-cb-btn border border-cb-border-strong bg-white py-1.5 text-center font-cb-sans text-[10.5px] font-medium text-cb-ink-text",
                !parts.length && "pointer-events-none opacity-40",
              )}
            >
              Download parts as ZIP
            </a>
          </div>

          <div className="flex items-center justify-between px-3 py-2">
            <SectionLabel>PARTS · {parts.length}</SectionLabel>
            <button
              type="button"
              onClick={() => setSortByPage((v) => !v)}
              className="cb-press font-cb-mono text-[10px] text-cb-muted"
            >
              ⇅ by {sortByPage ? "page" : "title"} ▾
            </button>
          </div>

          <div className="flex-1">
            {ordered.map((part) => {
              const badge = scanBadge(part);
              const isSelected = part.part_id === selected;
              const unread = part.scanned && !part.readable;
              return (
                <button
                  key={part.part_id}
                  type="button"
                  onClick={() => setSelected(part.part_id)}
                  className={cx(
                    "cb-row flex w-full flex-col gap-1 border-b border-cb-divider px-3 py-[9px] text-left",
                    isSelected && "border-l-[3px] border-l-cb-brass bg-cb-selected",
                    !isSelected && unread && "bg-cb-bad-tint",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={cx(
                        "flex-none font-cb-mono text-[10px] font-semibold",
                        isSelected ? "text-cb-ink-text" : "text-cb-muted",
                      )}
                    >
                      {part.part_id}
                    </span>
                    <Chip className={cx("ml-auto", badge.cls)}>{badge.text}</Chip>
                  </div>
                  <div
                    className={cx(
                      "font-cb-sans text-[11px] font-medium leading-[1.3]",
                      isSelected ? "text-cb-ink-text" : "text-cb-body",
                    )}
                  >
                    {part.title}
                  </div>
                  <div
                    className={cx(
                      "font-cb-mono text-[10px] font-medium",
                      isSelected ? "text-cb-brass-text-light" : "text-cb-faint",
                    )}
                  >
                    pp. {part.pages}
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mt-auto border-t border-dashed border-cb-border-strong px-3 py-3 font-cb-mono text-[10px] leading-[1.7] text-cb-muted">
            <div>read as text · {stats.text}</div>
            <div>read by vision · {stats.vision}</div>
            <div className={stats.unread ? "text-cb-bad-dark" : ""}>not read · {stats.unread}</div>
          </div>
        </Rail>
      ) : (
        <RailFolded
          lines={[
            { value: String(parts.length), label: "PARTS" },
            { value: String(stats.text), label: "TEXT" },
            { value: String(stats.vision), label: "OCR" },
            { value: String(stats.unread), label: "UNREAD" },
          ]}
        />
      )}

      {/* ---------------- pane 2 — the gate + context cards ---------------- */}
      <section
        // Fixed width while the document pane is showing (the divider owns it); fluid once the
        // pane is collapsed, so the cards take the freed space instead of leaving a dead gap.
        style={panes.docCollapsed ? undefined : { width: panes.midWidth }}
        className={cx(
          "flex min-w-0 flex-col bg-cb-surface",
          panes.docCollapsed ? "flex-1" : "flex-none",
        )}
      >
        <div className="flex-none border-b border-cb-border px-4 py-3">
          <div className="flex items-center gap-3">
            <SectionLabel>
              {isFolder
                ? `WHAT ARRIVED · ${manifest.parts.length} PARTS`
                : `SPLIT MANIFEST · ${manifest.parts.length} PARTS · ${coverage.covered} / ${coverage.pages} PAGES COVERED`}
            </SectionLabel>
            {!isFolder && (
            <Chip
              className={cx(
                "ml-auto",
                clean ? "bg-cb-ok-tint text-cb-ok-dark" : "bg-cb-bad-tint text-cb-bad-dark",
              )}
            >
              {coverage.gaps.length} GAPS · {coverage.overlaps.length} OVERLAPS
            </Chip>
            )}
          </div>

          {/* One segment per part, width proportional to its page count, plus an explicit
              empty segment wherever pages belong to no part. A gap has to be *visible*: a
              number saying "1 gap" is easy to skim past on the way to Approve; a hole in the
              bar is not. */}
          {!isFolder && (
          <div className="mt-3 flex h-[11px] gap-[1.5px] overflow-hidden rounded-[3px]">
            {segments(manifest.parts, coverage.gaps).map((seg) =>
              seg.kind === "gap" ? (
                <div
                  key={`gap-${seg.start}`}
                  title={`Pages ${seg.start}-${seg.end} belong to no part`}
                  style={{ flexGrow: seg.pages }}
                  className="h-full border border-dashed border-cb-bad bg-cb-bad-tint"
                />
              ) : (
                <button
                  key={seg.spec.part_id}
                  type="button"
                  title={`${seg.spec.part_id} · ${seg.spec.title} · pp. ${seg.spec.start}-${seg.spec.end}`}
                  onClick={() => setSelected(seg.spec.part_id)}
                  style={{
                    flexGrow: seg.pages,
                    background: (() => {
                      const row = parts.find((p) => p.part_id === seg.spec.part_id);
                      const isSel = seg.spec.part_id === selected;
                      if (row) return segmentColour(row, isSel);
                      return isSel ? "var(--color-cb-brass)" : "var(--color-cb-navy)";
                    })(),
                  }}
                  className="cb-row h-full"
                />
              ),
            )}
          </div>
          )}
          {!isFolder && !clean && (
            <p className="mt-2 font-cb-sans text-[10.5px] leading-[1.45] text-cb-bad-dark">
              {coverage.gaps.length > 0 && (
                <>
                  Belonging to no part:{" "}
                  {coverage.gaps.map((g) => `pp. ${g.start}-${g.end}`).join(", ")}.{" "}
                </>
              )}
              {coverage.overlaps.length > 0 && (
                <>
                  Claimed twice:{" "}
                  {coverage.overlaps
                    .map((o) => `pp. ${o.start}-${o.end} (parts ${o.parts.join(" & ")})`)
                    .join(", ")}
                  .
                </>
              )}
            </p>
          )}

          <div className="mt-3 flex items-center gap-3">
            {manifest.approved ? (
              <>
                <Chip
                  className={
                    manifest.auto_approved
                      ? "bg-cb-info-fill text-cb-navy"
                      : "bg-cb-ok-tint text-cb-ok-dark"
                  }
                >
                  {manifest.auto_approved ? "NOTHING TO APPROVE" : "✓ MANIFEST APPROVED"}
                </Chip>
                <Button variant="outline" onClick={split} disabled={running}>
                  {/* A pack is unpacked, not sliced. Saying "split into parts" about a zip is the
                      kind of wrong word that makes an operator hesitate over the one button they
                      need. */}
                  {manifest.layout === "archive"
                    ? parts.length
                      ? "Unpack again"
                      : "Unpack the tender pack"
                    : parts.length
                      ? "Re-split from this manifest"
                      : "Split into parts"}
                </Button>
                <Button variant="outline" onClick={reopen} disabled={running}>
                  Reopen
                </Button>
                <label className="flex flex-none cursor-pointer items-center gap-1.5 font-cb-sans text-[10.5px] text-cb-body">
                  <input
                    type="checkbox"
                    checked={chain}
                    onChange={(e) => setChain(e.target.checked)}
                    className="accent-cb-brass"
                  />
                  then run the review
                </label>
                <Consequence>
                  Re-splitting costs no model calls — the cut is deterministic. The interpreted
                  cards are rewritten. Reopening lets you correct a boundary; nothing already cut
                  is destroyed.
                </Consequence>
              </>
            ) : (
              <>
                <Button variant="brass" onClick={approve} disabled={busy} className="px-[22px]">
                  Approve
                </Button>
                <Button variant="outline" onClick={() => setEditingBounds(true)} disabled={busy}>
                  Edit page bounds
                </Button>
                <Consequence>
                  Locking freezes the parts. Every later step cites these page numbers. Approving
                  is reversible — Reopen sits here afterwards to correct a boundary.
                </Consequence>
              </>
            )}
          </div>
          {editingBounds && (
            <BoundsEditor
              manifest={manifest}
              open={editingBounds}
              onClose={() => setEditingBounds(false)}
              onSave={saveBounds}
            />
          )}

          {/* What arrived and is NOT a part. A file may be un-read; it may not be un-mentioned —
              before this, a workbook was written to disk and then absent from every screen. */}
          {/* The bills are the one thing here you can ACT on, so they get the real control rather
              than a read-only row. Before this they were listed and unclickable while the app told
              you to go and pick one somewhere that had no picker either. */}
          {isFolder && (manifest.bills?.length ?? 0) > 0 && (
            <div className="mt-3">
              <BillPicker setId={data.setId} onImported={onRefresh} onError={onError} />
            </div>
          )}

          {isFolder && (manifest.held?.length ?? 0) > 0 && (
            <div className="mt-3 rounded-cb-card border border-cb-border bg-cb-page px-3 py-2">
              {manifest.held?.map((file) => (
                <div key={file.relative_path} className="flex items-baseline gap-2">
                  <Chip className="bg-cb-panel text-cb-faint">HELD</Chip>
                  <span
                    title={file.note}
                    className="min-w-0 flex-1 truncate font-cb-mono text-[10px] text-cb-muted"
                  >
                    {file.relative_path}
                  </span>
                </div>
              ))}
              <p className="mt-1.5 font-cb-sans text-[10px] leading-[1.5] text-cb-faint">
                Held files are stored and can be opened, but nothing in the app reads them.
              </p>
            </div>
          )}
          {isFolder &&
            manifest.problems?.map((problem) => (
              <p
                key={problem}
                className="mt-2 font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text"
              >
                {problem}
              </p>
            ))}
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-[9px] overflow-y-auto p-4">
          {!parts.length ? (
            <div className="rounded-cb-card border border-dashed border-cb-border-strong bg-white p-5 text-center font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
              {manifest.approved
                ? "The manifest is approved but nothing has been cut yet. Split it to get one PDF and one context card per part."
                : "Approve the manifest to cut the binder into parts. Nothing is cut until you do."}
            </div>
          ) : (
            ordered.map((part) => (
              <ContextCard
                key={part.part_id}
                setId={data.setId}
                allParts={parts}
                part={part}
                context={contexts[part.part_id]}
                selected={part.part_id === selected}
                onSelect={() => setSelected(part.part_id)}
                onReinterpret={() => reinterpret(part.part_id)}
                onRevised={() => void onRefresh()}
                busy={reading === part.part_id}
                editing={editingCard === part.part_id}
                onEdit={() => setEditingCard(part.part_id)}
                onCancelEdit={() => setEditingCard(null)}
                onSave={(patch) => saveCard(part.part_id, patch)}
                locations={locations}
                onLocate={(quote) => locateQuote(part.part_id, quote)}
              />
            ))
          )}
        </div>
      </section>

      {/* ---------------- pane 3 — the source page ---------------- */}
      {panes.docCollapsed ? (
        <DocTab onOpen={panes.openDoc} label="DOCUMENT" />
      ) : (
        <>
          <Divider onDrag={panes.dragMiddle} />
          <PageView
            setId={data.setId}
            parts={parts}
            partId={selected}
            page={page}
            highlights={highlights}
            onPartChange={(id) => {
              setSelected(id);
              setHighlights([]); // a highlight belongs to the part it was measured in
            }}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// One part's interpreted card
// ---------------------------------------------------------------------------
/** "pending" while a locate is in flight; otherwise the verdict, or undefined if never asked. */
export type LocateResult =
  | "pending"
  | { verdict: "located" | "unverifiable" | "not_located"; page: number | null; note: string };

/** The unread card's way out — the flow its own copy always promised. Upload a readable copy,
 *  see which held part the server proposes it supersedes ("wrong? change the mapping before
 *  approving — the page numbers everything cites depend on it"), then APPROVE as a distinct
 *  act. Nothing commits until then; each approved file becomes a NEW revision (Rev 0 survives
 *  Rev 1), and everything the revision re-opened is rendered loudly, never summarised away. */
function UploadReadableCopy({
  setId,
  partId,
  allParts,
  onRevised,
}: {
  setId: string;
  partId: string;
  allParts: PartRow[];
  onRevised: () => void;
}) {
  const [proposal, setProposal] = useState<Awaited<ReturnType<typeof api.ingestDocument>> | null>(null);
  const [mappings, setMappings] = useState<{ filename: string; part_id: string }[]>([]);
  const [applied, setApplied] = useState<Awaited<ReturnType<typeof api.approveChanges>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);

  const propose = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setProblem("");
    try {
      const reply = await api.ingestDocument(setId, Array.from(files), "correction");
      setProposal(reply);
      // The server's proposal, with any file it could not place defaulted to THIS part — the
      // person clicked upload on this card, which is a statement of intent the server lacked.
      const proposed = new Map(reply.mappings.map((m) => [m.filename, m.part_id]));
      setMappings([
        ...reply.mappings,
        ...reply.unmatched
          .filter((f) => !proposed.has(f))
          .map((filename) => ({ filename, part_id: partId })),
      ]);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    if (!proposal) return;
    setBusy(true);
    setProblem("");
    try {
      const reply = await api.approveChanges(setId, proposal.doc_id, mappings);
      setApplied(reply);
      setProposal(null);
      onRevised();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span onClick={(e) => e.stopPropagation()} className="flex flex-wrap items-center gap-2">
      <input
        ref={fileInput}
        type="file"
        accept="application/pdf"
        multiple
        className="hidden"
        onChange={(e) => void propose(e.target.files)}
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => fileInput.current?.click()}
        className="cb-press font-cb-sans text-[10.5px] font-medium text-cb-brass-text underline underline-offset-2"
      >
        {busy ? "Working…" : "Upload a readable copy"}
      </button>

      {proposal && (
        <span className="basis-full rounded-cb-chip border border-cb-brass-line bg-cb-brass-tint p-2">
          <span className="block font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-brass-text">
            PROPOSED MAPPING — NOTHING IS COMMITTED YET
          </span>
          {mappings.map((m, i) => (
            <span key={m.filename} className="mt-1 flex items-center gap-2">
              <span className="truncate font-cb-mono text-[10px] text-cb-ink-text">
                {m.filename}
              </span>
              <span className="font-cb-sans text-[10px] text-cb-muted">supersedes</span>
              <select
                value={m.part_id}
                onChange={(e) =>
                  setMappings((prev) =>
                    prev.map((row, j) => (j === i ? { ...row, part_id: e.target.value } : row)))
                }
                className="rounded-cb-btn border border-cb-border bg-white px-1.5 py-0.5 font-cb-sans text-[10px]"
              >
                {allParts.map((p) => (
                  <option key={p.part_id} value={p.part_id}>
                    {p.part_id} · {p.title}
                  </option>
                ))}
              </select>
            </span>
          ))}
          {proposal.advisory && (
            <span className="mt-1 block font-cb-sans text-[10px] leading-[1.45] text-cb-brass-text">
              {proposal.advisory}
            </span>
          )}
          <span className="mt-1.5 flex items-center gap-2">
            <button
              type="button"
              disabled={busy || mappings.length === 0}
              onClick={() => void approve()}
              className="cb-press rounded-cb-btn bg-cb-ink px-3 py-1 font-cb-sans text-[10px] font-semibold text-white"
            >
              Approve — apply as new revisions
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setProposal(null)}
              className="cb-press font-cb-sans text-[10px] text-cb-muted"
            >
              cancel
            </button>
          </span>
        </span>
      )}

      {applied && (
        <span className="basis-full rounded-cb-chip border border-cb-border bg-cb-page p-2">
          <span className="block font-cb-sans text-[10px] leading-[1.5] text-cb-body">
            Applied: {applied.revised.map((r) => `${r.part_id} → rev ${r.rev}`).join(", ") || "nothing"}.
            {" "}Read the part again (⟳) so the new pages get a card.
          </span>
          {applied.reopened_register_items.length > 0 && (
            <span className="mt-1 block font-cb-sans text-[10px] leading-[1.5] text-cb-amber">
              ⚠ Register line(s) {applied.reopened_register_items.join(", ")} cited the replaced
              pages and are back to undecided — re-decide them on the Register.
            </span>
          )}
          {applied.overtaken_queries.length > 0 && (
            <span className="mt-1 block font-cb-sans text-[10px] leading-[1.5] text-cb-amber">
              ⚠ Open quer{applied.overtaken_queries.length === 1 ? "y" : "ies"} overtaken:{" "}
              {applied.overtaken_queries.join("; ")}
            </span>
          )}
        </span>
      )}

      {problem && (
        <span className="basis-full font-cb-sans text-[10px] leading-[1.45] text-cb-bad-dark">
          {problem}
        </span>
      )}
    </span>
  );
}


function ContextCard({
  setId,
  allParts,
  part,
  context,
  selected,
  onSelect,
  onReinterpret,
  onRevised,
  busy,
  editing,
  onEdit,
  onCancelEdit,
  onSave,
  locations,
  onLocate,
}: {
  setId: string;
  /** Every part on the set — the mapping selector's options when a correction lands. */
  allParts: PartRow[];
  part: PartRow;
  context: PartContext | undefined;
  selected: boolean;
  onSelect: () => void;
  onReinterpret: () => void;
  /** A revision was applied — parts and contexts must re-read. */
  onRevised: () => void;
  busy: boolean;
  editing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSave: (patch: {
    summary: string;
    obligations: string[];
    commercial_flags: string[];
  }) => void;
  locations: Record<string, LocateResult>;
  onLocate: (quote: string) => void;
}) {
  const unread = part.scanned && !part.readable;
  // NOT YET INTERPRETED is a different state from "interpreted, nothing to note", and they must
  // not look alike. A tender pack arrives as 203 parts and interpretation is deferred — one model
  // call each was never acceptable per tender — so most cards legitimately have no context yet.
  // An empty summary field would read as "there wasn't much in it", which is a claim nobody made.
  const uninterpreted = !unread && context === undefined;

  if (uninterpreted) {
    return (
      <div
        onClick={onSelect}
        className={cx(
          "cb-row cursor-pointer rounded-cb-card border border-dashed border-cb-border-strong bg-white p-[12px_13px]",
          selected && "border-l-[3px] border-l-cb-brass",
        )}
      >
        <div className="flex items-center gap-2">
          <span className="font-cb-mono text-[11px] font-semibold text-cb-muted">
            {part.part_id}
          </span>
          <span className="font-cb-sans text-[12.5px] font-semibold text-cb-ink-text">
            {part.title}
          </span>
          <Chip className="border border-cb-border-strong text-cb-muted">NOT YET INTERPRETED</Chip>
          <span className="ml-auto flex-none font-cb-mono text-[10px] font-semibold text-cb-muted">
            pp. {part.pages}
          </span>
        </div>
        <p className="mt-2 font-cb-sans text-[11.5px] leading-[1.5] text-cb-muted">
          Nobody has read this part yet — its category comes from where it sat in the pack, which
          is enough to route it and to keep it out of the contract review. Read it when you need
          what it says.
        </p>
        <div className="mt-3 flex items-center gap-2 border-t border-dashed border-cb-border pt-2">
          <IconButton
            filled
            title="Read this part now"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              onReinterpret();
            }}
          >
            <span className={busy ? "inline-block animate-spin" : undefined}>⟳</span>
          </IconButton>
          <span className="font-cb-sans text-[10.5px] text-cb-faint">
            One model call, this part only.
          </span>
        </div>
      </div>
    );
  }

  // A part that could not be read gets its own card, not a sparse version of the normal one.
  // An empty summary field reads as "there wasn't much in it"; this has to read as "nobody has
  // seen these pages", because nothing downstream may cite them.
  if (unread) {
    return (
      <div
        onClick={onSelect}
        className={cx(
          "cb-row cursor-pointer rounded-cb-card border border-cb-bad/40 bg-cb-bad-tint p-[12px_13px]",
          selected && "border-l-[3px] border-l-cb-brass",
        )}
      >
        <div className="flex items-center gap-2">
          <span className="font-cb-mono text-[11px] font-semibold text-cb-bad-dark">
            {part.part_id}
          </span>
          <span className="font-cb-sans text-[12.5px] font-semibold text-cb-ink-text">
            {part.title}
          </span>
          <Chip className="bg-cb-bad text-white">NOT READ · VISION ATTEMPTED</Chip>
          <span className="ml-auto flex-none font-cb-mono text-[10px] font-semibold text-cb-bad-dark">
            pp. {part.pages}
          </span>
        </div>
        <p className="mt-2 font-cb-sans text-[11.5px] leading-[1.5] text-cb-bad-dark">
          These pages carry no text layer, and vision returned nothing usable from them.{" "}
          <strong className="font-semibold">Nothing downstream cites these pages.</strong> Upload a
          readable copy, or read them here by eye — the pages themselves render on the right.
        </p>
        <div className="mt-3 flex items-center gap-2 border-t border-dashed border-cb-bad/30 pt-2">
          <IconButton
            filled
            title="Read this part again — retry vision OCR"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              onReinterpret();
            }}
          >
            <span className={busy ? "inline-block animate-spin" : undefined}>⟳</span>
          </IconButton>
          <IconButton title="Editing page bounds is not built yet" disabled>
            ✎
          </IconButton>
          <UploadReadableCopy
            setId={setId}
            partId={part.part_id}
            allParts={allParts}
            onRevised={onRevised}
          />
          <button
            type="button"
            onClick={onSelect}
            className="cb-press ml-auto font-cb-sans text-[10px] text-cb-bad-dark"
          >
            showing in document →
          </button>
        </div>
      </div>
    );
  }

  const summary = context?.summary || part.summary || "";
  const obligations = context?.obligations ?? [];
  const impact = context?.commercial_flags ?? [];

  return (
    <Card selected={selected}>
      <div className="flex flex-col gap-[9px]">
        <div onClick={onSelect} className="flex cursor-pointer flex-wrap items-center gap-2">
          <span className="flex-none font-cb-mono text-[11px] font-semibold text-cb-muted">
            {part.part_id}
          </span>
          <span className="font-cb-sans text-[12.5px] font-semibold text-cb-ink-text">
            {part.title}
          </span>
          <Chip className="bg-cb-info text-cb-navy">
            {CATEGORY_LABEL[part.category] ?? part.category}
          </Chip>
          <CardBadge badge={context?.badge ?? "ai"} />
          <span className="ml-auto flex-none font-cb-mono text-[10px] font-semibold text-cb-muted">
            pp. {part.pages}
          </span>
        </div>

        {editing ? (
          <CardEditor
            summary={summary}
            obligations={obligations}
            impact={impact}
            busy={busy}
            onCancel={onCancelEdit}
            onSave={onSave}
          />
        ) : (
          <>
            <div>
              <SectionLabel>WHAT IT IS</SectionLabel>
              <p className="mt-1 font-cb-serif text-[12px] leading-[1.55] text-cb-body">
                {summary || (
                  <span className="text-cb-faint">
                    Not yet interpreted. Re-read it, or write what it is yourself.
                  </span>
                )}
              </p>
            </div>

            {obligations.length > 0 && (
              <div>
                <SectionLabel>KEY OBLIGATIONS</SectionLabel>
                <ul className="mt-1 space-y-0.5">
                  {obligations.map((o, i) => (
                    <li key={i} className="font-cb-sans text-[11.5px] leading-[1.45] text-cb-body">
                      — {o}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {impact.length > 0 && (
              <div className="flex flex-wrap items-start gap-2">
                <Chip className="bg-cb-brass-tint text-cb-brass-text">PRICE IMPACT</Chip>
                <span className="font-cb-sans text-[11px] leading-[1.45] text-cb-body">
                  {impact[0]}
                </span>
              </div>
            )}

            {/* Quotations, so each one can be PROVED against the page — unlike the summary and
                the obligations above, which are paraphrases and get a search instead. */}
            {context?.strategy_flags?.length ? (
              <div className="rounded-cb-btn border-l-2 border-cb-brass bg-cb-selected/60 py-1.5 pl-[9px] pr-2">
                <SectionLabel>HOW THIS TENDER MUST BE BID</SectionLabel>
                {context.strategy_flags.map((flag, i) => (
                  <FlagQuote
                    key={i}
                    flag={flag}
                    located={locations[flag.quote]}
                    onLocate={() => onLocate(flag.quote)}
                  />
                ))}
              </div>
            ) : null}
          </>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Pill className="bg-cb-desk text-cb-muted">Rev 0 · Original intake</Pill>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 border-t border-dashed border-cb-border pt-2">
        <IconButton
          title="Read this part again — a fresh machine reading, replacing this card"
          disabled={busy || editing}
          onClick={onReinterpret}
        >
          <span className={busy ? "inline-block animate-spin" : undefined}>⟳</span>
        </IconButton>
        {!editing && (
          <button
            type="button"
            onClick={onEdit}
            className="cb-press font-cb-sans text-[10.5px] text-cb-brass-text underline underline-offset-2"
          >
            Edit this card
          </button>
        )}
        <button
          type="button"
          onClick={onSelect}
          className="cb-press ml-auto font-cb-sans text-[10px] text-cb-muted"
        >
          showing in document →
        </button>
      </div>
    </Card>
  );
}

/** Whose reading this card is. Same two states as a scope line, and the same rule behind them. */
function CardBadge({ badge }: { badge: "ai" | "user" }) {
  return (
    <span
      title={
        badge === "ai"
          ? "The model's reading of these pages. Edit it and it becomes yours."
          : "Your words. You corrected this card."
      }
      className={cx(
        "inline-flex flex-none items-center rounded-cb-chip border px-1.5 py-0.5 font-cb-mono text-[10px] font-semibold tracking-cb-chip",
        badge === "ai"
          ? "border-cb-disabled bg-cb-info text-cb-navy"
          : "border-cb-brass-line bg-cb-brass-tint text-cb-brass-text",
      )}
    >
      {badge.toUpperCase()}
    </span>
  );
}

/** One quoted clause, with a control that proves it against the page.
 *
 *  Three outcomes, deliberately the same vocabulary as a register citation. `not_located` earns
 *  its place here: an offline fixture broadcasts the same flags onto every part of a set, and
 *  this is what shows that only one of them actually contains the words. */
function FlagQuote({
  flag,
  located,
  onLocate,
}: {
  flag: StrategyFlag;
  located: LocateResult | undefined;
  onLocate: () => void;
}) {
  return (
    <div className="mt-1.5">
      <p className="font-cb-serif text-[11.5px] leading-[1.5] text-cb-body">
        “{flag.quote}”{" "}
        <span className="font-cb-mono text-[10px] text-cb-brass-text">
          {flag.clause}
          {flag.page ? ` · printed p.${flag.page}` : ""}
        </span>
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onLocate}
          disabled={located === "pending"}
          className="cb-press flex-none rounded-cb-chip border border-cb-brass-line bg-white px-1.5 py-0.5 font-cb-sans text-[10px] font-medium text-cb-brass-text"
        >
          {located === "pending" ? "looking…" : "Show me on the page"}
        </button>
        {located && located !== "pending" && (
          <span
            className={cx(
              "font-cb-mono text-[10px] tracking-cb-chip",
              located.verdict === "located" ? "text-cb-ok-dark" : "text-cb-bad-dark",
            )}
            title={located.note}
          >
            {located.verdict === "located"
              ? `✓ FOUND ON BINDER p.${located.page}`
              : located.verdict === "unverifiable"
                ? "COULD NOT CHECK — NO TEXT LAYER"
                : "✕ NOT ON THESE PAGES"}
          </span>
        )}
      </div>
      {located && located !== "pending" && located.verdict !== "located" && (
        <p className="mt-1 font-cb-sans text-[10px] leading-[1.4] text-cb-muted">{located.note}</p>
      )}
    </div>
  );
}

/** The card's edit surface. Obligations are one-per-line, which is how they read anyway. */
function CardEditor({
  summary,
  obligations,
  impact,
  busy,
  onCancel,
  onSave,
}: {
  summary: string;
  obligations: string[];
  impact: string[];
  busy: boolean;
  onCancel: () => void;
  onSave: (patch: { summary: string; obligations: string[]; commercial_flags: string[] }) => void;
}) {
  const [s, setS] = useState(summary);
  const [o, setO] = useState(obligations.join("\n"));
  const [c, setC] = useState(impact.join("\n"));

  const field =
    "w-full resize-y rounded-cb-btn border border-cb-brass bg-cb-warm p-[9px_10px] font-cb-serif text-[12px] leading-[1.6] text-cb-ink-text";

  return (
    <div className="flex flex-col gap-2">
      <div>
        <SectionLabel>WHAT IT IS</SectionLabel>
        <textarea value={s} onChange={(e) => setS(e.target.value)} rows={4} className={field} />
      </div>
      <div>
        <SectionLabel>KEY OBLIGATIONS · one per line</SectionLabel>
        <textarea value={o} onChange={(e) => setO(e.target.value)} rows={4} className={field} />
      </div>
      <div>
        <SectionLabel>PRICE IMPACT · one per line</SectionLabel>
        <textarea value={c} onChange={(e) => setC(e.target.value)} rows={2} className={field} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="dark"
          disabled={busy}
          onClick={() =>
            onSave({
              summary: s.trim(),
              obligations: o.split("\n").map((x) => x.trim()).filter(Boolean),
              commercial_flags: c.split("\n").map((x) => x.trim()).filter(Boolean),
            })
          }
        >
          Save
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <span className="font-cb-sans text-[10px] leading-[1.4] text-cb-muted">
          Saving stamps this card <strong className="font-semibold">USER</strong>. Whether the
          pages are readable stays a measurement — that is not editable.
        </span>
      </div>
    </div>
  );
}

export type { PartSpec };
