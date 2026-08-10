// Hash routing for the tender desk. The browser's history IS the router: every surface is a
// hash, so ← / → in the app bar are history.back()/forward() and survive a reload for free.
// Still no router dependency — the app has one branch point and a parse function.
//
//   #/tender                      the desk (home)
//   #/tender/archived             submitted / won / lost — off the shelf, on the record
//   #/tender/awaiting             tenders with open queries
//   #/tender/criteria|rates|costing|outputs|team|settings   the library screens
//   #/tender/subcontractors|benchmarks|projects   the management screens
//   #/tender/letters|positions|clients|audit  entry points without screens yet
//   #/tender/s/{setId}/{tab}      one tender, one tab

import { TABS } from "../chrome";
import type { TabId } from "../chrome";

export type ShelfFilter = "desk" | "archived" | "awaiting";

// ONE list per family, with the type DERIVED from it — the same fix as TAB_IDS below, for the same
// reason. A hand-maintained `ScreenId` union beside a hand-maintained `SCREENS` array only caught a
// REMOVED screen; an ADDED one compiled cleanly against a stale array and then `parseHash` silently
// dropped its deep link to the desk. Adding the three management screens doubles that list, so it
// is derived now rather than after someone loses a link.
const SCREENS = [
  "criteria",
  "rates",
  "costing",
  "outputs",
  "team",
  "settings",
  "subcontractors",
  "benchmarks",
  "projects",
] as const;
const NOT_DESIGNED = ["letters", "positions", "clients", "audit"] as const;

export type ScreenId = (typeof SCREENS)[number];
export type NotDesignedId = (typeof NOT_DESIGNED)[number];

export type Surface =
  | { kind: "home"; shelf: ShelfFilter }
  | { kind: "screen"; screen: ScreenId }
  | { kind: "notdesigned"; screen: NotDesignedId }
  | { kind: "set"; setId: string; tab: TabId };

// DERIVED, not re-listed. A hand-maintained copy only caught a REMOVED tab (the `TabId[]`
// annotation rejects an unknown string); an ADDED tab compiled cleanly against a stale list and
// then `parseHash` bounced its deep link back to "documents" — a failure invisible until someone
// shared the link. Deriving is the least clever fix that cannot drift.
const TAB_IDS: TabId[] = TABS.map((t) => t.id);

export function parseHash(hash: string): Surface {
  const parts = hash.replace(/^#\/tender\/?/, "").split("/").filter(Boolean);
  if (!parts.length) return { kind: "home", shelf: "desk" };
  if (parts[0] === "archived") return { kind: "home", shelf: "archived" };
  if (parts[0] === "awaiting") return { kind: "home", shelf: "awaiting" };
  if ((SCREENS as readonly string[]).includes(parts[0]))
    return { kind: "screen", screen: parts[0] as ScreenId };
  if ((NOT_DESIGNED as readonly string[]).includes(parts[0]))
    return { kind: "notdesigned", screen: parts[0] as NotDesignedId };
  if (parts[0] === "s" && parts[1]) {
    const tab = (TAB_IDS as string[]).includes(parts[2] ?? "") ? (parts[2] as TabId) : "documents";
    return { kind: "set", setId: decodeURIComponent(parts[1]), tab };
  }
  return { kind: "home", shelf: "desk" };
}

export function hashFor(surface: Surface): string {
  switch (surface.kind) {
    case "home":
      return surface.shelf === "desk" ? "#/tender" : `#/tender/${surface.shelf}`;
    case "screen":
    case "notdesigned":
      return `#/tender/${surface.screen}`;
    case "set":
      return `#/tender/s/${encodeURIComponent(surface.setId)}/${surface.tab}`;
  }
}

/** Navigate by pushing a hash — the browser records it, so Back works. */
export function go(surface: Surface): void {
  window.location.hash = hashFor(surface);
}
