// ScheduleImport — the take-off's way in.
//
// `POST /site/schedule` has always accepted a station schedule, and until this file nothing in this
// application ever called it. The Site tab's empty state said "the station schedule has not been
// read yet" and offered no button, no upload and no editor — a dead end on the step that gates the
// bill-vs-drawing check, the access map, and the only place a hole is ever given its class.
//
// Ninety-one rows and twelve columns is a thousand form fields, and whatever the estimator is
// reading from — an Excel take-off, a table copied out of a PDF, a column of figures — is already
// tabular. So: paste it, see exactly what was understood, then save.
//
// The rule the panel is built around, and the reason the preview exists at all:
//
//     A CELL THE PARSER COULD NOT READ IS NAMED, NEVER FILLED IN.
//
// A soil cell that read "n/a" must not arrive as 0.00. It is shown as "not read", in red, and the
// schedule refuses to be usable until somebody settles it.

import { useCallback, useState } from "react";
import { api } from "../api";
import type { SchedulePasteResponse, Station } from "../types";
import { Button, SectionLabel, cx, formatNorm } from "../ui";

const EXAMPLE = `CE19-ABH01\t834120.5\t817430.2\t34.90\t5.00\t34.90\t40.0\t29.90\t0\t5.00\tY\tN`;

export function ScheduleImport({
  setId,
  hasSchedule,
  onSaved,
  onError,
}: {
  setId: string;
  /** Whether this replaces a take-off that already exists — the copy changes, the mechanics do not. */
  hasSchedule: boolean;
  onSaved: () => void;
  onError: (msg: string) => void;
}) {
  const [text, setText] = useState("");
  const [sheet, setSheet] = useState("");
  const [read, setRead] = useState<SchedulePasteResponse | null>(null);
  const [busy, setBusy] = useState(false);

  const parse = useCallback(async () => {
    setBusy(true);
    try {
      setRead(await api.parseStationSchedule(setId, text, sheet));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [setId, text, sheet, onError]);

  const save = useCallback(async () => {
    if (!read) return;
    setBusy(true);
    try {
      await api.saveStationSchedule(setId, read.schedule, sheet);
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [read, setId, sheet, onSaved, onError]);

  const stations = read?.schedule.stations ?? [];
  const notSettled = read
    ? [...read.bad_rows, ...read.unread_rows, ...read.empty_rows, ...read.duplicate_names]
    : [];

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto max-w-3xl px-6 py-6">
        <div className="font-cb-serif text-[17px] font-semibold text-cb-ink-text">
          {hasSchedule ? "Replace the take-off" : "Read in the take-off"}
        </div>
        <p className="mt-2 font-cb-sans text-[11.5px] leading-[1.65] text-cb-muted">
          Every quantity in Bill No.2 comes from the borehole details drawing — the coordinates, the
          ground and rockhead levels, and the soil and rock split of each hole. Paste the schedule
          here, one row per hole, columns separated by tabs or commas. Nothing is saved until you
          have looked at what was read.
        </p>

        <div className="mt-5">
          <SectionLabel>THE SHEET IT CAME FROM</SectionLabel>
          <input
            value={sheet}
            onChange={(e) => setSheet(e.target.value)}
            placeholder="60740338/GI/210"
            className="mt-1 w-full rounded-cb-btn border border-cb-border bg-cb-surface px-2 py-1.5 font-cb-mono text-[11px] text-cb-body outline-none focus:border-cb-brass-line"
          />
          <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            Recorded against every row, so a quantity can be traced back to the drawing it was read
            off. Optional, and worth typing.
          </p>
        </div>

        <div className="mt-4">
          <SectionLabel>THE SCHEDULE</SectionLabel>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            spellCheck={false}
            placeholder={
              "Station\tEasting\tNorthing\tGround Level\tRockhead\tTentative Length\tMax Boring" +
              "\tLength in Soil\tHard\tLength in Rock\tStandpipe\tPiezometer\n" +
              EXAMPLE
            }
            className="mt-1 w-full rounded-cb-btn border border-cb-border bg-cb-surface p-2 font-cb-mono text-[10.5px] leading-[1.6] text-cb-body outline-none focus:border-cb-brass-line"
          />
          <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
            A header row is read by name if you paste one. Without it the columns are taken in the
            order the sheet prints them — station, easting, northing, ground level, rockhead,
            tentative length, max boring, soil, hard, rock, standpipe, piezometer. Trial pits go to
            their own list by name.
          </p>
        </div>

        <div className="mt-3 flex items-center gap-2">
          <Button
            variant="dark"
            onClick={parse}
            disabled={busy}
            disabledReason={text.trim() ? undefined : "Paste the schedule first."}
          >
            Read it
          </Button>
          {read && (
            <Button
              variant="brass"
              onClick={save}
              disabled={busy}
              disabledReason={stations.length ? undefined : "Nothing was read, so there is nothing to save."}
            >
              {hasSchedule ? "Replace the take-off" : "Save as the take-off"}
            </Button>
          )}
        </div>

        {read && (
          <>
            <div
              className={cx(
                "mt-5 rounded-cb-btn border px-3 py-2",
                read.usable && !read.skipped_lines.length
                  ? "border-cb-border bg-cb-tint"
                  : "border-cb-bad-line bg-cb-bad-tint",
              )}
            >
              <p className="font-cb-sans text-[11px] leading-[1.6] text-cb-body">{read.headline}</p>
              <p className="mt-1 font-cb-mono text-[9.5px] text-cb-faint">
                {read.header_found ? "header read by name" : "no header — columns taken by position"}
                {" · "}separated by {read.delimiter}
                {read.unmapped_columns.length > 0 &&
                  ` · ignored: ${read.unmapped_columns.join(", ")}`}
              </p>
            </div>

            {notSettled.length > 0 && (
              <div className="mt-3">
                <SectionLabel>ROWS THAT ARE NOT SETTLED</SectionLabel>
                {notSettled.map((row) => (
                  <p
                    key={row}
                    className="mt-1 font-cb-sans text-[10px] leading-[1.55] text-cb-bad-dark"
                  >
                    {row}
                  </p>
                ))}
                <p className="mt-2 font-cb-sans text-[9.5px] leading-[1.55] text-cb-faint">
                  You can still save this. It will be stored exactly as read, with every one of
                  these named on the schedule — no cell is filled in on your behalf, and the take-off
                  reads as unusable until they are settled.
                </p>
              </div>
            )}

            {read.skipped_lines.length > 0 && (
              <div className="mt-3">
                <SectionLabel>LINES THAT WERE NOT ROWS</SectionLabel>
                {read.skipped_lines.map((line) => (
                  <p key={line} className="mt-1 font-cb-mono text-[9.5px] text-cb-muted">
                    {line}
                  </p>
                ))}
              </div>
            )}

            {stations.length > 0 && <Preview stations={stations} totals={read.totals} />}

            {read.schedule.trial_pits.length > 0 && (
              <p className="mt-3 font-cb-sans text-[10px] leading-[1.55] text-cb-muted">
                {read.schedule.trial_pits.length} trial pit(s) went to their own list — they are
                measured by volume and dug rather than drilled, so they never join a drilling group.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Preview({
  stations,
  totals,
}: {
  stations: Station[];
  totals: Partial<Record<string, number>>;
}) {
  const head = "px-2 py-1.5 font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-faint";
  const cell = "px-2 py-1 font-cb-mono text-[10px] text-cb-body";

  // Refuses to print a number for a cell nobody could read. This is the whole point of the preview:
  // a confident "0.00" under SOIL is the failure the parser exists to prevent, and it would be
  // invisible here if the preview rendered the model's default like any other value.
  const Cell = ({ s, field, children }: { s: Station; field: string; children: React.ReactNode }) =>
    s.unread.includes(field) ? (
      <td className={cx(cell, "text-right font-semibold text-cb-bad-dark")}>not read</td>
    ) : (
      <td className={cx(cell, "text-right")}>{children}</td>
    );

  return (
    <div className="mt-4">
      <SectionLabel>
        WHAT WAS READ · {stations.length} HOLE(S) · {formatNorm(totals.soil_m ?? 0)} M SOIL ·{" "}
        {formatNorm(totals.rock_m ?? 0)} M ROCK
      </SectionLabel>
      <div className="mt-1 max-h-80 overflow-auto rounded-cb-btn border border-cb-border">
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
            {stations.map((s, i) => (
              <tr key={`${s.station}-${i}`} className="border-b border-cb-divider last:border-0">
                <td className={cx(cell, "font-semibold text-cb-ink-text")}>{s.station}</td>
                <Cell s={s} field="easting">{num(s.easting)}</Cell>
                <Cell s={s} field="northing">{num(s.northing)}</Cell>
                <Cell s={s} field="ground_level_mpd">{num(s.ground_level_mpd)}</Cell>
                <Cell s={s} field="soil_m">{formatNorm(s.soil_m)}</Cell>
                <Cell s={s} field="rock_m">{s.rock_m ? formatNorm(s.rock_m) : "—"}</Cell>
                <Cell s={s} field="standpipe">{s.standpipe ? "✓" : "—"}</Cell>
                <Cell s={s} field="piezometer">{s.piezometer ? "✓" : "—"}</Cell>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const num = (v: number | null) => (v === null ? "—" : formatNorm(v));
