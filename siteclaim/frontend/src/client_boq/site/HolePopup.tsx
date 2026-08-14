// The card that opens when you click a hole on the map.
//
// It exists because the map was a picture you could look at and not a thing you could work on:
// clicking a pin jumped you to another screen, and the four facts you need to class a hole —
// where it is, how deep it goes, what road is nearest, and what the approach actually looks like —
// lived on four different surfaces.
//
// THREE KINDS OF THING SHARE THIS CARD, and they are laid out so a reader can tell them apart:
//
//   MEASURED    the coordinates, the depth, the metres to the nearest mapped road. Arithmetic;
//               two people get the same number.
//   DRAFTED     the route note. Written by a model from the road data, and labelled as a draft
//               with its own uncertainties, because a route read off a map cannot see a gate.
//   DECIDED     the access class. A person's, on this card or on the Holes view — nothing on
//               this screen proposes one, and the drafted note has no field to put one in.
//
// The coordinates are editable here rather than on a form somewhere else, because moving a hole
// and looking at where it landed is one act. A drawing mixes surveyed positions with indicative
// ones and does not mark which is which; forty metres is nothing on an A1 sheet and everything on
// a hillside.

import { useEffect, useState } from "react";
import { api, readFailure } from "../api";
import type { ApproachResponse, NearestRoad, Station } from "../types";
import { Button, Segmented, cx, formatNorm } from "../ui";

const CLASS_OPTIONS = [
  { value: "", label: "—" },
  { value: "A", label: "A" },
  { value: "B", label: "B" },
  { value: "C", label: "C" },
];

export function HolePopup({
  setId,
  station,
  accessClass,
  road,
  onSetClass,
  onMoved,
  onOpenHoles,
  onClose,
  onError,
}: {
  setId: string;
  station: Station;
  accessClass: string;
  /** The measured nearest mapped road, if the roads have been read. */
  road: NearestRoad | null;
  onSetClass: (accessClass: string) => void;
  onMoved: () => Promise<void> | void;
  onOpenHoles: () => void;
  onClose: () => void;
  onError: (msg: string) => void;
}) {
  const [easting, setEasting] = useState(station.easting?.toString() ?? "");
  const [northing, setNorthing] = useState(station.northing?.toString() ?? "");
  const [busy, setBusy] = useState(false);
  const [moved, setMoved] = useState<string>("");
  const [note, setNote] = useState<ApproachResponse | null>(null);
  const [asking, setAsking] = useState(false);

  // A new hole means new fields. Without this the boxes keep the last hole's numbers and the
  // first save writes one hole's coordinates onto another.
  useEffect(() => {
    setEasting(station.easting?.toString() ?? "");
    setNorthing(station.northing?.toString() ?? "");
    setMoved("");
    setNote(null);
  }, [station.station, station.easting, station.northing]);

  const dirty =
    easting !== (station.easting?.toString() ?? "") ||
    northing !== (station.northing?.toString() ?? "");

  const save = async () => {
    const e = easting.trim() === "" ? null : Number(easting);
    const n = northing.trim() === "" ? null : Number(northing);
    if ((e !== null && !Number.isFinite(e)) || (n !== null && !Number.isFinite(n))) {
      onError(`"${easting}, ${northing}" is not a pair of coordinates. Nothing was saved.`);
      return;
    }
    setBusy(true);
    try {
      const reply = await api.setStationCoords(setId, station.station, {
        easting: e, northing: n, note: "moved on the map",
      });
      setMoved(reply.moved_m != null ? `moved ${formatNorm(reply.moved_m)} m` : "position set");
      await onMoved();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  // Undo restores the DRAWING, never a third guess — so it is a separate act from typing a number
  // back in, and it is worth saying which one it is on the button.
  const restore = async () => {
    setBusy(true);
    try {
      const reply = await api.setStationCoords(setId, station.station, { restore: true });
      setMoved(reply.restored ? "back to the drawing's reading" : "this hole had not been moved");
      await onMoved();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const describe = async () => {
    setAsking(true);
    try {
      setNote(await api.approach(setId, station.station));
    } catch (err) {
      onError(`The route note could not be read: ${readFailure(err)}`);
    } finally {
      setAsking(false);
    }
  };

  const depth = station.soil_m + station.rock_m;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-cb-mono text-[11px] font-semibold text-cb-ink-text">
          {station.station}
        </span>
        <button
          type="button"
          onClick={onClose}
          title="Close"
          className="cb-press font-cb-mono text-[11px] leading-none text-cb-faint"
        >
          ✕
        </button>
      </div>

      {/* MEASURED — what the schedule records. A column the drawing never printed prints blank,
          never zero: zero would be a claim that the hole has no depth. */}
      <div className="font-cb-mono text-[9px] leading-[1.5] text-cb-muted">
        {station.kind || "BH"} ·{" "}
        {depth > 0 ? `${formatNorm(depth)} m` : "no depth on the schedule"}
        {station.rock_m ? ` · ${formatNorm(station.rock_m)} m rock` : " · soil only"}
        {station.length_m !== null && ` · tentative ${formatNorm(station.length_m)} m`}
        {station.ground_level_mpd !== null &&
          ` · ${formatNorm(station.ground_level_mpd)} mPD`}
        {station.sheet ? ` · ${station.sheet}` : ""}
      </div>

      {/* MEASURED, and correctable. */}
      <div className="rounded-cb-chip bg-cb-panel px-2 py-1.5">
        <div className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">
          HK1980 GRID — TYPE TO MOVE THE PIN
        </div>
        <div className="mt-1 flex items-center gap-1.5">
          <input
            value={easting}
            onChange={(e) => setEasting(e.target.value)}
            placeholder="easting"
            aria-label={`${station.station} easting`}
            className="w-full min-w-0 rounded-cb-chip border border-cb-border bg-cb-warm px-1.5 py-1 font-cb-mono text-[10px] text-cb-ink-text"
          />
          <input
            value={northing}
            onChange={(e) => setNorthing(e.target.value)}
            placeholder="northing"
            aria-label={`${station.station} northing`}
            className="w-full min-w-0 rounded-cb-chip border border-cb-border bg-cb-warm px-1.5 py-1 font-cb-mono text-[10px] text-cb-ink-text"
          />
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <Button variant="brass" disabled={busy || !dirty} onClick={() => void save()}>
            {busy ? "Saving…" : "Move it"}
          </Button>
          <Button disabled={busy} onClick={() => void restore()}>
            Back to the drawing
          </Button>
        </div>
        {moved && (
          <p className="mt-1 font-cb-mono text-[8.5px] text-cb-ok-dark">{moved}</p>
        )}
        <p className="mt-1 font-cb-sans text-[8.5px] leading-[1.45] text-cb-faint">
          The drawing's own reading is kept. "Back to the drawing" restores it — nothing here
          overwrites what was printed.
        </p>
      </div>

      {/* MEASURED — the road, with the OSM way so the claim can be opened. */}
      {road && (
        <div className="font-cb-sans text-[9px] leading-[1.45] text-cb-brass-text">
          <span className="font-cb-mono font-semibold">
            {formatNorm(road.metres)} m
          </span>{" "}
          to the nearest mapped road{road.name ? ` — ${road.name}` : ""}
          {road.highway ? ` (${road.highway})` : ""}, straight line. OSM way {road.way_id}.
        </div>
      )}

      {/* DECIDED — a person's, here or on Holes. Nothing on this card proposes one. */}
      <div className="flex items-center gap-1.5 border-t border-cb-divider pt-2">
        <span className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">
          CLASS
        </span>
        <Segmented value={accessClass} options={CLASS_OPTIONS} onChange={onSetClass} />
      </div>

      {/* DRAFTED — and labelled as such, with what it could not see. */}
      <div className="border-t border-cb-divider pt-2">
        {!note ? (
          <Button disabled={asking} onClick={() => void describe()}>
            {asking ? "Reading the roads…" : "How would we get here?"}
          </Button>
        ) : (
          <div className="flex flex-col gap-1.5">
            <div className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint">
              DRAFTED FROM THE ROAD DATA — NOT A SURVEY
            </div>
            {note.waiting_on && (
              <p className="font-cb-sans text-[9px] leading-[1.45] text-cb-amber">
                {note.waiting_on}
              </p>
            )}
            {note.summary && (
              <p className="font-cb-sans text-[9.5px] leading-[1.5] text-cb-body">
                {note.summary}
              </p>
            )}
            {note.approach_road && (
              <p className="font-cb-mono text-[9px] text-cb-brass-text">
                in off {note.approach_road}
              </p>
            )}
            {note.steps.length > 0 && (
              <ol className="ml-3 list-decimal font-cb-sans text-[9px] leading-[1.5] text-cb-muted">
                {note.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            )}
            {note.last_stretch && (
              <p className="font-cb-sans text-[9px] leading-[1.5] text-cb-muted">
                {note.last_stretch}
              </p>
            )}
            <div>
              <div className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-amber">
                WHAT IT CANNOT SEE
              </div>
              <ul className="ml-3 list-disc font-cb-sans text-[9px] leading-[1.5] text-cb-muted">
                {note.uncertainties.map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
            </div>
            {note.checked.map((line) => (
              <p key={line} className="font-cb-sans text-[8.5px] leading-[1.45] text-cb-bad-dark">
                {line}
              </p>
            ))}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onOpenHoles}
        className={cx(
          "cb-press self-start font-cb-sans text-[9px] font-semibold text-cb-brass-text underline",
        )}
      >
        open on the Holes view →
      </button>
    </div>
  );
}
