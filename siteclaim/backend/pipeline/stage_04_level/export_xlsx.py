"""Excel export of the levelled comparison — a professional tender bid-adjudication
workbook (openpyxl, imported lazily so the leveling math / DEMO_MODE never depend
on it).

Sheets:
  * Summary                  — title block + a ranking table per work section,
                               recommended tenderer per section, benchmark shown
                               distinctly as a baseline (not a tenderer).
  * <one per section>        — the Schedule-of-Rates comparison. The tender's own
                               scheduled rates are the FIRST, distinct data column
                               (the benchmark); the firms taken to bid follow, each
                               with Rate / Amount / variance-vs-benchmark. Corrected
                               and normalised subtotals are bold; rates above the
                               scheduled rate are shaded.
  * Arithmetic Corrections   — every qty×rate correction (stated vs computed).
  * Scope Normalisation      — each scope gap added back at the peer rate, showing the
                               like-for-like flip.
  * Qualifications & Exclusions — each tenderer's stated exclusions / assumptions.

All values are read from the levelled bids, the bid line items (Qty/Unit), the
arithmetic findings, the scope gaps, and the "tender-scheduled-rates" benchmark bid
already present in the replies — nothing is invented here.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Optional

from rules_engine.leveling import peer_item_reference
from schemas.models import BidReply, LevelledBid

OUT_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "out" / "leveling.xlsx"

BENCHMARK_ID = "tender-scheduled-rates"
_CUR = '"HK$"#,##0'
_PCT = "+0.0%;-0.0%;0.0%"

# Honesty scoping (drainage demo): a section is only labelled when it carries the
# tender's scheduled-rate benchmark. Field testing returned no subcontractor SoR, so
# its bid columns are illustrative; in the other benchmarked sections the named real
# bidder's column is its true submitted rates and the second column is representative.
_REAL_BID_IDS = {
    "kai-wai-engineering-survey-and-geophysics-limited-3f7b",
    "sixense-limited-5d2c",
}
_ILLUSTRATIVE_TRADES = {"field_testing"}

_TITLES = {
    "field_testing": "Field Testing",
    "field_installations": "Field Installations",
    "geophysical_survey": "Geophysical Survey",
    "drilling": "Drilling",
    "sampling": "Sampling",
    "electrical": "Electrical",
    "mechanical_plumbing": "Mechanical & Plumbing",
    "fire_services": "Fire Services",
    "joinery_fitting_out": "Joinery & Fitting-out",
}


def _title(trade: str) -> str:
    return _TITLES.get(trade, trade.replace("_", " ").title())


def _sheet_name(name: str, used: set[str]) -> str:
    base = name[:31]
    candidate, i = base, 1
    while candidate in used:
        i += 1
        candidate = f"{base[:28]}~{i}"
    used.add(candidate)
    return candidate


def _bid_tag(trade: str, firm_id: str, has_benchmark: bool) -> str:
    """The honesty suffix on a bidder's column header (only in benchmarked sections)."""
    if not has_benchmark:
        return ""
    if trade in _ILLUSTRATIVE_TRADES:
        return " (illustrative)"
    if firm_id in _REAL_BID_IDS:
        return ""
    return " (representative)"


def _bid_label(firm_name: str, trade: str, firm_id: str, has_benchmark: bool) -> str:
    """Column header = firm name + honesty suffix, without doubling a marker the DB
    profile name already carries (e.g. ``Subcontractor GI-1 (illustrative)``)."""
    tag = _bid_tag(trade, firm_id, has_benchmark)
    if tag and tag.strip().lower() in firm_name.lower():
        return firm_name
    return f"{firm_name}{tag}"


def _section_note(trade: str, has_benchmark: bool) -> str:
    if not has_benchmark:
        return ""
    if trade in _ILLUSTRATIVE_TRADES:
        return (
            "No subcontractor schedule of rates was returned for this package — the bid "
            "columns are illustrative. The benchmark column is the tender's own scheduled rates."
        )
    return (
        "The named firm's column is its real submitted rates; the competitor column is "
        "representative. The benchmark column is the tender's own scheduled rates."
    )


def export_leveling_xlsx(
    levelled: list[LevelledBid],
    replies: list[BidReply],
    item_order: Optional[list[str]] = None,
    path: Path | str = OUT_PATH,
    project_name: str = "",
    *,
    employer: str = "",
    engineer: str = "",
    prepared_by: str = "",
    checked_by: str = "",
) -> Path:
    """Write the adjudication workbook to ``path`` and return it."""
    from openpyxl import Workbook  # lazy — leveling math must not require openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    # ---- shared styles -----------------------------------------------------
    INK = "0F1B2D"
    BENCH = "1F4E66"  # benchmark band — distinct from the tenderer band
    band = PatternFill("solid", fgColor=INK)
    bench_band = PatternFill("solid", fgColor=BENCH)
    band_font = Font(bold=True, color="FFFFFF", size=10)
    title_font = Font(bold=True, size=15, color=INK)
    sub_font = Font(size=9.5, italic=True, color="6B7A90")
    key_font = Font(bold=True, color=INK)
    bold = Font(bold=True)
    subtotal_fill = PatternFill("solid", fgColor="EEF2F8")
    bench_col_fill = PatternFill("solid", fgColor="EAF1F8")  # benchmark data column
    flag_fill = PatternFill("solid", fgColor="FCE4E4")        # rate above benchmark
    rec_fill = PatternFill("solid", fgColor="E5F4EC")         # recommended row
    thin = Side(style="thin", color="D5DCE6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    right = Alignment(horizontal="right")
    left = Alignment(horizontal="left", vertical="top", wrap_text=True)
    centre = Alignment(horizontal="center", vertical="center")
    centre_wrap = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def box(ws, r1, c1, r2, c2, *, fill=None, font=None, align=None, bordered=True):
        for rr in range(r1, r2 + 1):
            for cc in range(c1, c2 + 1):
                cell = ws.cell(row=rr, column=cc)
                if fill is not None:
                    cell.fill = fill
                if font is not None:
                    cell.font = font
                if align is not None:
                    cell.alignment = align
                if bordered:
                    cell.border = border

    # ---- data indexes ------------------------------------------------------
    trades: list[str] = []
    for b in levelled:
        if b.trade not in trades:
            trades.append(b.trade)
    line_of = {(r.firm_id, r.trade, ln.item_ref): ln for r in replies for ln in r.line_items}
    reply_of = {(r.firm_id, r.trade): r for r in replies}
    peer = peer_item_reference(replies)

    def section_bids(trade: str):
        bids = [b for b in levelled if b.trade == trade]
        tenderers = [b for b in bids if b.firm_id != BENCHMARK_ID]
        benchmark = next((b for b in bids if b.firm_id == BENCHMARK_ID), None)
        return tenderers, benchmark

    def ranked(tenderers: list[LevelledBid]) -> list[LevelledBid]:
        return sorted(tenderers, key=lambda b: (b.normalized_total, b.corrected_total))

    def section_items(trade: str, tenderers, benchmark) -> list[str]:
        order: list[str] = []
        for b in [*( [benchmark] if benchmark else []), *tenderers]:
            rep = reply_of.get((b.firm_id, trade))
            for ln in (rep.line_items if rep else []):
                if ln.item_ref not in order:
                    order.append(ln.item_ref)
        if item_order:  # honour an explicit hint where it overlaps this section
            hinted = [i for i in item_order if i in order]
            order = hinted + [i for i in order if i not in hinted]
        return order

    def fit(ws, widths: dict[int, int]) -> None:
        for col, w in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = w

    wb = Workbook()
    used_names: set[str] = set()

    # =======================================================================
    # SHEET: Summary  (title block + per-section ranking)
    # =======================================================================
    ws = wb.active
    ws.title = _sheet_name("Summary", used_names)
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:F1")
    ws["A1"] = "Tender Bid Adjudication — Levelled Comparison"
    ws["A1"].font = title_font

    code = (project_name or "").split(" — ")[0].strip()
    ctitle = project_name.split(" — ", 1)[1].strip() if " — " in (project_name or "") else ""
    meta: list[tuple[str, str]] = []
    if code:
        meta.append(("Contract No.", code))
    if ctitle:
        meta.append(("Contract", ctitle))
    if not code and not ctitle:
        meta.append(("Project", "Tender — levelled bid comparison"))
    if employer:
        meta.append(("Employer / Main Contractor", employer))
    if engineer:
        meta.append(("Engineer", engineer))
    meta.append(("Date", _dt.date.today().strftime("%d %b %Y")))
    meta.append(("Prepared by", prepared_by or "SiteSource — automated bid adjudication"))
    meta.append(("Checked by", checked_by or "For review and award by the Quantity Surveyor"))

    r = 2
    for k, v in meta:
        ws.cell(row=r, column=1, value=k).font = key_font
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
        ws.cell(row=r, column=2, value=v)
        r += 1
    ws.cell(row=r, column=1, value="Commercial in confidence").font = sub_font
    r += 2

    rec_lines: list[tuple[str, str]] = []
    for trade in trades:
        tenderers, benchmark = section_bids(trade)
        order = ranked(tenderers)
        rec = order[0] if order else None
        if rec:
            rec_lines.append((_title(trade), rec.firm_name))

        ws.cell(row=r, column=1, value=f"Section — {_title(trade)}").font = Font(bold=True, size=11, color=INK)
        r += 1
        head = ["Tenderer", "Corrected sum", "Normalised sum", "Rank", "Recommended", "Basis"]
        for c, h in enumerate(head, start=1):
            cell = ws.cell(row=r, column=c, value=h)
            cell.fill, cell.font, cell.border = band, band_font, border
            cell.alignment = centre if c in (4, 5) else left
        r += 1
        cheapest_corrected = min((b.corrected_total for b in tenderers), default=0.0)
        for i, b in enumerate(order, start=1):
            recommended = i == 1
            flip = recommended and b.corrected_total > cheapest_corrected + 0.5
            basis = (
                ("Lowest normalised tender sum after scope normalisation (a lower-priced bid omitted scope)"
                 if flip else "Lowest normalised (like-for-like) tender sum")
                if recommended else "Higher normalised tender sum"
            )
            vals = [b.firm_name, b.corrected_total, b.normalized_total, i, "Y" if recommended else "N", basis]
            for c, v in enumerate(vals, start=1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.border = border
                if c in (2, 3):
                    cell.number_format, cell.alignment = _CUR, right
                elif c in (4, 5):
                    cell.alignment = centre
                else:
                    cell.alignment = left
                if recommended:
                    cell.fill = rec_fill
                    if c in (1, 5):
                        cell.font = bold
            r += 1
        if benchmark:
            vals = [f"{benchmark.firm_name}", benchmark.corrected_total, benchmark.normalized_total, "—", "—",
                    "Tender Schedule of Rates — baseline for comparison, not a tenderer"]
            for c, v in enumerate(vals, start=1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.border, cell.fill = border, bench_col_fill
                cell.font = Font(italic=True, color=BENCH, bold=(c == 1))
                if c in (2, 3):
                    cell.number_format, cell.alignment = _CUR, right
                elif c in (4, 5):
                    cell.alignment = centre
                else:
                    cell.alignment = left
            r += 1
        r += 1

    ws.cell(row=r, column=1, value="Recommended award by section").font = bold
    r += 1
    for sect, firm in rec_lines:
        ws.cell(row=r, column=1, value=sect).font = key_font
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
        ws.cell(row=r, column=2, value=firm)
        r += 1
    fit(ws, {1: 34, 2: 16, 3: 16, 4: 7, 5: 13, 6: 56})
    ws.freeze_panes = "A2"

    # =======================================================================
    # SHEET per section: the SoR comparison (benchmark first, then tenderers)
    # =======================================================================
    finding_items = {(b.firm_id, b.trade): {f.location.replace("line ", "") for f in b.arithmetic_findings} for b in levelled}
    gap_items = {(b.firm_id, b.trade): {g.split(" — ")[0] for g in b.scope_gaps} for b in levelled}

    for trade in trades:
        tenderers, benchmark = section_bids(trade)
        has_bench = benchmark is not None
        order = section_items(trade, tenderers, benchmark)
        wss = wb.create_sheet(_sheet_name(_title(trade), used_names))
        wss.sheet_view.showGridLines = False

        # ---- column geometry: Item·Desc·Unit·Qty | [Bench Rate·Amount] |
        #      per tenderer [Rate·Amount·Var] | Remarks
        col = 5
        bench_rate_col = bench_amt_col = None
        if has_bench:
            bench_rate_col, bench_amt_col = col, col + 1
            col += 2
        rate_col, amt_col, var_col = {}, {}, {}
        for b in tenderers:
            rate_col[b.firm_id], amt_col[b.firm_id], var_col[b.firm_id] = col, col + 1, col + 2
            col += 3
        remarks_col = col
        ncols = remarks_col

        # row 1: banner ; row 2: honesty note ; rows 3-4: two-row header ; data row 5+
        wss.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
        wss.cell(row=1, column=1, value=f"{_title(trade)} — Schedule of Rates comparison (levelled)").font = title_font
        note = _section_note(trade, has_bench)
        wss.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
        nc = wss.cell(row=2, column=1, value=note)
        nc.font, nc.alignment = sub_font, left

        # identity columns span the two header rows
        for c, label in ((1, "Item"), (2, "Description"), (3, "Unit"), (4, "Qty")):
            wss.merge_cells(start_row=3, start_column=c, end_row=4, end_column=c)
            wss.cell(row=3, column=c, value=label)
            box(wss, 3, c, 4, c, fill=band, font=band_font, align=centre_wrap)
        # benchmark group
        if has_bench:
            wss.merge_cells(start_row=3, start_column=bench_rate_col, end_row=3, end_column=bench_amt_col)
            wss.cell(row=3, column=bench_rate_col, value="Tender Scheduled Rates (Benchmark)")
            box(wss, 3, bench_rate_col, 3, bench_amt_col, fill=bench_band, font=band_font, align=centre_wrap)
            wss.cell(row=4, column=bench_rate_col, value="Rate")
            wss.cell(row=4, column=bench_amt_col, value="Amount")
            box(wss, 4, bench_rate_col, 4, bench_amt_col, fill=bench_band, font=band_font, align=centre_wrap)
        # tenderer groups
        for b in tenderers:
            wss.merge_cells(start_row=3, start_column=rate_col[b.firm_id], end_row=3, end_column=var_col[b.firm_id])
            wss.cell(row=3, column=rate_col[b.firm_id], value=_bid_label(b.firm_name, trade, b.firm_id, has_bench))
            box(wss, 3, rate_col[b.firm_id], 3, var_col[b.firm_id], fill=band, font=band_font, align=centre_wrap)
            wss.cell(row=4, column=rate_col[b.firm_id], value="Rate")
            wss.cell(row=4, column=amt_col[b.firm_id], value="Amount")
            wss.cell(row=4, column=var_col[b.firm_id], value="Var vs SR")
            box(wss, 4, rate_col[b.firm_id], 4, var_col[b.firm_id], fill=band, font=band_font, align=centre_wrap)
        # remarks spans both header rows
        wss.merge_cells(start_row=3, start_column=remarks_col, end_row=4, end_column=remarks_col)
        wss.cell(row=3, column=remarks_col, value="Remarks / flags")
        box(wss, 3, remarks_col, 4, remarks_col, fill=band, font=band_font, align=centre_wrap)

        row = 5
        for item in order:
            sources = [*( [benchmark] if has_bench else []), *tenderers]
            sample = next((line_of.get((b.firm_id, trade, item)) for b in sources if line_of.get((b.firm_id, trade, item))), None)
            if sample is None:
                continue
            provisional = "provisional" in (sample.description or "").lower()
            wss.cell(row=row, column=1, value=item)
            wss.cell(row=row, column=2, value=sample.description)
            wss.cell(row=row, column=3, value=sample.unit)
            qcell = wss.cell(row=row, column=4, value=sample.qty)
            qcell.number_format = "#,##0.##"
            remarks: list[str] = []

            bench_line = line_of.get((BENCHMARK_ID, trade, item)) if has_bench else None
            bench_rate = bench_line.rate if bench_line else None
            if has_bench:
                rc = wss.cell(row=row, column=bench_rate_col)
                ac = wss.cell(row=row, column=bench_amt_col)
                if bench_line and bench_line.rate is not None:
                    rc.value, rc.number_format = bench_line.rate, _CUR
                    ac.value, ac.number_format = round(bench_line.qty * bench_line.rate, 2), _CUR
                else:
                    rc.value, ac.value = "—", "—"
                rc.alignment = ac.alignment = right
                rc.fill = ac.fill = bench_col_fill

            for b in tenderers:
                ln = line_of.get((b.firm_id, trade, item))
                rc = wss.cell(row=row, column=rate_col[b.firm_id])
                ac = wss.cell(row=row, column=amt_col[b.firm_id])
                vc = wss.cell(row=row, column=var_col[b.firm_id])
                rc.alignment = ac.alignment = vc.alignment = right
                if ln is None or ln.rate is None:
                    rc.value = ac.value = vc.value = "—"
                    if item in gap_items.get((b.firm_id, trade), set()):
                        rc.fill = ac.fill = flag_fill
                        remarks.append(f"{b.firm_name}: not priced — scope gap")
                else:
                    rc.value, rc.number_format = ln.rate, _CUR
                    ac.value, ac.number_format = round(ln.qty * ln.rate, 2), _CUR
                    if bench_rate not in (None, 0):
                        vc.value, vc.number_format = (ln.rate - bench_rate) / bench_rate, _PCT
                        if ln.rate > bench_rate:
                            rc.fill = flag_fill
                            remarks.append(f"{b.firm_name}: rate above benchmark")
                    else:
                        vc.value = "—"
                if item in finding_items.get((b.firm_id, trade), set()):
                    remarks.append(f"{b.firm_name}: arithmetic corrected")
            if provisional:
                remarks.append("Provisional sum — carried separately")
            rcell = wss.cell(row=row, column=remarks_col, value="; ".join(dict.fromkeys(remarks)))
            rcell.alignment = left
            for c in range(1, ncols + 1):
                wss.cell(row=row, column=c).border = border
            row += 1

        # subtotal rows: corrected then normalised
        for label, attr in (("Corrected tender sum", "corrected_total"), ("Normalised tender sum (like-for-like)", "normalized_total")):
            wss.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
            wss.cell(row=row, column=1, value=label).font = bold
            if has_bench:
                cell = wss.cell(row=row, column=bench_amt_col, value=getattr(benchmark, attr))
                cell.number_format, cell.font, cell.alignment, cell.fill = _CUR, bold, right, bench_col_fill
            for b in tenderers:
                cell = wss.cell(row=row, column=amt_col[b.firm_id], value=getattr(b, attr))
                cell.number_format, cell.font, cell.alignment = _CUR, bold, right
            for c in range(1, ncols + 1):
                cell = wss.cell(row=row, column=c)
                cell.border = border
                if not (has_bench and c in (bench_rate_col, bench_amt_col)):
                    cell.fill = subtotal_fill
                if not cell.font.bold:
                    cell.font = bold
            row += 1

        widths = {1: 10, 2: 46, 3: 9, 4: 8}
        if has_bench:
            widths[bench_rate_col] = 13
            widths[bench_amt_col] = 14
        for b in tenderers:
            widths[rate_col[b.firm_id]] = 13
            widths[amt_col[b.firm_id]] = 14
            widths[var_col[b.firm_id]] = 10
        widths[remarks_col] = 42
        fit(wss, widths)
        wss.row_dimensions[3].height = 42
        wss.freeze_panes = "E5"

    # =======================================================================
    # SHEET: Arithmetic Corrections
    # =======================================================================
    wsa = wb.create_sheet(_sheet_name("Arithmetic Corrections", used_names))
    wsa.sheet_view.showGridLines = False
    head = ["Tenderer", "Section", "Item", "Stated amount", "Computed (Qty × Rate)", "Corrected"]
    for c, h in enumerate(head, start=1):
        wsa.cell(row=1, column=c, value=h)
    box(wsa, 1, 1, 1, len(head), fill=band, font=band_font, align=centre)
    row = 2
    for b in levelled:
        for f in b.arithmetic_findings:
            item = f.location.replace("line ", "")
            ln = line_of.get((b.firm_id, b.trade, item))
            stated = ln.amount if ln else None
            vals = [b.firm_name, _title(b.trade), item, stated, f.corrected_value, f.corrected_value]
            for c, v in enumerate(vals, start=1):
                cell = wsa.cell(row=row, column=c, value=v)
                cell.border = border
                if c >= 4:
                    cell.number_format, cell.alignment = _CUR, right
            row += 1
    if row == 2:
        wsa.merge_cells("A2:F2")
        wsa.cell(row=2, column=1, value="No arithmetic corrections — all stated amounts tie to Qty × Rate.").font = sub_font
    fit(wsa, {1: 40, 2: 18, 3: 9, 4: 16, 5: 20, 6: 16})
    wsa.freeze_panes = "A2"

    # =======================================================================
    # SHEET: Scope Normalisation
    # =======================================================================
    wsn = wb.create_sheet(_sheet_name("Scope Normalisation", used_names))
    wsn.sheet_view.showGridLines = False
    wsn.merge_cells("A1:F1")
    wsn.cell(row=1, column=1, value="Scope normalisation — unpriced items added back at the peer (median) rate so every bid is compared like-for-like").font = sub_font
    head = ["Tenderer", "Section", "Item / description", "Peer amount added", "Corrected sum", "Normalised sum"]
    for c, h in enumerate(head, start=1):
        wsn.cell(row=2, column=c, value=h)
    box(wsn, 2, 1, 2, len(head), fill=band, font=band_font, align=centre)
    row = 3
    any_gap = False
    for b in levelled:
        if not b.scope_gaps:
            continue
        any_gap = True
        first = True
        for gap in b.scope_gaps:
            item = gap.split(" — ")[0]
            added = peer.get(item, 0.0)
            desc = gap.split(" — ", 1)[1] if " — " in gap else gap
            vals = [b.firm_name if first else "", _title(b.trade) if first else "", f"{item} — {desc}", added,
                    b.corrected_total if first else "", b.normalized_total if first else ""]
            for c, v in enumerate(vals, start=1):
                cell = wsn.cell(row=row, column=c, value=v)
                cell.border = border
                if c in (4, 5, 6) and isinstance(v, (int, float)):
                    cell.number_format, cell.alignment = _CUR, right
                if c == 3:
                    cell.alignment = left
            first = False
            row += 1
    if not any_gap:
        wsn.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        wsn.cell(row=row, column=1, value="No scope gaps — every tenderer priced the full scope.").font = sub_font
    fit(wsn, {1: 40, 2: 18, 3: 48, 4: 18, 5: 16, 6: 16})
    wsn.freeze_panes = "A3"

    # =======================================================================
    # SHEET: Qualifications & Exclusions
    # =======================================================================
    wsq = wb.create_sheet(_sheet_name("Qualifications & Exclusions", used_names))
    wsq.sheet_view.showGridLines = False
    wsq.merge_cells("A1:C1")
    wsq.cell(row=1, column=1, value="Stated exclusions and assumptions are flagged as non-comparable and are NOT deducted from the tender sum.").font = sub_font
    head = ["Tenderer", "Section", "Stated exclusion / assumption"]
    for c, h in enumerate(head, start=1):
        wsq.cell(row=2, column=c, value=h)
    box(wsq, 2, 1, 2, len(head), fill=band, font=band_font, align=centre)
    row = 3
    any_excl = False
    for b in levelled:
        for ex in b.exclusions:
            any_excl = True
            wsq.cell(row=row, column=1, value=b.firm_name).border = border
            wsq.cell(row=row, column=2, value=_title(b.trade)).border = border
            cell = wsq.cell(row=row, column=3, value=ex)
            cell.border, cell.alignment = border, left
            row += 1
    if not any_excl:
        wsq.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        wsq.cell(row=row, column=1, value="No stated exclusions or qualifications.").font = sub_font
    fit(wsq, {1: 40, 2: 18, 3: 76})
    wsq.freeze_panes = "A3"

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
