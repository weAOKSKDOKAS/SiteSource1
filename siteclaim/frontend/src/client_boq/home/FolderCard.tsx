// One tender as a folder on the shelf. The card's job is triage: which tender needs a person
// today. Everything on it is derived from measured counts — the blocking line is generated
// from numbers, never a status word somebody typed ("in progress" is banned by the handoff).

import type { SetRow, TeamMember } from "../types";
import { Avatar, cx } from "../ui";

// --- derivations ------------------------------------------------------------
export function daysToClose(row: SetRow, today = new Date()): number | null {
  const iso = row.meta.close_date;
  if (!iso) return null;
  const close = new Date(`${iso}T00:00:00`);
  return Math.ceil((close.getTime() - today.getTime()) / 86_400_000);
}

/** The card's stage line, e.g. `ON REGISTER · 14 UNDECIDED`. */
export function stageLine(row: SetRow): string {
  if (!row.gates.manifest) return row.parts > 0 ? "ON DOCUMENTS · SPLIT DONE" : "ON DOCUMENTS · MANIFEST OPEN";
  if (!row.gates.review)
    return row.counts.undecided > 0
      ? `ON REGISTER · ${row.counts.undecided} UNDECIDED`
      : "ON REGISTER · GATE 2 OPEN";
  if (!row.gates.scope) return "ON SCOPE · GATE 3 OPEN";
  if (row.price == null) return "ON PRICE · READY TO RUN";
  return row.has_letter ? "OFFER DRAFTED" : "PRICED · OFFER NEXT";
}

/** One sentence saying what is stopping this tender, composed from the counts. */
export function blockingSentence(row: SetRow): string {
  if (!row.gates.manifest)
    return row.parts > 0
      ? "The split ran but the manifest is not approved."
      : "The split manifest is waiting for approval — nothing can run until a person owns the boundaries.";
  const bits: string[] = [];
  if (row.counts.citation_failed > 0)
    bits.push(`${row.counts.citation_failed} citation${row.counts.citation_failed > 1 ? "s" : ""} failed and cannot be confirmed`);
  if (row.counts.undecided > 0)
    bits.push(`${row.counts.undecided} finding${row.counts.undecided > 1 ? "s" : ""} need${row.counts.undecided > 1 ? "" : "s"} a verdict`);
  if (row.counts.unaccepted_fallbacks > 0)
    bits.push(`${row.counts.unaccepted_fallbacks} AI fallback${row.counts.unaccepted_fallbacks > 1 ? "s are" : " is"} unaccepted`);
  if (row.counts.open_rfis > 0)
    bits.push(`${row.counts.open_rfis} quer${row.counts.open_rfis > 1 ? "ies are" : "y is"} with the client`);
  if (!bits.length) {
    if (!row.gates.review) return "The register is ready to sign off.";
    if (!row.gates.scope) return "The scope is ready to freeze.";
    if (row.price == null) return "Nothing blocks the estimate run.";
    return "Priced. The offer letter is drafted from here.";
  }
  return bits.join("; ") + ".";
}

/** Tab + top-border colour by state. Brass = last touched, red = behind, blue = ingesting,
 *  grey = normal — the handoff's mapping. */
function cardTone(row: SetRow, lastTouchedId: string | null): { tab: string; border: string } {
  const days = daysToClose(row);
  if (days != null && days <= 7 && days >= 0 && row.blocked)
    return { tab: "#E0A392", border: "#C25539" }; // behind schedule
  if (!row.gates.manifest && row.parts === 0)
    return { tab: "#9FC0CF", border: "#2F6E8A" }; // still ingesting / just arrived
  if (lastTouchedId && row.set_id === lastTouchedId)
    return { tab: "#C7B084", border: "#BD9A5F" }; // the one you touched last
  return { tab: "#CEC7B8", border: "#8A97A3" };
}

function StateBadge({ row }: { row: SetRow }) {
  const days = daysToClose(row);
  const badge =
    days != null && days <= 7 && days >= 0 && row.blocked
      ? { text: "BEHIND", cls: "bg-cb-bad-tint text-cb-bad-dark" }
      : row.counts.open_rfis > 0
        ? { text: "WAITING ON CLIENT", cls: "bg-cb-brass-tint text-cb-brass-text" }
        : row.blocked
          ? { text: "BLOCKED", cls: "bg-cb-bad-tint text-cb-bad-dark" }
          : { text: "ON TRACK", cls: "bg-cb-ok-tint text-cb-ok-dark" };
  return (
    <span className={cx("rounded-cb-chip px-[6px] py-[2px] font-cb-mono text-[10px] font-semibold tracking-cb-chip", badge.cls)}>
      {badge.text}
    </span>
  );
}

/** Five 4px gate segments: manifest → review → scope → price → offer. */
function GateSegments({ row }: { row: SetRow }) {
  const states = [
    row.gates.manifest,
    row.gates.review,
    row.gates.scope,
    row.price != null,
    row.has_letter,
  ];
  const currentIndex = states.findIndex((s) => !s);
  return (
    <div className="flex gap-1">
      {states.map((passed, i) => (
        <span
          key={i}
          className="h-[4px] flex-1 rounded-[1px]"
          style={{
            background: passed ? "#3C8A63" : i === currentIndex ? "#BD9A5F" : "#E3DED3",
          }}
        />
      ))}
    </div>
  );
}

function relTime(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.round((Date.now() - then) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days}d ago`;
}

// --- the card ---------------------------------------------------------------
export function FolderCard({
  row,
  team,
  currentUserId,
  lastTouchedId,
  onOpen,
  onOpenCitation,
  onConfirmCloseDate,
}: {
  row: SetRow;
  team: TeamMember[];
  currentUserId: string;
  /** The set the current user touched most recently — the brass folder. */
  lastTouchedId: string | null;
  onOpen: () => void;
  /** READ FROM COT is a citation; clicking it must open that page. */
  onOpenCitation: (partId: string, page: number) => void;
  onConfirmCloseDate: (date: string) => void;
}) {
  const tone = cardTone(row, lastTouchedId);
  const days = daysToClose(row);
  const owner = team.find((m) => m.member_id === row.meta.owner_id) ?? null;
  const touchedBy =
    row.meta.last_touched_by === currentUserId
      ? "you"
      : team.find((m) => m.member_id === row.meta.last_touched_by)?.name ?? row.meta.last_touched_by;
  const ingesting = !row.gates.manifest && row.parts === 0;

  return (
    <div className="flex flex-col">
      {/* the folder tab */}
      <div
        className="ml-4 h-[13px] w-[84px] rounded-t-[5px]"
        style={{ background: tone.tab }}
      />
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onOpen();
        }}
        style={{ borderTopColor: tone.border, borderTopWidth: 2 }}
        className="cb-press flex min-h-[250px] flex-1 cursor-pointer flex-col gap-2 rounded-cb-card border border-cb-border bg-cb-page p-[13px] shadow-[0_2px_8px_rgba(12,26,40,.07)]"
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate font-cb-sans text-[12.5px] font-semibold text-cb-ink-text">
              {row.name}
            </div>
            <div className="truncate font-cb-sans text-[10px] font-medium text-cb-muted">
              {[row.meta.client, row.meta.package].filter(Boolean).join(" · ") ||
                `${row.parts} part${row.parts === 1 ? "" : "s"}`}
            </div>
          </div>
          <Avatar member={owner} size={22} />
        </div>

        {/* days to close, between hairlines, with the PROVENANCE of the date */}
        <div className="border-y border-cb-divider py-1.5">
          <div
            className={cx(
              "font-cb-mono text-[21px] font-semibold leading-none",
              days != null && days <= 7 ? "text-cb-bad-dark" : "text-cb-ink-text",
            )}
          >
            {days != null ? `${days}d` : "—"}
            <span className="ml-1.5 font-cb-sans text-[10px] font-medium text-cb-faint">
              to close
            </span>
          </div>
          <CloseDateProvenance
            row={row}
            onOpenCitation={onOpenCitation}
            onConfirm={onConfirmCloseDate}
          />
        </div>

        <GateSegments row={row} />
        <div className="font-cb-mono text-[10px] font-medium text-cb-body">{stageLine(row)}</div>

        {/* the blocking sentence takes the slack so footers align across the shelf */}
        <p className="flex-1 font-cb-serif text-[10.5px] leading-[1.5] text-cb-muted">
          {blockingSentence(row)}
        </p>

        <div className="flex items-center justify-between border-t border-cb-divider pt-2">
          {ingesting ? (
            <span className="font-cb-mono text-[10px] text-cb-blue">READING THE BINDER…</span>
          ) : (
            <StateBadge row={row} />
          )}
          <span className="truncate font-cb-sans text-[10px] text-cb-faint">
            {row.meta.last_touched_at ? `${touchedBy} · ${relTime(row.meta.last_touched_at)}` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}

/** The one thing an AI-read field must always carry: where the value came from.
 *  Three states, per the handoff — a citation, an honest failure, or still reading. */
function CloseDateProvenance({
  row,
  onOpenCitation,
  onConfirm,
}: {
  row: SetRow;
  onOpenCitation: (partId: string, page: number) => void;
  onConfirm: (date: string) => void;
}) {
  const meta = row.meta;
  if (meta.close_date_status === "reading") {
    return <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">READING THE DATE…</div>;
  }
  if (meta.close_date_status === "found" || meta.close_date_status === "confirmed") {
    const cite =
      meta.close_date_status === "found" && meta.close_date_part_id && meta.close_date_page != null;
    return (
      <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">
        {cite ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onOpenCitation(meta.close_date_part_id, meta.close_date_page as number);
            }}
            title={meta.close_date_quote || undefined}
            className="cb-press underline decoration-cb-border-strong underline-offset-2"
          >
            READ FROM COT {meta.close_date_clause ? `cl. ${meta.close_date_clause}` : ""} · p.
            {meta.close_date_page}
          </button>
        ) : (
          <span>
            {meta.close_date_status === "confirmed"
              ? `CONFIRMED BY HAND${meta.close_date_confirmed_by ? ` · ${meta.close_date_confirmed_by.toUpperCase()}` : ""}`
              : "READ FROM COT"}
          </span>
        )}
      </div>
    );
  }
  // not_found: the number shown above is nothing — a person must read the clause and type it.
  return (
    <form
      className="mt-1 flex items-center gap-1"
      onClick={(e) => e.stopPropagation()}
      onSubmit={(e) => {
        e.preventDefault();
        const input = e.currentTarget.elements.namedItem("date") as HTMLInputElement;
        if (input.value) onConfirm(input.value);
      }}
    >
      <span className="font-cb-mono text-[10px] font-semibold text-cb-brass-text">
        DATE NOT FOUND —
      </span>
      <input
        name="date"
        type="date"
        required
        className="rounded-cb-chip border border-cb-border bg-cb-warm px-1 py-0.5 font-cb-mono text-[10px] text-cb-ink-text"
      />
      <button
        type="submit"
        className="cb-press rounded-cb-chip border border-cb-brass-line bg-cb-brass-tint px-1.5 py-0.5 font-cb-mono text-[10px] font-semibold text-cb-brass-text"
      >
        CONFIRM
      </button>
    </form>
  );
}
