// The app-level navigation sidebar — 206px open, a 48px icon rail collapsed. Per the home-page
// handoff: blocks (shelves · CUSTOMISE · MANAGE · ORGANISATION) separated by hairlines, "+ New
// tender" on top doing the same thing as dropping a file, and the signed-in user at the foot.
//
// There was a "‹ Procurement" button under "+ New tender" (and a "‹" on the icon rail) that
// cleared the hash to swap `main.tsx` to the other root. `main.tsx` no longer forks, so clearing
// the hash lands back on the desk — the control had no destination left and is gone. Its Atlas
// screens are still on disk; they are simply not somewhere the app can send you.

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
  // The LIBRARY: what the company knows, as against what one job needs. Everything here is
  // inherited by every tender and overridable on any of them — rates and outputs are the two
  // halves of the same idea (what a crew costs an hour; how many hours the work takes), so they
  // sit together at the top — and the costing model, which is how the engine turns the two into a
  // bill rate, sits between them.
  const customise: NavItem[] = [
    { label: "Criteria library", short: "CL", surface: { kind: "screen", screen: "criteria" }, count: counts.criteria },
    { label: "Pricing & rates", short: "PR", surface: { kind: "screen", screen: "rates" } },
    { label: "Costing model", short: "CM", surface: { kind: "screen", screen: "costing" } },
    { label: "Outputs & norms", short: "ON", surface: { kind: "screen", screen: "outputs" } },
    { label: "AI model", short: "AI", surface: { kind: "screen", screen: "settings" } },
    { label: "Letter templates", short: "LT", surface: { kind: "notdesigned", screen: "letters" } },
    { label: "Standard positions", short: "SP", surface: { kind: "notdesigned", screen: "positions" } },
  ];
  // The management screens: the firm register, the benchmark corpus and the project spine. These
  // are reference data that outlives any one tender, which is why they sit in the sidebar rather
  // than on a tender's tab strip.
  const manage: NavItem[] = [
    { label: "Subcontractors", short: "SC", surface: { kind: "screen", screen: "subcontractors" } },
    { label: "Benchmarks", short: "BM", surface: { kind: "screen", screen: "benchmarks" } },
    { label: "Projects", short: "PJ", surface: { kind: "screen", screen: "projects" } },
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
        {[shelves, customise, manage, organisation].map((block, bi) => (
          <div key={bi} className="flex w-full flex-col items-center gap-1">
            {bi > 0 && <span className="my-1 h-px w-6 bg-cb-border" />}
            {block.map((item) => (
              <button
                key={item.label}
                type="button"
                title={item.label}
                onClick={() => go(item.surface)}
                className={cx(
                  "cb-press flex h-7 w-7 items-center justify-center rounded-cb-btn font-cb-mono text-[10px] font-semibold",
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
      </div>
      <NavBlock items={shelves} active={active} />
      <NavBlock heading="CUSTOMISE" items={customise} active={active} />
      <NavBlock heading="MANAGE" items={manage} active={active} />
      <NavBlock heading="ORGANISATION" items={organisation} active={active} />

      <div className="mt-auto flex items-center gap-2 border-t border-cb-border p-2.5">
        <Avatar member={currentUser} size={24} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-cb-sans text-[11px] font-semibold text-cb-ink-text">
            {currentUser?.name ?? "Who are you?"}
          </div>
          <div className="truncate font-cb-sans text-[10px] text-cb-muted">
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
        <div className="px-[9px] pb-1 font-cb-mono text-[10px] font-semibold tracking-cb-label text-cb-faint">
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
                "font-cb-mono text-[10px] font-semibold",
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
