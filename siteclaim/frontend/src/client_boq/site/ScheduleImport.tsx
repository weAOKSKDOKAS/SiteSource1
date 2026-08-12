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

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { SchedulePasteResponse, ScheduleReadResponse, Station } from "../types";
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
  // What the tender already holds. null = the lookup has not answered yet (the one-click path is
  // simply not offered until it has — never a guess about drawings nobody counted).
  const [held, setHeld] = useState<{ count: number; names: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [drawn, setDrawn] = useState<ScheduleReadResponse | null>(null);

  useEffect(() => {
    let live = true;
    api
      .siteDrawings(setId)
      .then((r) => live && setHeld({ count: r.count, names: r.names }))
      .catch(() => live && setHeld({ count: 0, names: [] }));
    return () => {
      live = false;
    };
  }, [setId]);

  /** Read it off the drawings instead of typing it.
   *
   *  Measured on the reference pack: the schedule sheets are flattened raster carrying 28
   *  characters of text — the title-block stamp — so reading one is a vision call. Working out
   *  WHICH sheets they are is free, because the issuer ships a drawing register and it is the one
   *  document in the set with a real text layer. With NO files it reads the tender's own ingested
   *  drawings; with files, exactly those files.
   *
   *  It reads BOTH: the engineering schedule and the environmental one, which are billed under
   *  different bills. Stopping at the first would under-read the tender, and every check
   *  downstream would agree with it, because they all measure what was read against what was read.
   */
  const readDrawings = useCallback(
    async (files: File[]) => {
      setBusy(true);
      try {
        const report = await api.readStationSchedule(setId, files);
        setDrawn(report);
        // The proposal lands in the same review panel a pasted one does, so a machine reading and
        // a typed one get looked at the same way before either is saved.
        setRead({
          set_id: report.set_id,
          schedule: report.schedule,
          headline: report.headline,
          header_found: false,
          delimiter: "",
          mapping: {},
          unmapped_columns: [],
          missing_columns: [],
          skipped_lines: [],
          cells_unread: report.cells_unread,
          bad_rows: report.bad_rows,
          unread_rows: report.unread_rows,
          empty_rows: report.empty_rows,
          duplicate_names: report.duplicate_names,
          problems: report.problems,
          usable: report.usable,
          totals: report.totals,
        });
        if (report.triage.sheets.length) {
          setSheet(report.triage.sheets.map((entry) => entry.number).join(" + "));
        }
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [setId, onError],
  );

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
          <SectionLabel>READ IT OFF THE DRAWINGS</SectionLabel>
          {/* THE APP ALREADY HOLDS THE DRAWINGS. On the reference pack the archive ingest
              classified 35 DRG sheets and put every one on disk — and this screen used to ask
              the operator to go find those same PDFs in a Downloads folder and upload them
              again, with the button disabled until they did. One click now; upload stays below
              for a drawing that arrived outside the archive. */}
          {held && held.count > 0 && (
            <div className="mt-1">
              <p className="font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
                This tender already holds {held.count} drawing{held.count === 1 ? "" : "s"} from
                the ingest. The reader will use the drawing register to work out which sheets
                carry a station table — that part costs nothing — and then read those sheets.
                There are usually two: the engineering boreholes and the environmental holes,
                which are billed separately.
              </p>
              <Button
                variant="brass"
                disabled={busy}
                onClick={() => void readDrawings([])}
                className="mt-2"
              >
                Read the schedule off this tender&rsquo;s drawings
              </Button>
            </div>
          )}
          <p className="mt-2 font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            {held && held.count > 0
              ? "Or upload sheets that arrived outside the archive — a re-issued drawing, or a set that never went through ingest:"
              : "Give it the whole drawing folder. It reads the drawing register to work out which sheets carry a station table — that part costs nothing — and then reads those sheets. There are usually two: the engineering boreholes and the environmental holes, which are billed separately."}
          </p>
          <input
            type="file"
            accept="application/pdf"
            multiple
            disabled={busy}
            onChange={(e) => {
              const picked = [...(e.target.files ?? [])];
              e.target.value = "";
              if (picked.length) void readDrawings(picked);
            }}
            className="mt-2 w-full font-cb-sans text-[10.5px] text-cb-body"
          />
          {drawn && (
            <div
              className={cx(
                "mt-2 rounded-cb-btn border px-2.5 py-2",
                drawn.partial_sheets.length ||
                drawn.surrendered_sheets?.length ||
                drawn.sheets_read.some((s) => !s.read)
                  ? "border-cb-bad-line bg-cb-bad-tint"
                  : "border-cb-border bg-cb-tint",
              )}
            >
              <p className="font-cb-sans text-[10.5px] leading-[1.55] text-cb-body">
                {drawn.triage.headline}
              </p>
              {drawn.sheets_read.map((s) => (
                <p
                  key={s.sheet}
                  className={cx(
                    "mt-1 font-cb-sans text-[9.5px] leading-[1.5]",
                    // A PARTLY-READ SHEET IS NOT A READ SHEET, and neither is one whose rows
                    // carry no numbers. `read` is true for all three, because rows did come
                    // back — so both failures have to be as loud as an outright one, or a
                    // take-off short by twenty holes (or full of empty outlines) reads as a
                    // success. Measured live: 70 hollow rows looked fuller than 22 real ones.
                    !s.read || s.partial || s.gave_up ? "text-cb-bad-dark" : "text-cb-muted",
                  )}
                >
                  {s.headline}
                </p>
              ))}
            </div>
          )}
        </div>

        <div className="mt-5">
          <SectionLabel>OR PASTE IT — THE SHEET IT CAME FROM</SectionLabel>
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
