// Frames 04, 05 and 06 — the three panels the Register rail opens.
//
// 04 RFI build (active, not sent) · 05 RFI build (sent, read-only) · 06 Addendum.
//
// A sent batch is a cooler colour than an active one, which is the whole visual argument: one is
// still yours to edit, the other has left the building.

import { useEffect, useState } from "react";
import { api } from "./api";
import type { DocumentRow, RFIItem, RevisionRow } from "./types";
import { Button, Chip, SectionLabel, cx } from "./ui";

export type PanelRequest =
  | { kind: "rfi"; batchId: string | null }
  | { kind: "addendum"; docId: string };

export function Panel({
  title,
  status,
  tone,
  marker,
  onClose,
  children,
  footer,
}: {
  title: string;
  status: string;
  tone: "active" | "sent" | "addendum";
  marker: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const header =
    tone === "active" ? "bg-cb-ink" : tone === "sent" ? "bg-cb-navy-line" : "bg-cb-navy";
  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-[620px] max-w-full flex-col border-l border-cb-border-strong shadow-cb-card">
      <div className={cx("flex flex-none items-center gap-2 px-[18px] py-3", header)}>
        <span className={tone === "active" ? "text-cb-brass" : "text-cb-dim"}>{marker}</span>
        <span className="font-cb-sans text-[12.5px] font-semibold text-white">{title}</span>
        <span className="font-cb-mono text-[9px] tracking-cb-chip text-cb-dim">{status}</span>
        <button
          type="button"
          onClick={onClose}
          className="cb-press ml-auto font-cb-mono text-[12px] text-cb-dim"
        >
          ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto bg-cb-surface px-[18px] py-[14px]">
        {children}
      </div>
      {footer && (
        <div className="flex flex-none flex-wrap items-center gap-3 border-t border-dashed border-cb-border-strong bg-cb-surface px-[18px] py-3">
          {footer}
        </div>
      )}
    </div>
  );
}

/** Record the client's answer to one sent question. Nothing pre-filled — an answer is the
 *  CLIENT's words, and `carried by` is the document that brought them ("Tender Addendum No. 1"),
 *  not a person. Recording changes no document: if the reply arrived as an addendum, that
 *  addendum still goes through the Documents upload and its change-mapping gate. */
function AnswerForm({
  busy,
  onRecord,
}: {
  busy: boolean;
  onRecord: (answer: string, answeredBy: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [answer, setAnswer] = useState("");
  const [answeredBy, setAnsweredBy] = useState("");

  if (!open) {
    return (
      <div className="mt-2">
        <p className="font-cb-sans text-[10.5px] leading-[1.45] text-cb-brass-text">
          No answer yet. Until one arrives this is priced on our own conservative assumption,
          and the freeze gate will make that assumption explicit.
        </p>
        <Button className="mt-1.5" onClick={() => setOpen(true)}>
          Record the client's answer
        </Button>
      </div>
    );
  }
  return (
    <div className="mt-2 rounded-cb-chip border border-cb-border bg-cb-warm p-2">
      <SectionLabel>THE CLIENT'S ANSWER — THEIR WORDS</SectionLabel>
      <textarea
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        rows={3}
        className="mt-1 w-full rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1.5 font-cb-serif text-[11.5px] leading-[1.5] text-cb-ink-text"
      />
      <label className="mt-1.5 flex items-center gap-2">
        <span className="font-cb-mono text-[8px] tracking-cb-chip text-cb-faint">CARRIED BY</span>
        <input
          value={answeredBy}
          onChange={(e) => setAnsweredBy(e.target.value)}
          placeholder="e.g. Tender Addendum No. 1"
          className="flex-1 rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1 font-cb-sans text-[10.5px] text-cb-ink-text"
        />
      </label>
      <div className="mt-2 flex items-center gap-2">
        <Button
          variant="brass"
          disabled={busy || !answer.trim()}
          onClick={() => onRecord(answer.trim(), answeredBy.trim())}
        >
          Record it
        </Button>
        <span className="font-cb-sans text-[9.5px] leading-[1.4] text-cb-muted">
          Recording an answer changes no document. If it arrived as an addendum, upload the
          addendum on Documents — the change-mapping gate is what revises pages.
        </span>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Frames 04 / 05 — the RFI build
// ---------------------------------------------------------------------------
export function RfiPanel({
  setId,
  batchId,
  onClose,
  onError,
  onChanged,
}: {
  setId: string;
  /** null = the active build (every draft question). Otherwise a sent batch, read-only. */
  batchId: string | null;
  onClose: () => void;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<RFIItem[]>([]);
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  // THE LETTER SURVIVES THE EXPORT. `send()` used to await the response and throw the rendered
  // markdown away — the one artifact the whole panel exists to produce, reachable afterwards
  // only by curl. Now it is shown, copyable and saveable, here.
  const [letter, setLetter] = useState<string | null>(null);
  const [showLetter, setShowLetter] = useState(false);

  const load = () =>
    api
      .rfis(setId)
      .then((r) => {
        setItems(r.items);
        if (!ref) setRef(`Technical Query No. ${r.batches.length + 1}`);
      })
      .catch((e: unknown) => onError(e instanceof Error ? e.message : String(e)));

  useEffect(() => {
    void load();
    // A sent batch carries its letter — fetch it so the history is the letter, not a summary.
    if (batchId !== null) {
      api
        .rfiBatch(setId, batchId)
        .then((b) => setLetter(b.markdown))
        .catch((e: unknown) => onError(e instanceof Error ? e.message : String(e)));
    } else {
      setLetter(null);
      setShowLetter(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setId, batchId]);

  const sent = batchId !== null;
  const shown = sent
    ? items.filter((i) => i.batch_id === batchId)
    : items.filter((i) => i.status === "draft");

  const answered = shown.filter((i) => i.status === "answered");
  const stillOpen = shown.filter((i) => i.status === "sent");

  async function remove(rfiId: string) {
    setBusy(true);
    try {
      await api.withdrawRfi(setId, rfiId);
      await load();
      onChanged();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    setBusy(true);
    try {
      const reply = await api.sendRfiBatch(setId, ref, shown.map((i) => i.rfi_id));
      // Keep the panel open ON the letter: closing blind was the dead end. Nothing has been
      // transmitted — this is the draft a person sends.
      setLetter(reply.markdown);
      setShowLetter(true);
      await load();
      onChanged();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function recordAnswer(rfiId: string, answer: string, answeredBy: string) {
    setBusy(true);
    try {
      await api.answerRfi(setId, rfiId, answer, answeredBy);
      await load();
      onChanged();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title={sent ? `RFI batch ${batchId}` : ref || "RFI build"}
      status={sent ? "SENT · READ ONLY" : "ACTIVE · not sent"}
      tone={sent ? "sent" : "active"}
      marker={sent ? "○" : "●"}
      onClose={onClose}
      footer={
        sent ? (
          <span className="font-cb-sans text-[10px] leading-[1.45] text-cb-muted">
            Questions still open stay priced on your own conservative assumption until an answer
            arrives. The freeze gate is where each one becomes an answer or a stated assumption.
          </span>
        ) : (
          <>
            <Button variant="brass" onClick={send} disabled={busy || shown.length === 0}>
              Export query letter &amp; mark sent
            </Button>
            <span className="max-w-[300px] font-cb-sans text-[10px] leading-[1.45] text-cb-muted">
              Stamps today's date, moves this build into history read-only, and opens the next one
              for the following line you save.
            </span>
          </>
        )
      }
    >
      {sent && (
        <div className="mb-3 flex items-center gap-4 border-b border-cb-border pb-2">
          <Tally label="SENT" value={shown.length} className="text-cb-ink-text" />
          <Tally label="ANSWERED" value={answered.length} className="text-cb-ok" />
          <Tally label="STILL OPEN" value={stillOpen.length} className="text-cb-amber" />
        </div>
      )}

      {letter !== null && (
        <div className="mb-3 rounded-[5px] border border-cb-border bg-white p-[11px_13px]">
          <div className="flex items-center gap-2">
            <SectionLabel>THE QUERY LETTER</SectionLabel>
            <span className="ml-auto flex gap-2">
              <button
                type="button"
                onClick={() => void navigator.clipboard?.writeText(letter)}
                className="cb-press font-cb-sans text-[10px] font-medium text-cb-brass-text underline underline-offset-2"
              >
                copy
              </button>
              <button
                type="button"
                onClick={() => setShowLetter((v) => !v)}
                className="cb-press font-cb-sans text-[10px] font-medium text-cb-brass-text underline underline-offset-2"
              >
                {showLetter ? "hide" : "show"}
              </button>
            </span>
          </div>
          {showLetter && (
            <pre className="mt-2 max-h-[300px] overflow-y-auto whitespace-pre-wrap font-cb-mono text-[10px] leading-[1.55] text-cb-ink-text">
              {letter}
            </pre>
          )}
          <p className="mt-1.5 font-cb-sans text-[9.5px] leading-[1.45] text-cb-muted">
            Nothing has been transmitted — this is the draft you send, on your own letterhead,
            by your own channel.
          </p>
        </div>
      )}

      {!sent && (
        <div className="mb-3">
          <SectionLabel>LETTER REFERENCE</SectionLabel>
          <input
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            className="mt-1 w-full rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1.5 font-cb-sans text-[11px] text-cb-ink-text"
          />
        </div>
      )}

      {shown.length === 0 ? (
        <p className="font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          Nothing queued. Dismissing a register line lets you write what you will ask for instead,
          and save it into this build.
        </p>
      ) : (
        <div className="space-y-2">
          {shown.map((item, i) => (
            <div
              key={item.rfi_id}
              className="rounded-[5px] border border-cb-border bg-white p-[11px_13px]"
            >
              <div className="flex items-center gap-2">
                <span className="flex-none font-cb-mono text-[11px] font-semibold text-cb-ink-text">
                  Q{item.number || i + 1}
                </span>
                {(item.clause || item.register_item != null) && (
                  <span className="truncate font-cb-sans text-[11px] font-medium text-cb-muted">
                    {item.clause ? `cl. ${item.clause}` : ""}
                    {item.register_item != null ? ` · register item ${item.register_item}` : ""}
                  </span>
                )}
                {item.status === "answered" ? (
                  <Chip className="ml-auto bg-cb-ok-tint text-cb-ok-dark">ANSWERED ✓</Chip>
                ) : sent ? (
                  <Chip className="ml-auto bg-cb-brass-tint text-cb-brass-text">UNANSWERED</Chip>
                ) : (
                  <button
                    type="button"
                    onClick={() => remove(item.rfi_id)}
                    disabled={busy}
                    title="Remove from this build — the draft text on the register line is kept"
                    className="cb-press ml-auto font-cb-mono text-[11px] text-cb-muted"
                  >
                    ✕
                  </button>
                )}
              </div>
              <p className="mt-1.5 font-cb-serif text-[12px] leading-[1.55] text-cb-ink-text">
                {item.question}
              </p>
              {item.answer && (
                <div className="mt-2 border-l-2 border-cb-ok pl-[9px]">
                  <SectionLabel>THE CLIENT'S ANSWER</SectionLabel>
                  <p className="mt-1 font-cb-serif text-[11.5px] leading-[1.55] text-cb-body">
                    {item.answer}
                  </p>
                  {item.answered_by && (
                    <p className="mt-1 font-cb-mono text-[9px] text-cb-faint">
                      carried by {item.answered_by}
                    </p>
                  )}
                </div>
              )}
              {sent && !item.answer && (
                <AnswerForm
                  busy={busy}
                  onRecord={(answer, answeredBy) =>
                    void recordAnswer(item.rfi_id, answer, answeredBy)
                  }
                />
              )}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function Tally({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className?: string;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={cx("font-cb-mono text-[13px] font-semibold", className)}>{value}</span>
      <span className="font-cb-mono text-[8.5px] tracking-cb-chip text-cb-faint">{label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Frame 06 — an addendum
// ---------------------------------------------------------------------------
export function AddendumPanel({
  setId,
  docId,
  onClose,
  onError,
}: {
  setId: string;
  docId: string;
  onClose: () => void;
  onError: (message: string) => void;
}) {
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [revisions, setRevisions] = useState<RevisionRow[]>([]);

  useEffect(() => {
    api
      .revisions(setId)
      .then((r) => {
        setDocuments(r.documents);
        setRevisions(r.revisions);
      })
      .catch((e: unknown) => onError(e instanceof Error ? e.message : String(e)));
  }, [setId, onError]);

  const doc = documents.find((d) => d.doc_id === docId);
  const touched = revisions.filter((r) => r.doc_id === docId);

  return (
    <Panel
      title={doc ? doc.ref || doc.filename : "Addendum"}
      status={doc ? `${doc.kind.toUpperCase()} · ${doc.received_at.slice(0, 10)}` : ""}
      tone="addendum"
      marker="◈"
      onClose={onClose}
      footer={
        <span className="font-cb-sans text-[10px] leading-[1.45] text-cb-muted">
          {doc?.applied
            ? "Applied. Every touched part carries a new revision, and the register lines that depended on the old wording were re-opened for a fresh verdict."
            : "Nothing reaches the price until it is applied. Applying stamps every touched part with a new revision and re-opens the register lines that depended on the old wording."}
        </span>
      }
    >
      <p className="font-cb-sans text-[11px] leading-[1.6] text-cb-body">
        An addendum amends the contract; a clarification does not. What follows is which of our
        parts this document supersedes, and what each part's revision history now looks like.
      </p>

      <div className="mt-4">
        <SectionLabel>PARTS THIS DOCUMENT SUPERSEDES</SectionLabel>
        {touched.length === 0 ? (
          <p className="mt-1 font-cb-sans text-[11px] text-cb-muted">
            No part revisions are recorded against it.
          </p>
        ) : (
          <div className="mt-2 space-y-2">
            {touched.map((rev) => (
              <div
                key={`${rev.part_id}-${rev.rev}`}
                className="rounded-[5px] border border-cb-border bg-white p-[11px_13px]"
              >
                <div className="flex items-center gap-2">
                  <span className="font-cb-mono text-[10.5px] font-semibold text-cb-ink-text">
                    {rev.part_id}
                  </span>
                  <Chip className="bg-cb-brass-tint text-cb-brass-text">REV {rev.rev}</Chip>
                  <span className="ml-auto font-cb-mono text-[9px] text-cb-faint">
                    {rev.applied_at.slice(0, 10)}
                  </span>
                </div>
                {rev.note && (
                  <p className="mt-1.5 font-cb-serif text-[11.5px] leading-[1.55] text-cb-body">
                    {rev.note}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Stated rather than faked. `ChangeEntry` carries the addendum's own advisory change
          table — document, pages, description — and no old/new clause text, so there is nothing
          to diff. Drawing a WAS/NOW block from data we do not have would be inventing it. */}
      <div className="mt-4 rounded-cb-card border border-dashed border-cb-border-strong bg-white p-3">
        <SectionLabel>NO CLAUSE-LEVEL DIFF</SectionLabel>
        <p className="mt-1 font-cb-sans text-[11px] leading-[1.55] text-cb-muted">
          A side-by-side WAS / NOW of the changed wording is not shown, because the superseded and
          replacement text are not extracted and aligned anywhere yet. The replacement pages are
          the authority in any case — the real ND/2025/04 addendum states its own change table is
          "neither exhaustive nor guaranteed to be accurate".
        </p>
      </div>

      <div className="mt-4">
        <SectionLabel>DOCUMENT HISTORY</SectionLabel>
        <div className="mt-1 space-y-1">
          {documents.map((d) => (
            <div
              key={d.doc_id}
              className={cx(
                "flex items-center gap-2 rounded-cb-btn px-2 py-1.5",
                d.doc_id === docId ? "bg-cb-info" : "",
              )}
            >
              <span className="flex-none text-cb-blue">{d.doc_id === docId ? "◈" : "◇"}</span>
              <span className="flex-1 truncate font-cb-sans text-[10.5px] text-cb-ink-text">
                {d.ref || d.filename}
              </span>
              <span className="flex-none font-cb-mono text-[9px] text-cb-faint">
                {d.received_at.slice(0, 10)}
              </span>
            </div>
          ))}
        </div>
        <a
          href={api.revisionsWorkbookUrl(setId)}
          className="cb-press mt-2 inline-block rounded-cb-btn border border-cb-border-strong bg-white px-3 py-1.5 font-cb-sans text-[10.5px] font-medium text-cb-ink-text"
        >
          Download the revision history (.xlsx)
        </a>
      </div>
    </Panel>
  );
}
