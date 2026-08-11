# What the schedule reader still needs, precisely

**Status:** blocked on one artefact. Written 2026-08-11.
**Read with:** `reading_the_station_schedule.md`, which answered the five research questions.

Steps 1 and 2 landed — the `unread` mark, `empty_rows()`, `duplicate_names()`, and the paste door.
Steps 3 and 4 are sheet triage and vision transcription, and I declined to build them against a
synthesised raster because *a synthetic raster is a picture of our own assumptions: it can prove the
plumbing and it cannot measure the reading.* That judgement stands. Here is what would unblock it,
in a form that can be acted on.

---

## 1. Which sheet

**`GI/210`**, on the reference contract — the borehole details drawing. Named in
`build_backlog.md:814-817` as carrying, per borehole: easting, northing, ground level, rockhead,
total depth, tentative length in soil, expected length in rock, standpipe ✓, piezometer ✓ — plus a
second table of 21 trial pits.

**One sheet is enough to start.** If a second is cheap, `GI/310` (the environmental holes'
coordinate table) would tell me whether the two tables share a layout or are laid out differently,
which decides whether the reader can be one prompt or must be per-sheet. `GI/100` (the tentative
in-situ test quantities) is the third most useful and is not needed for the take-off.

**Two things about the naming I could not settle from the repo, and either answer is fine — I just
need to know which:** the docs say the pack holds **33** drawings and the brief said 35; and the
strings `DWGS COMBINED`, `DWGS` and `60740338-GI-` appear nowhere in this repository, so I do not
know the real filenames. Whatever arrives, I will read the names off it rather than assume.

## 2. What form

**A rendered PNG at a capped width is enough for the transcription step, and NOT enough for the
triage step. I would like the source PDF for the sheet, and I can work from a PNG.**

Why, specifically:

- **The transcription** (step 4) sends an image to a vision model regardless. `pdfops.render_page`
  caps at `MAX_RENDER_WIDTH_PX = 1400` and `MAX_RENDER_DPI = 300`, and the API downscales again, so
  a PNG somebody exported at ~2,500–4,000 px on the long edge is the same input the reader would
  produce. A PNG answers: are the columns legible at that width; does a 91-row table survive the
  downscale; are the ticks distinguishable from the blanks; is the rockhead column ever written as
  a level rather than a depth.
- **The triage** (step 3) is a question about the *file*, not the picture: does the sheet carry a
  text layer at all, does the PDF's `title`/`subject` metadata name it, does the filename, are there
  bookmarks. All four are free — 5.0 ms/page measured — and all four are destroyed by exporting to
  PNG. My whole cost argument rests on answering "which of 33 sheets is this one" for nothing before
  spending a token, and I cannot test that on a raster export.

**So, in order of usefulness:**

1. `GI/210` as its **source PDF page** — one page, and it sidesteps the 232 MB pack.
2. Failing that, a **PNG at the highest width you have** (≥2,500 px on the long edge), plus the
   sheet's **filename** as a separate line of text.
3. If neither: a PNG at any width still lets me build and measure the transcription half; I would
   ship the triage half as untested plumbing and say so on the screen.

**It must live outside version control.** Root `.gitignore:5` blocks `*.png`, and the standing rule
in this repo is that no client tender data enters it — `_bqfixture.py:2-4`, `_hke_workbook.py:12-13`,
`build_backlog.md:779-780`. `_hke_workbook.py` is the precedent: the transcription lives in the repo
and the source workbook does not.

## 3. What I need to know about it, beyond the pixels

The reader is graded, not trusted, so I need something to grade against.

**The ground truth: the 91 rows as CSV or JSON** — station, easting, northing, ground level,
rockhead, total depth, soil, rock, standpipe, piezometer. Without it I can tell you the reader ran;
I cannot tell you it was right, and "it produced 91 plausible rows" is exactly the claim this whole
module exists to refuse. The transcription itself may live in the repo (the `_hke_workbook.py`
precedent) even though the drawing may not.

**And the answers to five questions the pixels may not settle:**

1. **Is the table on one sheet, or continued?** A 91-row table on A1 is plausible; if it breaks
   across GI/210 and a second sheet, the reader needs to know that a part-table is normal rather
   than a failed read.
2. **How is a blank printed?** Empty cell, a dash, `-`, `N/A`? This decides what `unread` catches.
   A hyphen in a rock column is "no rock"; a smudge is "I could not read it"; the module already
   treats those as different states and I need to know which mark means which.
3. **How is a tick printed?** ✓, a cross, a filled circle, a letter? A vision model will describe
   whatever it sees, and the parser has to map it. Getting this wrong reads 47 standpipes and 68
   piezometers as uninstrumented.
4. **Is the rockhead a LEVEL (mPD) or a DEPTH?** The model's field is `rockhead_level_mpd`. If the
   sheet prints a depth, every row is wrong by the ground level and the per-row arithmetic check
   would not catch it, because soil + rock still equals the length.
5. **What is the row pitch and the raster resolution?** Whether a 91-row table survives the ~1,568 px
   downscale the API applies is the single biggest open question about whether this works at all. If
   it does not, the reader must slice the sheet into row bands and make several calls, which changes
   the cost estimate by an order of magnitude.

## 4. What arrives with it, and what does not

**What I will build once it lands:** the deterministic triage (metadata → filename → text layer →
width-capped thumbnails), then two vision calls behind a job — one asking *which sheet*, one asking
*what does this table say* — producing a `StationSchedule` **proposal** with `confirmed=False`, every
unreadable cell marked `unread`, and the whole thing graded against the CSV before anything is
claimed on a screen.

**What will still not be true:** that the reader works on a different client's drawing. One sheet
proves the mechanism and one contract's conventions. The screen will say so.

**What needs no drawing and is already done:** the `unread` mark, the empty-row and duplicate-name
checks, the paste door, `Station.notes` now being read rather than discarded, and the sweep's
unclassed-hole refusal now firing when the take-off is *absent* rather than only when it is present
and incomplete.
