// The chrome every tab sits inside: app bar, step strip, the folding rail and the drag divider.

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GateStates } from "./types";
import { Chip, cx } from "./ui";

// ---------------------------------------------------------------------------
// Steps
// ---------------------------------------------------------------------------
export type TabId =
  | "documents"
  | "register"
  | "scope"
  | "site"
  | "route"
  | "sourcing"
  | "price"
  | "offer";

// The order IS the reading order of a tender: what arrived, what we found in it, what we are
// pricing, who builds each package, who quotes the ones we sublet, the price, the offer.
//
// `route` and `sourcing` split at the routing decision. `sourcing` holds shortlist → dispatch →
// level → recommend as internal steps rather than four more tabs, because they are already a
// wizard with a stepper of their own.
export const TABS: { id: TabId; label: string }[] = [
  { id: "documents", label: "Documents" },
  { id: "register", label: "Register" },
  { id: "scope", label: "Scope" },
  { id: "site", label: "Site" },
  { id: "route", label: "Route" },
  { id: "sourcing", label: "Sourcing" },
  { id: "price", label: "Price" },
  { id: "offer", label: "Offer" },
];

export type StepState =
  | { kind: "done" }
  | { kind: "open"; shown?: boolean }
  | { kind: "waiting"; label: string };

/** What each step's chip says, given the gates and what has actually been run.
 *
 *  No step is ever disabled — a step that has not run opens and states what it is waiting for.
 *  The design replaced a padlock with this, because locking a tab produces a dead end and a
 *  409; a tab that opens and explains itself does not. */
export function stepStates(
  gates: GateStates,
  has: {
    parts: boolean;
    register: boolean;
    scope: boolean;
    estimate: boolean;
    // The routing fork. `proposal` = a route has been proposed for at least one package;
    // `decisions` = a human has chosen at least one. Both are read back from the bridge rather
    // than remembered, so a reload does not reset a chip to a state the tender is past.
    proposal: boolean;
    decisions: boolean;
    /** The take-off has been read. Site has no gate, so this only decides what its chip says. */
    site?: boolean;
    /** Holes with no access class. Carried on PRICE, not on Site — an unclassed hole cannot stop
     *  you pricing, but it is the sweep that will refuse, and the warning belongs where the
     *  consequence lands. */
    unassignedHoles?: number;
    /** The tender has been submitted — the offer step's terminal `done`. The finer lifecycle
     *  (priced → not yet approved → approved → submitted) lives inside the Offer tab, which is
     *  where the approve and submit actions are; the chip only needs the terminal fact. */
    submitted?: boolean;
  },
  /** The tab whose work is RUNNING right now, if any.
   *
   *  Without this the chips and the job disagree by construction: the chips are computed from
   *  `data`, which does not change until a run finishes, so a review in flight showed
   *  `NOT YET RUN` on the same screen as a strip reading `REVIEW · Still running`, above a run
   *  button the tab itself had disabled because it knew perfectly well it was busy.
   *
   *  A display fix, deliberately: the job is still owned where it was, and this only stops one
   *  surface saying something the surface beside it contradicts. */
  running: TabId | null = null,
  /** V1: the review gate is soft, so an unapproved register no longer BLOCKS scope or routing —
   *  it warns on the response and the tab renders that warning in amber.
   *
   *  The chips have to agree with that or they become the lie: a step reading `WAITS ON THE
   *  REGISTER` beside a Run button that works is the same class of contradiction as a tab saying
   *  `NOT YET RUN` above a strip saying `RUNNING`. Soft mode reads these two steps exactly as it
   *  would with the register approved.
   *
   *  Only these two. `sourcing` still waits on a route DECISION and `price` on the scope gate —
   *  those are data dependencies (there is nothing to source without a decision, nothing to price
   *  without a frozen scope), not the review gate, and the soft switch must not reach them. */
  reviewGateSoft = false,
): Record<TabId, StepState> {
  // The review gate as the downstream steps should read it. Soft mode does not mark the register
  // approved — `gates.review` is untouched and the Register tab still shows the real state — it
  // only stops scope and route from claiming they are blocked by something that is not blocking.
  const reviewClear = gates.review || reviewGateSoft;
  const unassigned = has.unassignedHoles ?? 0;
  const states = {
    documents: gates.manifest ? { kind: "done" } : has.parts ? { kind: "open" } : { kind: "open" },
    register: gates.review
      ? { kind: "done" }
      : has.register
        ? { kind: "open" }
        : gates.manifest
          ? { kind: "waiting", label: "NOT YET RUN" }
          : { kind: "waiting", label: "WAITS ON THE MANIFEST" },
    scope: gates.scope
      ? { kind: "done" }
      : has.scope
        ? { kind: "open" }
        : reviewClear
          ? { kind: "waiting", label: "NOT YET RUN" }
          : { kind: "waiting", label: "WAITS ON THE REGISTER" },
    // Site never waits and never blocks. The take-off is a thing you look up, and there is no
    // point at which looking something up should be refused.
    site: has.site ? { kind: "open" } : { kind: "waiting", label: "NO TAKE-OFF YET" },
    // Routing sits behind the review gate and both forks inherit it: you cannot decide
    // self-perform vs sublet without knowing the contract terms, and you should not send an RFQ
    // on terms nobody has read. Same chain as `scope` above, ending at the human decision.
    route: has.decisions
      ? { kind: "done" }
      : has.proposal
        ? { kind: "open" }
        : reviewClear
          ? { kind: "waiting", label: "NOT YET RUN" }
          : { kind: "waiting", label: "WAITS ON THE REGISTER" },
    // Sourcing prices only what we sublet, so it waits on the decision that says which packages
    // those are. It has no "done": an award is per package, not per tender.
    sourcing: has.decisions
      ? { kind: "open" }
      : { kind: "waiting", label: "WAITS ON THE ROUTE" },
    // `gates.scope` is client_boq's ESTIMATE scope gate — a different thing from the bill split
    // the Route tab runs, which is never called "scope" in this UI. Unassigned access-class holes
    // warn HERE, not on Site — the sweep is what will refuse, so the warning sits where the
    // consequence lands.
    price:
      unassigned > 0
        ? { kind: "waiting", label: `⚠ ${unassigned} HOLES UNASSIGNED` }
        : has.estimate
          ? { kind: "done" }
          : gates.scope
            ? { kind: "waiting", label: "NOT YET RUN" }
            : { kind: "waiting", label: "WAITS ON THE SCOPE" },
    // The last step: priced → (approve/submit happen in-tab) → submitted. `done` only once the
    // tender is actually out the door; before that it opens, because approving and submitting are
    // both actions you take here, not states you wait on.
    offer: has.submitted
      ? { kind: "done" }
      : has.estimate
        ? { kind: "open" }
        : { kind: "waiting", label: "WAITS ON THE PRICE" },
  } as Record<TabId, StepState>;
  // A running step says so, whatever it would otherwise have said — including over a `done`,
  // because a RE-run is still a run in flight.
  if (running && states[running]) states[running] = { kind: "waiting", label: "RUNNING…" };
  return states;
}

/** Which tab owns a job of this kind. The job store names workflows; the tab strip names tabs,
 *  and one screen has to be able to translate between them. Unknown kinds map to nothing rather
 *  than to a guess. */
export const TAB_FOR_JOB: Record<string, TabId> = {
  ingest: "documents",
  review: "register",
  scope: "scope",
  estimate: "price",
  // The bridge's whole-pack archive extract. It lands parts in Documents, exactly as an ingest
  // does. Absent before `/jobs/live` existed and harmless then — nothing looked a job's kind up
  // except a loop that already had one — but a recovered archive job would have mapped to nothing
  // and left the chips silent while the strip said it was running.
  archive: "documents",
};

function chipFor(state: StepState, current: boolean) {
  if (state.kind === "done") return { text: "✓ DONE", cls: "text-cb-ok" };
  if (state.kind === "open")
    return { text: current ? "OPEN · SHOWN" : "OPEN", cls: "text-cb-brass-text" };
  return { text: state.label, cls: "text-cb-faint" };
}

export function StepStrip({
  current,
  states,
  opened,
  onSelect,
}: {
  current: TabId;
  states: Record<TabId, StepState>;
  /** Steps the user has actually opened this session — a lighter underline than the shown one. */
  opened: Set<TabId>;
  onSelect: (id: TabId) => void;
}) {
  return (
    // Full width and ABOVE the rail: rail contents change per tab, the steps do not, so folding
    // the rail must not move them.
    <nav className="flex flex-none items-center overflow-x-auto border-b border-cb-border bg-cb-panel px-[18px]">
      {TABS.map((tab, i) => {
        const state = states[tab.id];
        const chip = chipFor(state, tab.id === current);
        const isCurrent = tab.id === current;
        const isOpen = !isCurrent && opened.has(tab.id);
        return (
          <div key={tab.id} className="flex flex-none items-center">
            {i > 0 && <span className="flex-none px-1 text-cb-border-strong">›</span>}
            <button
              type="button"
              onClick={() => onSelect(tab.id)}
              className={cx(
                "cb-press flex flex-none items-center gap-2 whitespace-nowrap px-[14px] py-[9px] font-cb-sans text-[11px]",
                isCurrent
                  ? "font-semibold text-cb-ink-text shadow-[inset_0_-2px_0_var(--color-cb-brass)]"
                  : isOpen
                    ? "font-semibold text-cb-body shadow-[inset_0_-2px_0_var(--color-cb-brass-line)]"
                    : "font-medium text-cb-muted",
              )}
            >
              <span>{tab.label}</span>
              <span
                className={cx(
                  "flex-none whitespace-nowrap font-cb-mono text-[9px] font-medium",
                  chip.cls,
                )}
              >
                {chip.text}
              </span>
            </button>
          </div>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// The global app bar — the same five nav controls on every screen, home and tender alike
// ---------------------------------------------------------------------------
/** Track our own position in the hash history, so → can honestly dim when there is nowhere to
 *  go. Each new entry gets an index stamped into history.state; back/forward restores it. */
export function useHashHistory(): { canBack: boolean; canForward: boolean } {
  const [idx, setIdx] = useState<number>(() => {
    const state = window.history.state as { cbIdx?: number } | null;
    if (state?.cbIdx == null) window.history.replaceState({ cbIdx: 0 }, "");
    return (window.history.state as { cbIdx?: number })?.cbIdx ?? 0;
  });
  const [max, setMax] = useState(idx);
  useEffect(() => {
    const onChange = () => {
      let state = window.history.state as { cbIdx?: number } | null;
      if (state?.cbIdx == null) {
        // A pushed entry (new navigation) has no stamp yet — it sits one past wherever we were.
        window.history.replaceState({ cbIdx: idx + 1 }, "");
        state = window.history.state as { cbIdx?: number };
      }
      const next = state?.cbIdx ?? 0;
      setIdx(next);
      setMax((m) => Math.max(m, next));
    };
    window.addEventListener("popstate", onChange);
    window.addEventListener("hashchange", onChange);
    return () => {
      window.removeEventListener("popstate", onChange);
      window.removeEventListener("hashchange", onChange);
    };
  }, [idx]);
  return { canBack: idx > 0, canForward: idx < max };
}

function BarButton({
  onClick,
  title,
  active,
  disabled,
  children,
}: {
  onClick: () => void;
  title: string;
  active?: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={cx(
        "cb-press flex h-6 w-[27px] flex-none items-center justify-center rounded-cb-btn border font-cb-mono text-[12px]",
        active
          ? "border-cb-brass bg-cb-ink-active text-cb-brass"
          : "border-cb-navy-line text-cb-dim",
        disabled && "cursor-not-allowed opacity-40",
      )}
    >
      {children}
    </button>
  );
}

export function GlobalBar({
  navOpen,
  onToggleNav,
  railOpen,
  onToggleRail,
  railEnabled,
  onSearch,
  title,
  meta,
  demoMode,
  right,
}: {
  navOpen: boolean;
  onToggleNav: () => void;
  /** The current tab's own rail — a separate control from ☰. Disabled off tender screens,
   *  where there is nothing to toggle. */
  railOpen: boolean;
  onToggleRail: () => void;
  railEnabled: boolean;
  onSearch: () => void;
  title: string;
  /** The mono chip beside the title (set_id on a tender, nothing on home). */
  meta?: string;
  demoMode: boolean;
  /** The right edge: avatar stack + deadline on a tender, the signed-in user on home. */
  right?: ReactNode;
}) {
  const { canBack: cbBack, canForward } = useHashHistory();
  // Arriving from procurement (the logo menu sets the hash) mounts this app fresh at index 0, so
  // our own counter says "nowhere to go back to" while the procurement page sits right behind us.
  // The browser's own history length is the honest tiebreak.
  const canBack = cbBack || window.history.length > 1;
  return (
    <header className="flex flex-none items-center gap-2 bg-cb-ink px-4 py-[9px] text-cb-info">
      <BarButton onClick={onToggleNav} title="Navigation sidebar" active={!navOpen}>
        ☰
      </BarButton>
      <BarButton
        onClick={onToggleRail}
        title={railEnabled ? "This tab's side panel" : "No side panel on this screen"}
        active={railEnabled && !railOpen}
        disabled={!railEnabled}
      >
        ▯
      </BarButton>
      <BarButton onClick={onSearch} title="Search (Ctrl-K)">
        ⌕
      </BarButton>
      <BarButton onClick={() => window.history.back()} title="Back" disabled={!canBack}>
        ←
      </BarButton>
      <BarButton onClick={() => window.history.forward()} title="Forward" disabled={!canForward}>
        →
      </BarButton>

      <span className="mx-1 h-[18px] w-px flex-none bg-cb-navy-line" />

      <span className="flex-none truncate font-cb-sans text-[12.5px] font-semibold">{title}</span>
      {meta && (
        <span className="flex-none whitespace-nowrap rounded-cb-chip border border-cb-navy-line px-[7px] py-[3px] font-cb-mono text-[10px] font-medium text-cb-dim">
          {meta}
        </span>
      )}

      {/* Not decoration. DEMO means the uploaded files were never read and every finding on
          screen came from a fixture — the one fact that changes how to read the whole app. */}
      {demoMode && (
        <Chip
          className="bg-cb-amber text-cb-on-brass"
          title="Offline demo: uploads were not read and all findings are canned."
        >
          DEMO — UPLOADS NOT READ
        </Chip>
      )}

      <span className="ml-auto flex flex-none items-center gap-2">{right}</span>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Divider — drag to resize the middle column against the document pane
// ---------------------------------------------------------------------------
export function Divider({
  onDrag,
  subtle,
}: {
  onDrag: (deltaX: number) => void;
  /** The rail's divider is quieter than the main one — it resizes chrome, not content. */
  subtle?: boolean;
}) {
  const dragging = useRef(false);
  const lastX = useRef(0);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    lastX.current = e.clientX;
    // Capture, so the drag survives the pointer leaving the 9px strip — otherwise a fast drag
    // detaches the moment it outruns the handle.
    e.currentTarget.setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging.current) return;
      onDrag(e.clientX - lastX.current);
      lastX.current = e.clientX;
    },
    [onDrag],
  );

  const stop = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
  }, []);

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      className={cx(
        "flex flex-none cursor-col-resize touch-none select-none items-center justify-center",
        subtle
          ? "w-[5px] border-r border-cb-border bg-cb-surface hover:bg-cb-desk"
          : "w-[9px] border-x border-cb-border-strong bg-cb-desk",
      )}
    >
      <div className="flex flex-col gap-[3px]">
        {(subtle ? [0, 1, 2] : [0, 1, 2, 3, 4]).map((i) => (
          <span key={i} className="h-[3px] w-[3px] rounded-full bg-cb-faint" />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rail
// ---------------------------------------------------------------------------
export function Rail({
  width,
  children,
  className,
  onResize,
}: {
  width: number;
  children: ReactNode;
  className?: string;
  /** Supply this to make the rail draggable. Omit it and the rail is a fixed width. */
  onResize?: (deltaX: number) => void;
}) {
  return (
    <>
      <aside
        style={{ width }}
        className={cx(
          "flex flex-none flex-col overflow-y-auto bg-cb-surface",
          !onResize && "border-r border-cb-border",
          className,
        )}
      >
        {children}
      </aside>
      {onResize && <Divider onDrag={onResize} subtle />}
    </>
  );
}

export const RAIL_MIN = 180;
export const RAIL_MAX = 420;
export const RAIL_FOLDED = 44;   // the count strip RailFolded renders at

/** How narrow the document pane may get before it is worth collapsing entirely.
 *
 *  480px is not a taste call: `PageView.BASE_PAGE_PX` is 460, so a page at 100% zoom fits inside
 *  480 with no sideways scrolling at all. Below that you are scrolling a page rather than reading
 *  one, and the honest move is the tab.
 *
 *  This number is ALSO applied as a real CSS `min-width` on the pane. It used to live only inside
 *  the arithmetic below, which meant a stale persisted middle width squeezed the pane to literally
 *  0px and the PDF silently vanished. */
export const DOC_MIN = 480;

/** The middle column's own floor. Narrower than this and the register table is unusable. */
export const MID_MIN = 320;

/** Both dividers: the subtle 5px one beside the rail and the 9px one beside the document pane.
 *  The old arithmetic counted only the 9 and was therefore 5px optimistic everywhere. */
export const DIVIDERS = 14;

/** Clamp a middle-column width against the space actually available.
 *
 *  The old caps were hard-coded (760px / 820px) and were the real reason the divider "would not
 *  go right" — on a wide screen they stopped nowhere near the edge. Deriving the limit from the
 *  container means the divider always travels as far as the layout genuinely allows. */
export function clampMiddle(
  next: number,
  { container, rail, min = MID_MIN }: { container: number; rail: number; min?: number },
): number {
  const room = Math.max(min, container - rail - DIVIDERS - DOC_MIN);
  return Math.max(min, Math.min(room, next));
}

/** What the three panes should be, given the width there actually is.
 *
 *  This is the piece that was missing entirely: nothing ever re-measured, so a layout persisted on
 *  a wide monitor was re-applied verbatim on a narrow window and simply ran off the right-hand
 *  edge — where the app root's `overflow-hidden` then CLIPPED it, putting the far pane out of
 *  reach rather than merely out of sight.
 *
 *  Capacity is given up in a stated order, stopping at the first step that fits. It is the design
 *  handoff's own order ("below 1280 the rail folds, then the third pane becomes a tab"), which had
 *  been written down and never built:
 *
 *    1. the middle column shrinks toward MID_MIN
 *    2. the rail folds to its 44px count strip
 *    3. the document pane collapses to its tab
 *
 *  Steps 2 and 3 are automatic AND reversible — widening the window undoes them — but they never
 *  override a fold the user performed deliberately, which is what the `userFolded` flags carry.
 */
export function fitPanes(
  container: number,
  current: { rail: number; mid: number; railOpen: boolean; docCollapsed: boolean },
  userFolded: { rail: boolean; doc: boolean },
): { mid: number; foldRail: boolean; collapseDoc: boolean } {
  const railWidth = current.railOpen ? current.rail : RAIL_FOLDED;

  // Step 1 — can it fit by shrinking the middle column alone?
  const roomForMid = container - railWidth - DIVIDERS - DOC_MIN;
  if (roomForMid >= MID_MIN) {
    return {
      mid: Math.max(MID_MIN, Math.min(roomForMid, current.mid)),
      // There is room; undo an automatic fold, but leave a deliberate one alone.
      foldRail: userFolded.rail ? !current.railOpen : false,
      collapseDoc: userFolded.doc ? current.docCollapsed : false,
    };
  }

  // Step 2 — fold the rail and try again.
  const roomFolded = container - RAIL_FOLDED - DIVIDERS - DOC_MIN;
  if (roomFolded >= MID_MIN) {
    return {
      mid: Math.max(MID_MIN, Math.min(roomFolded, current.mid)),
      foldRail: true,
      collapseDoc: userFolded.doc ? current.docCollapsed : false,
    };
  }

  // Step 3 — the document pane becomes a tab; the middle column takes what is left.
  return { mid: MID_MIN, foldRail: true, collapseDoc: true };
}

/** The document pane, folded away to a strip you click to bring back. The design specified this
 *  ("the PDF collapses to a tab at its widest") and the first build never did it. */
export function DocTab({ onOpen, label }: { onOpen: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      title="Show the document pane"
      className="cb-press flex w-[34px] flex-none flex-col items-center justify-center gap-3 border-l border-cb-border-strong bg-cb-panel py-4"
    >
      <span className="font-cb-mono text-[11px] text-cb-brass">‹</span>
      <span
        className="whitespace-nowrap font-cb-mono text-[9px] tracking-cb-chip text-cb-muted"
        style={{ writingMode: "vertical-rl" }}
      >
        {label}
      </span>
    </button>
  );
}

/** The 44px folded rail: counts only, so the register and the page absorb the freed width. */
export function RailFolded({ lines }: { lines: { value: string; label: string }[] }) {
  return (
    <aside className="flex w-[44px] flex-none flex-col items-center gap-3 border-r border-cb-border bg-cb-panel py-4">
      {lines.map((line, i) => (
        <div key={line.label} className="flex flex-col items-center">
          {i > 0 && <span className="mb-3 h-px w-4 bg-cb-border-strong" />}
          <span className="font-cb-mono text-[11px] font-semibold text-cb-ink-text">
            {line.value}
          </span>
          <span className="font-cb-mono text-[7.5px] font-medium tracking-cb-chip text-cb-faint">
            {line.label}
          </span>
        </div>
      ))}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Persistence — the rail state and the split ratio survive a reload, per the design
// ---------------------------------------------------------------------------
/** Rail width, middle-column width, and whether the document pane is collapsed — for one tab.
 *
 *  Shared rather than duplicated per tab because the limits are the interesting part: they are
 *  derived from the container so the divider always travels as far as the layout allows, and
 *  dragging past the document pane's floor collapses it instead of jamming.
 */
export function usePanes(
  tab: string,
  railInitial: number,
  midInitial: number,
  /** Whether the tab is rendering its full rail or the 44px count strip. The arithmetic used to
   *  ignore this and reserve the full rail width even while the folded strip was on screen,
   *  which stopped the divider ~200px short of where it could actually travel. */
  railOpen = true,
) {
  const [railWidth, setRailWidth] = usePersisted(`${tab}.rail`, railInitial);
  const [midWidth, setMidWidth] = usePersisted(`${tab}.mid`, midInitial);
  const [docCollapsed, setDocCollapsed] = usePersisted(`${tab}.docCollapsed`, false);
  /** Did a PERSON fold these, or did the window? An automatic fold must undo itself when the
   *  room comes back; a deliberate one must not. */
  const [userFoldedDoc, setUserFoldedDoc] = usePersisted(`${tab}.docUserSet`, false);
  const [autoFoldRail, setAutoFoldRail] = useState(false);
  /** A CALLBACK ref held in state, not a plain `useRef`.
   *
   *  A tab may not render its container on the first pass — Price returns a "Reading the
   *  estimate…" panel while it loads, Register a gate explanation — and with a plain ref the
   *  refit effect below runs once against `null`, bails, and then never re-runs, because nothing
   *  in its dependency list changes when the div finally mounts. The result is a layout that is
   *  never measured at all: exactly the right-hand overflow this hook exists to prevent, on
   *  precisely the tabs that load something first. Holding the node in state re-runs the effect
   *  the moment it attaches. */
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const container = useCallback((el: HTMLDivElement | null) => setNode(el), []);

  const effectiveRailOpen = railOpen && !autoFoldRail;
  const renderedRail = effectiveRailOpen ? railWidth : RAIL_FOLDED;

  // --- refit whenever the space changes ------------------------------------
  // The whole point: on mount and on every resize, not only while dragging.
  useEffect(() => {
    const el = node;
    if (!el) return;
    const apply = () => {
      const width = el.clientWidth;
      if (!width) return;
      const next = fitPanes(
        width,
        { rail: railWidth, mid: midWidth, railOpen, docCollapsed },
        { rail: false, doc: userFoldedDoc },
      );
      if (next.mid !== midWidth) setMidWidth(next.mid);
      if (next.foldRail !== autoFoldRail) setAutoFoldRail(next.foldRail);
      if (next.collapseDoc !== docCollapsed) setDocCollapsed(next.collapseDoc);
    };
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(el);
    return () => observer.disconnect();
  }, [node, railWidth, midWidth, railOpen, docCollapsed, userFoldedDoc, autoFoldRail, setMidWidth, setDocCollapsed]);

  const dragRail = useCallback(
    (dx: number) => setRailWidth(Math.max(RAIL_MIN, Math.min(RAIL_MAX, railWidth + dx))),
    [railWidth, setRailWidth],
  );

  const dragMiddle = useCallback(
    (dx: number) => {
      const width = node?.clientWidth ?? window.innerWidth;
      const wanted = midWidth + dx;
      const room = width - renderedRail - DIVIDERS - DOC_MIN;
      // Dragging decisively PAST the floor collapses the pane rather than jamming against it.
      // `dx > 0` matters: without it, a middle width that is already over-wide collapses the pane
      // even on a leftward drag — i.e. dragging to ENLARGE the PDF made it disappear.
      if (dx > 0 && wanted > room + 60) {
        setUserFoldedDoc(true);
        setDocCollapsed(true);
        return;
      }
      setMidWidth(clampMiddle(wanted, { container: width, rail: renderedRail }));
    },
    [node, midWidth, renderedRail, setMidWidth, setDocCollapsed, setUserFoldedDoc],
  );

  return {
    container,
    railWidth,
    midWidth,
    docCollapsed,
    /** False when the window folded the rail for lack of room, even if the user wants it open. */
    railOpen: effectiveRailOpen,
    dragRail,
    dragMiddle,
    openDoc: () => {
      setUserFoldedDoc(false);
      setDocCollapsed(false);
    },
  };
}

export function usePersisted<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(`cboq.${key}`);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(`cboq.${key}`, JSON.stringify(value));
    } catch {
      /* a full or blocked localStorage must not break the app */
    }
  }, [key, value]);
  return [value, setValue];
}
