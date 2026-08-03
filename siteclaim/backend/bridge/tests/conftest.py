"""bridge test fixtures — every test runs offline (DEMO_MODE) against a throwaway DB.

Same shape as ``client_boq/tests/conftest.py``, and for the same reason: the bridge's tables (and
the ``client_boq_*`` tables it reads) are created lazily in whatever DB ``store.get_connection``
opens, so pointing ``SITESOURCE_DB`` at a fresh empty file per test keeps the committed
``sitesource.db`` byte-identical.
"""

import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _demo_and_isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    db = tmp_path / "bridge_test.db"
    sqlite3.connect(str(db)).close()  # create the file so get_connection accepts it
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    yield
