// The app-level navigation sidebar — 206px open, a 48px icon rail collapsed. Per the home-page
// handoff: three blocks (shelves · CUSTOMISE · ORGANISATION) separated by hairlines, "+ New
// tender" on top doing the same thing as dropping a file, and the signed-in user at the foot.

import type { Surface } from "./routes";
import { go } from "./routes";
import type { TeamMember } from "../types";
import { Avatar, cx } from "../ui";

interface NavItem {
  label: string;
  short: string; // the icon-rail glyph (text for now; swap for the icon set when one exists)
  surface: Surface;
  count?: number;
  countTone?: "plain" | "warn";
}

/** Back to the procurement product. Clearing the hash is all it takes: `main.tsx` branches on
 *  `#/tender` and re-renders the other root. */
function toProcurement() {
  window.location.hash = "";
}

export function NavSidebar({
  open,
  surface,
  counts,
  currentUser,
  onNewTender,
  onSwitchUser,
}: {
  open: boolean;
  surface: Surface;
  counts: { desk: number; archived: number; awaiting: number; criteria: number; team: number };
  currentUser: TeamMember | null;
  onNewTender: () => void;
  onSwitchUser: () => void;
}) {
  const shelves: NavItem[] = [
    { label: "Tender desk", short: "TD", surface: { kind: "home", shelf: "desk" }, count: counts.desk },
    { label: "Archived", short: "AR", surface: { kind: "home", shelf: "archived" }, count: counts.archived },
    { label: "Awaiting client", short: "AW", surface: { kind: "home", shelf: "awaiting" }, count: counts.awaiting, countTone: "warn" },
  ];
  const customise: NavItem[] = [
    { label: "Criteria library", short: "CL", surface: { kind: "screen", screen: "criteria" }, count: counts.criteria },
    { label: "Pricing & rates", short: "PR", surface: { kind: "screen", screen: "rates" } },
    { label: "AI model", short: "AI", surface: { kind: "screen", screen: "settings" } },
    { label: "Letter templates", short: "LT", surface: { kind: "notdesigned", screen: "letters" } },
    { label: "Standard positions", short: "SP", surface: { kind: "notdesigned", screen: "positions" } },
  ];
  const organisation: NavItem[] = [
    { label: "Team & access", short: "TM", surface: { kind: "screen", screen: "team" }, count: counts.team },
    { label: "Clients", short: "CS", surface: { kind: "notdesigned", screen: "clients" } },
    { label: "Audit log", short: "AL", surface: { kind: "notdesigned", screen: "audit" } },
  ];

  const active = (item: NavItem) => sameSurface(item.surface, surface);

  if (!open) {
    return (
      <aside className="flex w-[48px] flex-none flex-col items-center gap-1 overflow-y-auto border-r border-cb-border bg-cb-panel py-2">
        <button
          type="button"
          onClick={onNewTender}
          title="Start a new tender"
          className="cb-press flex h-7 w-7 flex-none items-center justify-center rounded-cb-btn bg-cb-brass font-cb-sans text-[14px] font-semibold text-cb-on-brass"
        >
          +
        </button>
        <button
          type="button"
          onClick={toProcurement}
          title="Procurement — the other product"
          className="cb-press mb-1 flex h-7 w-7 flex-none items-center justify-center rounded-cb-btn border border-cb-border font-cb-mono text-[11px] text-cb-muted"
        >
          ‹
        </button>
        {[shelves, customise, organisation].map((block, bi) => (
          <div key={bi} className="flex w-full flex-col items-center gap-1">
            {bi > 0 && <span className="my-1 h-px w-6 bg-cb-border" />}
            {block.map((item) => (
              <button
                key={item.label}
                type="button"
                title={item.label}
                onClick={() => go(item.surface)}
                className={cx(
                  "cb-press flex h-7 w-7 items-center justify-center rounded-cb-btn font-cb-mono text-[8.5px] font-semibold",
                  active(item)
                    ? "border border-cb-border bg-cb-page text-cb-ink-text"
                    : "text-cb-muted",
                )}
              >
                {item.short}
              </button>
            ))}
          </div>
        ))}
        <div className="mt-auto pt-2">
          <button type="button" onClick={onSwitchUser} title={currentUser?.name ?? "Who are you?"}>
            <Avatar member={currentUser} size={24} />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex w-[206px] flex-none flex-col overflow-y-auto border-r border-cb-border bg-cb-panel">
      <div className="flex flex-col gap-1.5 p-2.5">
        <button
          type="button"
          onClick={onNewTender}
          className="cb-press w-full rounded-[5px] bg-cb-brass px-3 py-2 text-left font-cb-sans text-[11.5px] font-semibold text-cb-on-brass"
        >
          + New tender
        </button>
        {/* The way back to the other product. Setting the hash is the whole navigation —
            main.tsx listens for it and swaps the root — and because it pushes a history entry,
            the browser's Back button works between the two products in both directions. */}
        <button
          type="button"
          onClick={toProcurement}
          title="Switch to the procurement product"
          className="cb-press flex w-full items-center gap-1.5 rounded-[5px] border border-cb-border px-3 py-1.5 text-left font-cb-sans text-[11px] font-medium text-cb-body"
        >
          <span className="font-cb-mono text-[11px] text-cb-muted">‹</span>
          Procurement
        </button>
      </div>
      <NavBlock items={shelves} active={active} />
      <NavBlock heading="CUSTOMISE" items={customise} active={active} />
      <NavBlock heading="ORGANISATION" items={organisation} active={active} />

      <div className="mt-auto flex items-center gap-2 border-t border-cb-border p-2.5">
        <Avatar member={currentUser} size={24} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-cb-sans text-[11px] font-semibold text-cb-ink-text">
            {currentUser?.name ?? "Who are you?"}
          </div>
          <div className="truncate font-cb-sans text-[9.5px] text-cb-muted">
            {currentUser?.role || (currentUser ? "estimator" : "pick a profile")}
          </div>
        </div>
        <button
          type="button"
          onClick={onSwitchUser}
          title="Switch profile"
          className="cb-press flex-none px-1 font-cb-mono text-[12px] text-cb-muted"
        >
          ⋯
        </button>
      </div>
    </aside>
  );
}

function NavBlock({
  heading,
  items,
  active,
}: {
  heading?: string;
  items: NavItem[];
  active: (i: NavItem) => boolean;
}) {
  return (
    <div className="border-t border-cb-border px-2.5 py-2">
      {heading && (
        <div className="px-[9px] pb-1 font-cb-mono text-[8px] font-semibold tracking-cb-label text-cb-faint">
          {heading}
        </div>
      )}
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          onClick={() => go(item.surface)}
          className={cx(
            "cb-press flex w-full items-center justify-between rounded-cb-btn px-[9px] py-[7px] text-left font-cb-sans text-[11px]",
            active(item)
              ? "border border-cb-border bg-cb-page font-semibold text-cb-ink-text"
              : "font-medium text-cb-body",
          )}
        >
          <span>{item.label}</span>
          {item.count != null && item.count > 0 && (
            <span
              className={cx(
                "font-cb-mono text-[9.5px] font-semibold",
                item.countTone === "warn" ? "text-cb-brass-text" : "text-cb-muted",
              )}
            >
              {item.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

function sameSurface(a: Surface, b: Surface): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "home" && b.kind === "home") return a.shelf === b.shelf;
  if ((a.kind === "screen" || a.kind === "notdesigned") && (b.kind === "screen" || b.kind === "notdesigned"))
    return a.screen === b.screen;
  return false;
}
