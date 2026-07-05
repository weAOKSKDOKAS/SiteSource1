"""Excel export of the levelled comparison (openpyxl, imported lazily).

A multi-sheet workbook — ONE sheet per trade: each sheet carries a row per SoR item
with each of that trade's firms' rate and corrected amount, a totals row of each
firm's ``corrected_total``, and a Notes column calling out corrected lines and scope
gaps; stated exclusions are listed below the table. Two trades' items are never
merged into one table. Saved to ``backend/fixtures/out/leveling.xlsx`` by default.

openpyxl is imported inside the function so the leveling arithmetic (and DEMO_MODE)
never depend on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rules_engine.leveling import computable_amount
from schemas.models import BidReply, LevelledBid

OUT_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "out" / "leveling.xlsx"


def sheet_title(trade: str) -> str:
    """A valid worksheet name for a trade key ("mechanical_plumbing" -> "Mechanical
    Plumbing"), capped at Excel's 31-character sheet-name limit."""
    label = (trade or "").replace("_", " ").strip().title() or "Leveling"
    return label[:31]


def export_leveling_xlsx(
    levelled: list[LevelledBid],
    replies: list[BidReply],
    item_order: Optional[list[str]] = None,
    path: Path | str = OUT_PATH,
    *,
    project_name: str = "",
) -> Path:
    """Write the levelled comparison to ``path`` and return it — one styled sheet per
    trade, plus a Summary cover tab when the comparison spans more than one trade."""
    from openpyxl import Workbook  # lazy — leveling math must not require openpyxl

    # Group by trade, preserving first-seen order. Each trade is written as its own
    # sheet so a multi-trade comparison never mixes two trades' items in one table.
    trades: list[str] = []
    for b in levelled:
        if b.trade not in trades:
            trades.append(b.trade)

    wb = Workbook()
    first_used = False
    if not trades:  # nothing levelled — keep a single empty comparison sheet
        wb.active.title = "Leveling"
        first_used = True
    if len(trades) > 1:  # the cover tab: each trade's corrected totals at a glance
        ws = wb.active
        ws.title = "Summary"
        first_used = True
        _write_summary_sheet(ws, trades, levelled, project_name)
    for trade in trades:
        ws = wb.create_sheet() if first_used else wb.active
        first_used = True
        ws.title = sheet_title(trade)
        _write_trade_sheet(
            ws,
            [b for b in levelled if b.trade == trade],
            [r for r in replies if r.trade == trade],
            item_order,
            project_name,
        )

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def _write_summary_sheet(ws, trades: list[str], levelled: list[LevelledBid], project_name: str) -> None:
    """The multi-trade cover: one row per trade with its bid count and the lowest
    corrected total (every value straight from the Layer-1 leveling)."""
    import datetime as _dt

    from pipeline._xlsx_style import autofit, money_cell, style_body, style_header, title_block

    meta = [m for m in (
        f"Project: {project_name}" if project_name else "",
        f"Generated: {_dt.date.today().isoformat()}",
        "One comparison sheet per trade follows.",
    ) if m]
    title_block(ws, "Levelled bid comparison — summary", meta)

    ws.append(["Trade", "Bids", "Lowest corrected total", "Lowest bidder"])
    header_row = ws.max_row
    style_header(ws, header_row, 4)
    for trade in trades:
        bids = [b for b in levelled if b.trade == trade]
        low = min(bids, key=lambda b: b.corrected_total)
        ws.append([sheet_title(trade), len(bids), low.corrected_total, low.firm_name])
        money_cell(ws.cell(row=ws.max_row, column=3))
    style_body(ws, header_row + 1, ws.max_row, 4)
    autofit(ws, min_row=header_row)


def _write_trade_sheet(
    ws,
    levelled: list[LevelledBid],
    replies: list[BidReply],
    item_order: Optional[list[str]],
    project_name: str = "",
) -> None:
    """One trade's comparison table onto ``ws`` (this trade's firms/items only),
    styled with the shared kit — the table's values are exactly the leveling output."""
    import datetime as _dt

    from pipeline._xlsx_style import (
        autofit,
        footer_note,
        money_cell,
        style_body,
        style_header,
        style_totals,
        title_block,
    )

    levelled_by_firm = {b.firm_id: b for b in levelled}
    firm_ids = [b.firm_id for b in levelled]

    # Item rows in scope order (only refs this trade's bids actually price), then any
    # extra item the bids introduced.
    priced_refs = {line.item_ref for r in replies for line in r.line_items}
    items: list[str] = [ref for ref in (item_order or []) if ref in priced_refs]
    for reply in replies:
        for line in reply.line_items:
            if line.item_ref not in items:
                items.append(line.item_ref)

    # Per (firm, item): (rate, corrected_amount, has_finding/gap note)
    line_index = {
        (r.firm_id, line.item_ref): line for r in replies for line in r.line_items
    }
    finding_items = {
        firm_id: {f.location.replace("line ", "") for f in b.arithmetic_findings}
        for firm_id, b in levelled_by_firm.items()
    }
    gap_items = {
        firm_id: {gap.split(" — ")[0] for gap in b.scope_gaps}
        for firm_id, b in levelled_by_firm.items()
    }

    label = sheet_title(ws.title if not levelled else levelled[0].trade)
    meta = [m for m in (
        f"Project: {project_name}" if project_name else "",
        f"Trade: {label}",
        f"Generated: {_dt.date.today().isoformat()}",
        "Rates are the primary comparison; amounts appear only where a quantity exists ('—' = rate-only line).",
    ) if m]
    title_block(ws, f"Levelled bid comparison — {label}", meta)

    header = ["Item", "Description"]
    for firm_id in firm_ids:
        name = levelled_by_firm[firm_id].firm_name
        header += [f"{name} — rate", f"{name} — corrected"]
    header.append("Notes")
    ws.append(header)
    header_row = ws.max_row
    style_header(ws, header_row, len(header))

    for item_ref in items:
        description = ""
        row = [item_ref, ""]
        notes: list[str] = []
        for firm_id in firm_ids:
            line = line_index.get((firm_id, item_ref))
            if line is None:
                row += ["", ""]
                continue
            description = description or line.description or ""
            # Rate is the primary comparison and is always shown; the amount cell is filled
            # only where an amount is computable — a rate-only line shows the rate and "—".
            amount = computable_amount(line)
            row += [
                line.rate if line.rate is not None else "—",
                amount if amount is not None else "—",
            ]
            if item_ref in finding_items.get(firm_id, set()):
                notes.append(f"{levelled_by_firm[firm_id].firm_name}: arithmetic corrected")
            if item_ref in gap_items.get(firm_id, set()):
                notes.append(f"{levelled_by_firm[firm_id].firm_name}: scope gap (unpriced)")
        row[1] = description
        row.append("; ".join(notes))
        ws.append(row)
        for col in range(3, 3 + 2 * len(firm_ids)):  # rate + corrected columns are currency
            money_cell(ws.cell(row=ws.max_row, column=col))
    style_body(ws, header_row + 1, ws.max_row, len(header))

    totals = ["", "TOTAL (corrected)"]
    for firm_id in firm_ids:
        totals += ["", levelled_by_firm[firm_id].corrected_total]
    totals.append("")
    ws.append(totals)
    style_totals(ws, ws.max_row, len(header))
    for col in range(3, 3 + 2 * len(firm_ids)):
        money_cell(ws.cell(row=ws.max_row, column=col))

    ws.append([])
    footer_note(ws, "Exclusions (non-comparable — not deducted from price)")
    for firm_id in firm_ids:
        for exclusion in levelled_by_firm[firm_id].exclusions:
            ws.append([levelled_by_firm[firm_id].firm_name, exclusion])

    autofit(ws, min_row=header_row)
