// Site — the drawing's half of the estimate. Three views behind one tab:
//
//   Schedule  what the borehole details drawing said, checked against what the client billed
//   Map       where the holes actually are, clustered, with the evidence for reaching each
//   Photos    what somebody saw on the walk — read with vision, kept as conditions
//   Holes     the class of every hole — the judgement no document in the set contains
//   Groups    which holes drill alike, and the arithmetic that follows
//
// There is NO GATE here. An unassigned hole cannot stop you pricing; the Price step carries the
// count and the sweep is what refuses. Locking this tab would produce a dead end on a step whose
// whole purpose is looking things up.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { SetData } from "../App";
import { api, isNotYet, readFailure } from "../api";
import { Divider, DocTab, Rail, RailFolded, usePanes } from "../chrome";
import { PageView } from "../PageView";
import { AccessMap } from "../site/AccessMap";
import { Photos } from "../site/Photos";
import { ScheduleImport } from "../site/ScheduleImport";
import type {
  DerivedResponse,
  GeorefCrop,
  GeorefResponse,
  GridMark,
  GroupPreview,
  GroupsResponse,
  HoleGroup,
  NearestRoad,
  RoadResponse,
  RoadsResponse,
  Station,
  StationScheduleResponse,
} from "../types";
import {
  Button,
  MapCrop,
  SectionLabel,
  Segmented,
  SourceChip,
  WaitingOn,
  cx,
  formatNorm,
} from "../ui";

type View = "schedule" | "map" | "photos" | "holes" | "groups" | "sheets" | "import";

// HOW THE SPREAD REACHES A GROUP. Deliberately NOT derived from the access class: PS 7.01B puts
// road access and manual labour in the same Class A, so the class cannot express the difference
// and inferring one from the other would invent a judgement nobody made.
const TRANSPORT_OPTIONS = [
  { value: "", label: "—" },
  { value: "vehicle", label: "DRIVEN" },
  { value: "manual", label: "CARRIED" },
  { value: "air", label: "LIFTED" },
];

const TRANSPORT_MEANING: Record<string, string> = {
  vehicle: "Driven or craned to the hole.",
  manual:
    "Broken down and carried in by hand — portage labour, and a rig small enough to be carried, " +
    "which is a depth limit as well as a cost.",
  air: "Lifted in. No bill item covers a lift at any class, so that money goes to the checks screen.",
};

const CLASS_OPTIONS = [
  { value: "A", label: "A", title: "Reachable by road, or by hand without a temporary platform." },
  { value: "B", label: "B", title: "Needs a temporary access platform built before a rig can stand." },
  {
    value: "C",
    label: "C",
    title: "Helicopter only — and the bill has no item for it, so it goes to the sweep.",
    tone: "warn" as const,
  },
];

export function SiteTab({
  data,
  railOpen,
  onError,
}: {
  data: SetData;
  railOpen: boolean;
  onError: (msg: string) => void;
}) {
  const [view, setView] = useState<View>("schedule");
  const [schedule, setSchedule] = useState<StationScheduleResponse | null>(null);
  const [groups, setGroups] = useState<GroupsResponse | null>(null);
  const [derived, setDerived] = useState<DerivedResponse | null>(null);
  const [georef, setGeoref] = useState<GeorefResponse | null>(null);
  const [road, setRoad] = useState<RoadResponse | null>(null);
  /** The nearest MAPPED road to each hole, from OpenStreetMap. Evidence beside the class
   *  decision — a hole 40 m from a road it cannot be reached from is ordinary on a hillside. */
  const [osmRoads, setOsmRoads] = useState<RoadsResponse | null>(null);
  const [failed, setFailed] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [partId, setPartId] = useState<string | null>(null);
  const panes = usePanes("site", 236, 620, railOpen);

  const load = useCallback(async () => {
    // `App.tsx` already applies this rule to the ten tender-state reads; these two are the tab's
    // own, and they were still `.catch(() => null)`. The screens below read `null` as tender state
    // in the most misleading way available: no groups becomes "None yet. A group is a set of holes
    // that drill alike…", and no derivation becomes "No bill of quantities has been imported" —
    // said about a bill that may be sitting right there.
    const failures: Record<string, string> = {};
    const optional = <T,>(key: string, p: Promise<T>): Promise<T | null> =>
      p.catch((e: unknown) => {
        if (!isNotYet(e)) failures[key] = readFailure(e);
        return null;
      });
    try {
      const [s, g] = await Promise.all([
        api.stationSchedule(data.setId),
        optional("groups", api.holeGroups(data.setId)),
      ]);
      setSchedule(s);
      setGroups(g);
      // A derivation needs a schedule; asking for one before there is a take-off is a 404 that
      // means "not yet", not "broken". The georef read rides the same rule — and its failure is
      // named, because a tile silently showing "no grid marks" over a failed read would tell an
      // operator to re-type marks that are already there.
      setDerived(s.stations.length ? await optional("derived", api.derived(data.setId)) : null);
      setGeoref(s.stations.length ? await optional("georef", api.georef(data.setId)) : null);
      setRoad(s.stations.length ? await optional("road", api.road(data.setId)) : null);
      setOsmRoads(
        s.stations.length ? await optional("roads", api.nearestRoads(data.setId)) : null);
      setFailed(failures);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [data.setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const parts = data.parts?.parts ?? [];
    if (!parts.length) return;
    if (!partId || !parts.some((p) => p.part_id === partId)) setPartId(parts[0].part_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.parts]);

  const classOf = useCallback(
    (station: string) => schedule?.classes[station]?.access_class ?? "",
    [schedule],
  );

  const setClass = useCallback(
    async (station: string, accessClass: string) => {
      try {
        await api.setStationClass(data.setId, station, accessClass);
        await load();
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    },
    [data.setId, load, onError],
  );

  if (!schedule) {
    return <WaitingOn title="Reading the take-off…">Loading the stations.</WaitingOn>;
  }

  // A FAILED READ IS NOT AN EMPTY TAKE-OFF. `data.site` is null for both, and showing the importer
  // over a read that did not happen invites an operator to read in a schedule that may already be
  // there — and then to save it over one somebody has confirmed.
  if (data.failures.site) {
    return (
      <WaitingOn title="The take-off could not be read">
        {data.failures.site}. That is a gap in what was read, not a tender with no schedule — so
        nothing is offered here, because reading one in now could overwrite a take-off that already
        exists. Reload once the server is answering.
      </WaitingOn>
    );
  }

  // No take-off yet: the whole tab IS the way in. This used to be a `WaitingOn` with no button —
  // a dead end on the step that gates the bill-vs-drawing check, the access map, and the only
  // place in the application where a hole is given its class.
  if (!schedule.stations.length) {
    return (
      <ScheduleImport
        setId={data.setId}
        hasSchedule={false}
        onSaved={() => void load()}
        onError={onError}
      />
    );
  }

  const totals = schedule.totals;
  const counts = groups?.counts ?? {};
  const billed = groups?.billed_class_counts ?? {};
  const unassigned = totals.holes ? totals.holes - assignedCount(schedule) : 0;

  return (
    <div ref={panes.container} className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      {/* ---------------- pane 1 — what the numbers mean ---------------- */}
      {panes.railOpen ? (
        <Rail width={panes.railWidth} onResize={panes.dragRail}>
          {view === "holes" || view === "map" ? (
            <ClassRail counts={counts} billed={billed} unassigned={unassigned} />
          ) : view === "groups" ? (
            <GroupsRail groups={groups} failed={failed.groups} />
          ) : (
            <ScheduleRail schedule={schedule} derived={derived} failed={failed.derived} />
          )}
        </Rail>
      ) : (
        <RailFolded
          lines={[
            { value: String(totals.holes ?? 0), label: "HOLE" },
            { value: String(counts.A ?? 0), label: "A" },
            { value: String(counts.B ?? 0), label: "B" },
            { value: String(unassigned), label: "TODO" },
          ]}
        />
      )}

      {/* ---------------- pane 2 — the work ---------------- */}
      <section
        style={panes.docCollapsed ? undefined : { width: panes.midWidth }}
        className={cx(
          "flex min-w-0 flex-col overflow-hidden border-r border-cb-border bg-cb-surface",
          panes.docCollapsed ? "flex-1" : "flex-none",
        )}
      >
        <header className="flex flex-none items-center gap-2 border-b border-cb-border px-4 py-2.5">
          <Segmented
            value={view}
            options={[
              { value: "schedule" as View, label: "SCHEDULE" },
              { value: "map" as View, label: "MAP" },
              { value: "photos" as View, label: "PHOTOS" },
              { value: "holes" as View, label: "HOLES" },
              { value: "groups" as View, label: "GROUPS" },
              { value: "sheets" as View, label: "SHEETS" },
              { value: "import" as View, label: "IMPORT" },
            ]}
            onChange={setView}
          />
          <span className="ml-auto font-cb-mono text-[9.5px] text-cb-faint">
            {schedule.meta.source_sheet || "sheet not named"}
            {schedule.meta.confirmed_by
              ? ` · confirmed ${schedule.meta.confirmed_by}`
              : " · not confirmed"}
          </span>
        </header>

        {view === "import" ? (
          // A re-read is a better reading of the same drawing, not a new document. It lands
          // unconfirmed, because confirming is a person saying they checked THIS reading.
          <ScheduleImport
            setId={data.setId}
            hasSchedule
            onSaved={() => {
              setView("schedule");
              void load();
            }}
            onError={onError}
          />
        ) : view === "photos" ? (
          <Photos setId={data.setId} onError={onError} />
        ) : view === "map" ? (
          <AccessMap
            setId={data.setId}
            onError={onError}
            classOf={classOf}
            // A pin now opens a card ON the map — where it is, how deep, the nearest mapped road,
            // the drafted approach, and the class control. Everything the decision needs, beside
            // the ground it is about. The jump to HOLES is still there as a link for the grid
            // view, but it is no longer the only thing a click can do.
            stationOf={(station) =>
              schedule?.stations.find((s) => s.station === station)}
            roadOf={(station) =>
              osmRoads?.nearest.find((r) => r.station === station) ?? null}
            onSetClass={(station, accessClass) => void setClass(station, accessClass)}
            // A moved hole changes the schedule, the pins, the clusters and the road distances,
            // so the whole tab re-reads rather than patching one number in place.
            onMoved={load}
            onFocusStation={(station) => {
              setSelected(station);
              setView("holes");
            }}
          />
        ) : view === "schedule" ? (
          <ScheduleView
            schedule={schedule}
            derived={derived}
            derivedFailed={failed.derived}
            selected={selected}
            onSelect={setSelected}
          />
        ) : view === "holes" ? (
          <HolesView
            setId={data.setId}
            schedule={schedule}
            georef={georef}
            georefFailed={failed.georef}
            roadM={road?.station_m ?? null}
            osmRoads={osmRoads}
            classOf={classOf}
            onSetClass={(s, c) => void setClass(s, c)}
            selected={selected}
            onSelect={setSelected}
          />
        ) : view === "sheets" ? (
          <SheetsView
            setId={data.setId}
            georef={georef}
            parts={data.parts?.parts ?? []}
            onChanged={() => void load()}
            onError={onError}
          />
        ) : (
          <GroupsView
            setId={data.setId}
            groups={groups}
            failed={failed.groups}
            schedule={schedule}
            onChanged={() => void load()}
            onError={onError}
          />
        )}
      </section>

      {/* ---------------- pane 3 — the drawing ---------------- */}
      {panes.docCollapsed ? (
        <DocTab onOpen={panes.openDoc} label="DRAWING" />
      ) : (
        <>
          <Divider onDrag={panes.dragMiddle} />
          <PageView
            setId={data.setId}
            parts={data.parts?.parts ?? []}
            partId={partId}
            page={null}
            onPartChange={setPartId}
          />
        </>
      )}
    </div>
  );
}

function assignedCount(schedule: StationScheduleResponse): number {
  return schedule.stations.filter((s) => schedule.classes[s.station]?.access_class).length;
}

// ---------------------------------------------------------------------------
// Schedule — the reading, and whether the bill agrees with it
// ---------------------------------------------------------------------------
function ScheduleRail({
  schedule,
  derived,
  failed,
}: {
  schedule: StationScheduleResponse;
  derived: DerivedResponse | null;
  failed?: string;
}) {
  const t = schedule.totals;
  const good = schedule.stations.length - schedule.bad_rows.length;
  return (
    <>
      <div className="border-b border-cb-border p-3">
        <SectionLabel>STATIONS</SectionLabel>
        <RailLine label="boreholes" value={String(t.holes ?? 0)} />
        <RailLine label="trial pits" value={String(t.trial_pits ?? 0)} />
      </div>

      <div className="border-b border-cb-border p-3">
        <SectionLabel>ROWS THAT ADD UP</SectionLabel>
        <RailLine
          label="length = soil + rock"
          value={`${good} of ${schedule.stations.length}`}
          tone={schedule.bad_rows.length ? "bad" : "ok"}
        />
        {schedule.bad_rows.map((row) => (
          <p key={row} className="mt-1 font-cb-sans text-[9.5px] leading-[1.5] text-cb-bad-dark">
            {row}
          </p>
        ))}
      </div>

      {/*
        The three things the arithmetic cannot see. A row only reaches `bad_rows` if somebody read
        it — a cell nobody could make out, a hole that drills no metres, and a name read twice all
        slide underneath that check, and each of them is what a MACHINE reading of the sheet
        produces. Kept in its own block, and only when there is something in it.
      */}
      {schedule.unread_rows.length +
        schedule.empty_rows.length +
        schedule.duplicate_names.length >
        0 && (
        <div className="border-b border-cb-border p-3">
          <SectionLabel>ROWS THAT ARE NOT SETTLED</SectionLabel>
          {schedule.unread_rows.length > 0 && (
            <RailLine
              label="cells not read"
              value={String(schedule.unread_rows.length)}
              tone="bad"
            />
          )}
          {schedule.empty_rows.length > 0 && (
            <RailLine
              label="holes with no metres"
              value={String(schedule.empty_rows.length)}
              tone="bad"
            />
          )}
          {schedule.duplicate_names.length > 0 && (
            <RailLine
              label="names read twice"
              value={String(schedule.duplicate_names.length)}
              tone="bad"
            />
          )}
          {[...schedule.unread_rows, ...schedule.empty_rows, ...schedule.duplicate_names].map(
            (row) => (
              <p
                key={row}
                className="mt-1 font-cb-sans text-[9.5px] leading-[1.5] text-cb-bad-dark"
              >
                {row}
              </p>
            ),
          )}
        </div>
      )}

      {schedule.stations.some((s) => s.notes.length > 0) && (
        <div className="border-b border-cb-border p-3">
          <SectionLabel>WHAT THE READING RECORDED</SectionLabel>
          {schedule.stations
            .filter((s) => s.notes.length > 0)
            .map((s) =>
              s.notes.map((note) => (
                <p
                  key={`${s.station}-${note}`}
                  className="mt-1 font-cb-sans text-[9.5px] leading-[1.5] text-cb-muted"
                >
                  <span className="font-cb-mono font-semibold text-cb-body">{s.station}</span>{" "}
                  {note}
                </p>
              )),
            )}
        </div>
      )}

      <div className="border-b border-cb-border p-3">
        <SectionLabel>AGAINST THE BILL</SectionLabel>
        {failed ? (
          <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-bad-dark">
            NOT CHECKED — the derivation could not be read. {failed}. This panel is not saying the
            drawing and the bill agree, and it is not saying no bill was imported.
          </p>
        ) : !derived?.checked_against_a_bill ? (
          <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            No bill of quantities has been imported, so there is nothing to check this reading
            against. The quantities below are what the drawing implies.
          </p>
        ) : (
          derived.derived
            .filter((d) => d.billed !== null)
            .map((d) => (
              <RailLine
                key={d.label}
                label={d.label.toLowerCase()}
                value={d.agrees ? formatNorm(d.value) : `${formatNorm(d.value)} | ${formatNorm(d.billed!)}`}
                tone={d.agrees ? "ok" : "warn"}
              />
            ))
        )}
        <p className="mt-2 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
          The bill is the check on our reading. A disagreement is worth more than a match — it
          means one of the two documents is wrong, and finding out which is cheaper now than
          after the tender goes in.
        </p>
      </div>
    </>
  );
}

function ScheduleView({
  schedule,
  derived,
  derivedFailed,
  selected,
  onSelect,
}: {
  schedule: StationScheduleResponse;
  derived: DerivedResponse | null;
  derivedFailed?: string;
  selected: string | null;
  onSelect: (station: string) => void;
}) {
  const bad = useMemo(
    () => new Set(schedule.bad_rows.map((row) => row.split(/[\s:]/)[0])),
    [schedule.bad_rows],
  );
  const head = "px-2 py-1.5 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint";
  const cell = "px-2 py-1 font-cb-mono text-[10px] text-cb-body";

  /**
   * One numeric cell, which refuses to print a number for a cell nobody could read.
   *
   * This is the whole point of `Station.unread` reaching the screen. Soil, rock and hard metres are
   * plain numbers defaulting to 0, and a soil-only hole legitimately shows `—` for rock, so a
   * missing cell and a printed one are indistinguishable once they are rendered. A reader that
   * could not make out the soil column would otherwise put a confident `0.00` under SOIL, and
   * nobody would ever look at it again.
   */
  const Cell = ({ station, field, children }: { station: Station; field: string; children: ReactNode }) =>
    station.unread.includes(field) ? (
      <td className={cx(cell, "text-right font-semibold text-cb-bad-dark")} title="not read off the sheet">
        not read
      </td>
    ) : (
      <td className={cx(cell, "text-right")}>{children}</td>
    );

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      {/* No banner is the app saying the drawing and the bill agree. When the derivation could not
          be read, the banner cannot be trusted to be absent for that reason, so it says so. */}
      {derivedFailed && (
        <div className="border-b border-cb-bad-line bg-cb-bad-tint px-4 py-2">
          <p className="font-cb-sans text-[10.5px] leading-[1.55] text-cb-bad-dark">
            The drawing has NOT been checked against the client's quantities — that read failed
            ({derivedFailed}). A quiet table here is not agreement.
          </p>
        </div>
      )}
      {derived && derived.divergences.length > 0 && (
        <div className="border-b border-cb-brass-line bg-cb-brass-tint px-4 py-2">
          {derived.divergences.map((d) => (
            <p key={d.full_ref} className="font-cb-sans text-[10.5px] leading-[1.55] text-cb-brass-text">
              <span className="font-cb-mono font-semibold">{d.full_ref}</span> — the drawing gives{" "}
              {formatNorm(d.value)} {d.unit} and the client billed {formatNorm(d.billed ?? 0)}.{" "}
              {d.note}
            </p>
          ))}
        </div>
      )}

      <table className="w-full text-left">
        <thead className="sticky top-0 bg-cb-surface">
          <tr className="border-b border-cb-border">
            {["STATION", "EASTING", "NORTHING", "GL", "SOIL", "ROCK", "ST", "PZ"].map((h) => (
              <th key={h} className={cx(head, h !== "STATION" && "text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {schedule.stations.map((s) => (
            <tr
              key={s.station}
              onClick={() => onSelect(s.station)}
              // `Station.notes` was declared on the model, written by the reader, and consumed by
              // NOTHING — no backend reader, no router field, no render. A field that silently
              // discards what somebody wrote down is worse than no field, so it is read here.
              title={s.notes.length ? s.notes.join("\n") : undefined}
              className={cx(
                "cb-row cursor-pointer border-b border-cb-divider last:border-0",
                bad.has(s.station) && "bg-cb-bad-tint",
                selected === s.station && "bg-cb-selected",
              )}
            >
              <td className={cx(cell, "font-semibold text-cb-ink-text")}>
                {s.station}
                {s.notes.length > 0 && (
                  <span className="ml-1 font-cb-sans text-[9px] text-cb-brass-text">
                    ({s.notes.length} note{s.notes.length > 1 ? "s" : ""})
                  </span>
                )}
              </td>
              <Cell station={s} field="easting">{fmt(s.easting)}</Cell>
              <Cell station={s} field="northing">{fmt(s.northing)}</Cell>
              <Cell station={s} field="ground_level_mpd">{fmt(s.ground_level_mpd)}</Cell>
              <Cell station={s} field="soil_m">{formatNorm(s.soil_m)}</Cell>
              <Cell station={s} field="rock_m">{s.rock_m ? formatNorm(s.rock_m) : "—"}</Cell>
              <Cell station={s} field="standpipe">{s.standpipe ? "✓" : "—"}</Cell>
              <Cell station={s} field="piezometer">{s.piezometer ? "✓" : "—"}</Cell>
            </tr>
          ))}
        </tbody>
      </table>

      {schedule.trial_pits.length > 0 && (
        <div className="border-t border-cb-border px-4 py-3">
          <SectionLabel>TRIAL PITS · {schedule.trial_pits.length}</SectionLabel>
          <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            Measured by volume, not by metre, and dug rather than drilled — so they are never part
            of a drilling group.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Holes — ninety-one small pictures instead of five big sheets
// ---------------------------------------------------------------------------
function ClassRail({
  counts,
  billed,
  unassigned,
}: {
  counts: Record<string, number>;
  billed: Record<string, number>;
  unassigned: number;
}) {
  // Three states, and the third is the one worth building the screen for: everything decided and
  // the count still wrong means one of you and the client is mistaken, which is a query, not a
  // typo to quietly fix.
  const agrees =
    Object.keys(billed).length > 0 &&
    Object.entries(billed).every(([name, n]) => (counts[name] ?? 0) === n);
  const state = unassigned > 0 ? "working" : agrees ? "agreed" : "disagrees";

  return (
    <>
      <div className="border-b border-cb-border p-3">
        <SectionLabel>THE CLIENT BILLS</SectionLabel>
        {Object.keys(billed).length === 0 ? (
          <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            No bill imported, so there is no count to check yours against.
          </p>
        ) : (
          Object.entries(billed).map(([name, n]) => (
            <RailLine key={name} label={`class ${name}`} value={String(n)} />
          ))
        )}
      </div>

      <div className="border-b border-cb-border p-3">
        <SectionLabel>YOU HAVE</SectionLabel>
        {["A", "B", "C"].map((name) => (
          <RailLine key={name} label={`class ${name}`} value={String(counts[name] ?? 0)} />
        ))}
        {unassigned > 0 && <RailLine label="unassigned" value={String(unassigned)} tone="warn" />}
      </div>

      <div
        className={cx(
          "border-b p-3",
          state === "agreed"
            ? "border-cb-ok bg-cb-ok-tint"
            : state === "disagrees"
              ? "border-cb-bad bg-cb-bad-tint"
              : "border-cb-brass-line bg-cb-negotiated",
        )}
      >
        <p
          className={cx(
            "font-cb-sans text-[10.5px] font-semibold leading-[1.5]",
            state === "agreed"
              ? "text-cb-ok-dark"
              : state === "disagrees"
                ? "text-cb-bad-dark"
                : "text-cb-brass-text",
          )}
        >
          {state === "agreed"
            ? "✓ Your count matches the bill."
            : state === "disagrees"
              ? "Every hole is classed and your count still disagrees with the bill. One of you is wrong — raise it as a query."
              : `${unassigned} hole${unassigned === 1 ? "" : "s"} still to class.`}
        </p>
      </div>

      <div className="p-3">
        <SectionLabel>WHAT THE CLASSES MEAN</SectionLabel>
        {CLASS_OPTIONS.map((o) => (
          <p key={o.value} className="mt-1 font-cb-sans text-[9.5px] leading-[1.5] text-cb-muted">
            <span className="font-cb-mono font-semibold text-cb-ink-text">{o.label}</span> —{" "}
            {o.title}
          </p>
        ))}
        <p className="mt-2 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
          No document says which eleven. Your count is the only check there is.
        </p>
      </div>
    </>
  );
}

function HolesView({
  setId,
  schedule,
  georef,
  georefFailed,
  roadM,
  osmRoads,
  classOf,
  onSetClass,
  selected,
  onSelect,
}: {
  setId: string;
  schedule: StationScheduleResponse;
  georef: GeorefResponse | null;
  georefFailed?: string;
  /** Station → straight-line metres to the nearest picked road-access point. Null = none picked
   *  (or the read failed) — the hint line simply does not render; never a guessed figure. */
  roadM: Record<string, number> | null;
  /** The nearest MAPPED road per hole, measured from OpenStreetMap. */
  osmRoads: RoadsResponse | null;
  classOf: (station: string) => string;
  onSetClass: (station: string, accessClass: string) => void;
  selected: string | null;
  onSelect: (station: string) => void;
}) {
  const [only, setOnly] = useState<"all" | "unassigned">("all");
  const shown = schedule.stations.filter(
    (s) => only === "all" || !classOf(s.station),
  );

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="flex items-center gap-2 border-b border-cb-border px-4 py-2">
        <Segmented
          value={only}
          options={[
            { value: "all" as const, label: `ALL ${schedule.stations.length}` },
            { value: "unassigned" as const, label: "UNASSIGNED" },
          ]}
          onChange={setOnly}
        />
        {georefFailed && (
          <span className="ml-auto font-cb-sans text-[9.5px] text-cb-bad-dark">
            The sheet registrations could not be read: {georefFailed}. The tiles below say "no
            grid marks" about a read that failed, not about the sheets.
          </span>
        )}
      </div>

      <div className="grid gap-2 p-3 [grid-template-columns:repeat(auto-fill,minmax(150px,1fr))]">
        {shown.map((s) => (
          <HoleTile
            key={s.station}
            setId={setId}
            station={s}
            crop={georef?.crops[s.station] ?? null}
            roadM={roadM?.[s.station] ?? null}
            osmRoad={osmRoads?.nearest.find((r) => r.station === s.station) ?? null}
            accessClass={classOf(s.station)}
            decidedBy={schedule.classes[s.station]?.decided_by ?? ""}
            selected={selected === s.station}
            onSelect={() => onSelect(s.station)}
            onSetClass={(c) => onSetClass(s.station, c)}
          />
        ))}
      </div>

      {shown.length === 0 && (
        <p className="px-4 pb-4 font-cb-sans text-[11px] text-cb-muted">
          Every hole is classed.
        </p>
      )}
    </div>
  );
}

function HoleTile({
  setId,
  station,
  crop,
  roadM,
  osmRoad,
  accessClass,
  decidedBy,
  selected,
  onSelect,
  onSetClass,
}: {
  setId: string;
  station: Station;
  crop: GeorefCrop | null;
  roadM: number | null;
  osmRoad: NearestRoad | null;
  accessClass: string;
  decidedBy: string;
  selected: boolean;
  onSelect: () => void;
  onSetClass: (accessClass: string) => void;
}) {
  // ARRIVING FROM THE MAP HAS TO LAND SOMEWHERE YOU CAN SEE. Clicking a pin sets this station
  // and switches to this view, and with a hundred holes in the grid the picked one is usually
  // forty rows down — so the handoff looked like a button that did nothing. `nearest` scrolls
  // only when the tile is actually off-screen, so clicking a tile you can already see is still.
  const tile = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (selected) tile.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  return (
    <div
      ref={tile}
      onClick={onSelect}
      className={cx(
        "cb-row flex cursor-pointer flex-col gap-1.5 rounded-cb-card border p-2",
        selected ? "border-cb-brass bg-cb-selected" : "border-cb-border bg-cb-page",
      )}
    >
      {/* One render per sheet, cropped 91 ways in CSS — the crop is this station's, from the
          sheet whose grid CONTAINS its coordinates. Null still renders the honest waiting
          state, never a decorative square somebody might classify a hole from. */}
      <MapCrop
        src={crop ? api.pageUrl(setId, crop.part_id, crop.page) : null}
        box={crop?.box ?? null}
        size={96}
        className="self-center"
      />
      <div className="font-cb-mono text-[10px] font-semibold text-cb-ink-text">
        {station.station}
      </div>
      {/* A tentative length is a COLUMN THE DRAWING MAY NOT HAVE — GI/210 prints none — so it
          arrives null, and null prints as a blank. Filling it with soil+rock would read as a
          printed length, and filling it with 0 would read as a hole with no depth; both are
          claims about a cell nobody saw. */}
      <div
        className="font-cb-mono text-[9px] text-cb-muted"
        title={station.length_m === null
          ? "No tentative borehole length is printed for this hole on the drawing."
          : undefined}
      >
        {station.length_m === null ? "— m" : `${formatNorm(station.length_m)} m`} ·{" "}
        {station.rock_m ? `${formatNorm(station.rock_m)} m rock` : "soil only"}
      </div>
      {/* The design's brass hint line: "▪road 40 m". A hint, not a classification — the number
          is arithmetic from a person's picked access point, it is optional (absent point =
          absent line), and the tile is designed so you can classify from the picture alone. */}
      {(roadM !== null || osmRoad) && (
        <div className="font-cb-sans text-[9px] font-semibold text-cb-brass-text">
          <span
            className="mr-1 inline-block h-[7px] w-[7px] rounded-[1px] align-middle"
            style={{ background: "var(--color-cb-brass)" }}
          />
          {roadM !== null && <>access {formatNorm(roadM)} m</>}
          {roadM !== null && osmRoad && " · "}
          {osmRoad && (
            <span title={`nearest mapped road — OSM way ${osmRoad.way_id}${osmRoad.highway ? `, ${osmRoad.highway}` : ""}`}>
              road {formatNorm(osmRoad.metres)} m
              {osmRoad.name ? ` (${osmRoad.name})` : ""}
            </span>
          )}
        </div>
      )}
      <div className="flex items-center gap-1.5">
        <Segmented value={accessClass} options={CLASS_OPTIONS} onChange={onSetClass} />
        {accessClass === "C" && (
          <span className="font-cb-mono text-[7.5px] font-semibold text-cb-amber">
            → SWEEP
          </span>
        )}
      </div>
      {decidedBy && (
        <div className="font-cb-mono text-[7.5px] text-cb-faint">{decidedBy}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sheets — two grid marks per site-plan sheet, and every hole follows by arithmetic
// ---------------------------------------------------------------------------
const EMPTY_MARK: GridMark = { easting: 0, northing: 0, x: 0, y: 0, label: "" };

function SheetsView({
  setId,
  georef,
  parts,
  onChanged,
  onError,
}: {
  setId: string;
  georef: GeorefResponse | null;
  parts: { part_id: string; title: string; pages: string }[];
  onChanged: () => void;
  onError: (msg: string) => void;
}) {
  const [sheet, setSheet] = useState("");
  const [partId, setPartId] = useState(parts[0]?.part_id ?? "");
  const [page, setPage] = useState(1);
  const [marks, setMarks] = useState<[GridMark, GridMark]>([{ ...EMPTY_MARK }, { ...EMPTY_MARK }]);
  // Which mark the next click on the page places. Coordinates are TYPED (they are printed on the
  // sheet); the page position is a click — nobody can reasonably type a fraction.
  const [arming, setArming] = useState<0 | 1>(0);
  const [saved, setSaved] = useState<{ usable: boolean; problems: string[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const setMark = (i: 0 | 1, patch: Partial<GridMark>) =>
    setMarks((prev) => {
      const next: [GridMark, GridMark] = [{ ...prev[0] }, { ...prev[1] }];
      next[i] = { ...next[i], ...patch };
      return next;
    });

  const placeByClick = (e: React.MouseEvent<HTMLImageElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    setMark(arming, { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 });
    setArming(arming === 0 ? 1 : 0);
  };

  const save = async (confirm: boolean) => {
    setBusy(true);
    try {
      const reply = await api.saveRegistration(
        setId, { sheet: sheet.trim(), part_id: partId, page, marks: [...marks] }, confirm);
      setSaved(reply);
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const edit = (row: GeorefResponse["sheets"][number]) => {
    setSheet(row.sheet);
    setPartId(row.part_id);
    setPage(row.page);
    if (row.marks.length >= 2) setMarks([{ ...row.marks[0] }, { ...row.marks[1] }]);
    setSaved(null);
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <SectionLabel>REGISTERED SHEETS</SectionLabel>
      <p className="mt-1 max-w-[640px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
        Read the coordinates printed beside any two grid crosses on a site-plan sheet, click where
        each cross sits on the page, and every station on that sheet follows by arithmetic. A
        mistyped coordinate is caught by the scale check and named — never averaged away.
      </p>

      {(georef?.sheets ?? []).length === 0 && (
        <p className="mt-2 font-cb-sans text-[10.5px] text-cb-muted">None yet.</p>
      )}
      {(georef?.sheets ?? []).map((row) => (
        <div
          key={row.sheet}
          className="mt-2 flex flex-wrap items-center gap-2 rounded-cb-card border border-cb-border bg-cb-page px-3 py-2"
        >
          <span className="font-cb-mono text-[10px] font-semibold text-cb-ink-text">{row.sheet}</span>
          <span className="font-cb-mono text-[9px] text-cb-muted">
            {row.part_id} · p{row.page}
          </span>
          {row.usable ? (
            <span className="font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-ok-dark">
              {row.stations_on} STATION(S) ON THIS SHEET
            </span>
          ) : (
            <span className="font-cb-sans text-[9.5px] text-cb-bad-dark">{row.problems[0]}</span>
          )}
          <span className="font-cb-mono text-[8.5px] text-cb-faint">
            {row.confirmed_by ? `confirmed ${row.confirmed_by}` : "not confirmed"}
          </span>
          <span className="ml-auto flex gap-1.5">
            <Button onClick={() => edit(row)}>Edit</Button>
            <Button
              onClick={async () => {
                try {
                  await api.deleteRegistration(setId, row.sheet);
                  onChanged();
                } catch (e) {
                  onError(e instanceof Error ? e.message : String(e));
                }
              }}
            >
              Remove
            </Button>
          </span>
        </div>
      ))}

      {(georef?.unplaced ?? []).length > 0 && (
        <p className="mt-2 max-w-[640px] font-cb-sans text-[9.5px] leading-[1.5] text-cb-amber">
          {georef!.unplaced.length} located station(s) land on no registered sheet:{" "}
          {georef!.unplaced.slice(0, 8).join(", ")}
          {georef!.unplaced.length > 8 ? " …" : ""}. They keep their honest empty tiles rather
          than a crop of the wrong place.
        </p>
      )}

      <div className="mt-4 border-t border-cb-border pt-3">
        <SectionLabel>REGISTER A SHEET</SectionLabel>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="font-cb-mono text-[8px] tracking-cb-chip text-cb-faint">SHEET NO.</span>
            <input
              value={sheet}
              onChange={(e) => setSheet(e.target.value)}
              placeholder="60740338/GI/201"
              className="w-44 rounded-cb-btn border border-cb-border bg-cb-warm px-2 py-1 font-cb-mono text-[10.5px] text-cb-ink-text"
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="font-cb-mono text-[8px] tracking-cb-chip text-cb-faint">PART</span>
            <select
              value={partId}
              onChange={(e) => setPartId(e.target.value)}
              className="rounded-cb-btn border border-cb-border bg-cb-warm px-2 py-1 font-cb-sans text-[10.5px] text-cb-ink-text"
            >
              {parts.map((p) => (
                <option key={p.part_id} value={p.part_id}>
                  {p.part_id} · {p.title} ({p.pages})
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="font-cb-mono text-[8px] tracking-cb-chip text-cb-faint">PAGE</span>
            <input
              type="number"
              min={1}
              value={page}
              onChange={(e) => setPage(Math.max(1, Math.round(Number(e.target.value) || 1)))}
              className="w-16 rounded-cb-btn border border-cb-border bg-cb-warm px-2 py-1 font-cb-mono text-[10.5px] text-cb-ink-text"
            />
          </label>
        </div>

        <div className="mt-3 flex flex-wrap gap-3">
          {([0, 1] as const).map((i) => (
            <div
              key={i}
              className={cx(
                "rounded-cb-card border p-2.5",
                arming === i ? "border-cb-brass bg-cb-selected" : "border-cb-border bg-cb-page",
              )}
            >
              <button
                type="button"
                onClick={() => setArming(i)}
                className="font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-brass-text"
              >
                MARK {i === 0 ? "A" : "B"} {arming === i ? "— NEXT CLICK PLACES IT" : "— click to arm"}
              </button>
              <div className="mt-1.5 flex gap-2">
                <label className="flex flex-col gap-0.5">
                  <span className="font-cb-mono text-[8px] text-cb-faint">EASTING</span>
                  <input
                    type="number"
                    value={marks[i].easting || ""}
                    onChange={(e) => setMark(i, { easting: Number(e.target.value) || 0 })}
                    className="w-24 rounded-cb-btn border border-cb-border bg-cb-warm px-2 py-1 font-cb-mono text-[10px]"
                  />
                </label>
                <label className="flex flex-col gap-0.5">
                  <span className="font-cb-mono text-[8px] text-cb-faint">NORTHING</span>
                  <input
                    type="number"
                    value={marks[i].northing || ""}
                    onChange={(e) => setMark(i, { northing: Number(e.target.value) || 0 })}
                    className="w-24 rounded-cb-btn border border-cb-border bg-cb-warm px-2 py-1 font-cb-mono text-[10px]"
                  />
                </label>
              </div>
              <div className="mt-1 font-cb-mono text-[8.5px] text-cb-muted">
                on page: {marks[i].x || marks[i].y ? `${marks[i].x}, ${marks[i].y}` : "click the sheet below"}
              </div>
            </div>
          ))}
        </div>

        {partId && (
          <div className="mt-3 max-w-[720px] overflow-hidden rounded-cb-card border border-cb-border">
            <img
              src={api.pageUrl(setId, partId, page)}
              alt={`page ${page} of ${partId}`}
              onClick={placeByClick}
              className="w-full cursor-crosshair"
            />
          </div>
        )}

        <div className="mt-3 flex items-center gap-2">
          <Button
            variant="brass"
            disabled={busy || !sheet.trim() || !partId}
            onClick={() => void save(false)}
          >
            Save the registration
          </Button>
          <Button disabled={busy || !sheet.trim() || !partId} onClick={() => void save(true)}>
            Save &amp; confirm — I checked the sheet
          </Button>
        </div>

        {saved && (
          <div className="mt-2">
            {saved.usable ? (
              <p className="font-cb-mono text-[9px] font-semibold tracking-cb-chip text-cb-ok-dark">
                USABLE — the stations on this sheet now have tiles on HOLES
              </p>
            ) : (
              saved.problems.map((p) => (
                <p key={p} className="font-cb-sans text-[9.5px] leading-[1.5] text-cb-bad-dark">
                  {p}
                </p>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Groups — your judgement on the left, arithmetic on the right
// ---------------------------------------------------------------------------
function GroupsRail({ groups, failed }: { groups: GroupsResponse | null; failed?: string }) {
  return (
    <>
      <div className="border-b border-cb-border p-3">
        <SectionLabel>GROUPS</SectionLabel>
        {(groups?.groups ?? []).map((g) => (
          <RailLine
            key={g.label}
            label={g.label}
            value={String(g.stations.length)}
            tone={groups?.not_ready[g.label]?.length ? "warn" : "ok"}
          />
        ))}
        {failed ? (
          <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-bad-dark">
            NOT KNOWN — the groups could not be read. {failed}. There may be groups on this tender;
            this panel is not saying there are none.
          </p>
        ) : (
          !groups?.groups.length && (
            <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
              None yet. A group is a set of holes that drill alike — nothing in the client's
              documents draws these lines, so they are yours.
            </p>
          )
        )}
      </div>

      {/* AGAINST THE BILL. The endpoint calls this "the whole point of the screen" — the client
          bills 80 Class A and 11 Class B rig moves and never says which holes, so his counts are
          the only external check on a judgement the estimator otherwise makes alone. It was
          computed on every request and rendered by nothing. */}
      {groups && (
        <div className="border-b border-cb-border p-3">
          <SectionLabel>AGAINST THE BILL</SectionLabel>
          {!groups.take_off_read ? (
            <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-bad-dark">
              NOT CHECKED — {groups.not_checked_because}
            </p>
          ) : groups.reconcile.length === 0 ? (
            <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-ok-dark">
              ✓ Every hole is classed and your counts match what the client billed.
            </p>
          ) : (
            groups.reconcile.map((problem) => (
              <p
                key={problem}
                className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-brass-text"
              >
                {problem}
              </p>
            ))
          )}
        </div>
      )}

      {/* CAN THE RIG REACH THE BOTTOM. A separate block from the reconciliation above because it
          is a different kind of wrong: that one is counts disagreeing with the bill, this one is
          a hole that cannot be drilled at all by the spread you said you were sending. A rig
          broken into man-carriable loads is a smaller rig. */}
      {groups && groups.reach.length > 0 && (
        <div className="border-b border-cb-border bg-cb-bad-tint p-3">
          <SectionLabel>CAN THE RIG REACH THE BOTTOM</SectionLabel>
          {groups.reach.map((problem) => (
            <p
              key={problem}
              className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-bad-dark"
            >
              {problem}
            </p>
          ))}
          {groups.portable_rig_max_depth_m > 0 && (
            <p className="mt-1.5 font-cb-sans text-[9px] leading-[1.5] text-cb-muted">
              This is not a programme to lengthen. A carried-in rig that cannot reach the
              scheduled depth is the wrong machine for that hole — it needs a platform and a
              bigger rig, a different route in, or a query.
            </p>
          )}
        </div>
      )}

      {groups && Object.keys(groups.not_ready).length > 0 && (
        <div className="border-b border-cb-border p-3">
          <SectionLabel>NOT READY</SectionLabel>
          {Object.entries(groups.not_ready).map(([label, missing]) => (
            <div key={label} className="mt-1">
              <div className="font-cb-sans text-[10.5px] text-cb-body">{label}</div>
              {missing.map((m) => (
                <div key={m} className="font-cb-mono text-[9px] text-cb-amber">
                  {m}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      <div className="p-3">
        <p className="font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
          One rate has to cover ninety-one unlike holes. Pricing each group separately and letting
          arithmetic average them is how that stays honest — averaging by eye is how a bid gets
          lost.
        </p>
      </div>
    </>
  );
}

function GroupsView({
  setId,
  groups,
  failed,
  schedule,
  onChanged,
  onError,
}: {
  setId: string;
  groups: GroupsResponse | null;
  failed?: string;
  schedule: StationScheduleResponse;
  onChanged: () => void;
  onError: (msg: string) => void;
}) {
  const [openLabel, setOpenLabel] = useState<string | null>(null);
  const current = groups?.groups.find((g) => g.label === openLabel) ?? groups?.groups[0] ?? null;

  const addGroup = async () => {
    const unassigned = schedule.stations
      .filter((s) => !schedule.classes[s.station]?.group_id)
      .map((s) => s.station);
    const label = `Group ${(groups?.groups.length ?? 0) + 1}`;
    try {
      await api.saveGroup(setId, label.toLowerCase().replace(/\s+/g, "-"), {
        label,
        stations: unassigned,
      });
      setOpenLabel(label);
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  // NOT AN EMPTY SET OF GROUPS. The harm here is concrete rather than cosmetic: "+ Group" names
  // the new one `Group ${count + 1}` and saves it under that slug, so over a failed read it
  // proposes `Group 1` — and `saveGroup` writes by key, over whatever `group-1` already holds.
  // A read that did not happen must not become a write.
  if (failed) {
    return (
      <WaitingOn title="The groups could not be read">
        {failed}. That is a gap in what was read, not a tender with no groups — so nothing is
        offered here, because adding one now would number it from a count of zero and could save
        over a group that already exists. Reload once the server is answering.
      </WaitingOn>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="flex items-center gap-2 border-b border-cb-border px-4 py-2">
        {(groups?.groups ?? []).map((g) => (
          <button
            key={g.label}
            type="button"
            onClick={() => setOpenLabel(g.label)}
            className={cx(
              "cb-press rounded-cb-btn border px-2.5 py-1 font-cb-sans text-[10.5px]",
              current?.label === g.label
                ? "border-cb-brass bg-cb-selected font-semibold text-cb-ink-text"
                : "border-cb-border bg-white text-cb-muted",
            )}
          >
            {g.label}
          </button>
        ))}
        <Button variant="outline" className="ml-auto px-3 py-1 text-[10.5px]" onClick={() => void addGroup()}>
          + Group
        </Button>
      </div>

      {!current ? (
        <div className="p-4">
          <p className="max-w-[520px] font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
            A group is your judgement about which holes drill alike — the roadside ones a lorry can
            reach, the hillside ones that need a platform built first. Nothing in the client's
            documents draws these lines, which is why the app will not draw them for you.
          </p>
        </div>
      ) : (
        <GroupEditor
          key={current.label}
          setId={setId}
          group={current}
          allGroups={groups?.groups ?? []}
          sources={groups?.sources[current.label] ?? {}}
          onSaved={onChanged}
          onError={onError}
        />
      )}
    </div>
  );
}

function GroupEditor({
  setId,
  group,
  allGroups,
  sources,
  onSaved,
  onError,
}: {
  setId: string;
  group: HoleGroup;
  /** Every group on the set — the move targets. Membership authority is the group's OWN station
   *  list, so a move must rewrite BOTH groups or the hole is counted twice. */
  allGroups: HoleGroup[];
  sources: Record<string, { source: "book" | "yours" | "missing"; book_value: number | null }>;
  onSaved: () => void;
  onError: (msg: string) => void;
}) {
  const [draft, setDraft] = useState<HoleGroup>(group);
  const [preview, setPreview] = useState<GroupPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  // Debounced, not local. Rewriting the day-by-day simulation in TypeScript would give this
  // product two implementations of its load-bearing calculation, and they would eventually
  // disagree with no way to tell which was right. 250 ms feels the same and is exact.
  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      void api
        .previewGroup(setId, draft)
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 250);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [setId, draft]);

  // `transport` is a choice rather than a number, and it is recorded as an override exactly like
  // one: what matters is that somebody decided, not what the digits or the word turned out to be.
  const edit = (field: keyof HoleGroup, value: number | string) =>
    setDraft((d) => ({
      ...d,
      [field]: value,
      // Overriding is recorded as an act. `decay` defaults to 0.05, so the value alone can never
      // say whether anybody chose it — and an inherited number and a chosen one are different
      // claims even when the digits match.
      overrides: d.overrides.includes(field as string)
        ? d.overrides
        : [...d.overrides, field as string],
    }));

  const save = async () => {
    setBusy(true);
    try {
      await api.saveGroup(setId, group.label.toLowerCase().replace(/\s+/g, "-"), draft);
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const slugOf = (label: string) => label.toLowerCase().replace(/\s+/g, "-");

  /** Move one hole to `targetLabel`, or ungroup it (null). TWO writes on a move — the source
   *  group loses it, the target gains it — because the group's own station list is the
   *  membership authority and a one-sided write double-counts the hole. */
  const moveStation = async (station: string, targetLabel: string | null) => {
    setBusy(true);
    try {
      const source = { ...draft, stations: draft.stations.filter((s) => s !== station) };
      await api.saveGroup(setId, slugOf(group.label), source);
      if (targetLabel !== null) {
        const target = allGroups.find((g) => g.label === targetLabel);
        if (target) {
          await api.saveGroup(setId, slugOf(target.label),
            { ...target, stations: [...target.stations, station] });
        }
      }
      setDraft(source);
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // The number that exists so somebody can say "we have never beaten 9 on that hill" and fix it
  // before any money is involved.
  const blend = preview?.blended_m_per_day ?? 0;
  const suspicious = blend > draft.soil_output && draft.soil_output > 0;

  return (
    <div className="p-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="font-cb-serif text-[16px] font-semibold text-cb-ink-text">{group.label}</h2>
        <span className="font-cb-mono text-[10px] text-cb-muted">
          {group.stations.length} holes
          {group.access_class ? ` · class ${group.access_class}` : " · class not set"}
        </span>
        <span className="font-cb-mono text-[10px] text-cb-muted">
          soil {formatNorm(group.soil_m)} m · rock {formatNorm(group.rock_m)} m · deepest{" "}
          {formatNorm(group.deepest_m)} m
        </span>
        {/* THE WAY BACK OUT. "+ Group" existed and this did not, so a group made by mistake — or
            one whose holes turned out to drill differently — could only be worked around. The
            backend has said `deleted` and returned its own note since the endpoint was written;
            nothing on any screen called it.

            Deleting a group KEEPS the classes its holes were given: a class is a judgement about
            a hole, not about the group it happened to sit in. The confirm quotes that, because
            the opposite is the reasonable thing to assume. */}
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            if (!window.confirm(
              `Delete ${group.label}? Its holes keep the class of site they were given — only the ` +
              `grouping goes.`)) return;
            void (async () => {
              setBusy(true);
              try {
                await api.deleteGroup(setId, group.label.toLowerCase().replace(/\s+/g, "-"));
                onSaved();
              } catch (e) {
                onError(e instanceof Error ? e.message : String(e));
              } finally {
                setBusy(false);
              }
            })();
          }}
          className="ml-auto flex-none font-cb-sans text-[10px] text-cb-bad-dark underline underline-offset-2 disabled:opacity-50"
        >
          Delete group
        </button>
      </div>

      {/* MEMBERSHIP — the judgement the group IS, editable at last. Moving a hole rewrites BOTH
          groups' station lists (the group's own list is the membership authority; one-sided
          writes double-count the hole in every count and reconciliation), the totals re-derive
          server-side on save, and the class is untouched — classifying a hole and deciding
          which spread works it are two different acts. */}
      <div className="mt-3">
        <SectionLabel>STATIONS — {draft.stations.length}</SectionLabel>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {draft.stations.map((station) => (
            <span
              key={station}
              className="flex items-center gap-1.5 rounded-cb-pill border border-cb-border bg-cb-page px-2 py-0.5 font-cb-mono text-[9px] text-cb-ink-text"
            >
              {station}
              <select
                value=""
                disabled={busy}
                title="Move this hole to another group, or ungroup it. Its class stays."
                onChange={(e) => {
                  const target = e.target.value;
                  if (target === "") return;
                  void moveStation(station, target === "·ungroup" ? null : target);
                }}
                className="rounded-cb-btn border-0 bg-transparent font-cb-sans text-[9px] text-cb-brass-text"
              >
                <option value="">move ▾</option>
                {allGroups
                  .filter((g) => g.label !== group.label)
                  .map((g) => (
                    <option key={g.label} value={g.label}>
                      → {g.label}
                    </option>
                  ))}
                <option value="·ungroup">ungroup — back to unassigned</option>
              </select>
            </span>
          ))}
          {draft.stations.length === 0 && (
            <span className="font-cb-sans text-[10px] text-cb-muted">
              No holes left — a group of nothing prices nothing. Delete it, or move holes in from
              another group.
            </span>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-6 [grid-template-columns:minmax(220px,1fr)_minmax(220px,1fr)]">
        <div>
          <SectionLabel>YOURS</SectionLabel>
          <NumberField label="rigs" value={draft.rigs} onChange={(v) => edit("rigs", Math.max(1, Math.round(v)))} />
          <NumberField
            label="soil m/day"
            value={draft.soil_output}
            source={sources.soil_output}
            onChange={(v) => edit("soil_output", v)}
          />
          <NumberField
            label="rock m/day"
            value={draft.rock_output}
            source={sources.rock_output}
            onChange={(v) => edit("rock_output", v)}
          />
          <NumberField
            label="decay per 20 m"
            value={draft.decay * 100}
            unit="%"
            source={sources.decay}
            onChange={(v) => edit("decay", v / 100)}
          />
          {/* HOW THE SPREAD GETS THERE, which the CLASS does not tell you. PS 7.01B reads Class A
              as "road traffic OR manual labour", so the bill pays one rate whether the lorry
              delivered the rig or six people carried it up a hill. This is where that difference
              is recorded, and the three costs below are where it is priced. */}
          <div className="mt-3 flex items-baseline gap-2">
            <span className="min-w-0 flex-1 font-cb-sans text-[10.5px] text-cb-muted">
              how it gets there
            </span>
            <Segmented
              value={draft.transport}
              options={TRANSPORT_OPTIONS}
              onChange={(v) => edit("transport", v as HoleGroup["transport"])}
            />
          </div>
          <p className="mt-1 font-cb-sans text-[9px] leading-[1.45] text-cb-faint">
            {TRANSPORT_MEANING[draft.transport] ??
              "Nobody has said yet. The class is what the bill pays against; this is what actually happens."}
          </p>

          <NumberField
            label="platform build"
            value={draft.access_build_cost}
            unit="HK$"
            onChange={(v) => edit("access_build_cost", v)}
          />
          <NumberField
            label="carry it in (labour)"
            value={draft.access_labour_cost}
            unit="HK$"
            onChange={(v) => edit("access_labour_cost", v)}
          />
          <NumberField
            label="lift it in (air)"
            value={draft.access_air_cost}
            unit="HK$"
            onChange={(v) => edit("access_air_cost", v)}
          />
          <p className="mt-1 font-cb-sans text-[9px] leading-[1.5] text-cb-faint">
            A platform lands in the Class B move rate (SMM S02 ¶2.08(h)). Carrying lands in this
            group's own class rate — including Class A, which is the only place that difference
            can be priced. A lift lands nowhere: no item covers one at any class, so it goes to
            the checks screen to be queried, loaded, spread or accepted.
          </p>
        </div>

        <div>
          <SectionLabel>DERIVED</SectionLabel>
          {!preview?.ready ? (
            <p className="mt-2 font-cb-sans text-[10.5px] leading-[1.55] text-cb-amber">
              {preview?.waiting_on?.length
                ? `Waiting on: ${preview.waiting_on.join(", ")}.`
                : "Working…"}
            </p>
          ) : (
            <>
              <DerivedLine label="soil days" value={preview.soil_days} />
              <DerivedLine label="rock days charged" value={preview.rock_days_charged} />
              <DerivedLine label="drilling days" value={preview.drilling_days} strong />
              <DerivedLine label="on site (n + mob)" value={preview.on_site_days} />
              <DerivedLine
                label="blended m/day"
                value={blend}
                strong
                tone={suspicious ? "bad" : undefined}
              />
              {suspicious && (
                <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.5] text-cb-bad-dark">
                  Faster than the output you typed — depth decay can only slow a group down, so
                  something here is not what you meant.
                </p>
              )}
            </>
          )}
          <p className="mt-3 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            Days and the blend recompute as you type because they are exact and cheap. The rate
            does not: it needs the whole bill, and it comes from the Price step.
          </p>
        </div>
      </div>

      <div className="mt-5">
        <SectionLabel>BASIS</SectionLabel>
        <textarea
          value={draft.basis}
          onChange={(e) => setDraft((d) => ({ ...d, basis: e.target.value }))}
          rows={3}
          placeholder="Why you believe these numbers."
          className="mt-1 w-full max-w-[560px] rounded-cb-card border border-cb-border bg-cb-warm p-2 font-cb-serif text-[12px] leading-[1.55] text-cb-body placeholder:text-cb-faint"
        />
        <p className="mt-1 max-w-[560px] font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
          The group stays "not ready" until you write this. A number nobody can explain is a number
          nobody can defend.
        </p>
      </div>

      <div className="mt-4">
        <Button variant="brass" disabled={busy} onClick={() => void save()}>
          Save the group
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small shared pieces
// ---------------------------------------------------------------------------
function RailLine({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "bad";
}) {
  return (
    <div className="mt-1 flex items-baseline gap-2">
      <span className="min-w-0 flex-1 truncate font-cb-sans text-[10.5px] text-cb-muted">
        {label}
      </span>
      <span
        className={cx(
          "flex-none font-cb-mono text-[11px] font-semibold",
          tone === "ok"
            ? "text-cb-ok-dark"
            : tone === "warn"
              ? "text-cb-amber"
              : tone === "bad"
                ? "text-cb-bad-dark"
                : "text-cb-ink-text",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function NumberField({
  label,
  value,
  unit,
  source,
  onChange,
}: {
  label: string;
  value: number;
  unit?: string;
  source?: { source: "book" | "yours" | "missing"; book_value: number | null };
  onChange: (value: number) => void;
}) {
  return (
    <div className="mt-2 flex items-baseline gap-2">
      <label className="min-w-0 flex-1 font-cb-sans text-[10.5px] text-cb-muted">{label}</label>
      <input
        value={String(value)}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isNaN(n)) onChange(n);
        }}
        className="w-[74px] flex-none rounded-cb-chip border border-cb-border bg-cb-warm px-2 py-1 text-right font-cb-mono text-[11px] text-cb-ink-text"
      />
      {unit && <span className="w-[34px] flex-none font-cb-mono text-[9px] text-cb-faint">{unit}</span>}
      {source && <SourceChip source={source.source} bookValue={source.book_value} />}
    </div>
  );
}

function DerivedLine({
  label,
  value,
  strong,
  tone,
}: {
  label: string;
  value: number | undefined;
  strong?: boolean;
  tone?: "bad";
}) {
  return (
    <div className="mt-2 flex items-baseline gap-2">
      <span className="min-w-0 flex-1 font-cb-sans text-[10.5px] text-cb-muted">{label}</span>
      <span
        className={cx(
          "flex-none font-cb-mono",
          strong ? "text-[13px] font-semibold" : "text-[11px]",
          tone === "bad" ? "text-cb-bad-dark" : "text-cb-ink-text",
        )}
      >
        {value === undefined ? "—" : formatNorm(Number(value.toFixed(2)))}
      </span>
    </div>
  );
}

function fmt(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}
