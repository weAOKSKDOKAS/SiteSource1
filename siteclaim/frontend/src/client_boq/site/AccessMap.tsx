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
import type { AccessBoardResponse, ClusterEvidence, Evidence } from "../types";
import { Card, SectionLabel, WaitingOn, cx } from "../ui";
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
}: {
  setId: string;
  onError: (msg: string) => void;
  /** Sends the reader to the HOLES view with this station picked — where classifying happens. */
  onFocusStation?: (station: string) => void;
}) {
  const [board, setBoard] = useState<AccessBoardResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBoard(await api.accessBoard(setId));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const points: MapPoint[] = useMemo(
    () =>
      (board?.clusters ?? []).map((c) => ({
        id: c.label,
        lat: c.lat,
        lon: c.lon,
        label: `${c.label} — ${c.holes} hole(s)${c.decided?.[""] ? `, ${c.decided[""]} unclassed` : ""}`,
        tone: TONE_FOR(c),
        count: c.holes,
      })),
    [board],
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
          caption="Brass = unclassed · green A · amber B · red C. Click a cluster for its evidence."
        />
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
