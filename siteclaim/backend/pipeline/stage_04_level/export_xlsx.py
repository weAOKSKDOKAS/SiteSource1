"""Excel export of the levelled comparison (openpyxl, imported lazily).

One sheet: a row per SoR item with each firm's rate and corrected amount, a totals
row of each firm's ``corrected_total``, and a Notes column calling out corrected
lines and scope gaps; stated exclusions are listed below the table. Saved to
``backend/fixtures/out/leveling.xlsx`` by default.

openpyxl is imported inside the function so the leveling arithmetic (and DEMO_MODE)
never depend on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rules_engine.leveling import computable_amount
from schemas.models import BidReply, LevelledBid

OUT_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "out" / "leveling.xlsx"


def export_leveling_xlsx(
    levelled: list[LevelledBid],
    replies: list[BidReply],
    item_order: Optional[list[str]] = None,
    path: Path | str = OUT_PATH,
) -> Path:
    """Write the levelled comparison to ``path`` and return it."""
    from openpyxl import Workbook  # lazy — leveling math must not require openpyxl
    from openpyxl.styles import Font

    replies_by_firm = {r.firm_id: r for r in replies}
    levelled_by_firm = {b.firm_id: b for b in levelled}
    firm_ids = [b.firm_id for b in levelled]

    # Item rows in scope order, then any extra item the bids introduced.
    items: list[str] = list(item_order or [])
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

    wb = Workbook()
    ws = wb.active
    ws.title = "Leveling"

    header = ["Item", "Description"]
    for firm_id in firm_ids:
        name = levelled_by_firm[firm_id].firm_name
        header += [f"{name} — rate", f"{name} — corrected"]
    header.append("Notes")
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)

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

    totals = ["", "TOTAL (corrected)"]
    for firm_id in firm_ids:
        totals += ["", levelled_by_firm[firm_id].corrected_total]
    totals.append("")
    ws.append(totals)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    ws.append([])
    ws.append(["Exclusions (non-comparable — not deducted from price)"])
    ws[ws.max_row][0].font = Font(bold=True)
    for firm_id in firm_ids:
        for exclusion in levelled_by_firm[firm_id].exclusions:
            ws.append([levelled_by_firm[firm_id].firm_name, exclusion])

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
