// A slippy map, in about two hundred lines and no dependency.
//
// WHY NOT LEAFLET. The app has five runtime dependencies and every one of them earns its place.
// What this map has to do is small and completely specified: draw XYZ tiles for a bounded region,
// pan, zoom, and put markers at known lat/lons. That is Web Mercator arithmetic and absolutely
// positioned <img> tags. A mapping library would bring a stylesheet, a plugin ecosystem, and a
// CRS abstraction for a case that has exactly one CRS.
//
// THE TILES are the Lands Department's, which are keyless and have the best rural New Territories
// coverage there is — which matters, because the holes that are hard to classify are the ones on
// hillsides. They are served in the standard Web Mercator XYZ scheme, so the tile maths below is
// the ordinary one and nothing here is Hong Kong-specific except the default view.
//
// A TILE THAT DOES NOT LOAD is left as an empty square rather than retried or hidden. In DEMO
// there is no network, so the map draws its markers over blank ground and says so in the caption —
// which is the honest picture. Pretending is the failure mode this whole product is built against.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { cx } from "../ui";

const TILE = 256;
const MIN_ZOOM = 10;
const MAX_ZOOM = 19;

export interface MapPoint {
  id: string;
  lat: number;
  lon: number;
  label: string;
  /** Drives the pin's colour. "" means nobody has decided, which is the state that matters. */
  tone: "undecided" | "a" | "b" | "c" | "road";
  count?: number;
}

/** Web Mercator. x and y are in tile units at zoom `z` — fractional, so a point lands inside one. */
function project(lat: number, lon: number, z: number): { x: number; y: number } {
  const n = 2 ** z;
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const rad = (clamped * Math.PI) / 180;
  return {
    x: ((lon + 180) / 360) * n,
    y: ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n,
  };
}

function unproject(x: number, y: number, z: number): { lat: number; lon: number } {
  const n = 2 ** z;
  const lon = (x / n) * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI;
  return { lat, lon };
}

/** The zoom and centre that fit every point with a margin. One point gets a sensible close zoom
 *  rather than the maximum, because a single pin at z19 tells you nothing about where it is. */
function fitView(points: MapPoint[], width: number, height: number) {
  if (!points.length) return { z: 11, lat: 22.35, lon: 114.15 };
  const lats = points.map((p) => p.lat);
  const lons = points.map((p) => p.lon);
  const lat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const lon = (Math.min(...lons) + Math.max(...lons)) / 2;
  if (points.length === 1) return { z: 16, lat, lon };

  for (let z = MAX_ZOOM; z >= MIN_ZOOM; z--) {
    const xs = points.map((p) => project(p.lat, p.lon, z).x * TILE);
    const ys = points.map((p) => project(p.lat, p.lon, z).y * TILE);
    const spanX = Math.max(...xs) - Math.min(...xs);
    const spanY = Math.max(...ys) - Math.min(...ys);
    if (spanX < width * 0.8 && spanY < height * 0.8) return { z, lat, lon };
  }
  return { z: MIN_ZOOM, lat, lon };
}

// A brass pin means nobody has decided — which is the state that matters on this screen, so it
// gets the accent rather than a grey. A, B and C take the app's ok / warning / bad hues in the
// order their cost rises: road access, a platform to build, and a class the bill has no item for.
const TONE_FILL: Record<MapPoint["tone"], string> = {
  undecided: "var(--color-cb-brass)",
  a: "var(--color-cb-ok)",
  b: "var(--color-cb-amber)",
  c: "var(--color-cb-bad)",
  // A person's picked road-access point — dark ink so it reads as a fixture of the site, not
  // one of the classification hues (which would make a pick look like a verdict).
  road: "var(--color-cb-ink)",
};

export function SlippyMap({
  points,
  tiles,
  labelTiles,
  attribution,
  selected,
  onSelect,
  onPick,
  picking = false,
  onZoom,
  fullscreen = false,
  onFullscreen,
  height = 420,
  caption,
  renderPopup,
}: {
  points: MapPoint[];
  tiles: string;
  labelTiles?: string;
  attribution: string;
  selected?: string | null;
  onSelect?: (id: string) => void;
  /** A click (not a drag, not a marker) resolved to coordinates — the road-access picker's
   *  input. Only fires while `picking` is on, so an ordinary pan can never place a point. */
  onPick?: (lat: number, lon: number) => void;
  picking?: boolean;
  /** The current zoom, reported so a caller can decide what to plot at this scale — the map
   *  owns the view, the caller owns the meaning of what is on it. */
  onZoom?: (z: number) => void;
  fullscreen?: boolean;
  onFullscreen?: (next: boolean) => void;
  height?: number;
  caption?: string;
  /** A card pinned to the SELECTED point, drawn inside the map so it stays put while you pan.
   *  A separate prop rather than children because it has to know where the pin ended up, and
   *  because a popup that scrolled away from its own pin would be worse than no popup. */
  renderPopup?: (id: string) => ReactNode;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 640, h: height });
  const [view, setView] = useState<{ z: number; lat: number; lon: number } | null>(null);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  // Where the pointer went down and whether it moved since — a pick is a click, and a click is
  // a press that did not travel. 4px of slack forgives a shaky hand without eating a pan.
  const press = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const [tilesSeen, setTilesSeen] = useState(0);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Fit once per point-set. Re-fitting on every render would fight the user's pan.
  const fingerprint = points.map((p) => p.id).join("|");
  useEffect(() => {
    setView(fitView(points, size.w, size.h));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint]);

  const centre = view ?? { z: 11, lat: 22.35, lon: 114.15 };

  // Report the scale, so the caller can swap cluster circles for individual holes. Effect, not
  // an inline call: firing a parent setState during render is the classic loop.
  useEffect(() => {
    onZoom?.(centre.z);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centre.z]);

  // Escape leaves fullscreen. A map that fills the screen with no way out but the mouse is a
  // trap on a keyboard.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onFullscreen?.(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen, onFullscreen]);

  const origin = useMemo(() => {
    const c = project(centre.lat, centre.lon, centre.z);
    return { x: c.x * TILE - size.w / 2, y: c.y * TILE - size.h / 2 };
  }, [centre.lat, centre.lon, centre.z, size.w, size.h]);

  const toScreen = useCallback(
    (lat: number, lon: number) => {
      const p = project(lat, lon, centre.z);
      return { left: p.x * TILE - origin.x, top: p.y * TILE - origin.y };
    },
    [centre.z, origin.x, origin.y],
  );

  const grid = useMemo(() => {
    const n = 2 ** centre.z;
    const x0 = Math.floor(origin.x / TILE);
    const y0 = Math.floor(origin.y / TILE);
    const cols = Math.ceil(size.w / TILE) + 1;
    const rows = Math.ceil(size.h / TILE) + 1;
    const cells: { key: string; x: number; y: number; left: number; top: number }[] = [];
    for (let dy = 0; dy < rows; dy++) {
      for (let dx = 0; dx < cols; dx++) {
        const x = x0 + dx;
        const y = y0 + dy;
        if (y < 0 || y >= n) continue;
        cells.push({
          key: `${centre.z}/${x}/${y}`,
          x: ((x % n) + n) % n,
          y,
          left: x * TILE - origin.x,
          top: y * TILE - origin.y,
        });
      }
    }
    return cells;
  }, [centre.z, origin.x, origin.y, size.w, size.h]);

  const url = (template: string, z: number, x: number, y: number) =>
    template.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));

  const zoomBy = (delta: number, at?: { x: number; y: number }) => {
    const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, centre.z + delta));
    if (z === centre.z) return;
    // Zoom about the cursor when there is one, so the thing under the pointer stays put.
    const anchor = at ?? { x: size.w / 2, y: size.h / 2 };
    const world = { x: (origin.x + anchor.x) / TILE, y: (origin.y + anchor.y) / TILE };
    const under = unproject(world.x, world.y, centre.z);
    const next = project(under.lat, under.lon, z);
    const nextOrigin = { x: next.x * TILE - anchor.x, y: next.y * TILE - anchor.y };
    const middle = unproject(
      (nextOrigin.x + size.w / 2) / TILE,
      (nextOrigin.y + size.h / 2) / TILE,
      z,
    );
    setView({ z, lat: middle.lat, lon: middle.lon });
  };

  const pan = (dx: number, dy: number) => {
    const next = unproject(
      (origin.x + size.w / 2 - dx) / TILE,
      (origin.y + size.h / 2 - dy) / TILE,
      centre.z,
    );
    setView({ z: centre.z, lat: next.lat, lon: next.lon });
  };

  return (
    <div
      className={cx(
        "rounded-cb-card border border-cb-border bg-cb-page",
        // Fullscreen is a fixed overlay rather than the Fullscreen API: it keeps the app's own
        // chrome and Escape handling, and it cannot leave the page in a state the browser owns.
        fullscreen && "fixed inset-0 z-50 flex flex-col rounded-none border-0",
      )}
    >
      <div
        ref={box}
        style={fullscreen ? undefined : { height }}
        className={cx(
          "relative w-full select-none overflow-hidden bg-cb-panel",
          fullscreen ? "flex-1" : "rounded-t-cb-card",
          picking ? "cursor-crosshair" : drag ? "cursor-grabbing" : "cursor-grab",
        )}
        onPointerDown={(e) => {
          (e.target as Element).setPointerCapture?.(e.pointerId);
          setDrag({ x: e.clientX, y: e.clientY });
          press.current = { x: e.clientX, y: e.clientY, moved: false };
        }}
        onPointerMove={(e) => {
          if (!drag) return;
          if (press.current &&
              Math.hypot(e.clientX - press.current.x, e.clientY - press.current.y) > 4) {
            press.current.moved = true;
          }
          pan(e.clientX - drag.x, e.clientY - drag.y);
          setDrag({ x: e.clientX, y: e.clientY });
        }}
        onPointerUp={(e) => {
          setDrag(null);
          const p = press.current;
          press.current = null;
          if (!picking || !onPick || !p || p.moved) return;
          const rect = box.current?.getBoundingClientRect();
          if (!rect) return;
          const at = unproject(
            (origin.x + (e.clientX - rect.left)) / TILE,
            (origin.y + (e.clientY - rect.top)) / TILE,
            centre.z,
          );
          onPick(at.lat, at.lon);
        }}
        onPointerLeave={() => {
          setDrag(null);
          press.current = null;
        }}
        onWheel={(e) => {
          const rect = box.current?.getBoundingClientRect();
          zoomBy(e.deltaY < 0 ? 1 : -1, rect ? { x: e.clientX - rect.left, y: e.clientY - rect.top } : undefined);
        }}
      >
        {grid.map((cell) => (
          <img
            key={cell.key}
            src={url(tiles, centre.z, cell.x, cell.y)}
            alt=""
            draggable={false}
            onLoad={() => setTilesSeen((n) => n + 1)}
            style={{ position: "absolute", left: cell.left, top: cell.top, width: TILE, height: TILE }}
            className="pointer-events-none"
          />
        ))}
        {labelTiles &&
          grid.map((cell) => (
            <img
              key={`L${cell.key}`}
              src={url(labelTiles, centre.z, cell.x, cell.y)}
              alt=""
              draggable={false}
              style={{ position: "absolute", left: cell.left, top: cell.top, width: TILE, height: TILE }}
              className="pointer-events-none"
            />
          ))}

        {points.map((point) => {
          const at = toScreen(point.lat, point.lon);
          if (at.left < -60 || at.top < -60 || at.left > size.w + 60 || at.top > size.h + 60) {
            return null;
          }
          const active = selected === point.id;
          return (
            <button
              key={point.id}
              type="button"
              title={point.label}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => onSelect?.(point.id)}
              style={{ left: at.left, top: at.top, background: TONE_FILL[point.tone] }}
              className={cx(
                "absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 font-cb-mono text-[9px] font-semibold leading-none text-cb-on-brass shadow",
                active ? "z-10 border-cb-ink-text" : "border-white",
                point.count && point.count > 1 ? "h-[26px] w-[26px]" : "h-[13px] w-[13px]",
              )}
            >
              {point.count && point.count > 1 ? point.count : ""}
            </button>
          );
        })}

        {/* THE CARD FOR THE SELECTED PIN, drawn inside the map so it travels with the point when
            you pan. It flips to the other side of the pin near an edge rather than being clipped
            by the map's own overflow, because a card you cannot read is the same as no card. */}
        {(() => {
          const point = renderPopup && selected
            ? points.find((p) => p.id === selected)
            : undefined;
          if (!point || !renderPopup) return null;
          const at = toScreen(point.lat, point.lon);
          const left = at.left > size.w - 300 ? at.left - 288 : at.left + 18;
          const top = Math.max(6, Math.min(at.top - 20, Math.max(6, size.h - 300)));
          return (
            <div
              style={{ left: Math.max(6, left), top }}
              onPointerDown={(e) => e.stopPropagation()}
              className="absolute z-20 w-[272px] max-h-[calc(100%-16px)] overflow-y-auto rounded-cb-card border border-cb-border-strong bg-cb-surface p-2.5 shadow-lg"
            >
              {renderPopup(point.id)}
            </div>
          );
        })()}

        <div className="absolute right-2 top-2 flex flex-col gap-1">
          {[1, -1].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => zoomBy(d)}
              className="cb-press h-6 w-6 rounded-cb-btn border border-cb-border bg-cb-page font-cb-mono text-[13px] font-semibold text-cb-ink-text"
            >
              {d > 0 ? "+" : "−"}
            </button>
          ))}
          <button
            type="button"
            title="Fit every hole back on screen"
            onClick={() => setView(fitView(points, size.w, size.h))}
            className="cb-press h-6 w-6 rounded-cb-btn border border-cb-border bg-cb-page font-cb-mono text-[9px] font-semibold text-cb-ink-text"
          >
            FIT
          </button>
          {onFullscreen && (
            <button
              type="button"
              title={fullscreen ? "Leave fullscreen (Esc)" : "Fill the screen with the map"}
              onClick={() => onFullscreen(!fullscreen)}
              className="cb-press h-6 w-6 rounded-cb-btn border border-cb-border bg-cb-page font-cb-mono text-[11px] font-semibold text-cb-ink-text"
            >
              {fullscreen ? "✕" : "⛶"}
            </button>
          )}
        </div>

        {tilesSeen === 0 && (
          <div className="pointer-events-none absolute inset-x-0 bottom-8 text-center">
            <span className="rounded-cb-chip bg-cb-page/90 px-2 py-1 font-cb-sans text-[10px] text-cb-muted">
              No basemap tile has loaded. The pins are still where the coordinates put them — the
              ground behind them is missing, not wrong.
            </span>
          </div>
        )}
      </div>
      <div className="flex items-baseline gap-3 border-t border-cb-border px-3 py-1.5">
        <span className="font-cb-mono text-[8.5px] text-cb-faint">
          z{centre.z} · {centre.lat.toFixed(5)}, {centre.lon.toFixed(5)}
        </span>
        {caption && <span className="font-cb-sans text-[9.5px] text-cb-muted">{caption}</span>}
        <span className="ml-auto font-cb-sans text-[8.5px] text-cb-faint">{attribution}</span>
      </div>
    </div>
  );
}
