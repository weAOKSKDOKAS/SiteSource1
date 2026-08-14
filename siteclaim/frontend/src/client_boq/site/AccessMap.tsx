// Site › MAP — where the holes actually are, and everything that can be known about reaching them.
//
// THE PROBLEM THIS SCREEN IS FOR. The bill prices 80 Class A rig moves and 11 Class B, and a Class
// B platform is real money on the rig-move item. No document in the tender says which hole is
// which: GI/210 has no class column, and the drawing legend's four symbols denote none of it. So
// somebody has to decide, hole by hole, about ground they have probably not walked — and until now
// the only thing they had to decide from was a coordinate pair in a table.
//
// WHAT THIS SCREEN IS NOT. It does not propose a class. Every cluster's card carries
// `proposed_class`, and it is permanently empty by construction on the backend. A machine reading
// a photograph would be guessing at something a person signs their name to, and the guess would be
// believed. What the card does is assemble: the imagery, the drawing crop, the map link, and — when
// a key is configured — the satellite still and Street View. Then a human classifies, on the HOLES
// view, exactly as before.
//
// EVIDENCE THAT IS DARK SAYS SO BY NAME. An absent Google key makes one kind of evidence
// unavailable and nothing else; it never blocks the map, which runs on keyless Lands Department
// tiles. Keyed stills are fetched through this API so the credential stays on the server.

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  AccessBoardResponse,
  ClusterEvidence,
  Evidence,
  NearestRoad,
  RoadResponse,
  Station,
  StationPosition,
} from "../types";
import { usePersisted } from "../chrome";
import { Button, Card, SectionLabel, Segmented, WaitingOn, cx } from "../ui";
import { HolePopup } from "./HolePopup";
import { SlippyMap } from "./SlippyMap";
import type { MapPoint } from "./SlippyMap";

const TONE_FOR = (cluster: ClusterEvidence): MapPoint["tone"] => {
  const decided = cluster.decided ?? {};
  if ((decided[""] ?? 0) > 0) return "undecided";
  if ((decided.C ?? 0) > 0) return "c";
  if ((decided.B ?? 0) > 0) return "b";
  return "a";
};

export function AccessMap({
  setId,
  onError,
  onFocusStation,
  classOf,
  stationOf,
  roadOf,
  onSetClass,
  onMoved,
}: {
  setId: string;
  onError: (msg: string) => void;
  /** Sends the reader to the HOLES view with this station picked — where classifying happens. */
  onFocusStation?: (station: string) => void;
  /** The class a person gave each hole, for colouring per-hole pins. Read only: this screen
   *  assembles evidence and proposes nothing, and a pin's colour is a person's decision
   *  rendered, never one the map made. */
  classOf?: (station: string) => string;
  /** The schedule row for one hole, so the popup can show what was actually read about it. */
  stationOf?: (station: string) => Station | undefined;
  /** The measured nearest MAPPED road for one hole, when the roads have been read. Passed in
   *  rather than fetched here: Site.tsx already holds one reading for the whole tender, and a
   *  second fetch would be a second Overpass call for numbers it already has. */
  roadOf?: (station: string) => NearestRoad | null;
  /** Classing from the popup. Still a person's act — this screen never proposes one. */
  onSetClass?: (station: string, accessClass: string) => void;
  /** A coordinate was corrected: the schedule, the pins and the clusters all need re-reading. */
  onMoved?: () => Promise<void> | void;
}) {
  const [board, setBoard] = useState<AccessBoardResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [road, setRoad] = useState<RoadResponse | null>(null);
  // EVERY HOLE, INDIVIDUALLY. The map plotted one pin per proximity cluster, so a site whose
  // holes chain within the 250 m clustering radius drew ONE circle reading "99" and the
  // per-point map link opened the cluster's centroid. The coordinates were never missing —
  // `/site/{set}/positions` has returned every station separately all along and nothing asked.
  const [positions, setPositions] = useState<StationPosition[]>([]);
  // The picker is ARMED, never ambient: an ordinary pan or a mis-click must not place the point
  // every distance on the tender is measured from.
  const [picking, setPicking] = useState(false);
  const [zoom, setZoom] = useState(11);
  const [fullscreen, setFullscreen] = useState(false);
  const [perHole, setPerHole] = usePersisted<"auto" | "holes" | "clusters">(
    `siteMapPins.${setId}`, "auto");

  const load = useCallback(async () => {
    try {
      const [b, r, p] = await Promise.all([
        api.accessBoard(setId),
        api.road(setId),
        api.positions(setId).catch(() => ({ positions: [] as StationPosition[] })),
      ]);
      setBoard(b);
      setRoad(r);
      setPositions(p.positions ?? []);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  // AUTO: individual holes once the view is close enough that 99 pins are readable rather than
  // a smear; the cluster circles below that. A site is looked at both ways and neither is the
  // right answer at every scale — so the choice is also manual, and remembered per tender.
  const showHoles =
    perHole === "holes" || (perHole === "auto" && zoom >= 15 && positions.length > 0);

  const points: MapPoint[] = useMemo(
    () => [
      ...(showHoles
        ? positions.map((p) => ({
            id: p.station,
            lat: p.lat,
            lon: p.lon,
            label: `${p.station} — ${p.easting.toFixed(0)}E ${p.northing.toFixed(0)}N`
              + (classOf?.(p.station) ? ` · class ${classOf(p.station)}` : " · unclassed"),
            // The pin carries the class a PERSON gave this hole — the same brass-means-undecided
            // rule the cluster circles use, at the grain the decision is actually made on.
            tone: ((classOf?.(p.station) || "").toLowerCase() || "undecided") as MapPoint["tone"],
          }))
        : (board?.clusters ?? []).map((c) => ({
            id: c.label,
            lat: c.lat,
            lon: c.lon,
            label: `${c.label} — ${c.holes} hole(s)${c.decided?.[""] ? `, ${c.decided[""]} unclassed` : ""}`,
            tone: TONE_FOR(c),
            count: c.holes,
          }))),
      ...(road?.points ?? []).map((p) => ({
        id: `road:${p.point_id}`,
        lat: p.lat,
        lon: p.lon,
        label: `${p.label || p.point_id} — road access, picked by ${p.picked_by || "someone"}`,
        tone: "road" as const,
      })),
    ],
    [board, road, positions, showHoles, classOf],
  );

  const pick = useCallback(
    async (lat: number, lon: number) => {
      try {
        await api.pickRoadPoint(setId, lat, lon);
        setPicking(false);
        await load();
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    },
    [setId, load, onError],
  );

  if (!board) {
    return <WaitingOn title="Placing the holes…">Converting HK1980 Grid to WGS84.</WaitingOn>;
  }
  if (board.waiting_on) {
    return (
      <WaitingOn title="Nothing to place yet">
        {board.waiting_on}. Every coordinate on this map comes from the borehole details schedule;
        there is no other source for where a hole is.
      </WaitingOn>
    );
  }
  if (!board.clusters.length) {
    return (
      <WaitingOn title="No station on the schedule has coordinates">
        {board.problems[0] ??
          "The schedule was read, but no station carried an easting and a northing — so there is nowhere honest to put a pin."}
      </WaitingOn>
    );
  }

  const basemap = board.providers.basemap;
  const undecided = board.clusters.reduce((n, c) => n + (c.decided?.[""] ?? 0), 0);
  const open = board.clusters.find((c) => c.label === selected) ?? null;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="flex items-baseline gap-3">
        <SectionLabel>WHERE THE HOLES ARE</SectionLabel>
        <span className="font-cb-mono text-[9.5px] text-cb-faint">
          {board.clusters.length} cluster(s) within {board.radius_m}m · {undecided} hole(s)
          unclassed
        </span>
      </div>
      <p className="mt-1 max-w-[720px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
        Clustered by proximity — single-link, on the coordinates the schedule already carries. It is
        a <strong>proposal</strong>: it knows nothing about terrain, roads or access. Nothing here
        proposes an access class either; the cards assemble what can be looked at, and the
        classification stays a person's, made on the HOLES view.
      </p>

      <div className="mt-3">
        <SlippyMap
          points={points}
          tiles={basemap.imagery_tiles}
          labelTiles={basemap.label_tiles}
          attribution={basemap.attribution}
          selected={selected}
          onSelect={(id) => setSelected((s) => (s === id ? null : id))}
          renderPopup={(id) => {
            // A HOLE opens its card here, on the map, where you can see the ground around it —
            // that is the point of clicking a pin. A cluster keeps its card in the list below,
            // which is where the evidence rows live and where there is room for them.
            const hole = showHoles && !id.startsWith("road:") ? stationOf?.(id) : undefined;
            if (!hole) return null;
            return (
              <HolePopup
                setId={setId}
                station={hole}
                accessClass={classOf?.(id) ?? ""}
                road={roadOf?.(id) ?? null}
                onSetClass={(c) => onSetClass?.(id, c)}
                onMoved={async () => {
                  await onMoved?.();
                  await load();
                }}
                onOpenHoles={() => onFocusStation?.(id)}
                onClose={() => setSelected(null)}
                onError={onError}
              />
            );
          }}
          onPick={(lat, lon) => void pick(lat, lon)}
          picking={picking}
          onZoom={setZoom}
          fullscreen={fullscreen}
          onFullscreen={setFullscreen}
          height={fullscreen ? undefined : 420}
          caption={
            picking
              ? "Click where the site is entered from — a gate, a track head. Pan still works; only a clean click places the point."
              : showHoles
                ? `Every hole, individually — ${positions.length} placed. Brass = unclassed · green A · amber B · red C · dark = road access. Click a hole to class it.`
                : "Brass = unclassed · green A · amber B · red C · dark = road access. Click a cluster for its evidence — zoom in for individual holes."
          }
        />
      </div>

      {/* WHAT THE PINS MEAN, chosen rather than inferred. One pin per cluster is right when you
          are looking at where a site is; one pin per hole is right when you are deciding which
          hole needs a platform. */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Segmented
          value={perHole}
          options={[
            { value: "auto" as const, label: "AUTO" },
            { value: "holes" as const, label: `EVERY HOLE (${positions.length})` },
            { value: "clusters" as const, label: `CLUSTERS (${board.clusters.length})` },
          ]}
          onChange={setPerHole}
        />
        <span className="font-cb-mono text-[9px] text-cb-faint">
          {showHoles
            ? "one pin per borehole, from its own coordinates"
            : `one pin per proximity cluster · zoom ${zoom}${perHole === "auto" ? " — individual holes at 15+" : ""}`}
        </span>
      </div>

      {/* The road-access point: a person's judgement about WHERE, so every distance can be
          arithmetic. The picker is a mode, entered on purpose and left on the first pick. */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button
          variant={picking ? undefined : "brass"}
          onClick={() => setPicking((v) => !v)}
        >
          {picking ? "Cancel picking" : "Pick a road-access point"}
        </Button>
        {(road?.points ?? []).map((p) => (
          <span
            key={p.point_id}
            className="flex items-center gap-1.5 rounded-cb-pill border border-cb-border bg-cb-page px-2.5 py-1 font-cb-mono text-[9px] text-cb-ink-text"
          >
            ● {p.label || p.point_id}
            <span className="text-cb-faint">{p.picked_by}</span>
            <button
              type="button"
              title="Remove this point — the distances measured from it go with it."
              onClick={async () => {
                try {
                  await api.deleteRoadPoint(setId, p.point_id);
                  await load();
                } catch (e) {
                  onError(e instanceof Error ? e.message : String(e));
                }
              }}
              className="cb-press text-cb-bad-dark"
            >
              ×
            </button>
          </span>
        ))}
        {(road?.points ?? []).length === 0 && !picking && (
          <span className="font-cb-sans text-[9.5px] text-cb-muted">
            None picked — the road-distance evidence stays dark until somebody says where the
            site is entered from.
          </span>
        )}
      </div>

      {board.problems.length > 0 && (
        <div className="mt-3 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2">
          {board.problems.map((p) => (
            <p key={p} className="font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text">
              {p}
            </p>
          ))}
        </div>
      )}

      <div className="mt-4">
        <SectionLabel>ACCESS CARDS</SectionLabel>
        <div className="mt-2 grid gap-2.5 [grid-template-columns:repeat(auto-fill,minmax(320px,1fr))]">
          {board.clusters.map((cluster) => (
            <AccessCard
              key={cluster.label}
              cluster={cluster}
              open={open?.label === cluster.label}
              onOpen={() => setSelected((s) => (s === cluster.label ? null : cluster.label))}
              onFocusStation={onFocusStation}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function AccessCard({
  cluster,
  open,
  onOpen,
  onFocusStation,
}: {
  cluster: ClusterEvidence;
  open: boolean;
  onOpen: () => void;
  onFocusStation?: (station: string) => void;
}) {
  const decided = cluster.decided ?? {};
  const undecided = decided[""] ?? 0;
  const metres = cluster.soil_m + cluster.rock_m;

  return (
    <Card selected={open} className="flex flex-col gap-2">
      <button type="button" onClick={onOpen} className="cb-press text-left">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
            {cluster.label}
          </span>
          <span className="font-cb-mono text-[9.5px] text-cb-muted">
            {cluster.holes} hole{cluster.holes === 1 ? "" : "s"}
          </span>
        </div>
        <div className="mt-0.5 font-cb-mono text-[9px] text-cb-faint">
          {metres.toLocaleString("en-US", { maximumFractionDigits: 0 })} m · deepest{" "}
          {cluster.deepest_m.toFixed(1)} m · spread {cluster.spread_m.toFixed(0)} m ·{" "}
          {cluster.lat.toFixed(5)}, {cluster.lon.toFixed(5)}
        </div>
      </button>

      <div className="flex flex-wrap items-center gap-1.5">
        {(["A", "B", "C"] as const).map((c) =>
          decided[c] ? (
            <span
              key={c}
              className={cx(
                "rounded-cb-chip px-1.5 py-0.5 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip",
                c === "A" && "bg-cb-ok-tint text-cb-ok-dark",
                c === "B" && "bg-cb-brass-tint text-cb-brass-text",
                c === "C" && "bg-cb-bad-tint text-cb-bad-dark",
              )}
            >
              {decided[c]} CLASS {c}
            </span>
          ) : null,
        )}
        {undecided > 0 && (
          <span className="rounded-cb-chip border border-dashed border-cb-brass-line px-1.5 py-0.5 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-brass-text">
            {undecided} UNCLASSED
          </span>
        )}
      </div>

      {cluster.notes.map((note) => (
        <p key={note} className="font-cb-sans text-[9.5px] leading-[1.45] text-cb-muted">
          {note}
        </p>
      ))}

      {open && (
        <>
          <div className="border-t border-cb-divider pt-2">
            <div className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">
              EVIDENCE — WHAT CAN BE LOOKED AT
            </div>
            <div className="mt-1.5 flex flex-col gap-1.5">
              {cluster.evidence.map((item) => (
                <EvidenceLine key={item.kind} item={item} />
              ))}
            </div>
          </div>
          <div className="border-t border-cb-divider pt-2">
            <div className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">
              STATIONS
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {cluster.stations.map((station) => (
                <button
                  key={station}
                  type="button"
                  onClick={() => onFocusStation?.(station)}
                  title="Open this hole on the HOLES view, where the class is decided"
                  className="cb-press rounded-cb-chip border border-cb-border px-1.5 py-0.5 font-cb-mono text-[8.5px] text-cb-body"
                >
                  {station}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

function EvidenceLine({ item }: { item: Evidence }) {
  const [still, setStill] = useState(false);

  if (!item.available) {
    return (
      <div className="flex gap-2">
        <span className="w-[92px] flex-none font-cb-sans text-[9.5px] text-cb-disabled">
          {item.label}
        </span>
        <span className="flex-1 font-cb-sans text-[9px] leading-[1.4] text-cb-faint">
          {item.unavailable_reason}
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline gap-2">
        <span className="w-[92px] flex-none font-cb-sans text-[9.5px] text-cb-body">
          {item.label}
        </span>
        {item.external ? (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="cb-press font-cb-sans text-[9.5px] font-medium text-cb-brass-text underline underline-offset-2"
          >
            open ↗
          </a>
        ) : item.url ? (
          <button
            type="button"
            onClick={() => setStill((v) => !v)}
            className="cb-press font-cb-sans text-[9.5px] font-medium text-cb-brass-text underline underline-offset-2"
          >
            {still ? "hide" : "fetch"}
          </button>
        ) : item.note ? (
          // The evidence IS a number: the measured road distance. Mono, because a machine
          // computed it — from a point a person picked.
          <span className="font-cb-mono text-[9.5px] text-cb-ink-text">{item.note}</span>
        ) : (
          <span className="font-cb-sans text-[9px] text-cb-faint">on the map above</span>
        )}
      </div>
      {still && item.url && (
        <img
          src={item.url}
          alt={item.label}
          className="w-full rounded-cb-chip border border-cb-border"
          // A still that will not load is a fact about the provider, not about the site. The alt
          // text stays visible rather than the app claiming there is nothing to see.
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      )}
    </div>
  );
}
