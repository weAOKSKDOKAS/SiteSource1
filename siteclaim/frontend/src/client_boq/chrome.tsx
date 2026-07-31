// The chrome every tab sits inside: app bar, step strip, the folding rail and the drag divider.

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GateStates, SetRow } from "./types";
import { Chip, cx } from "./ui";

// ---------------------------------------------------------------------------
// Steps
// ---------------------------------------------------------------------------
export type TabId = "documents" | "register" | "scope" | "price" | "offer";

export const TABS: { id: TabId; label: string }[] = [
  { id: "documents", label: "Documents" },
  { id: "register", label: "Register" },
  { id: "scope", label: "Scope" },
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
  has: { parts: boolean; register: boolean; scope: boolean; estimate: boolean },
): Record<TabId, StepState> {
  return {
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
        : gates.review
          ? { kind: "waiting", label: "NOT YET RUN" }
          : { kind: "waiting", label: "WAITS ON THE REGISTER" },
    price: has.estimate
      ? { kind: "done" }
      : gates.scope
        ? { kind: "waiting", label: "NOT YET RUN" }
        : { kind: "waiting", label: "WAITS ON THE SCOPE" },
    offer: has.estimate ? { kind: "open" } : { kind: "waiting", label: "WAITS ON THE PRICE" },
  };
}

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
// App bar
// ---------------------------------------------------------------------------
export function AppBar({
  projectName,
  setId,
  demoMode,
  sets,
  railOpen,
  onToggleRail,
  onReopen,
}: {
  projectName: string;
  setId: string;
  demoMode: boolean;
  sets: SetRow[];
  railOpen: boolean;
  onToggleRail: () => void;
  onReopen: (setId: string) => void;
}) {
  return (
    <header className="flex flex-none items-center gap-[13px] bg-cb-ink px-[18px] py-[11px] text-cb-info">
      <button
        type="button"
        onClick={onToggleRail}
        title={railOpen ? "Fold the rail" : "Unfold the rail"}
        aria-pressed={!railOpen}
        className={cx(
          "cb-press flex h-[22px] w-[26px] flex-none flex-col items-center justify-center gap-[3px] rounded-cb-btn border",
          railOpen ? "border-cb-navy-line" : "border-cb-brass bg-cb-ink-active",
        )}
      >
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={cx("h-[1.5px] w-3", railOpen ? "bg-cb-info" : "bg-cb-brass")}
          />
        ))}
      </button>

      <span className="flex-none font-cb-sans text-[12.5px] font-semibold">{projectName}</span>

      <span className="flex-none whitespace-nowrap rounded-cb-chip border border-cb-navy-line px-[7px] py-[3px] font-cb-mono text-[10px] font-medium text-cb-dim">
        set_id · {setId}
      </span>

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

      <label className="ml-auto flex flex-none items-center gap-2">
        <span className="sr-only">Reopen a set</span>
        <select
          value={setId}
          onChange={(e) => onReopen(e.target.value)}
          className="cb-press max-w-[220px] truncate rounded-cb-chip border border-cb-navy-line bg-transparent px-2 py-1 font-cb-sans text-[10.5px] text-cb-dim"
        >
          {sets.map((s) => (
            <option key={s.set_id} value={s.set_id} className="text-cb-ink-text">
              {s.name} · {s.parts} parts
            </option>
          ))}
        </select>
      </label>
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

/** How narrow the document pane may get before it is worth collapsing entirely. Half the old
 *  ~320px floor, which is what the user asked for; below it a page is unreadable anyway. */
export const DOC_MIN = 160;

/** Clamp a middle-column width against the space actually available.
 *
 *  The old caps were hard-coded (760px / 820px) and were the real reason the divider "would not
 *  go right" — on a wide screen they stopped nowhere near the edge. Deriving the limit from the
 *  container means the divider always travels as far as the layout genuinely allows. */
export function clampMiddle(
  next: number,
  { container, rail, min = 320 }: { container: number; rail: number; min?: number },
): number {
  const room = Math.max(min, container - rail - 9 /* divider */ - DOC_MIN);
  return Math.max(min, Math.min(room, next));
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
export function usePanes(tab: string, railInitial: number, midInitial: number) {
  const [railWidth, setRailWidth] = usePersisted(`${tab}.rail`, railInitial);
  const [midWidth, setMidWidth] = usePersisted(`${tab}.mid`, midInitial);
  const [docCollapsed, setDocCollapsed] = usePersisted(`${tab}.docCollapsed`, false);
  const container = useRef<HTMLDivElement | null>(null);

  const dragRail = useCallback(
    (dx: number) => setRailWidth(Math.max(RAIL_MIN, Math.min(RAIL_MAX, railWidth + dx))),
    [railWidth, setRailWidth],
  );

  const dragMiddle = useCallback(
    (dx: number) => {
      const width = container.current?.clientWidth ?? window.innerWidth;
      const wanted = midWidth + dx;
      const room = width - railWidth - 9 - DOC_MIN;
      // Dragging decisively past the floor collapses the pane rather than jamming against it.
      if (wanted > room + 60) {
        setDocCollapsed(true);
        return;
      }
      setMidWidth(clampMiddle(wanted, { container: width, rail: railWidth }));
    },
    [midWidth, railWidth, setMidWidth, setDocCollapsed],
  );

  return {
    container,
    railWidth,
    midWidth,
    docCollapsed,
    dragRail,
    dragMiddle,
    openDoc: () => setDocCollapsed(false),
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
