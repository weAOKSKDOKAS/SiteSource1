// Frames 02 and 03 — the Register. Every finding gets a human verdict, and this is the gate that
// decides what goes into the price and the letter.
//
// Three rules from the design carry real weight here:
//
//  * 5 of 17 findings have no clause, no quote and no position. The row must read correctly on
//    rationale alone — enrichments appear only when the payload has them, and a missing citation
//    says "no clause — nothing to show" instead of guessing a page.
//  * a citation_failed row has Confirm DISABLED with the reason where the button was. The backend
//    returns 409 on that line; disabling designs the error out rather than catching it.
//  * a negotiated line counts as decided. Both verdict types advance the progress bar, because
//    "we will ask for X instead" is a decision, not a deferral.

import { useEffect, useMemo, useState } from "react";
import type { SetData } from "../App";
import { api, runJob } from "../api";
import { Divider, DocTab, Rail, RailFolded, TAB_FOR_JOB, usePanes } from "../chrome";
import { PageView } from "../PageView";
import type {
  CitationRow,
  Criterion,
  DepartureItem,
  DocumentRow,
  Highlight,
  JobState,
  LocationVerdict,
  RFIItem,
  RegisterSource,
} from "../types";
import {
  AUTHOR,
  AuthorBadge,
  AuthorSwatch,
  Button,
  Chip,
  SectionLabel,
  WaitingOn,
  authorOf,
  cx,
  money,
} from "../ui";
import type { Author } from "../ui";

const CHECK_LABEL: Record<RegisterSource, string> = {
  criteria: "Criteria",
  scope_alignment: "Scope alignment",
  program: "Programme",
  cashflow: "Cash flow",
};

const DECIDED = new Set(["confirmed", "dismissed"]);

type SortMode = "register" | "page" | "status";

export function RegisterTab({
  data,
  job,
  railOpen,
  onRefresh,
  onError,
  onOpenPanel,
  onProgress,
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
  onOpenPanel?: (
    panel: { kind: "rfi"; batchId: string | null } | { kind: "addendum"; docId: string },
  ) => void;
}) {
  const register = data.register?.register;
  const items = register?.line_items ?? [];

  const [selected, setSelected] = useState<number | null>(null);
  const [partId, setPartId] = useState<string | null>(null);
  const [page, setPage] = useState<number | null>(null);
  /** The result of a "show me on the page" run, and its verdict — separate from the precomputed
   *  citation highlights so proving one row never rewrites what the citation pass measured. */
  const [located, setLocated] = useState<Highlight[]>([]);
  const [locating, setLocating] = useState<LocationVerdict | "pending" | null>(null);
  const [locateNote, setLocateNote] = useState("");
  const [filterCheck, setFilterCheck] = useState<RegisterSource | null>(null);
  const [filterAuthor, setFilterAuthor] = useState<Author | null>(null);
  const [undecidedOnly, setUndecidedOnly] = useState(false);
  const [sort, setSort] = useState<SortMode>("register");
  const [negotiating, setNegotiating] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [rfis, setRfis] = useState<RFIItem[]>([]);
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [criteriaRows, setCriteriaRows] = useState<Criterion[]>([]);
  const [busy, setBusy] = useState(false);
  // The shell's job, narrowed to work that belongs to THIS tab. `TAB_FOR_JOB` is the one
  // place that translates a workflow name into a tab, so this cannot drift from the chips.
  const jobRunning =
    !!job &&
    (job.status === "queued" || job.status === "running") &&
    TAB_FOR_JOB[job.kind] === "register";
  // Everything that used to gate on `busy` gates on this instead.
  const running = busy || jobRunning;
  /** Read the specification tree as well. Off by default — on a real government pack that is ~150
   *  of 206 parts, mostly appendices (borehole logs, test schedules) that carry no contractual
   *  position, and reading them is most of a long run. It is a DEFERRAL, not an exclusion: the
   *  parts are named in the run's notes and this brings them back. */
  const [includeSpecs, setIncludeSpecs] = useState(false);
  /** The finished run's notes — chiefly which parts it did not read, and why. */
  const [runNotes, setRunNotes] = useState<string[]>([]);
  const panes = usePanes("register", 224, 520, railOpen);

  // The acceptable-terms library, so a row can say what `PS-01` actually means. Loaded once per
  // set; it is a small static file behind the endpoint.
  useEffect(() => {
    api
      .criteria()
      .then((r) => setCriteriaRows([...r.criteria, ...r.placeholders]))
      .catch(() => setCriteriaRows([]));
  }, []);

  const criteria = useMemo(
    () => new Map(criteriaRows.map((c) => [c.id, c])),
    [criteriaRows],
  );

  useEffect(() => {
    if (!data.setId) return;
    api
      .rfis(data.setId)
      .then((r) => setRfis(r.items))
      .catch(() => setRfis([]));
    api
      .revisions(data.setId)
      .then((r) => setDocuments(r.documents))
      .catch(() => setDocuments([]));
  }, [data.setId, data.register]);

  // Seed the negotiation drafts from what is already stored, so reopening a dismissed line
  // shows the text that was written rather than an empty box.
  useEffect(() => {
    const stored: Record<number, string> = {};
    items.forEach((i) => {
      if (i.contractor_response) stored[i.item] = i.contractor_response;
    });
    setDrafts((cur) => ({ ...stored, ...cur }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.register]);

  // Citations, keyed by item — this is where the measured page and the highlight come from.
  const byItem = useMemo(() => {
    const map = new Map<number, CitationRow>();
    (data.citations?.citations ?? []).forEach((c) => map.set(c.item, c));
    return map;
  }, [data.citations]);

  // Open on a document rather than "Select a part to read it here." A clause viewer with
  // nothing in it was the commonest reason the PDF looked broken: the Register only ever set a
  // part when a citation LOCATED, which in DEMO never happens.
  useEffect(() => {
    const parts = data.parts?.parts ?? [];
    if (!parts.length) return;
    if (!partId || !parts.some((p) => p.part_id === partId)) setPartId(parts[0].part_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.parts]);

  // A new selection invalidates the last row's locate result — leaving it up would attach one
  // row's proof to another row's claim.
  useEffect(() => {
    setLocated([]);
    setLocating(null);
    setLocateNote("");
  }, [selected]);

  const rfiFor = useMemo(() => {
    const map = new Map<number, RFIItem>();
    rfis.forEach((r) => {
      if (r.register_item != null && r.status !== "withdrawn") map.set(r.register_item, r);
    });
    return map;
  }, [rfis]);

  // Counts for the rail. Built off the full list, never the filtered one — a filter must not
  // change what the tallies say is there.
  const counts = useMemo(() => {
    const byCheck = new Map<RegisterSource, Map<Author, number>>();
    items.forEach((i) => {
      const check = i.source;
      const author = authorOf(i);
      if (!byCheck.has(check)) byCheck.set(check, new Map());
      const inner = byCheck.get(check)!;
      inner.set(author, (inner.get(author) ?? 0) + 1);
    });
    return byCheck;
  }, [items]);

  const open = items.filter((i) => !DECIDED.has(i.status));
  const confirmed = items.filter((i) => i.status === "confirmed");
  const dismissed = items.filter((i) => i.status === "dismissed");
  const decided = confirmed.length + dismissed.length;

  const shown = useMemo(() => {
    let out = items;
    if (filterCheck) out = out.filter((i) => i.source === filterCheck);
    if (filterAuthor) out = out.filter((i) => authorOf(i) === filterAuthor);
    if (undecidedOnly) out = out.filter((i) => !DECIDED.has(i.status));
    if (sort === "page") {
      out = [...out].sort((a, b) => (a.page ?? 9e9) - (b.page ?? 9e9) || a.item - b.item);
    } else if (sort === "status") {
      out = [...out].sort((a, b) => a.status.localeCompare(b.status) || a.item - b.item);
    }
    return out;
  }, [items, filterCheck, filterAuthor, undecidedOnly, sort]);

  /** Selecting a row shows its clause.
   *
   *  Two levels, and the difference between them is the whole point. A LOCATED citation moves the
   *  pane to the measured page and the highlight draws — that is proof. Anything else moves the
   *  pane to the part the clause belongs to and draws nothing: the document is on screen to read,
   *  and the banner says why no mark is on it. Never a guessed page. */
  function selectRow(item: DepartureItem) {
    setSelected(item.item);
    const citation = byItem.get(item.item);
    if (citation?.verdict === "located" && citation.page != null) {
      const part = (data.parts?.parts ?? []).find((p) => {
        const [s, e] = p.pages.split("-").map(Number);
        return citation.page! >= s && citation.page! <= e;
      });
      if (part) {
        setPartId(part.part_id);
        setPage(citation.page);
        return;
      }
    }
    // Unverifiable / not located / no citation at all: show the part, not a page.
    const part = partForClause(item.clause);
    if (part) {
      setPartId(part);
      setPage(null);
    }
  }

  /** Which part a clause id belongs to, from the parts' own page ranges via the citation, else
   *  from the clause prefix the part ids carry. Best-effort by design: a miss leaves the pane
   *  alone rather than opening an arbitrary document. */
  function partForClause(clause: string): string | null {
    if (!clause) return null;
    const parts = data.parts?.parts ?? [];
    const citation = [...byItem.values()].find((c) => c.clause === clause && c.page != null);
    if (citation?.page != null) {
      const hit = parts.find((p) => {
        const [s, e] = p.pages.split("-").map(Number);
        return citation.page! >= s && citation.page! <= e;
      });
      if (hit) return hit.part_id;
    }
    return null;
  }

  /** Prove a selected row's quotation against the page — the same control the Documents tab has,
   *  and the same three verdicts. This is what makes the Register's highlight demandable rather
   *  than only ever precomputed: in LIVE it draws the mark, and in DEMO it reports honestly that
   *  fixture text is not in this binder instead of leaving the pane blank and unexplained. */
  async function locateSelected(item: DepartureItem) {
    const quote = item.cited_text?.trim();
    if (!quote) return;
    const target = partId ?? partForClause(item.clause) ?? (data.parts?.parts ?? [])[0]?.part_id;
    if (!target) return;
    setLocating("pending");
    try {
      const r = await api.locateQuote(data.setId, target, quote);
      setLocating(r.verdict);
      setLocateNote(r.note);
      if (r.verdict === "located" && r.page != null) {
        setPartId(target);
        setLocated(r.highlights);
        setPage(r.page);
      } else {
        setLocated([]);
      }
    } catch (e: unknown) {
      setLocating(null);
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  async function decide(item: DepartureItem, verdict: "confirmed" | "dismissed" | "query") {
    setBusy(true);
    try {
      await api.approveReview(
        data.setId,
        { [item.item]: verdict },
        // The gate's CURRENT state, not `false`. `/review/approve` both records verdicts and
        // writes the gate flag, so sending `false` here would silently REOPEN a closed register
        // every time someone changed a verdict — and reopening a gate invalidates everything
        // built after it. Closing and reopening are the footer's job, deliberately and with the
        // consequence stated.
        data.gates.review,
        drafts[item.item] ? { [item.item]: drafts[item.item] } : {},
      );
      await onRefresh();
      if (verdict === "dismissed") setNegotiating(item.item);
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function undo(item: DepartureItem) {
    // There is no "clear the verdict" endpoint; re-running the review is the honest reset and
    // is a much larger action. Until one exists, an Undo can only move the line to the third
    // verdict, so the row says so rather than pretending.
    onError(
      `Item ${item.item}: a verdict cannot be cleared once recorded — the register keeps what was decided. Re-run the review to start the register over.`,
    );
  }

  async function saveNegotiation(item: DepartureItem) {
    setBusy(true);
    try {
      // Same rule as `decide`: carry the gate's current state, never assume `false`.
      await api.approveReview(data.setId, {}, data.gates.review, {
        [item.item]: drafts[item.item] ?? "",
      });
      await onRefresh();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function queueRfi(item: DepartureItem) {
    const question = (drafts[item.item] ?? "").trim();
    if (!question) return;
    setBusy(true);
    try {
      const citation = byItem.get(item.item);
      await api.raiseRfi({
        set_id: data.setId,
        question,
        origin: "register",
        register_item: item.item,
        clause: item.clause,
        page: citation?.page ?? item.page,
        context: item.cited_text,
      });
      const fresh = await api.rfis(data.setId);
      setRfis(fresh.items);
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function unqueueRfi(item: DepartureItem) {
    const rfi = rfiFor.get(item.item);
    if (!rfi) return;
    setBusy(true);
    try {
      await api.withdrawRfi(data.setId, rfi.rfi_id);
      const fresh = await api.rfis(data.setId);
      setRfis(fresh.items);
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /** Run the review over the split parts. Through runJob because in LIVE this is a background
   *  job — reading the first response would work offline and do nothing with a real key. */
  async function runReview() {
    setBusy(true);
    // A new run makes the previous refusal history: clear the shell banner at the START,
    // before the work, so it can never describe a run that has been superseded.
    onError("");
    try {
      const finished = await runJob(
        () => api.runReview(data.setId, data.name, includeSpecs),
        api.reviewStatus,
        (s) => onProgress?.(s),
      );
      // What the run did NOT read, kept where the person reading the register will see it. The
      // backend has always written these notes; nothing displayed them for a review, so a part
      // skipped on the operator's behalf was invisible. A deferral nobody can see is an exclusion.
      setRunNotes(finished.warnings ?? []);
      onProgress?.(null);
      await onRefresh();
    } catch (e: unknown) {
      const err = e as Error & { status?: number };
      // Belt and braces on the race the recovery effect otherwise closes. If a review was already
      // running when this button was pressed — two windows on one set, or a click that beat the
      // mount-time `liveJob` call — the server says 409 and NAMES the job. That is not an error
      // worth a red banner: the thing the operator asked for is already happening. So adopt it
      // and show its progress, which is what they wanted to see in the first place.
      if (err.status === 409 && /already running/i.test(err.message ?? "")) {
        try {
          const live = await api.liveJob(data.setId);
          if (live.job_id) {
            onProgress?.(live);
            const finished = await runJob(
              () => Promise.resolve(live),
              api.reviewStatus,
              (s) => onProgress?.(s),
            );
            setRunNotes(finished.warnings ?? []);
            onProgress?.(null);
            await onRefresh();
            return;
          }
        } catch {
          /* fall through to the banner — a 409 we cannot attach to is worth reporting */
        }
      }
      onProgress?.(null);
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function closeRegister() {
    setBusy(true);
    try {
      await api.approveReview(data.setId, {}, true);
      await onRefresh();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!register && running) {
    // The tab knows the set is busy — its own run, or one it has just adopted from the shell —
    // so it must not also say the review has not been run. That contradiction, beside a strip
    // reading "REVIEW · running", was the same component arguing with itself on one screen. It is
    // `running` and not `busy` because the run is very often NOT this mount's: start a review,
    // navigate away, come back, and `busy` is false while the review is still going.
    return (
      <WaitingOn title="The review is running">
        Reading each part against the criteria library. It keeps going if you navigate away — the
        strip above follows it, and stops it.
      </WaitingOn>
    );
  }

  if (!register) {
    return (
      <WaitingOn
        title="The register has not been run yet"
        action={
          data.gates.manifest ? (
            <div className="flex flex-col items-center gap-2.5">
              <Button variant="brass" onClick={runReview} disabled={running}>
                Run the review
              </Button>
              {/* The skip, made visible and reversible at the point of decision — not a constant
                  buried in the engine. A departure register concerns the conditions of contract;
                  on a real government pack the specification tree is most of the set and mostly
                  appendices. Naming the choice here, before the run, is the difference between a
                  deferral the operator made and an exclusion the code made for them. */}
              <label className="flex items-center gap-1.5 font-cb-sans text-[10px] text-cb-muted">
                <input
                  type="checkbox"
                  checked={includeSpecs}
                  onChange={(e) => setIncludeSpecs(e.target.checked)}
                  disabled={running}
                  className="accent-[#BD9A5F]"
                />
                Read the specifications too — slower, and mostly appendices
              </label>
            </div>
          ) : undefined
        }
      >
        {data.gates.manifest
          ? "The parts are split and ready. Running the review reads each part against the criteria library and produces the departure register."
          : "The register waits on the manifest — every finding cites a page, and those page numbers are not fixed until the split is approved."}
      </WaitingOn>
    );
  }

  const selectedItem = shown.find((i) => i.item === selected) ?? null;
  const citation = selected != null ? byItem.get(selected) : undefined;
  // The citation pass's measured marks, plus whatever a "show me on the page" run proved.
  // Both are evidence; neither overwrites the other.
  const highlights: Highlight[] = [...(citation?.highlights ?? []), ...located];
  const mismatch = data.register?.parse_mismatch ?? null;

  return (
    <div ref={panes.container} className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      {/* ---------------- pane 1 — rail ---------------- */}
      {panes.railOpen ? (
        <Rail width={panes.railWidth} onResize={panes.dragRail}>
          <RailBlock title="CHECKS">
            {[...counts.entries()].map(([check, authors]) => {
              const total = [...authors.values()].reduce((a, b) => a + b, 0);
              const active = filterCheck === check;
              return (
                <div key={check}>
                  <button
                    type="button"
                    onClick={() => setFilterCheck(active ? null : check)}
                    className={cx(
                      "cb-row flex w-full items-center gap-2 rounded-cb-btn px-2 py-1 text-left",
                      active && "bg-cb-info",
                    )}
                  >
                    <span className="flex-1 truncate font-cb-sans text-[11.5px] font-semibold text-cb-ink-text">
                      {CHECK_LABEL[check] ?? check}
                    </span>
                    <span className="flex-none font-cb-mono text-[10.5px] font-semibold text-cb-muted">
                      {total}
                    </span>
                  </button>
                  {/* Checks are the parents on purpose: a reviewer asks "how do the criteria
                      look?" before "who wrote this?", and the counts must add up inside a check. */}
                  <div className="ml-[10px] border-l border-dashed border-cb-border-strong pl-2">
                    <div className="py-0.5 font-cb-mono text-[8.5px] tracking-cb-chip text-cb-faint">
                      FROM:
                    </div>
                    {[...authors.entries()].map(([author, n]) => (
                      <button
                        key={author}
                        type="button"
                        onClick={() => setFilterAuthor(filterAuthor === author ? null : author)}
                        title={AUTHOR[author].long}
                        className={cx(
                          "cb-row flex w-full items-center gap-2 rounded-cb-btn px-1.5 py-1 text-left",
                          filterAuthor === author && "bg-cb-info",
                        )}
                      >
                        <AuthorSwatch author={author} />
                        <span className="flex-1 truncate font-cb-sans text-[10.5px] font-medium text-cb-body">
                          {AUTHOR[author].label.toLowerCase()}
                        </span>
                        <span className="flex-none font-cb-mono text-[9.5px] text-cb-muted">
                          {n}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </RailBlock>

          <RailBlock title="STATUS">
            <RailTally label="Unresolved criteria" value={register.unresolved.count} />
            <RailTally label="Aligned / passed" value={register.aligned.length} />
            <RailTally label="Negotiated" value={dismissed.length} />
            {register.cashflow && (
              <RailTally
                label="Cash-flow section"
                value={`${register.cashflow.points.length} periods`}
              />
            )}
          </RailBlock>

          <RailBlock title="RFIS / BATCHES">
            {rfis.length === 0 ? (
              <p className="px-2 py-1 font-cb-sans text-[10px] leading-[1.5] text-cb-faint">
                No questions raised yet. Dismissing a line lets you write what you will ask for
                instead, and queue it here.
              </p>
            ) : (
              <button
                type="button"
                onClick={() => onOpenPanel?.({ kind: "rfi", batchId: null })}
                className="cb-press flex w-full items-center gap-2 rounded-cb-btn bg-cb-ink px-2 py-1.5 text-left"
              >
                <span className="flex-none text-cb-brass">●</span>
                <span className="flex-1 truncate font-cb-sans text-[11px] font-semibold text-white">
                  Current build
                </span>
                <span className="flex-none whitespace-nowrap font-cb-mono text-[9px] text-cb-dim">
                  ACTIVE
                </span>
                <span className="flex-none rounded-cb-chip bg-cb-brass px-1.5 font-cb-mono text-[9px] font-semibold text-cb-on-brass">
                  {rfis.filter((r) => r.status === "draft").length}
                </span>
              </button>
            )}
          </RailBlock>

          <RailBlock title="ADDENDA RECEIVED">
            {documents.filter((d) => d.kind !== "base").length === 0 ? (
              <p className="px-2 py-1 font-cb-sans text-[10px] leading-[1.5] text-cb-faint">
                Only the original issue. An addendum amends the contract; a clarification does not.
              </p>
            ) : (
              documents
                .filter((d) => d.kind !== "base")
                .map((d, i) => (
                  <button
                    key={d.doc_id}
                    type="button"
                    onClick={() => onOpenPanel?.({ kind: "addendum", docId: d.doc_id })}
                    className={cx(
                      "cb-row flex w-full items-center gap-2 rounded-cb-btn px-2 py-1.5 text-left",
                      i === 0 && "border border-cb-disabled bg-cb-info",
                    )}
                  >
                    <span className="flex-none text-cb-blue">{i === 0 ? "◈" : "◇"}</span>
                    <span
                      className={cx(
                        "flex-1 truncate font-cb-sans text-[10.5px] font-medium",
                        i === 0 ? "text-cb-navy" : "text-cb-muted",
                      )}
                    >
                      {d.ref || d.filename}
                    </span>
                    {i === 0 && !d.applied && (
                      <Chip className="bg-cb-blue text-white">NEW</Chip>
                    )}
                    <span className="flex-none whitespace-nowrap font-cb-mono text-[9px] text-cb-faint">
                      {d.received_at.slice(5, 10)}
                    </span>
                  </button>
                ))
            )}
          </RailBlock>
        </Rail>
      ) : (
        <RailFolded
          lines={[
            { value: String(open.length), label: "OPEN" },
            { value: String(register.unresolved.count), label: "UNR" },
            { value: String(register.aligned.length), label: "ALGN" },
            { value: String(dismissed.length), label: "NEG" },
          ]}
        />
      )}

      {/* ---------------- pane 2 — the register ---------------- */}
      <section
        style={panes.docCollapsed ? undefined : { width: panes.midWidth }}
        className={cx(
          "flex min-w-0 flex-col bg-cb-surface",
          panes.docCollapsed ? "flex-1" : "flex-none",
        )}
      >
        <div className="flex flex-none flex-wrap items-end gap-3 border-b border-cb-border px-4 py-3">
          <div className="flex-1">
            <SectionLabel>DEPARTURE REGISTER</SectionLabel>
            <div className="font-cb-serif text-[17px] font-semibold text-cb-ink-text">
              {open.length} need a verdict
            </div>
          </div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortMode)}
            className="flex-none rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1 font-cb-sans text-[10px] text-cb-body"
          >
            <option value="register">Sort: register order</option>
            <option value="page">Sort: page order</option>
            <option value="status">Sort: status</option>
          </select>
          <label className="flex flex-none items-center gap-1.5 font-cb-sans text-[10px] text-cb-body">
            <input
              type="checkbox"
              checked={undecidedOnly}
              onChange={(e) => setUndecidedOnly(e.target.checked)}
              className="accent-[#BD9A5F]"
            />
            Undecided only
          </label>
        </div>

        {/* The single most confusing state in the app, said out loud. When the review returned
            its bundled sample instead of reading the upload, every citation is unlocatable and
            nothing highlights — which looks like a broken viewer and is not one. */}
        {mismatch && (
          <div className="flex-none border-b border-cb-amber bg-cb-brass-tint px-4 py-2.5">
            <div className="flex items-start gap-2">
              <span className="flex-none font-cb-mono text-[11px] text-cb-brass-text">⚠</span>
              <div className="min-w-0">
                <div className="font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-brass-text">
                  THESE FINDINGS ARE NOT ABOUT YOUR DOCUMENT
                </div>
                <p className="mt-1 font-cb-sans text-[11px] leading-[1.5] text-cb-brass-text">
                  {mismatch.note}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* What this run did not read. Amber border and text, no fill claim: it is not a failure
            and not a finding — it is the boundary of what was looked at, which the person reading
            a register has to know to read it correctly. */}
        {runNotes.length > 0 && (
          <div className="flex-none border-b border-cb-amber bg-cb-brass-tint px-4 py-2.5">
            <div className="flex items-start gap-2">
              <span className="flex-none font-cb-mono text-[11px] text-cb-brass-text">◑</span>
              <div className="min-w-0 flex-1">
                <div className="font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-brass-text">
                  WHAT THIS RUN DID NOT READ
                </div>
                {runNotes.map((note) => (
                  <p
                    key={note}
                    className="mt-1 font-cb-sans text-[11px] leading-[1.5] text-cb-brass-text"
                  >
                    {note}
                  </p>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setRunNotes([])}
                className="cb-press flex-none font-cb-sans text-[10px] text-cb-brass-text underline"
              >
                dismiss
              </button>
            </div>
          </div>
        )}

        {(filterCheck || filterAuthor) && (
          <div className="flex flex-none items-center gap-2 border-b border-cb-border bg-cb-info/50 px-4 py-1.5">
            <span className="font-cb-mono text-[9px] tracking-cb-chip text-cb-navy">
              FILTERED · {shown.length} OF {items.length}
            </span>
            <button
              type="button"
              onClick={() => {
                setFilterCheck(null);
                setFilterAuthor(null);
              }}
              className="cb-press ml-auto font-cb-sans text-[10px] text-cb-navy underline"
            >
              clear
            </button>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {shown.map((item) => (
            <RegisterRow
              key={item.item}
              item={item}
              criterion={criteria.get(item.criterion_id)}
              citation={byItem.get(item.item)}
              rfi={rfiFor.get(item.item)}
              selected={item.item === selected}
              negotiating={negotiating === item.item}
              draft={drafts[item.item] ?? ""}
              busy={busy}
              onSelect={() => selectRow(item)}
                  onLocate={() => void locateSelected(item)}
                  locating={selected === item.item ? locating : null}
                  locateNote={locateNote}
              onDecide={(v) => decide(item, v)}
              onUndo={() => undo(item)}
              onToggleNegotiate={() =>
                setNegotiating(negotiating === item.item ? null : item.item)
              }
              onDraft={(text) => setDrafts((cur) => ({ ...cur, [item.item]: text }))}
              onSaveNegotiation={() => saveNegotiation(item)}
              onQueueRfi={() => queueRfi(item)}
              onUnqueueRfi={() => unqueueRfi(item)}
            />
          ))}

          {/* Outside the verdict queue on purpose. These are the two things reviewers misread,
              so each explains itself in one sentence rather than sitting there as a number. */}
          <div className="space-y-2 p-4">
            <SectionLabel>NO VERDICT NEEDED — READ AND MOVE ON</SectionLabel>

            <div className="rounded-cb-card border border-dashed border-cb-border-strong bg-white p-[12px_13px]">
              <div className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
                {register.unresolved.count} criteria unanswered
              </div>
              <p className="mt-1 font-cb-serif text-[11.5px] leading-[1.55] text-cb-body">
                Of the ones we check for, {register.unresolved.count} are not addressed anywhere in
                the documents. What the contract is silent about. There is nothing to decide —
                silence is the risk: no liability cap written at all is worse than a bad one.
              </p>
            </div>

            {register.cashflow && (
              <div className="rounded-cb-card border border-dashed border-cb-border-strong bg-white p-[12px_13px]">
                <div className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
                  Cash position ·{" "}
                  {register.cashflow.negative_periods.length} of{" "}
                  {register.cashflow.points.length} periods negative
                </div>
                <p className="mt-1 font-cb-serif text-[11.5px] leading-[1.55] text-cb-body">
                  What the payment terms cost you in funding, not what the work costs. Peak{" "}
                  {money(register.cashflow.working_capital_peak)}. Deterministic arithmetic on the
                  payment clauses — no model involved.
                </p>
                <div className="mt-2 flex h-[52px] items-end gap-[5px] border-b border-cb-border-strong">
                  {register.cashflow.points.map((p, i) => {
                    const peak =
                      Math.max(
                        ...register.cashflow!.points.map((q) => Math.abs(q.cumulative)),
                      ) || 1;
                    const h = Math.max(3, (Math.abs(p.cumulative) / peak) * 48);
                    return (
                      <div
                        key={p.period}
                        title={`${p.period}: ${money(p.cumulative)}`}
                        style={{ height: h }}
                        className={cx(
                          "flex-1 rounded-t-[1px]",
                          p.cumulative < 0
                            ? "bg-cb-bad"
                            : i === register.cashflow!.points.length - 1
                              ? "bg-cb-ok"
                              : "bg-cb-disabled",
                        )}
                      />
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Gate footer — sticky at the column foot. */}
        <div className="flex flex-none items-end gap-4 bg-cb-ink px-[18px] py-3">
          <div className="max-w-[260px] flex-1">
            <div className="flex h-[5px] overflow-hidden rounded-[3px] bg-cb-navy-line">
              <div
                style={{ width: `${items.length ? (confirmed.length / items.length) * 100 : 0}%` }}
                className="bg-cb-brass transition-[width] duration-200 ease-out"
              />
              <div
                style={{ width: `${items.length ? (dismissed.length / items.length) * 100 : 0}%` }}
                className="bg-cb-amber transition-[width] duration-200 ease-out"
              />
            </div>
            <p className="mt-1.5 font-cb-sans text-[10px] text-cb-dim">
              {decided} of {items.length} decided · {confirmed.length} confirmed ·{" "}
              {dismissed.length} negotiated
            </p>
          </div>
          {data.gates.review ? (
            <Chip className="ml-auto bg-cb-ok-tint text-cb-ok-dark">✓ REGISTER CLOSED</Chip>
          ) : (
            <div className="ml-auto flex items-center gap-3">
              {/* A gate states its consequence BEFORE it is passed. Open queries are named here
                  rather than blocking, because the submission deadline does not move because
                  the client has not replied — the freeze gate is the forcing function. */}
              <p className="max-w-[230px] text-right font-cb-sans text-[10px] leading-[1.4] text-cb-dim">
                Closing injects the {confirmed.length} confirmed position
                {confirmed.length === 1 ? "" : "s"} into the scope and Appendix A.
                {open.length > 0 && ` ${open.length} line${open.length === 1 ? "" : "s"} still without a verdict will close as-is.`}
              </p>
              <Button variant="brass" onClick={closeRegister} disabled={busy}>
                Close register &amp; unlock scope
              </Button>
            </div>
          )}
        </div>
      </section>

      {/* ---------------- pane 3 — the clause viewer ---------------- */}
      {panes.docCollapsed ? (
        <DocTab onOpen={panes.openDoc} label="CLAUSE" />
      ) : (
        <>
          <Divider onDrag={panes.dragMiddle} />
          <PageView
            setId={data.setId}
            parts={data.parts?.parts ?? []}
            partId={partId}
            page={page}
            highlights={highlights}
            onPartChange={setPartId}
            onPageChange={setPage}
            toolbarChip={<CitationChip citation={citation} item={selectedItem} />}
            banner={
              <CitationBanner citation={citation} item={selectedItem} mismatch={Boolean(mismatch)} />
            }
          />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The viewer's citation state — pass, failure, and "there is nothing to show"
// ---------------------------------------------------------------------------
function CitationChip({
  citation,
  item,
}: {
  citation: CitationRow | undefined;
  item: DepartureItem | null;
}) {
  if (!item) return null;
  if (!item.clause) return <Chip className="bg-cb-panel text-cb-muted">NO CLAUSE CITED</Chip>;
  if (!citation) return null;
  if (citation.verdict === "located") {
    return <Chip className="bg-cb-ok-tint text-cb-ok-dark">✓ QUOTE FOUND HERE</Chip>;
  }
  if (citation.verdict === "not_located") {
    return <Chip className="bg-cb-bad-tint text-cb-bad-dark">✕ QUOTE NOT FOUND</Chip>;
  }
  return <Chip className="bg-cb-brass-tint text-cb-brass-text">COULD NOT CHECK</Chip>;
}

/** No panel in the pass case — the green chip and the highlight already say it, and dropping it
 *  buys three more clauses of reading height. It returns only on failure. */
function CitationBanner({
  citation,
  item,
  mismatch,
}: {
  citation: CitationRow | undefined;
  item: DepartureItem | null;
  /** The register is about a different document. Blaming the citation would be wrong. */
  mismatch?: boolean;
}) {
  if (!item) return null;

  // The mismatch outranks every other explanation: when the findings describe another document,
  // nothing about THIS citation is at fault and saying otherwise would be misleading.
  if (mismatch) {
    return (
      <div className="flex-none border-b border-cb-brass-line bg-cb-brass-tint px-4 py-[9px] font-cb-sans text-[11px] leading-[1.45] text-cb-brass-text">
        This finding is about a different document, so there is nothing to highlight here. The
        pages on the right are your upload; the clause on the left is not from them.
      </div>
    );
  }

  if (!item.clause) {
    return (
      <div className="flex-none border-b border-cb-border-strong bg-cb-panel px-4 py-[9px] font-cb-sans text-[11px] leading-[1.45] text-cb-muted">
        This finding cites no clause — there is nothing to show. The document pane has been left
        where it was rather than guessing a page.
      </div>
    );
  }
  if (!citation || citation.verdict === "located") return null;

  if (citation.verdict === "not_located") {
    return (
      <div className="flex-none border border-cb-bad bg-cb-bad-tint px-4 py-[9px] font-cb-sans text-[11px] leading-[1.45] text-cb-bad-dark">
        The quoted words are not in clause {item.clause} of the parsed set. Nothing is highlighted
        below because there is nothing to highlight. Do not rely on this line.
      </div>
    );
  }
  return (
    <div className="flex-none border-b border-cb-brass-line bg-cb-brass-tint px-4 py-[9px] font-cb-sans text-[11px] leading-[1.45] text-cb-brass-text">
      {citation.note ||
        "This part could not be searched, so the quotation was never checked against the page. That is the document's shortcoming, not the citation's."}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rail helpers
// ---------------------------------------------------------------------------
function RailBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-cb-border px-2 py-2">
      <SectionLabel className="px-2 pb-1">{title}</SectionLabel>
      {children}
    </div>
  );
}

function RailTally({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <span className="flex-1 truncate font-cb-sans text-[10.5px] text-cb-body">{label}</span>
      <span className="flex-none font-cb-mono text-[10px] font-semibold text-cb-ink-text">
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// One register line
// ---------------------------------------------------------------------------
function RegisterRow({
  item,
  criterion,
  citation,
  rfi,
  selected,
  negotiating,
  draft,
  busy,
  onSelect,
  onDecide,
  onUndo,
  onToggleNegotiate,
  onDraft,
  onSaveNegotiation,
  onQueueRfi,
  onUnqueueRfi,
  onLocate,
  locating,
  locateNote,
}: {
  item: DepartureItem;
  /** The acceptable-terms row this finding was measured against, when it resolves. */
  criterion: Criterion | undefined;
  citation: CitationRow | undefined;
  rfi: RFIItem | undefined;
  selected: boolean;
  negotiating: boolean;
  draft: string;
  busy: boolean;
  onSelect: () => void;
  onDecide: (v: "confirmed" | "dismissed" | "query") => void;
  onUndo: () => void;
  onToggleNegotiate: () => void;
  onDraft: (text: string) => void;
  onSaveNegotiation: () => void;
  onQueueRfi: () => void;
  onUnqueueRfi: () => void;
  /** Prove this row's quotation against the page — only offered on the selected row, and only
   *  when there is a quotation to prove. */
  onLocate: () => void;
  locating: LocationVerdict | "pending" | null;
  locateNote: string;
}) {
  const author = authorOf(item);
  const failed = item.status === "citation_failed" || citation?.verdict === "not_located";
  const isConfirmed = item.status === "confirmed";
  const isDismissed = item.status === "dismissed";
  const isQueried = item.status === "query";
  const page = citation?.page ?? item.page;

  return (
    <div
      onClick={onSelect}
      className={cx(
        "cb-row flex cursor-pointer flex-col gap-2 border-b border-cb-border px-4 py-3",
        selected && "border-l-[3px] border-l-cb-brass bg-cb-selected",
        !selected && isConfirmed && "bg-cb-panel",
        !selected && isDismissed && "bg-cb-negotiated",
        !selected && failed && !isConfirmed && !isDismissed && "bg-cb-bad-tint",
      )}
    >
      {/* 1 — meta */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex-none font-cb-mono text-[13px] font-semibold text-cb-ink-text">
          {item.item}
        </span>
        <AuthorBadge author={author} />
        {(item.criterion_id || item.clause_area || item.category) && (
          <span className="truncate font-cb-sans text-[10.5px] text-cb-muted">
            {item.criterion_id || item.clause_area || item.category}
          </span>
        )}
        {item.clause ? (
          <span className="ml-auto flex-none whitespace-nowrap font-cb-mono text-[10px] text-cb-brass-text-light">
            cl. {item.clause}
            {page != null && ` · p.${page}`} →
          </span>
        ) : (
          <span className="ml-auto flex-none whitespace-nowrap font-cb-mono text-[9.5px] text-cb-faint">
            no clause
          </span>
        )}
      </div>

      {/* 1b — PROVE IT. The clause reference above is what the parse CLAIMS; this measures it
             against the rendered page. Only on the selected row (it is a request to the server)
             and only when there is a quotation to look for. */}
      {selected && item.cited_text?.trim() && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onLocate();
            }}
            disabled={locating === "pending"}
            className="cb-press rounded-cb-chip border border-cb-brass-line bg-cb-brass-tint px-2 py-[3px] font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-brass-text disabled:opacity-60"
          >
            {locating === "pending" ? "LOOKING…" : "SHOW ME ON THE PAGE"}
          </button>
          {locating && locating !== "pending" && (
            <span
              className={cx(
                "font-cb-mono text-[8.5px] font-semibold tracking-cb-chip",
                locating === "located" ? "text-cb-ok-dark" : "text-cb-bad-dark",
              )}
              title={locateNote}
            >
              {locating === "located"
                ? "FOUND — HIGHLIGHTED"
                : locating === "not_located"
                  ? "NOT ON THIS PART"
                  : "NO TEXT LAYER TO SEARCH"}
            </span>
          )}
        </div>
      )}

      {/* 2 — rationale: the only field present on every finding, so it is the body text */}
      <p className="font-cb-serif text-[12.5px] leading-[1.55] text-cb-ink-text">
        {item.rationale}
      </p>

      {/* 3 — WHAT THIS IS ABOUT. The register stores `PS-01`, which on its own is a code nobody
             can decode; the position it is measured against lives in the criteria library. Side
             by side, the finding explains itself: this is what we accept, this is what the
             contract says. Rendered only when the criterion resolves — the 5-of-17 findings with
             no criterion still read on rationale alone, which was always the rule. */}
      {(criterion || item.extracted_value) && (
        <div className="rounded-cb-btn border border-cb-border bg-cb-panel/60 px-[10px] py-2">
          <dl className="grid grid-cols-[74px_1fr] gap-x-2 gap-y-1">
            {criterion?.acceptable_position && (
              <>
                <dt className="font-cb-mono text-[8.5px] tracking-cb-label text-cb-ok-dark">
                  WE ACCEPT
                </dt>
                <dd className="font-cb-sans text-[11px] leading-[1.45] text-cb-body">
                  {criterion.acceptable_position}
                </dd>
              </>
            )}
            {item.extracted_value && (
              <>
                <dt className="font-cb-mono text-[8.5px] tracking-cb-label text-cb-bad-dark">
                  IT SAYS
                </dt>
                <dd className="font-cb-mono text-[10.5px] leading-[1.45] text-cb-ink-text">
                  {item.extracted_value}
                </dd>
              </>
            )}
            {criterion?.red_flag && (
              <>
                <dt className="font-cb-mono text-[8.5px] tracking-cb-label text-cb-faint">
                  RED FLAG
                </dt>
                <dd className="font-cb-sans text-[10.5px] leading-[1.45] text-cb-muted">
                  {criterion.red_flag}
                </dd>
              </>
            )}
          </dl>
          {criterion?.why_it_matters && (
            <p className="mt-1.5 border-t border-dashed border-cb-border pt-1.5 font-cb-sans text-[10.5px] leading-[1.45] text-cb-muted">
              {criterion.why_it_matters}
            </p>
          )}
        </div>
      )}
      {item.proposed_position && (
        <div className="border-l-2 border-cb-brass pl-[9px]">
          <SectionLabel>PROPOSED POSITION · verbatim into the offer</SectionLabel>
          <p className="mt-1 font-cb-serif text-[12px] leading-[1.55] text-cb-body">
            {item.proposed_position}
          </p>
        </div>
      )}

      {/* 4 — state chips */}
      <div className="flex flex-wrap items-center gap-2">
        {isConfirmed && <Chip className="bg-cb-ok-tint text-cb-ok-dark">CONFIRMED BY YOU</Chip>}
        {isDismissed && (
          <Chip className="bg-cb-brass-tint text-cb-brass-text">DISMISSED · TO NEGOTIATE</Chip>
        )}
        {isQueried && <Chip className="bg-cb-brass-tint text-cb-brass-text">QUERIED</Chip>}
        {rfi && (
          <Chip className="border border-cb-ink bg-transparent text-cb-ink-text">
            {rfi.status === "sent" ? "SENT IN" : "SAVED TO"} RFI {rfi.rfi_id.toUpperCase()}
          </Chip>
        )}
        {citation?.verdict === "unverifiable" && (
          <Chip className="bg-cb-panel text-cb-muted">CITATION NOT CHECKED</Chip>
        )}
      </div>

      {/* 5 — verdicts */}
      <div className="flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
        {isConfirmed || isDismissed ? (
          <button
            type="button"
            onClick={onUndo}
            className="cb-press font-cb-sans text-[10.5px] text-cb-brass-text-light underline underline-offset-2"
          >
            Undo
          </button>
        ) : (
          <>
            {failed ? (
              // Disabled, with the reason where the button was. The backend 409s on this line;
              // designing the error out beats catching it.
              <span className="rounded-cb-btn border border-dashed border-cb-border-strong px-[15px] py-[7px] font-cb-sans text-[10.5px] font-semibold text-cb-disabled">
                Confirm
              </span>
            ) : (
              <Button
                variant="outline"
                className="border-cb-ink px-[15px] py-[7px] text-[10.5px] font-semibold"
                onClick={() => onDecide("confirmed")}
                disabled={busy}
              >
                Confirm
              </Button>
            )}
            <Button
              variant="outline"
              className="px-[15px] py-[7px] text-[10.5px] font-semibold"
              onClick={() => onDecide("dismissed")}
              disabled={busy}
            >
              Dismiss
            </Button>
            <Button
              variant="ghost"
              onClick={() => onDecide("query")}
              disabled={busy}
              title="Ask the client. The line stays open and does not block pricing."
            >
              Query
            </Button>
          </>
        )}
        {failed && (
          <span className="font-cb-sans text-[10px] leading-[1.4] text-cb-bad-dark">
            {citation?.note || item.citation_note ||
              "The quoted words could not be found where this line says they are — it cannot be confirmed until re-reviewed."}
          </span>
        )}
        {(isDismissed || negotiating) && (
          <button
            type="button"
            onClick={onToggleNegotiate}
            className="cb-press ml-auto font-cb-sans text-[10px] text-cb-brass-text underline underline-offset-2"
          >
            {negotiating ? "hide" : "what you will negotiate instead"}
          </button>
        )}
      </div>

      {/* 6 — the negotiation box */}
      <div
        className="cb-expand"
        data-open={negotiating || (isDismissed && Boolean(item.contractor_response))}
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <div className="mt-1 rounded-cb-card border border-cb-brass-line bg-cb-warm p-3">
            <SectionLabel>
              WHAT YOU WILL NEGOTIATE INSTEAD · your words, sent with the register
            </SectionLabel>
            <textarea
              value={draft}
              onChange={(e) => onDraft(e.target.value)}
              rows={3}
              className="mt-1.5 w-full resize-y rounded-cb-btn border border-cb-brass bg-white p-[9px_10px] font-cb-serif text-[12px] leading-[1.6] text-cb-ink-text"
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button variant="dark" onClick={onSaveNegotiation} disabled={busy || !draft.trim()}>
                Save
              </Button>
              {rfi ? (
                <>
                  <Chip className="bg-cb-ok-tint text-cb-ok-dark">
                    ✓ ADDED TO {rfi.rfi_id.toUpperCase()}
                  </Chip>
                  {rfi.status === "draft" && (
                    <button
                      type="button"
                      onClick={onUnqueueRfi}
                      disabled={busy}
                      className="cb-press font-cb-sans text-[10px] text-cb-brass-text underline underline-offset-2"
                    >
                      Remove from the build — keeps this draft text
                    </button>
                  )}
                </>
              ) : (
                <Button variant="outline" onClick={onQueueRfi} disabled={busy || !draft.trim()}>
                  Save to the RFI build
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
