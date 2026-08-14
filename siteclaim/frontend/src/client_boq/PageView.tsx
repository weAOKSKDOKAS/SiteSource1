// The document pane — pane 3 of every tab. The part's pages, scrolled, with the cited words drawn
// over them.
//
// Pages are PNGs from the backend rather than a client-side PDF render, for one reason that
// matters more than bundle size: the server measured the highlight rectangles in the same
// coordinate space it rasterises from. Nothing has to agree about scale across a process
// boundary. The boxes are fractions of page width and height, so they land correctly at any zoom.
//
// Three things here exist because the first version got them wrong:
//   * pages SCROLL. Clicking prev/next through a 105-page drawings part is not reading.
//   * zoom is a NUMBER YOU TYPE. A five-step array cannot express 155%.
//   * pages load as they approach the viewport. Rendering 105 A3 sheets at once is ~100 MB.

import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { DOC_MIN } from "./chrome";
import type { Highlight, PartRow, SearchHit } from "./types";
import { Chip, cx } from "./ui";

/** Page width in CSS pixels at 100%. A readable A4 column; 150% is comfortable reading. */
const BASE_PAGE_PX = 460;
const MIN_ZOOM = 25;
const MAX_ZOOM = 400;
const DEFAULT_ZOOM = 150;

/** Render enough pixels for the zoom AND the display's density, then quantise.
 *
 *  Quantising to steps of 20 matters: without it every 1% zoom change requests a new DPI and
 *  therefore a new URL, so the browser cache never hits and typing "155" re-fetches every visible
 *  page. With it, a whole band of zoom levels shares one render. */
function dpiFor(zoom: number): number {
  const dpr = typeof window === "undefined" ? 1 : Math.min(window.devicePixelRatio || 1, 2);
  const raw = 96 * (zoom / 100) * dpr;
  return Math.max(96, Math.min(300, Math.round(raw / 20) * 20));
}

export interface PageViewProps {
  setId: string;
  parts: PartRow[];
  /** The part being shown. Null renders the empty state rather than guessing one. */
  partId: string | null;
  /** A source-document page number to scroll to. Null means "nothing has asked yet". */
  page: number | null;
  /** Rectangles to draw — from a citation, or from a search hit. Same shape either way. */
  highlights?: Highlight[];
  onPartChange?: (partId: string) => void;
  onPageChange?: (page: number) => void;
  banner?: React.ReactNode;
  toolbarChip?: React.ReactNode;
  className?: string;
}

function pageRange(part: PartRow | undefined): [number, number] {
  if (!part) return [1, 1];
  const [start, end] = part.pages.split("-").map((n) => parseInt(n, 10));
  return [start || 1, end || start || 1];
}

export function PageView({
  setId,
  parts,
  partId,
  page,
  highlights = [],
  onPartChange,
  onPageChange,
  banner,
  toolbarChip,
  className,
}: PageViewProps) {
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [zoomText, setZoomText] = useState(String(DEFAULT_ZOOM));
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searchable, setSearchable] = useState(true);
  const [searchNote, setSearchNote] = useState("");
  const [visible, setVisible] = useState<number | null>(null);
  const [flash, setFlash] = useState<number | null>(null);
  /** Marks hidden by the reader — Escape or the Clear chip. Reset by anything that changes what
   *  would be marked; see the effect beside `marksFor`. */
  const [dismissed, setDismissed] = useState(false);

  const scroller = useRef<HTMLDivElement | null>(null);
  const pageEls = useRef(new Map<number, HTMLDivElement>());
  const searchTimer = useRef<number | null>(null);
  const suppressScrollSync = useRef(false);

  const part = parts.find((p) => p.part_id === partId);
  const [first, last] = pageRange(part);
  const pageNumbers = useMemo(
    () => (part ? Array.from({ length: last - first + 1 }, (_, i) => first + i) : []),
    [part, first, last],
  );
  const dpi = dpiFor(zoom);
  const widthPx = Math.round((BASE_PAGE_PX * zoom) / 100);

  // A new part invalidates the last part's search — leaving hits up would show results for a
  // document that is no longer on screen.
  //
  // The clear happens in the CLEANUP, i.e. against the part we are leaving. Clearing on the way in
  // wiped the map that the new part's ref callbacks had already filled in the same commit, so the
  // first scroll-to-page after a part change found nothing and silently did nothing — which is why
  // the first citation click landed on page 1 instead of the cited page.
  useEffect(() => {
    setQuery("");
    setHits(null);
    setSearchNote("");
    setSearchable(true);
    scroller.current?.scrollTo({ top: 0 });
    return () => {
      pageEls.current.clear();
    };
  }, [partId]);

  // --- scroll to a requested page ------------------------------------------
  const scrollToPage = useCallback((target: number, why: "jump" | "cite") => {
    const root = scroller.current;
    const el = pageEls.current.get(target);
    if (!root || !el) return;
    // Suppress the observer briefly, or the pages flying past on the way there would each
    // overwrite the indicator and fight the scroll.
    suppressScrollSync.current = true;
    // Scroll THIS pane, by hand. `el.scrollIntoView()` defaults to `inline: "nearest"` and walks
    // every scrollable ancestor — including the app root, which is `overflow-hidden` and therefore
    // has no scrollbar to scroll back with. That is what dragged the whole app bar and the left
    // rail off the left edge whenever a page was brought into view.
    const top = el.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop;
    root.scrollTo({ top, behavior: "smooth" });
    setVisible(target);
    if (why === "cite") {
      setFlash(target);
      window.setTimeout(() => setFlash(null), 1400);
    }
    window.setTimeout(() => {
      suppressScrollSync.current = false;
    }, 600);
  }, []);

  useEffect(() => {
    if (page == null || !part) return;
    if (page < first || page > last) return;
    // Wait a frame so a page that has only just mounted has an element to scroll to.
    const id = window.requestAnimationFrame(() => scrollToPage(page, "cite"));
    return () => window.cancelAnimationFrame(id);
  }, [page, part, first, last, scrollToPage]);

  // --- the indicator follows what is actually on screen ---------------------
  useEffect(() => {
    const root = scroller.current;
    if (!root || !pageNumbers.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (suppressScrollSync.current) return;
        // The page occupying the most of the viewport wins; ties go to the lower page number so
        // the indicator does not flicker between two half-visible pages.
        let best: { n: number; ratio: number } | null = null;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const n = Number((entry.target as HTMLElement).dataset.page);
          if (!best || entry.intersectionRatio > best.ratio + 0.01) best = { n, ratio: entry.intersectionRatio };
        }
        if (best) setVisible(best.n);
      },
      { root, threshold: [0.1, 0.35, 0.6, 0.9] },
    );
    pageEls.current.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [pageNumbers, partId]);

  useEffect(() => {
    if (visible != null) onPageChange?.(visible);
    // onPageChange is deliberately excluded: the parent re-creates it each render, and including
    // it would re-fire on every parent update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  // --- search ---------------------------------------------------------------
  useEffect(() => {
    if (searchTimer.current) window.clearTimeout(searchTimer.current);
    if (!partId || !query.trim()) {
      setHits(null);
      setSearchNote("");
      return;
    }
    searchTimer.current = window.setTimeout(() => {
      api
        .search(setId, partId, query)
        .then((r) => {
          setHits(r.hits);
          setSearchable(r.searchable);
          setSearchNote(r.note);
          if (r.hits.length) scrollToPage(r.hits[0].page, "jump");
        })
        .catch(() => {
          setHits([]);
          setSearchNote("");
        });
    }, 250);
    return () => {
      if (searchTimer.current) window.clearTimeout(searchTimer.current);
    };
  }, [query, partId, setId, scrollToPage]);

  // Both sets of marks show. A search used to REPLACE the citation's highlight, so typing in the
  // search box made the very quotation you were checking disappear off the page — the two answer
  // different questions ("where does this claim sit" vs "where does this word appear") and a
  // reader needs both at once.
  const marksFor = useCallback(
    (n: number): Highlight[] =>
      dismissed
        ? []
        : [
            ...highlights.filter((h) => h.page === n),
            ...(query.trim()
              ? (hits ?? []).filter((h) => h.page === n).flatMap((h) => h.highlights)
              : []),
          ],
    [dismissed, query, hits, highlights],
  );

  // Dismissal is per-answer, not permanent: a new citation or a new search is a new question, and
  // marks that stayed hidden would read as "nothing was found" rather than "you cleared the last
  // one". Anything that changes what would be marked brings the marks back.
  //
  // Keyed BY VALUE, not by array identity. The Register tab builds its highlights inline
  // (`[...(citation?.highlights ?? []), ...located]`), so the array is a new object on every
  // render; an identity-based dependency would fire this effect continuously and clearing would
  // never appear to do anything — on the one tab where citations matter most.
  const markKey = useMemo(
    () =>
      [
        highlights.map((h) => `${h.page}:${h.x0.toFixed(4)},${h.y0.toFixed(4)}`).join("|"),
        query.trim(),
        (hits ?? []).length,
      ].join("#"),
    [highlights, query, hits],
  );
  useEffect(() => {
    setDismissed(false);
  }, [markKey]);

  const hasMarks =
    !dismissed && (highlights.length > 0 || (query.trim() !== "" && (hits ?? []).length > 0));

  function commitZoom(raw: string) {
    const parsed = parseFloat(raw.replace(/[^0-9.]/g, ""));
    if (Number.isFinite(parsed)) {
      const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(parsed)));
      setZoom(next);
      setZoomText(String(next));
    } else {
      setZoomText(String(zoom));
    }
  }

  const fitWidth = useCallback(() => {
    const root = scroller.current;
    if (!root) return;
    // 40px for the scroller's own padding; keep it inside the legal range.
    const next = Math.max(
      MIN_ZOOM,
      Math.min(MAX_ZOOM, Math.round(((root.clientWidth - 40) / BASE_PAGE_PX) * 100)),
    );
    setZoom(next);
    setZoomText(String(next));
  }, []);

  // Fit ONCE when a part opens, and only when the page would not otherwise fit. After that the
  // zoom is the user's: typing 155% and then dragging the divider must not silently rewrite it.
  const fittedFor = useRef<string | null>(null);
  useEffect(() => {
    const root = scroller.current;
    if (!root || !partId || fittedFor.current === partId) return;
    fittedFor.current = partId;
    if (widthPx > root.clientWidth - 40) fitWidth();
  }, [partId, widthPx, fitWidth]);

  return (
    // `minWidth: DOC_MIN` is the floor made real. It used to exist only inside the divider's
    // arithmetic, which meant any mistake there — or a middle width persisted on a wider screen —
    // squeezed this pane to 0px and the PDF vanished with nothing on screen to explain it.
    <div
      style={{ minWidth: DOC_MIN }}
      className={cx("flex min-w-0 flex-1 flex-col overflow-hidden bg-cb-panel", className)}
    >
      {/* --- toolbar --- */}
      <div className="flex flex-none flex-wrap items-center gap-2 border-b border-cb-border bg-cb-surface px-3 py-2">
        <select
          value={partId ?? ""}
          onChange={(e) => onPartChange?.(e.target.value)}
          disabled={!parts.length}
          className="min-w-0 max-w-[190px] flex-none truncate rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1 font-cb-sans text-[10.5px] text-cb-ink-text"
        >
          {!partId && <option value="">Select a part…</option>}
          {parts.map((p) => (
            <option key={p.part_id} value={p.part_id}>
              {p.part_id} · {p.title}
            </option>
          ))}
        </select>

        {/* Jump to a page by number — the stepper's replacement, and faster than it ever was. */}
        {part && (
          <label className="flex flex-none items-center gap-1 font-cb-mono text-[10px] text-cb-muted">
            p.
            <input
              type="number"
              min={first}
              max={last}
              value={visible ?? first}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                if (n >= first && n <= last) scrollToPage(n, "jump");
              }}
              className="w-[52px] rounded-cb-chip border border-cb-border-strong bg-white px-1 py-0.5 text-center tabular-nums"
            />
            <span className="whitespace-nowrap">/ {last}</span>
          </label>
        )}

        {toolbarChip}

        {/* Typed zoom. Any value, not five presets. */}
        <div className="flex flex-none items-center gap-1 font-cb-mono text-[10px] text-cb-muted">
          <button
            type="button"
            title="Zoom out"
            onClick={() => commitZoom(String(zoom - 10))}
            className="cb-press h-5 w-5 rounded-cb-chip border border-cb-border-strong bg-white"
          >
            −
          </button>
          <input
            value={zoomText}
            onChange={(e) => setZoomText(e.target.value)}
            onBlur={(e) => commitZoom(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
            aria-label="Zoom percentage"
            className="w-[44px] rounded-cb-chip border border-cb-border-strong bg-white px-1 py-0.5 text-center tabular-nums"
          />
          <span>%</span>
          <button
            type="button"
            title="Zoom in"
            onClick={() => commitZoom(String(zoom + 10))}
            className="cb-press h-5 w-5 rounded-cb-chip border border-cb-border-strong bg-white"
          >
            +
          </button>
          <button
            type="button"
            title="Fit the page to the pane"
            onClick={fitWidth}
            className="cb-press ml-1 whitespace-nowrap rounded-cb-chip border border-cb-border-strong bg-white px-1.5 py-0.5 font-cb-sans text-[10px] font-medium"
          >
            Fit
          </button>
          {/* Only while there is something to clear. Escape does the same thing, but a
              keyboard-only affordance is one nobody discovers. */}
          {hasMarks && (
            <button
              type="button"
              title="Hide the highlights (Esc). Choosing another citation brings them back."
              onClick={() => setDismissed(true)}
              className="cb-press whitespace-nowrap rounded-cb-chip border border-cb-brass-line bg-cb-brass-tint px-1.5 py-0.5 font-cb-sans text-[10px] font-medium text-cb-brass-text"
            >
              Clear
            </button>
          )}
        </div>

        <div className="flex min-w-[140px] flex-1 items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={part ? `Search ${part.part_id}…` : "Search"}
            disabled={!part}
            className="min-w-0 flex-1 rounded-cb-btn border border-cb-border-strong bg-white px-2 py-1 font-cb-sans text-[10.5px] text-cb-ink-text placeholder:text-cb-faint disabled:bg-cb-panel"
          />
          {query.trim() && hits !== null && (
            <SearchResult
              searchable={searchable}
              hits={hits}
              current={visible ?? first}
              onGo={(p) => scrollToPage(p, "jump")}
            />
          )}
        </div>
      </div>

      {/* The search's honest half: an image-only part could not be looked at, which is a
          different thing from having no matches, and is said differently. */}
      {searchNote && (
        <div className="flex-none border-b border-cb-brass-line bg-cb-brass-tint px-4 py-2 font-cb-sans text-[10.5px] leading-[1.45] text-cb-brass-text">
          {searchNote}
        </div>
      )}

      {banner}

      {/* --- the pages, scrolled --- */}
      <div
        ref={scroller}
        // Focusable so Escape reaches it. -1 keeps it out of the tab order: this is a scroll
        // region, not a control, and it should not sit between the toolbar and the pages.
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === "Escape" && hasMarks) {
            e.stopPropagation();
            setDismissed(true);
          }
        }}
        className="min-h-0 flex-1 overflow-auto p-5 outline-none"
      >
        {!part ? (
          <EmptyPane>Select a part to read it here.</EmptyPane>
        ) : (
          <div className="mx-auto flex flex-col items-center gap-4" style={{ width: widthPx }}>
            {pageNumbers.map((n) => (
              <PageImage
                key={n}
                ref={(el) => {
                  if (el) pageEls.current.set(n, el);
                  else pageEls.current.delete(n);
                }}
                setId={setId}
                partId={part.part_id}
                page={n}
                dpi={dpi}
                width={widthPx}
                root={scroller.current}
                marks={marksFor(n)}
                flash={flash === n}
                title={part.title}
              />
            ))}
            <p className="pb-4 font-cb-mono text-[10px] text-cb-faint">
              end of {part.part_id} · pp. {part.pages}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// One page. Its <img> is not mounted until the page comes near the viewport.
// ---------------------------------------------------------------------------
interface PageImageProps {
  setId: string;
  partId: string;
  page: number;
  dpi: number;
  width: number;
  root: HTMLElement | null;
  marks: Highlight[];
  flash: boolean;
  title: string;
}

const PageImage = forwardRef<HTMLDivElement, PageImageProps>(
  function PageImage(
    { setId, partId, page, dpi, width, root, marks, flash, title },
    ref,
  ) {
    const [near, setNear] = useState(false);
    const [failed, setFailed] = useState(false);
    const [ratio, setRatio] = useState(1.414); // A4 until the real image reports otherwise
    const own = useRef<HTMLDivElement | null>(null);

    // 800px of lookahead: far enough that a page is decoded before it is reached at a normal
    // scroll speed, close enough that a 105-page part never has more than a handful in flight.
    useEffect(() => {
      const el = own.current;
      if (!el || near) return;
      const observer = new IntersectionObserver(
        (entries) => entries.forEach((e) => e.isIntersecting && setNear(true)),
        { root, rootMargin: "800px 0px" },
      );
      observer.observe(el);
      return () => observer.disconnect();
    }, [root, near]);

    useEffect(() => {
      setFailed(false);
    }, [dpi, page]);

    return (
      <div
        ref={(node) => {
          own.current = node;
          if (typeof ref === "function") ref(node);
          else if (ref) (ref as React.MutableRefObject<HTMLDivElement | null>).current = node;
        }}
        data-page={page}
        // The placeholder reserves the page's real height, so the scrollbar does not jump around
        // as pages load in — the single thing that makes lazy loading feel broken.
        style={{ width, height: near ? undefined : Math.round(width * ratio) }}
        className="relative w-full flex-none scroll-mt-4 bg-white shadow-cb-page ring-1 ring-cb-border-strong"
      >
        <span className="pointer-events-none absolute -top-3.5 right-0 font-cb-mono text-[10px] text-cb-faint">
          p. {page}
        </span>

        {near && !failed && (
          <img
            src={api.pageUrl(setId, partId, page, dpi)}
            alt={`${title}, page ${page}`}
            onLoad={(e) => {
              const img = e.currentTarget;
              if (img.naturalWidth) setRatio(img.naturalHeight / img.naturalWidth);
            }}
            onError={() => setFailed(true)}
            className="block w-full select-none"
            draggable={false}
          />
        )}

        {failed && (
          <div className="flex h-full items-center justify-center p-4 text-center font-cb-sans text-[10.5px] leading-[1.5] text-cb-faint">
            Page {page} could not be rendered. The part PDF may have been moved or replaced by a
            revision — re-split the set to restore it.
          </div>
        )}

        {marks.map((h, i) => (
          <mark
            key={i}
            aria-hidden
            style={{
              left: `${h.x0 * 100}%`,
              top: `${h.y0 * 100}%`,
              width: `${(h.x1 - h.x0) * 100}%`,
              height: `${(h.y1 - h.y0) * 100}%`,
            }}
            className={cx(
              // .cb-mark carries the fill and the multiply blend — see tokens.css. No border:
              // multiplying keeps the clause text readable through the mark, so it does not need
              // an outline to be findable.
              "cb-mark pointer-events-none absolute",
              // A one-shot pulse when you arrive from a citation: without it, scrolling to a page
              // that is already highlighted gives no signal that anything happened.
              flash && "animate-[cbMarkFlash_1.4s_ease-out_1]",
            )}
          />
        ))}
      </div>
    );
  },
);

function SearchResult({
  searchable,
  hits,
  current,
  onGo,
}: {
  searchable: boolean;
  hits: SearchHit[];
  current: number;
  onGo: (page: number) => void;
}) {
  if (!searchable) {
    return <Chip className="bg-cb-brass-tint text-cb-brass-text">CANNOT SEARCH</Chip>;
  }
  if (!hits.length) {
    return <Chip className="bg-cb-panel text-cb-muted">NO MATCHES</Chip>;
  }
  const index = hits.findIndex((h) => h.page === current);
  const next = hits[(index + 1) % hits.length];
  return (
    <button
      type="button"
      onClick={() => onGo(next.page)}
      title={`Pages ${hits.map((h) => h.page).join(", ")}`}
      className="cb-press flex-none whitespace-nowrap rounded-cb-chip bg-cb-ok-tint px-[7px] py-[3px] font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-ok-dark"
    >
      {hits.length} PAGE{hits.length === 1 ? "" : "S"} · NEXT p.{next.page}
    </button>
  );
}

function EmptyPane({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center">
      <p className="max-w-[280px] text-center font-cb-sans text-[11px] leading-[1.6] text-cb-faint">
        {children}
      </p>
    </div>
  );
}
