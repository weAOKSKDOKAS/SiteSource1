"""The tender close date, treated as a FINDING rather than a form field.

The desk card shows "days to close", and that number has to come from somewhere. The honest
chain, in order of authority (a measurement outranks a model proposal):

1. Ingest already asks the model to quote — verbatim, with clause and page — any clause stating
   the submission deadline (``RULE_SUBMISSION_DEADLINE`` in ``s02_interpret``). The QUOTE is the
   finding; it can be checked against the page like any citation.
2. This module turns that quoted string into an ISO date **deterministically**. The parser is
   conservative on purpose: only unambiguous formats parse. ``14 August 2026`` parses;
   ``04/05/2026`` refuses, because April-May ambiguity silently resolved is a wrong deadline
   silently shown — the one failure this feature exists to prevent. A refusal is not an error:
   the status becomes ``not_found`` with the quote and citation retained, and a person types the
   date after reading the clause themselves.
3. In DEMO the interpret cards are fixtures, so their quotes describe the sample tender, not the
   upload. Deriving a date from them and labelling it "READ FROM COT" would be a lie; DEMO
   therefore always lands on ``not_found`` and the confirm-by-hand path.
4. A human confirmation (``confirmed``) is never overwritten by re-derivation.

The same rules apply to the query cut-off (``RULE_QUERY_CUTOFF``), which the desk's Blocked
filter needs: an RFI still open past that date is a question that can no longer be asked.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Optional

from client_boq import models, store
from pipeline.llm_client import demo_mode

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "14 August 2026", "14th August, 2026", "14 Aug 2026"
_DAY_MONTH_YEAR = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?,?\s+(\d{4})\b",
    re.IGNORECASE,
)
# "August 14, 2026"
_MONTH_DAY_YEAR = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)
# ISO "2026-08-14"
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def parse_close_date(quote: str) -> Optional[str]:
    """The ISO date stated in a quoted clause, or None when the phrasing is not unambiguous.

    Deliberately NOT a general date parser. Numeric forms like ``04/05/2026`` are refused —
    day-first and month-first readings disagree and there is no safe default for a deadline.
    When more than one distinct date appears in the quote, refuse too: choosing one would be an
    interpretation, and interpretations belong to the person reading the clause.
    """
    if not quote:
        return None
    found: list[str] = []
    for m in _ISO.finditer(quote):
        found.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    for m in _DAY_MONTH_YEAR.finditer(quote):
        day, month, year = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
        found.append(f"{year:04d}-{month:02d}-{day:02d}")
    for m in _MONTH_DAY_YEAR.finditer(quote):
        month, day, year = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
        found.append(f"{year:04d}-{month:02d}-{day:02d}")
    distinct = sorted(set(found))
    if len(distinct) != 1:
        return None
    year, month, day = (int(x) for x in distinct[0].split("-"))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return distinct[0]


def _flag_rows(conn: sqlite3.Connection, set_id: str) -> list[dict]:
    """Every strategy flag on the set's operative parts, with its part id — the same hoist the
    parts payload does, reused here so the two can never disagree about what was found."""
    rows = store.load_parts(conn, set_id)
    return [
        {**flag.model_dump(), "part_id": spec.part_id}
        for spec, _path, ctx in rows
        for flag in ctx.strategy_flags
    ]


def derive(conn: sqlite3.Connection, set_id: str) -> Optional[dict]:
    """Derive the close date (and query cut-off) for a set from its interpreted parts, and
    persist the result. Returns the updated meta fields, or None when nothing changed.

    Never overwrites ``confirmed`` — a person read the clause; re-running a machine step does
    not outrank them. In DEMO the outcome is always ``not_found``: the interpret fixtures
    describe the sample tender, and a fixture date labelled as read from this upload would be
    fabrication (CLAUDE.md trap 9 is the same rule at ingest).
    """
    current = store.load_set_meta(conn, set_id)
    if current["close_date_status"] == "confirmed":
        return None

    fields: dict = {}
    if demo_mode():
        fields = {"close_date_status": "not_found"}
    else:
        flags = _flag_rows(conn, set_id)
        deadline = next((f for f in flags if f["kind"] == models.RULE_SUBMISSION_DEADLINE), None)
        if deadline is None:
            fields = {"close_date_status": "not_found"}
        else:
            parsed = parse_close_date(deadline.get("quote", ""))
            fields = {
                "close_date_status": "found" if parsed else "not_found",
                "close_date": parsed or "",
                "close_date_clause": deadline.get("clause", ""),
                "close_date_page": deadline.get("page"),
                "close_date_part_id": deadline.get("part_id", ""),
                "close_date_quote": deadline.get("quote", ""),
            }
        cutoff = next((f for f in flags if f["kind"] == models.RULE_QUERY_CUTOFF), None)
        if cutoff is not None:
            parsed_cutoff = parse_close_date(cutoff.get("quote", ""))
            if parsed_cutoff:
                fields["query_cutoff"] = parsed_cutoff

    store.upsert_set_meta(conn, set_id, **fields)
    return store.load_set_meta(conn, set_id)
