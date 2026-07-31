"""The criteria library, editable — DB-backed, seeded once from the markdown.

``review_criteria.md`` promised "a contractor edits rows here without any code change", and that
promise predates a UI. Editing through a screen needs three things a markdown file cannot honestly
carry: **disable without deleting** (a past register may reference the id, and a referenced
criterion must stay resolvable forever), **authorship** (who changed the acceptable position — the
same rule as everywhere else in this module: editing stamps the editor), and **write-safety**
(re-emitting a hand-maintained markdown file from parsed rows silently reformats it).

So the DB is the source of truth from first access on, and the markdown remains as the seed and
the human-readable documentation of the library's intent. ``load(conn)`` returns the same
:class:`CriteriaLibrary` object ``criteria_loader.load_criteria()`` does, so the review stage and
``GET /criteria`` switch over without their consumers noticing.

Threshold rules are seeded but not editable: their ``extract_field`` is wired into ``rules.py``,
and rule text a person can edit but code does not obey would be a lie on the screen.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from client_boq import criteria_loader
from client_boq.models import Criterion, CriteriaLibrary, ThresholdRule


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    """First access parses the markdown and fills the tables; every later access reads the DB.
    Idempotent by construction — a non-empty table is never reseeded, so edits survive."""
    row = conn.execute("SELECT COUNT(*) AS n FROM client_boq_criteria").fetchone()
    if int(row["n"]) > 0:
        return
    library = criteria_loader.load_criteria()
    order = 0
    for crit in list(library.criteria) + list(library.placeholders):
        order += 10
        conn.execute(
            """
            INSERT OR IGNORE INTO client_boq_criteria
                (id, category_id, category, clause_area, acceptable_position, why_it_matters,
                 red_flag, is_placeholder, enabled, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (crit.id, crit.category_id, crit.category, crit.clause_area,
             crit.acceptable_position, crit.why_it_matters, crit.red_flag,
             int(crit.is_placeholder), order),
        )
    for rule in library.threshold_rules:
        conn.execute(
            "INSERT OR IGNORE INTO client_boq_threshold_rules (id, rule, extract_field) VALUES (?, ?, ?)",
            (rule.id, rule.rule, rule.extract_field),
        )
    conn.commit()


def _row_to_criterion(row) -> Criterion:
    return Criterion(
        id=row["id"], category_id=row["category_id"], category=row["category"],
        clause_area=row["clause_area"], acceptable_position=row["acceptable_position"],
        why_it_matters=row["why_it_matters"], red_flag=row["red_flag"],
        is_placeholder=bool(row["is_placeholder"]),
    )


def load(conn: sqlite3.Connection, enabled_only: bool = False) -> CriteriaLibrary:
    """The library, in the same shape ``criteria_loader.load_criteria()`` returns.

    ``enabled_only=True`` is what a review run reads — a disabled criterion stops being checked.
    The default includes disabled rows, because anything RESOLVING an id (a past register line,
    the criteria screen itself) must always find it.
    """
    _seed_if_empty(conn)
    where = "WHERE enabled = 1" if enabled_only else ""
    rows = conn.execute(
        f"SELECT * FROM client_boq_criteria {where} ORDER BY sort_order, id"
    ).fetchall()
    criteria = [_row_to_criterion(r) for r in rows if not r["is_placeholder"]]
    placeholders = [_row_to_criterion(r) for r in rows if r["is_placeholder"]]
    rule_rows = conn.execute(
        # rowid = insertion order = the markdown table's order; the switch from the file must
        # be invisible, and the file's order is part of its shape.
        "SELECT * FROM client_boq_threshold_rules WHERE enabled = 1 ORDER BY rowid"
    ).fetchall()
    rules = [ThresholdRule(id=r["id"], rule=r["rule"], extract_field=r["extract_field"])
             for r in rule_rows]
    return CriteriaLibrary(criteria=criteria, placeholders=placeholders, threshold_rules=rules)


def load_rows(conn: sqlite3.Connection) -> list[dict]:
    """Every criterion row with its editing metadata — what the criteria screen renders."""
    _seed_if_empty(conn)
    rows = conn.execute(
        "SELECT * FROM client_boq_criteria ORDER BY sort_order, id"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["is_placeholder"] = bool(d["is_placeholder"])
        d["enabled"] = bool(d["enabled"])
        out.append(d)
    return out


def next_id(conn: sqlite3.Connection, category_id: str) -> str:
    """The next free id in a category — ``PS-06`` after ``PS-05``. Numbers are never reused:
    an id may be stamped on a historical register, so a freed number stays freed."""
    rows = conn.execute(
        "SELECT id FROM client_boq_criteria WHERE category_id = ?", (category_id,)
    ).fetchall()
    highest = 0
    for r in rows:
        tail = r["id"].split("-")[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{category_id}-{highest + 1:02d}"


def upsert(conn: sqlite3.Connection, *, id: str, actor: str = "", **fields) -> dict:
    """Create or update one criterion, stamping who and when. Unknown fields are refused."""
    allowed = {"category_id", "category", "clause_area", "acceptable_position",
               "why_it_matters", "red_flag", "is_placeholder", "enabled", "sort_order"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown criterion fields: {sorted(unknown)}")
    _seed_if_empty(conn)
    existing = conn.execute(
        "SELECT * FROM client_boq_criteria WHERE id = ?", (id,)
    ).fetchone()
    merged = dict(existing) if existing else {
        "id": id, "category_id": "", "category": "", "clause_area": "",
        "acceptable_position": "", "why_it_matters": "", "red_flag": "",
        "is_placeholder": 0, "enabled": 1, "sort_order": 0,
    }
    merged.update(fields)
    merged["is_placeholder"] = int(bool(merged["is_placeholder"]))
    merged["enabled"] = int(bool(merged["enabled"]))
    # A row that now has an acceptable position stops being a placeholder — the definition of one.
    if merged["acceptable_position"].strip():
        merged["is_placeholder"] = 0
    merged["updated_by"] = actor
    merged["updated_at"] = _now()
    conn.execute(
        """
        INSERT INTO client_boq_criteria
            (id, category_id, category, clause_area, acceptable_position, why_it_matters,
             red_flag, is_placeholder, enabled, sort_order, updated_by, updated_at)
        VALUES (:id, :category_id, :category, :clause_area, :acceptable_position,
                :why_it_matters, :red_flag, :is_placeholder, :enabled, :sort_order,
                :updated_by, :updated_at)
        ON CONFLICT(id) DO UPDATE SET
            category_id = excluded.category_id, category = excluded.category,
            clause_area = excluded.clause_area,
            acceptable_position = excluded.acceptable_position,
            why_it_matters = excluded.why_it_matters, red_flag = excluded.red_flag,
            is_placeholder = excluded.is_placeholder, enabled = excluded.enabled,
            sort_order = excluded.sort_order,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        merged,
    )
    conn.commit()
    row = conn.execute("SELECT * FROM client_boq_criteria WHERE id = ?", (id,)).fetchone()
    d = dict(row)
    d["is_placeholder"] = bool(d["is_placeholder"])
    d["enabled"] = bool(d["enabled"])
    return d


def get(conn: sqlite3.Connection, id: str) -> Optional[dict]:
    _seed_if_empty(conn)
    row = conn.execute("SELECT * FROM client_boq_criteria WHERE id = ?", (id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["is_placeholder"] = bool(d["is_placeholder"])
    d["enabled"] = bool(d["enabled"])
    return d
