// The Offer tab — the letter that goes out, and the provenance of every line in it.
//
// Also not in the drawn frames. The rules it follows are the ones the rest of the product already
// lives by, and on this screen they matter more than anywhere else, because this is the document
// that leaves the building:
//
//  * AUTHORSHIP IS VISIBLE PER LINE. `LetterOfOffer` marks each appendix item `register` (a
//    confirmed departure, carried VERBATIM) or `draft` (an AI condition from the scope). One is a
//    decision already taken by a person; the other is a proposal. On a page that becomes a
//    contract those two must never look alike, so they do not.
//  * THE PRICE IS INJECTED, NEVER WRITTEN. `price`, `price_str` and the pricing schedule come
//    from the persisted estimate; the model writes the prose around them. That boundary is the
//    product's whole argument, and the screen states it rather than assuming it is obvious.
//  * NOTHING SENDS IT. There is no transmit path in this product at all — the letter is a draft
//    for a human to take away, and saying so plainly is more honest than a disabled Send button.

import { useEffect, useState } from "react";
import type { SetData } from "../App";
import { api } from "../api";
import type {
  BridgeCombinedPricing,
  BridgeSubmissionState,
  LetterAppendixItem,
  LetterResponse,
} from "../types";
import { Button, Chip, OpenTab, SectionLabel, WaitingOn, cx, money } from "../ui";

/** `LetterMeta`'s built-in fallback. Matching it is how the screen knows the letterhead has never
 *  been set — the backend deliberately keeps a renderable default so a letter always assembles. */
const DEFAULT_COMPANY = "SiteSource Contracting Ltd";

export function OfferTab({
  data,
  onError,
  onRefresh,
}: {
  data: SetData;
  onError: (message: string) => void;
  onRefresh?: () => Promise<void> | void;
}) {
  const [letter, setLetter] = useState<LetterResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"structured" | "markdown">("structured");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api
      .letter(data.setId)
      .then((r) => live && setLetter(r))
      .catch(() => live && setLetter(null)) // 404 = the estimate has not been run
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [data.setId, data.hasEstimate]);

  // Two different states, and telling them apart is the whole point. "Nothing has been priced" is
  // a step you have not reached; "priced with the costing engine" is a gap in THIS screen, and
  // sending that estimator to Price — whose own next-action line then points back here — was a
  // closed loop with the way out on neither side.
  if (!data.hasEstimate && !letter && data.hasBill) {
    return (
      <WaitingOn title="This tender was priced with the costing engine">
        The letter is assembled by the earlier resource-schedule engine, from its figure, its
        pricing schedule and the departures the register confirmed. It cannot read a priced client
        bill yet, so there is nothing for it to assemble here. The priced bill itself is on Price —
        download the workbook, or run the estimate if this tender needs a letter.
      </WaitingOn>
    );
  }
  if (!data.hasEstimate && !letter) {
    return (
      <WaitingOn
        title="The offer waits on the price"
        action={<OpenTab setId={data.setId} tab="price">Open Price</OpenTab>}
      >
        The letter is assembled from the priced estimate — its figure, its pricing schedule, and the
        departures the register confirmed. Run the estimate on the Price tab and it appears here.
      </WaitingOn>
    );
  }
  if (loading) return <WaitingOn title="Reading the draft…">Loading the offer letter.</WaitingOn>;
  if (!letter) {
    return (
      <WaitingOn title="No letter for this tender">
        The estimate ran but no letter was persisted. Re-running the estimate assembles one.
      </WaitingOn>
    );
  }

  const doc = letter.letter;
  const fromRegister = doc.appendix.filter((a) => a.source === "register");
  const drafted = doc.appendix.filter((a) => a.source !== "register");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(doc.markdown);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[760px] p-[18px]">
          {/* --- approval + submission: the last human gate before it goes out --- */}
          <SubmitPanel data={data} doc={doc} onError={onError} onRefresh={onRefresh} />

          {/* --- node 43: the WHOLE tender, both engines, gaps named --- */}
          <CombinedPanel setId={data.setId} />

          {/* --- the header: what this is, and what it is not --- */}
          <div className="mt-4 flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1">
              <SectionLabel>LETTER OF OFFER · DRAFT</SectionLabel>
              <h1 className="mt-1 font-cb-serif text-[20px] font-semibold text-cb-ink-text">
                {doc.meta.project || data.name}
              </h1>
              <p className="mt-0.5 font-cb-sans text-[11px] text-cb-muted">
                to {doc.meta.client_name} · from {doc.meta.company_name}
              </p>
              {/* The letterhead is app-wide and set once. Saying it is still the default is more
                  use than silently sending a letter under a placeholder company. */}
              {doc.meta.company_name === DEFAULT_COMPANY && (
                <p className="mt-1 font-cb-sans text-[10.5px] text-cb-brass-text">
                  That is the built-in placeholder, not your firm.{" "}
                  <a
                    href="#/tender/settings"
                    className="underline underline-offset-2"
                  >
                    Set your company details
                  </a>{" "}
                  and re-run the estimate to stamp them on.
                </p>
              )}
            </div>
            <div className="text-right">
              <div className="font-cb-mono text-[8.5px] font-semibold tracking-cb-label text-cb-faint">
                THE PRICE
              </div>
              <div className="font-cb-mono text-[19px] font-semibold text-cb-ink-text">
                {doc.price_str || money(doc.price)}
              </div>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="flex rounded-cb-btn border border-cb-border-strong">
              {(["structured", "markdown"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setView(v)}
                  className={cx(
                    "cb-press px-3 py-1 font-cb-sans text-[10.5px] font-medium first:rounded-l-cb-btn last:rounded-r-cb-btn",
                    view === v ? "bg-cb-ink text-white" : "bg-white text-cb-body",
                  )}
                >
                  {v === "structured" ? "By section" : "As markdown"}
                </button>
              ))}
            </div>
            <Button variant="outline" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy the letter"}
            </Button>
            <a
              href={api.qualificationsUrl(data.setId)}
              className="cb-press rounded-cb-btn border border-cb-border-strong bg-white px-3 py-2 font-cb-sans text-[11px] font-medium text-cb-ink-text"
            >
              Letter of Qualifications
            </a>
            <a
              href={api.departureScheduleUrl(data.setId)}
              className="cb-press rounded-cb-btn border border-cb-border-strong bg-white px-3 py-2 font-cb-sans text-[11px] font-medium text-cb-ink-text"
            >
              Departure Schedule
            </a>
          </div>

          {/* The two companion documents are internal by default, and the reason is a real clause
              in both reference tenders. Stating it here is the difference between a working paper
              and something someone attaches to a bid by accident. */}
          <div className="mt-2 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2">
            <p className="font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text">
              Those two open as <strong>internal working papers</strong>. Both reference tenders warn
              that qualifying a bid "may cause the tender to be disqualified", so the submission
              versions are opt-in and carry the tender's own clause as a warning. The safe route for
              a problem clause is a written query before the cut-off, not a qualification attached to
              the bid.
            </p>
          </div>

          {view === "markdown" ? (
            <pre className="mt-4 overflow-x-auto whitespace-pre-wrap rounded-cb-card border border-cb-border bg-cb-page p-4 font-cb-mono text-[10.5px] leading-[1.6] text-cb-ink-text">
              {doc.markdown}
            </pre>
          ) : (
            <div className="mt-4 flex flex-col gap-4">
              <Section label="INTRODUCTION" author="ai">
                <p className="font-cb-serif text-[12.5px] leading-[1.6] text-cb-ink-text">
                  {doc.intro}
                </p>
              </Section>

              {doc.pricing_schedule.length > 0 && (
                <Section label="PRICING SCHEDULE" author="injected">
                  <table className="w-full text-left">
                    <tbody>
                      {doc.pricing_schedule.map((row) => (
                        <tr key={row.item_id} className="border-b border-cb-divider last:border-0">
                          <td className="w-[56px] py-1.5 font-cb-mono text-[9.5px] text-cb-muted">
                            {row.item_id}
                          </td>
                          <td className="py-1.5 font-cb-sans text-[11px] text-cb-body">
                            {row.description}
                          </td>
                          <td className="py-1.5 text-right font-cb-mono text-[11px] font-semibold text-cb-ink-text">
                            {money(row.total)}
                          </td>
                        </tr>
                      ))}
                      <tr className="border-t-2 border-cb-border-strong">
                        <td />
                        <td className="pt-2 font-cb-sans text-[11px] font-semibold text-cb-ink-text">
                          Total
                        </td>
                        <td className="pt-2 text-right font-cb-mono text-[13px] font-semibold text-cb-ink-text">
                          {doc.price_str || money(doc.price)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </Section>
              )}

              {doc.inclusions.length > 0 && (
                <Section label="INCLUSIONS" author="ai">
                  <Bullets items={doc.inclusions} />
                </Section>
              )}
              {doc.exclusions.length > 0 && (
                <Section label="EXCLUSIONS" author="ai">
                  <Bullets items={doc.exclusions} />
                </Section>
              )}

              {/* Appendix A is the one place the two authorships sit side by side, so it is the
                  one place the distinction is drawn hardest. */}
              <Section label={`APPENDIX A · ${doc.appendix.length} conditions`} author="mixed">
                {fromRegister.length > 0 && (
                  <>
                    <div className="mb-1 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-navy">
                      FROM THE REGISTER · CONFIRMED, VERBATIM · {fromRegister.length}
                    </div>
                    <ul className="mb-3 flex flex-col gap-1.5">
                      {fromRegister.map((item, i) => (
                        <AppendixLine key={`r-${i}`} item={item} />
                      ))}
                    </ul>
                  </>
                )}
                {drafted.length > 0 && (
                  <>
                    <div className="mb-1 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-brass-text">
                      DRAFTED FROM THE SCOPE · A PROPOSAL · {drafted.length}
                    </div>
                    <ul className="flex flex-col gap-1.5">
                      {drafted.map((item, i) => (
                        <AppendixLine key={`d-${i}`} item={item} />
                      ))}
                    </ul>
                  </>
                )}
                {!doc.appendix.length && (
                  <p className="font-cb-sans text-[11px] text-cb-muted">
                    No conditions — the register confirmed no departures and the scope proposed none.
                  </p>
                )}
              </Section>
            </div>
          )}

          <div className="mt-5 rounded-cb-card border border-cb-border bg-cb-panel px-4 py-3">
            <div className="font-cb-mono text-[8.5px] font-semibold tracking-cb-label text-cb-faint">
              THIS IS A DRAFT
            </div>
            <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
              Nothing here sends it — this product has no transmit path at all. Copy it out, edit it
              on your own letterhead, and check every drafted condition before it goes anywhere. The
              price came from the estimate; the prose did not.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/** A section of the letter, labelled with who wrote it. `injected` is the important one: those
 *  figures came from the persisted estimate, not from a model. */
function Section({
  label,
  author,
  children,
}: {
  label: string;
  author: "ai" | "injected" | "mixed";
  children: React.ReactNode;
}) {
  const badge = {
    ai: { text: "AI DRAFTED", cls: "bg-cb-brass-tint text-cb-brass-text" },
    injected: { text: "INJECTED FROM THE ESTIMATE", cls: "bg-cb-info-fill text-cb-navy" },
    mixed: { text: "MIXED — SEE EACH LINE", cls: "bg-cb-panel text-cb-muted" },
  }[author];
  return (
    <section className="rounded-cb-card border border-cb-border bg-cb-page p-[14px]">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <SectionLabel>{label}</SectionLabel>
        <Chip className={cx("font-cb-mono text-[7.5px]", badge.cls)}>{badge.text}</Chip>
      </div>
      {children}
    </section>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((text, i) => (
        <li key={i} className="flex gap-2">
          <span className="mt-[6px] h-1 w-1 flex-none rounded-full bg-cb-brass" />
          <span className="font-cb-serif text-[11.5px] leading-[1.55] text-cb-body">{text}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// The back of the funnel: final approval, then submission (nodes 46–48).
// ---------------------------------------------------------------------------
// The same rules the rest of the product lives by, at the point they matter most — this is the
// screen where the tender actually leaves the building:
//   * THE VERDICT IS THE HUMAN'S. The machine assembles the letter and surfaces a checklist; a
//     person presses Approve or Revise. Nothing here is inferred.
//   * SUBMISSION IS IMPOSSIBLE WITHOUT AN APPROVE — a hard precondition the backend enforces (409),
//     restated on screen so the Submit control is not even offered before it.
//   * NOTHING IS FABRICATED. An unknown deadline says "deadline unknown", never an invented pass;
//     proof is what the operator types, never generated.

type Doc = LetterResponse["letter"];

/** One line of the final-review checklist. `navy` = a deterministic fact; `bad` = a failed check
 *  (the one authorship colour that stops a submission being sensible). */
function CheckLine({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  return (
    <li className="flex items-start gap-2">
      <span
        className={cx(
          "mt-[1px] flex h-4 w-4 flex-none items-center justify-center rounded-full font-cb-mono text-[9px] font-semibold",
          ok ? "bg-cb-info-fill text-cb-navy" : "bg-cb-bad-tint text-cb-bad-dark",
        )}
        aria-hidden
      >
        {ok ? "✓" : "!"}
      </span>
      <span className="font-cb-sans text-[11px] leading-[1.5]">
        <span className={cx("font-semibold", ok ? "text-cb-ink-text" : "text-cb-bad-dark")}>
          {label}
        </span>
        <span className="text-cb-muted"> — {detail}</span>
      </span>
    </li>
  );
}

function SubmitPanel({
  data,
  doc,
  onError,
  onRefresh,
}: {
  data: SetData;
  doc: Doc;
  onError: (message: string) => void;
  onRefresh?: () => Promise<void> | void;
}) {
  const state: BridgeSubmissionState | null = data.submission;
  const approval = state?.approval ?? null;
  const submission = state?.submission ?? null;
  const isApproved = approval?.verdict === "approve";

  const [rationale, setRationale] = useState("");
  const [proof, setProof] = useState("");
  const [busy, setBusy] = useState<"" | "approve" | "revise" | "submit">("");

  const reviewApproved = data.gates.review;

  // The final-review checklist, surfaced from what already exists. Deterministic reads — no model.
  const departures = doc.appendix.filter((a) => a.source === "register").length;
  const checks = [
    { ok: reviewApproved, label: "Review register approved",
      detail: reviewApproved
        ? "the departures were signed off"
        : "the register is NOT approved — these terms are unread (Register tab)" },
    { ok: Boolean(data.scope), label: "Scope frozen",
      detail: data.scope ? "the scope of record is set" : "no scope of record yet (Scope tab)" },
    { ok: doc.price > 0, label: "Price present",
      detail: doc.price > 0 ? `${doc.price_str || money(doc.price)} from the estimate`
        : "the letter carries no price" },
    { ok: true, label: "Confirmed departures & exclusions",
      detail: `${departures} confirmed departure(s), ${doc.exclusions.length} exclusion(s) in the letter` },
  ];

  const run = async (
    kind: "approve" | "revise" | "submit", fn: () => Promise<unknown>,
  ) => {
    setBusy(kind);
    try {
      await fn();
      await onRefresh?.();
      if (kind === "revise") setRationale("");
      if (kind === "submit") setProof("");
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  // --- SUBMITTED: show the frozen record, nothing more to do ---
  if (submission) {
    const onTime =
      submission.on_time == null
        ? { text: "deadline unknown", cls: "bg-cb-panel text-cb-muted" }
        : submission.on_time === 1
          ? { text: "ON TIME", cls: "bg-cb-ok-tint text-cb-ok-dark" }
          : { text: "AFTER THE DEADLINE", cls: "bg-cb-bad-tint text-cb-bad-dark" };
    return (
      <section className="rounded-cb-card border border-cb-ok bg-cb-ok-tint/40 p-[14px]">
        <div className="flex flex-wrap items-center gap-2">
          <SectionLabel>SUBMITTED</SectionLabel>
          <Chip className={cx("font-cb-mono text-[8px]", onTime.cls)}>{onTime.text}</Chip>
        </div>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-cb-sans text-[11px]">
          <dt className="text-cb-faint">Submitted</dt>
          <dd className="text-cb-ink-text">
            {submission.submitted_at} · by {submission.submitted_by}
          </dd>
          <dt className="text-cb-faint">Approved</dt>
          <dd className="text-cb-ink-text">{submission.approval_ref || "—"}</dd>
          <dt className="text-cb-faint">Deadline</dt>
          <dd className="text-cb-ink-text">{submission.deadline || "unknown"}</dd>
          <dt className="text-cb-faint">Price submitted</dt>
          <dd className="font-cb-mono text-cb-ink-text">
            {submission.price_str || money(submission.price_snapshot ?? 0)}
          </dd>
          <dt className="text-cb-faint">Proof</dt>
          <dd className="text-cb-ink-text">{submission.proof || "— none recorded —"}</dd>
        </dl>
        <p className="mt-2 font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
          This is the FROZEN letter as it went out. Editing the estimate now changes the draft
          above, never this record.
        </p>
      </section>
    );
  }

  // --- PRICED → NOT YET APPROVED → APPROVED (ready to submit) ---
  return (
    <section className="rounded-cb-card border border-cb-brass-line bg-cb-warm p-[14px]">
      <div className="flex flex-wrap items-center gap-2">
        <SectionLabel>FINAL APPROVAL &amp; SUBMISSION</SectionLabel>
        <Chip
          className={cx(
            "font-cb-mono text-[8px]",
            isApproved ? "bg-cb-ok-tint text-cb-ok-dark" : "bg-cb-panel text-cb-muted",
          )}
        >
          {isApproved ? "APPROVED" : approval?.verdict === "revise" ? "REVISE REQUESTED" : "NOT YET APPROVED"}
        </Chip>
      </div>

      <ul className="mt-2 flex flex-col gap-1.5">
        {checks.map((c) => (
          <CheckLine key={c.label} ok={c.ok} label={c.label} detail={c.detail} />
        ))}
      </ul>

      {/*
        DOES THE MONEY COME OUT THE OTHER SIDE EXACTLY ONCE?

        This is in front of the signature because it is the one thing the checks above cannot say.
        A basis nothing claims sits OUTSIDE the bill: every line can be priced, `unpriced` and
        `placeholders` can both be empty, and a third of the direct cost can still be missing —
        which is exactly what happened, to the tune of HK$3,038,117. Cost that reaches no rate is
        not saved; General Preambles ¶6 gives it away for the life of a remeasured contract.

        It WARNS and does not block. A basis nothing claims may genuinely not be required by this
        contract, and arithmetic cannot tell which — refusing a correct tender would make the
        product wrong more often than the estimator is. What it does instead is put the verdict
        under the button and freeze it onto the signature, so an approval given over an
        unconserved model is a fact on the record rather than a memory.
      */}
      {state?.conservation && (
        <div className="mt-2 rounded-cb-btn border-l-[3px] border-l-cb-bad bg-cb-bad-tint px-2.5 py-1.5">
          <div className="font-cb-mono text-[7.5px] font-semibold tracking-cb-chip text-cb-bad-dark">
            THE COST DOES NOT COME OUT ONCE
          </div>
          <p className="font-cb-sans text-[11px] leading-[1.55] text-cb-bad-dark">
            {state.conservation}
          </p>
        </div>
      )}

      {/* What the arithmetic said when somebody signed, which is not the same question as what it
          says now — and a model edited after approval is exactly where the two part company. */}
      {approval?.conservation && approval.conservation !== state?.conservation && (
        <div className="mt-2 rounded-cb-btn border-l-[3px] border-l-cb-amber bg-cb-negotiated/60 px-2.5 py-1.5">
          <div className="font-cb-mono text-[7.5px] font-semibold tracking-cb-chip text-cb-amber">
            AT THE MOMENT OF APPROVAL
          </div>
          <p className="font-cb-sans text-[11px] leading-[1.55] text-cb-ink-text">
            {approval.conservation}
          </p>
        </div>
      )}

      {approval?.verdict === "revise" && approval.rationale && (
        <div className="mt-2 rounded-cb-btn border-l-[3px] border-l-cb-amber bg-cb-negotiated/60 px-2.5 py-1.5">
          <div className="font-cb-mono text-[7.5px] font-semibold tracking-cb-chip text-cb-amber">
            REVISE — WHAT TO CORRECT
          </div>
          <p className="font-cb-serif text-[11.5px] leading-[1.5] text-cb-ink-text">
            {approval.rationale}
          </p>
        </div>
      )}

      {!isApproved ? (
        <div className="mt-3">
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="If revising: what must be corrected before this goes out (required to Revise)"
            rows={2}
            className="w-full rounded-cb-btn border border-cb-border-strong bg-white px-2.5 py-1.5 text-[11px] leading-relaxed text-cb-ink-text"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              variant="brass"
              disabled={busy !== ""}
              onClick={() => void run("approve", () => api.bridge.finalApproval(data.setId, "approve"))}
            >
              {busy === "approve" ? "Recording…" : "Approve for submission"}
            </Button>
            <Button
              variant="amber"
              disabled={busy !== "" || !rationale.trim()}
              onClick={() =>
                void run("revise", () =>
                  api.bridge.finalApproval(data.setId, "revise", rationale.trim()))
              }
            >
              {busy === "revise" ? "Recording…" : "Request a revision"}
            </Button>
            <span className="font-cb-sans text-[10px] text-cb-muted">
              The verdict is yours — the machine only assembled the letter.
            </span>
          </div>
        </div>
      ) : (
        <div className="mt-3 rounded-cb-card border border-cb-border bg-cb-page p-3">
          <div className="font-cb-mono text-[8.5px] font-semibold tracking-cb-label text-cb-faint">
            SUBMIT — FREEZE THIS VERSION
          </div>
          <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-muted">
            Submitting snapshots the letter above and its price as the record of what went out. A
            later estimate edit never changes a recorded submission — recording again overwrites
            this record with a new snapshot, so what is on screen when you press is what is kept.
          </p>
          <input
            value={proof}
            onChange={(e) => setProof(e.target.value)}
            placeholder="Submission proof — portal reference or filename (stored as typed)"
            className="mt-2 w-full rounded-cb-btn border border-cb-border-strong bg-white px-2.5 py-1.5 font-cb-mono text-[11px] text-cb-ink-text"
          />
          <div className="mt-2 flex items-center gap-2">
            <Button
              variant="dark"
              disabled={busy !== ""}
              onClick={() => void run("submit", () => api.bridge.submit(data.setId, proof.trim()))}
            >
              {busy === "submit" ? "Submitting…" : "Record submission"}
            </Button>
            {!state?.deadline_known && (
              <span className="font-cb-sans text-[10px] text-cb-muted">
                Deadline unknown — the record will not claim on-time or late.
              </span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

// The combined tender total — self-perform priced bill + awarded sublet packages, every gap and
// double-count NAMED, fork 5's normalisation questions shown beside the figure so a raw
// composition can never read as a settled price. A pure read; nothing here rewrites the letter.
function CombinedPanel({ setId }: { setId: string }) {
  const [combined, setCombined] = useState<BridgeCombinedPricing | null>(null);

  useEffect(() => {
    let live = true;
    api.bridge
      .combinedPricing(setId)
      .then((c) => live && setCombined(c))
      .catch(() => live && setCombined(null));
    return () => {
      live = false;
    };
  }, [setId]);

  if (!combined) return null;
  const fmt = (v: number | null) => (v == null ? "—" : money(v));
  const healthy = !combined.gaps.length && !combined.double_counts.length;

  return (
    <section className="mt-4 rounded-cb-card border border-cb-border bg-cb-page p-[14px]">
      <div className="flex flex-wrap items-center gap-2">
        <SectionLabel>THE WHOLE TENDER · BOTH ENGINES</SectionLabel>
        <Chip
          className={cx(
            "font-cb-mono text-[8px]",
            healthy ? "bg-cb-info-fill text-cb-navy" : "bg-cb-bad-tint text-cb-bad-dark",
          )}
        >
          {healthy ? "EVERY PACKAGE PRICED ONCE" : `${combined.gaps.length + combined.double_counts.length} PROBLEM(S)`}
        </Chip>
      </div>

      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-cb-sans text-[11px]">
        <dt className="text-cb-faint">Self-perform (priced bill)</dt>
        <dd className="font-cb-mono text-cb-ink-text">{fmt(combined.self_perform_total)}</dd>
        <dt className="text-cb-faint">Sublet (awarded returns)</dt>
        <dd className="font-cb-mono text-cb-ink-text">{fmt(combined.sublet_total)}</dd>
        <dt className="text-cb-faint">Combined</dt>
        <dd className="font-cb-mono text-[13px] font-semibold text-cb-ink-text">
          {fmt(combined.combined_total)}
        </dd>
        {combined.displaced_estimate_total > 0 && (
          <>
            <dt className="text-cb-faint">Displaced estimate</dt>
            <dd className="font-cb-mono text-cb-muted">
              {fmt(combined.displaced_estimate_total)} — what the estimate said for the sublet
              items; shown beside the awards, never added to them
            </dd>
          </>
        )}
      </dl>

      {combined.gaps.map((g, i) => (
        <p key={`g-${i}`} className="mt-1.5 rounded-cb-btn border-l-[3px] border-l-cb-bad bg-cb-bad-tint/50 px-2.5 py-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-bad-dark">
          {g}
        </p>
      ))}
      {combined.double_counts.map((d, i) => (
        <p key={`d-${i}`} className="mt-1.5 rounded-cb-btn border-l-[3px] border-l-cb-bad bg-cb-bad-tint/50 px-2.5 py-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-bad-dark">
          {d}
        </p>
      ))}
      {combined.notes.map((n, i) => (
        <p key={`n-${i}`} className="mt-1.5 font-cb-sans text-[10.5px] leading-[1.5] text-cb-muted">
          {n}
        </p>
      ))}

      <div className="mt-2 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2">
        <div className="font-cb-mono text-[7.5px] font-semibold tracking-cb-chip text-cb-brass-text">
          OPEN BEFORE THIS FIGURE GOES NEAR THE LETTER
        </div>
        <ul className="mt-1 flex flex-col gap-0.5">
          {combined.open_questions.map((q, i) => (
            <li key={i} className="font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text">
              — {q}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function AppendixLine({ item }: { item: LetterAppendixItem }) {
  const fromRegister = item.source === "register";
  return (
    <li
      className={cx(
        "flex gap-2 rounded-cb-btn border-l-[3px] px-2.5 py-1.5",
        fromRegister ? "border-l-cb-navy bg-cb-info/40" : "border-l-cb-brass bg-cb-selected/50",
      )}
    >
      <span className="font-cb-serif text-[11.5px] leading-[1.55] text-cb-ink-text">
        {item.text}
      </span>
    </li>
  );
}
