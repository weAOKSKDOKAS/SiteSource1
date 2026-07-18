"""client_boq test fixtures — every test runs offline (DEMO_MODE) against a throwaway DB.

The module's ``client_boq_*`` tables are created lazily in whatever DB ``store.get_connection``
opens. To keep tests hermetic — never mutating the committed ``sitesource.db`` — point
``SITESOURCE_DB`` at a fresh empty SQLite file per test (client_boq only ever touches its own
tables, so an empty file is enough; it needs no seed).
"""

import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _demo_and_isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    db = tmp_path / "client_boq_test.db"
    sqlite3.connect(str(db)).close()  # create the file so get_connection accepts it
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    yield
