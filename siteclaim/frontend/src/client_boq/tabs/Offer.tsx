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
import type { LetterAppendixItem, LetterResponse } from "../types";
import { Button, Chip, SectionLabel, WaitingOn, cx, money } from "../ui";

/** `LetterMeta`'s built-in fallback. Matching it is how the screen knows the letterhead has never
 *  been set — the backend deliberately keeps a renderable default so a letter always assembles. */
const DEFAULT_COMPANY = "SiteSource Contracting Ltd";

export function OfferTab({
  data,
  onError,
}: {
  data: SetData;
  onError: (message: string) => void;
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

  if (!data.hasEstimate && !letter) {
    return (
      <WaitingOn title="The offer waits on the price">
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
          {/* --- the header: what this is, and what it is not --- */}
          <div className="flex flex-wrap items-start gap-3">
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
