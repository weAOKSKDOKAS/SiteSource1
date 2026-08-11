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
import { api } from "../api";
import { Divider, DocTab, Rail, RailFolded, usePanes } from "../chrome";
import { PageView } from "../PageView";
import { AccessMap } from "../site/AccessMap";
import { Photos } from "../site/Photos";
import { ScheduleImport } from "../site/ScheduleImport";
import type {
  DerivedResponse,
  GroupPreview,
  GroupsResponse,
  HoleGroup,
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

type View = "schedule" | "map" | "photos" | "holes" | "groups" | "import";

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
  const [selected, setSelected] = useState<string | null>(null);
  const [partId, setPartId] = useState<string | null>(null);
  const panes = usePanes("site", 236, 620, railOpen);

  const load = useCallback(async () => {
    try {
      const [s, g] = await Promise.all([
        api.stationSchedule(data.setId),
        api.holeGroups(data.setId).catch(() => null),
      ]);
      setSchedule(s);
      setGroups(g);
      // A derivation needs a schedule; asking for one before there is a take-off is a 404 that
      // means "not yet", not "broken".
      setDerived(s.stations.length ? await api.derived(data.setId).catch(() => null) : null);
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
            <GroupsRail groups={groups} />
          ) : (
            <ScheduleRail schedule={schedule} derived={derived} />
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
            onFocusStation={(station) => {
              // The map assembles evidence; the class is decided on HOLES. Sending the reader
              // there with the hole already picked is the whole handoff.
              setSelected(station);
              setView("holes");
            }}
          />
        ) : view === "schedule" ? (
          <ScheduleView
            schedule={schedule}
            derived={derived}
            selected={selected}
            onSelect={setSelected}
          />
        ) : view === "holes" ? (
          <HolesView
            schedule={schedule}
            classOf={classOf}
            onSetClass={(s, c) => void setClass(s, c)}
            selected={selected}
            onSelect={setSelected}
          />
        ) : (
          <GroupsView
            setId={data.setId}
            groups={groups}
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
}: {
  schedule: StationScheduleResponse;
  derived: DerivedResponse | null;
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
        {!derived?.checked_against_a_bill ? (
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
  selected,
  onSelect,
}: {
  schedule: StationScheduleResponse;
  derived: DerivedResponse | null;
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
  schedule,
  classOf,
  onSetClass,
  selected,
  onSelect,
}: {
  schedule: StationScheduleResponse;
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
      </div>

      <div className="grid gap-2 p-3 [grid-template-columns:repeat(auto-fill,minmax(150px,1fr))]">
        {shown.map((s) => (
          <HoleTile
            key={s.station}
            station={s}
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
  station,
  accessClass,
  decidedBy,
  selected,
  onSelect,
  onSetClass,
}: {
  station: Station;
  accessClass: string;
  decidedBy: string;
  selected: boolean;
  onSelect: () => void;
  onSetClass: (accessClass: string) => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={cx(
        "cb-row flex cursor-pointer flex-col gap-1.5 rounded-cb-card border p-2",
        selected ? "border-cb-brass bg-cb-selected" : "border-cb-border bg-cb-page",
      )}
    >
      {/* No registration is persisted yet, so this shows what it is waiting for rather than a
          decorative square somebody might classify a hole from. */}
      <MapCrop src={null} box={null} size={96} className="self-center" />
      <div className="font-cb-mono text-[10px] font-semibold text-cb-ink-text">
        {station.station}
      </div>
      <div className="font-cb-mono text-[9px] text-cb-muted">
        {formatNorm(station.length_m)} m ·{" "}
        {station.rock_m ? `${formatNorm(station.rock_m)} m rock` : "soil only"}
      </div>
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
// Groups — your judgement on the left, arithmetic on the right
// ---------------------------------------------------------------------------
function GroupsRail({ groups }: { groups: GroupsResponse | null }) {
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
        {!groups?.groups.length && (
          <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            None yet. A group is a set of holes that drill alike — nothing in the client's
            documents draws these lines, so they are yours.
          </p>
        )}
      </div>

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
  schedule,
  onChanged,
  onError,
}: {
  setId: string;
  groups: GroupsResponse | null;
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
  sources,
  onSaved,
  onError,
}: {
  setId: string;
  group: HoleGroup;
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

  const edit = (field: keyof HoleGroup, value: number) =>
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
          <NumberField
            label="platform build"
            value={draft.access_build_cost}
            unit="HK$"
            onChange={(v) => edit("access_build_cost", v)}
          />
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
