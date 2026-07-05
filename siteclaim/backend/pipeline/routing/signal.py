"""The deterministic routing signal (Phase P1b — Layer 1).

Per package, compute the objective coverage inputs that inform (never decide) the
self-perform vs sublet recommendation: how many trade-matched register firms exist, how
many carry an assessable closeout, whether the pool is thin (a specialist trade), and any
in-house benchmark history for the trade. Pure DB reads over the active connection —
deterministic and offline (no LLM).
"""

from __future__ import annotations

import sqlite3

from db import store

# A trade with fewer than this many register firms is a thin, specialist pool.
THIN_POOL_THRESHOLD = 3


def _in_house_history(conn: sqlite3.Connection, trade: str) -> int:
    """How many LIVE benchmark projects we hold for this trade (our own track record).
    Zero in a clean live profile until the archive fills through the compounding loop."""
    from db.benchmark import has_benchmark_tables

    if not has_benchmark_tables(conn):
        return 0
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM projects WHERE trade = ? AND provenance = 'live'", (trade,)
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def package_signal(conn: sqlite3.Connection, trade: str, scope_summary: str = "") -> dict:
    """The Layer-1 coverage signal for one package's trade."""
    firms = store.firms_for_trade(conn, trade)
    assessable = store.shortlistable_firms_for_trade(conn, trade)
    n = len(firms)
    a = len(assessable)
    return {
        "trade": trade,
        "trade_firm_count": n,
        "assessable_firm_count": a,
        "thin_pool": n < THIN_POOL_THRESHOLD,
        "in_house_history": _in_house_history(conn, trade),
        "has_sublet_pool": a > 0 or n > 0,
    }
