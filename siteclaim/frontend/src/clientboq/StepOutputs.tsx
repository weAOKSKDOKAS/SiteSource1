// Step 5 — what leaves the building.
//
// Two deliverables, and the screen's job is to be honest about how each was made. The
// workbook is generated from the persisted estimate, so every figure in it equals the figure
// on the previous screen — it is a download, not a second opinion. The letter is a *draft*:
// code injects the price, the header fields, the pricing schedule and the confirmed
// departures; Claude writes only the prose around them. So the letter is shown twice — once
// as the document it is, in the serif surface the app reserves for rendered instruments, and
// once split by authorship, because a letter that goes out under the company's name should
// never leave a reader guessing which sentences a model wrote.

import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Pill, StepHeading } from "../components";
import { Button, Card, Collapse, LayerBadge, SectionHeader, StatCallout } from "../ui";
import { DownloadLink, EmptyState, money } from "./boqUi";
import type { EstimateResult, LetterResult } from "./types";

const APPENDIX_PREVIEW = 6;

// Appendix A runs long on a busy register. Preview and expand rather than hide: the count is
// always on the chip, and the full letter below always contains every bullet.
function AuthorshipList({ title, tone, note, items }: {
  title: string;
  tone: "ok" | "brand";
  note: string;
  items: string[];
}) {
  const [expanded, setExpanded] = useState(false);
  if (!items.length) return null;
  const shown = expanded ? items : items.slice(0, APPENDIX_PREVIEW);
  const hidden = items.length - shown.length;
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <Pill tone={tone}>
          {title} · {items.length}
        </Pill>
        <span className="text-[11px] text-ink-faint">{note}</span>
      </div>
      <ul className="space-y-1">
        {shown.map((t, i) => (
          <li key={i} className="flex gap-2 text-sm leading-relaxed text-ink-soft">
            <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-faint" />
            {t}
          </li>
        ))}
      </ul>
      {(hidden > 0 || expanded) && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-1.5 text-xs font-semibold text-brand hover:underline"
        >
          {expanded ? "Show fewer" : `Show all ${items.length}`}
        </button>
      )}
    </div>
  );
}

export function StepOutputs({
  setId,
  estimate,
  letter,
  workbookUrl,
  onBack,
}: {
  setId: string;
  estimate: EstimateResult | null;
  letter: LetterResult | null;
  workbookUrl: string;
  onBack: () => void;
}) {
  const fromRegister = letter?.letter.appendix.filter((a) => a.source === "register") ?? [];
  const fromDraft = letter?.letter.appendix.filter((a) => a.source !== "register") ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <StepHeading
          title="Workbook and offer letter"
          lead="Both are generated from the estimate you just priced and the register you closed. The workbook is the arithmetic in full; the letter is a draft for you to edit and send yourself — nothing here sends anything."
        />
        <LayerBadge layer="L4" />
      </div>

      {/* Three tiles, not four: the offer price carries cents and needs the column width to be
          read at a glance, which is the only reason it is on screen. */}
      {estimate && (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCallout
            label="Offer price"
            value={money(estimate.totals.price)}
            tone="brand"
            hint={`excluding GST · ${money(estimate.totals.total_cost)} cost`}
          />
          <StatCallout
            label="Activities priced"
            value={estimate.estimate.activities.length}
            hint={`${estimate.estimate.indirects.length} indirect items`}
          />
          <StatCallout
            label="Departures carried"
            value={fromRegister.length}
            tone="ok"
            hint="into Appendix A, verbatim"
          />
        </div>
      )}

      <Card className="p-4">
        <SectionHeader
          title="Pricing workbook"
          lead="A WBS summary, the resources, one sheet per activity, the indirect costs and the flags — generated from the persisted estimate, so every figure equals what you saw on the pricing screen."
          right={<LayerBadge layer="L1" />}
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <DownloadLink href={workbookUrl}>Download estimate_{setId}.xlsx</DownloadLink>
          <span className="text-xs text-ink-faint">Regenerated on every download from the stored estimate.</span>
        </div>
      </Card>

      {!letter ? (
        <EmptyState title="No offer letter yet">
          The letter is composed during the pricing run. Run the estimate and it appears here.
        </EmptyState>
      ) : (
        <>
          <Card className="p-4">
            <SectionHeader
              title="Who wrote what"
              lead="The letter is assembled, not generated. Everything that carries a number or a commitment is injected by code; Claude writes only the prose that surrounds it."
              right={<Pill tone="warn">draft — you own the letter that goes out</Pill>}
            />
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div className="rounded-xl border border-line-soft bg-paper-soft px-4 py-3">
                <div className="tabular text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-faint">
                  Injected by code
                </div>
                <ul className="mt-1.5 space-y-1 text-sm text-ink-soft">
                  <li>
                    Offer price <span className="tabular font-semibold text-ink">{letter.price_str}</span> excluding GST
                  </li>
                  <li>The pricing schedule table ({letter.letter.pricing_schedule.length} items)</li>
                  <li>Project, client, reference, date and validity</li>
                  <li>Appendix A departures ({fromRegister.length}) — verbatim from the register</li>
                </ul>
              </div>
              <div className="rounded-xl border border-brand/20 bg-brand-bg/40 px-4 py-3">
                <div className="tabular text-[10.5px] font-semibold uppercase tracking-[0.06em] text-brand">
                  Drafted by Claude
                </div>
                <ul className="mt-1.5 space-y-1 text-sm text-ink-soft">
                  <li>The opening paragraph</li>
                  <li>Inclusions ({letter.letter.inclusions.length}) and exclusions ({letter.letter.exclusions.length})</li>
                  <li>Additional conditions ({fromDraft.length})</li>
                </ul>
              </div>
            </div>

            <div className="mt-4 space-y-4">
              <AuthorshipList
                title="Appendix A — from the register"
                tone="ok"
                note="each one a departure you confirmed, unchanged"
                items={fromRegister.map((a) => a.text)}
              />
              <AuthorshipList
                title="Appendix A — Claude's conditions"
                tone="brand"
                note="drafted from the approved scope; edit before sending"
                items={fromDraft.map((a) => a.text)}
              />
            </div>
          </Card>

          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-soft px-4 py-2.5">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-ink">Letter of offer</h3>
                <Pill tone="warn">draft</Pill>
              </div>
              <div className="flex items-center gap-2">
                <span className="tabular text-xs text-ink-faint">REF {letter.letter.meta.ref || "—"}</span>
                <Button
                  variant="subtle"
                  onClick={() => navigator.clipboard?.writeText(letter.markdown)}
                  title="Copy the letter markdown to paste into your own template"
                >
                  Copy markdown
                </Button>
              </div>
            </div>
            {/* The serif `.doc` surface — the app reserves it for rendered instruments, and a
                letter of offer is exactly that. Figures inside it stay as the backend composed
                them, in $ with cents; the app's own readouts are HK$. A document is never
                silently reformatted. */}
            <div className="doc max-h-[36rem] overflow-y-auto px-6 py-5">
              <Markdown remarkPlugins={[remarkGfm]}>{letter.markdown}</Markdown>
            </div>
          </Card>

          <Card className="p-4">
            <Collapse title="Pricing schedule as the letter states it" count={letter.letter.pricing_schedule.length}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line-soft text-left text-xs text-ink-faint">
                    <th className="py-1.5 pr-3 font-medium">Item</th>
                    <th className="py-1.5 pr-3 font-medium">Description</th>
                    <th className="py-1.5 text-right font-medium">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {letter.letter.pricing_schedule.map((row) => (
                    <tr key={row.item_id} className="border-b border-line-soft last:border-0">
                      <td className="tabular py-1.5 pr-3 font-semibold text-ink">{row.item_id}</td>
                      <td className="py-1.5 pr-3 text-ink-soft">{row.description}</td>
                      <td className="tabular py-1.5 text-right text-ink-soft">{money(row.total)}</td>
                    </tr>
                  ))}
                  <tr>
                    <td />
                    <td className="py-2 pr-3 text-right text-sm font-semibold text-ink">Offer price (excl. GST)</td>
                    <td className="tabular py-2 text-right text-sm font-bold text-ink">{money(letter.price)}</td>
                  </tr>
                </tbody>
              </table>
            </Collapse>
          </Card>
        </>
      )}

      <div className="flex items-center justify-between gap-3 pt-1">
        <Button variant="ghost" onClick={onBack}>
          ← Price
        </Button>
      </div>
    </div>
  );
}
