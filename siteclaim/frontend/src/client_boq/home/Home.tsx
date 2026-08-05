// The tender desk — a shelf of folders, one per live tender, worked by a small team.
// Frame 00 of the home-page handoff: summary strip, ownership filters, sort, the drop tile,
// and the grid of folder cards. The WHOLE page is a drop target; the tile is only where the
// affordance is stated.

import { useMemo, useState } from "react";
import type { SetRow, TeamMember } from "../types";
import { cx } from "../ui";
import type { ShelfFilter } from "../nav/routes";
import { FolderCard, daysToClose, stageLine } from "./FolderCard";

type OwnerFilter = "everyone" | "mine" | "blocked";
type SortKey = "closing" | "touched" | "client" | "stage";

export function Home({
  rows,
  shelf,
  team,
  currentUserId,
  navOpen,
  onOpenSet,
  onOpenCitation,
  onConfirmCloseDate,
  onBrowse,
  onBrowseFolder,
}: {
  rows: SetRow[];
  shelf: ShelfFilter;
  team: TeamMember[];
  currentUserId: string;
  /** Grid density follows the sidebar: 4 columns open, 5 collapsed — the handoff's numbers. */
  navOpen: boolean;
  onOpenSet: (setId: string) => void;
  onOpenCitation: (setId: string, partId: string, page: number) => void;
  onConfirmCloseDate: (setId: string, date: string) => void;
  onBrowse: () => void;
  onBrowseFolder: () => void;
}) {
  const [owner, setOwner] = useState<OwnerFilter>("everyone");
  const [sort, setSort] = useState<SortKey>("closing");

  const shelved = useMemo(() => {
    if (shelf === "archived") return rows.filter((r) => r.meta.archived);
    const live = rows.filter((r) => !r.meta.archived);
    if (shelf === "awaiting") return live.filter((r) => r.counts.open_rfis > 0);
    return live;
  }, [rows, shelf]);

  const counts = useMemo(
    () => ({
      everyone: shelved.length,
      mine: shelved.filter((r) => r.meta.owner_id === currentUserId).length,
      blocked: shelved.filter((r) => r.blocked).length,
    }),
    [shelved, currentUserId],
  );

  const visible = useMemo(() => {
    let out = shelved;
    if (owner === "mine") out = out.filter((r) => r.meta.owner_id === currentUserId);
    if (owner === "blocked") out = out.filter((r) => r.blocked);
    const sorted = [...out];
    if (sort === "closing") {
      // A tender whose date is unknown cannot claim urgency — unknowns sort last.
      sorted.sort((a, b) => (daysToClose(a) ?? 9e9) - (daysToClose(b) ?? 9e9));
    } else if (sort === "touched") {
      sorted.sort((a, b) =>
        (b.meta.last_touched_at ?? "").localeCompare(a.meta.last_touched_at ?? ""),
      );
    } else if (sort === "client") {
      sorted.sort((a, b) => (a.meta.client || "￿").localeCompare(b.meta.client || "￿"));
    } else {
      sorted.sort((a, b) => stageLine(a).localeCompare(stageLine(b)));
    }
    return sorted;
  }, [shelved, owner, sort, currentUserId]);

  const summary = useMemo(() => {
    const live = rows.filter((r) => !r.meta.archived);
    return {
      live: live.length,
      closingWeek: live.filter((r) => {
        const d = daysToClose(r);
        return d != null && d >= 0 && d <= 7;
      }).length,
      waiting: live.reduce((n, r) => n + r.counts.open_rfis, 0),
      verdicts: live.reduce((n, r) => n + r.counts.undecided, 0),
    };
  }, [rows]);

  const lastTouchedId = useMemo(() => {
    const mine = rows
      .filter((r) => r.meta.last_touched_by === currentUserId && r.meta.last_touched_at)
      .sort((a, b) => (b.meta.last_touched_at ?? "").localeCompare(a.meta.last_touched_at ?? ""));
    return mine[0]?.set_id ?? null;
  }, [rows, currentUserId]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      {/* summary strip */}
      <div className="flex flex-none flex-wrap items-center gap-[22px] bg-cb-panel px-[18px] py-[11px]">
        <Figure label="LIVE TENDERS" value={summary.live} />
        <Figure label="CLOSING THIS WEEK" value={summary.closingWeek} tone={summary.closingWeek > 0 ? "bad" : undefined} />
        <Figure label="WAITING ON THE CLIENT" value={summary.waiting} tone={summary.waiting > 0 ? "warn" : undefined} />
        <Figure label="NEEDS A VERDICT" value={summary.verdicts} />

        <div className="ml-auto flex items-center gap-1.5">
          {(
            [
              ["everyone", `Everyone ${counts.everyone}`],
              ["mine", `Mine ${counts.mine}`],
              ["blocked", `Blocked ${counts.blocked}`],
            ] as [OwnerFilter, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setOwner(key)}
              className={cx(
                "cb-press rounded-cb-pill px-3 py-1 font-cb-sans text-[10.5px] font-medium",
                owner === key
                  ? "bg-cb-ink text-white"
                  : "border border-cb-border bg-cb-surface text-cb-body",
              )}
            >
              {label}
            </button>
          ))}
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="cb-press ml-2 rounded-cb-chip border border-cb-border bg-cb-surface px-2 py-1 font-cb-sans text-[10px] text-cb-body"
          >
            <option value="closing">closing soonest</option>
            <option value="touched">recently touched</option>
            <option value="client">client</option>
            <option value="stage">stage</option>
          </select>
        </div>
      </div>

      {/* the shelf */}
      <div
        className={cx(
          "grid flex-1 content-start gap-4 p-[18px]",
          navOpen ? "grid-cols-4" : "grid-cols-5",
        )}
      >
        {shelf === "desk" && <DropTile onBrowse={onBrowse} onBrowseFolder={onBrowseFolder} />}
        {visible.map((row) => (
          <FolderCard
            key={row.set_id}
            row={row}
            team={team}
            currentUserId={currentUserId}
            lastTouchedId={lastTouchedId}
            onOpen={() => onOpenSet(row.set_id)}
            onOpenCitation={(partId, page) => onOpenCitation(row.set_id, partId, page)}
            onConfirmCloseDate={(date) => onConfirmCloseDate(row.set_id, date)}
          />
        ))}
        {shelf !== "desk" && !visible.length && (
          <div className="col-span-full py-16 text-center">
            <div className="font-cb-serif text-[16px] font-semibold text-cb-ink-text">
              {shelf === "archived" ? "Nothing archived yet." : "Nothing is waiting on the client."}
            </div>
            <p className="mt-2 font-cb-sans text-[11px] text-cb-muted">
              {shelf === "archived"
                ? "Submitted, won and lost tenders leave the shelf and live here — a lost tender's register is the best reference for the next bid to the same client."
                : "Tenders appear here while any query to the client is open."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function Figure({ label, value, tone }: { label: string; value: number; tone?: "bad" | "warn" }) {
  return (
    <div>
      <div className="font-cb-mono text-[8.5px] font-semibold tracking-cb-label text-cb-faint">
        {label}
      </div>
      <div
        className={cx(
          "font-cb-mono text-[17px] font-semibold leading-tight",
          tone === "bad" ? "text-cb-bad-dark" : tone === "warn" ? "text-cb-brass-text" : "text-cb-ink-text",
        )}
      >
        {value}
      </div>
    </div>
  );
}

/** The first cell of the grid. The affordance, not the drop target — the whole page accepts a
 *  drop; this tile is where that is stated, with the sentence that sets expectations.
 *
 *  Two routes in, because tenders arrive both ways. A binder gets split and the split gets
 *  approved; a folder is already organised, so each file is a part and there is nothing to
 *  approve. The tile says which is which rather than making somebody find out by trying. */
function DropTile({ onBrowse, onBrowseFolder }: { onBrowse: () => void; onBrowseFolder: () => void }) {
  return (
    <div
      className="flex min-h-[250px] flex-col items-center justify-center gap-3 self-stretch rounded-[8px] border-[1.5px] border-dashed border-cb-brass bg-cb-selected p-4 text-center"
      style={{ marginTop: 13 /* aligns with card bodies below their tabs */ }}
    >
      <button
        type="button"
        onClick={onBrowse}
        className="cb-press flex flex-col items-center gap-3"
      >
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-cb-brass font-cb-sans text-[20px] font-semibold text-cb-on-brass">
          +
        </span>
        <span className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
          Start a new tender
        </span>
        <span className="max-w-[210px] font-cb-sans text-[10px] leading-[1.55] text-cb-muted">
          Drop the binder anywhere on this page and the split starts, with the close date read
          from the Conditions of Tender for you to confirm.
        </span>
        <span className="font-cb-sans text-[10px] font-medium text-cb-brass-text underline underline-offset-2">
          or browse for a file
        </span>
      </button>

      <span className="my-1 h-px w-24 bg-cb-brass-line" />

      <button type="button" onClick={onBrowseFolder} className="cb-press flex flex-col items-center gap-1">
        <span className="font-cb-sans text-[11px] font-semibold text-cb-ink-text">
          Or upload a whole folder
        </span>
        <span className="max-w-[210px] font-cb-sans text-[10px] leading-[1.55] text-cb-muted">
          Already organised into subfolders? Each file becomes its own part — nothing is split
          and there is nothing to approve.
        </span>
      </button>
    </div>
  );
}
