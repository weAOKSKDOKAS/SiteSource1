"""bridge test fixtures — every test runs offline (DEMO_MODE) against a throwaway DB.

Same shape as ``client_boq/tests/conftest.py``, and for the same reason: the bridge's tables (and
the ``client_boq_*`` tables it reads) are created lazily in whatever DB ``store.get_connection``
opens, so pointing ``SITESOURCE_DB`` at a fresh empty file per test keeps the committed
``sitesource.db`` byte-identical.

``make_set`` stands a client_boq set up through **client_boq's own public store API** rather than
raw SQL, so a fixture follows their schema instead of duplicating assumptions about it. The
bridge's production code only ever READS client_boq; this write path exists solely to create test
data that a real ingest would have created.
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


@pytest.fixture
def part_spec():
    """Build a ``PartSpec`` with sane defaults — ``part_id`` derives from ``n`` and ``abbr``."""
    from client_boq.models import PartSpec

    def _build(n: int, abbr: str, title: str, category: str = "other", *,
               start: int = 1, end: int = 10, scanned: bool = False, source_doc: str = "binder.pdf"):
        return PartSpec(
            n=n, abbr=abbr, slug=abbr.lower(), title=title, start=start, end=end,
            category=category, scanned=scanned, source_doc=source_doc,
        )

    return _build


@pytest.fixture
def make_set():
    """Create a client_boq document set with parts (and optional pdf paths / context cards)."""
    def _make(set_id: str, name: str, parts: list, *, pdf_paths=None, contexts=None,
              review_approved: bool | None = None):
        from client_boq import store as cb_store

        conn = cb_store.get_conn()
        try:
            cb_store.upsert_document_set(
                conn, set_id=set_id, name=name, slug=set_id, status="ingested"
            )
            # A real split ALWAYS writes a cut-pdf path for every part it cuts, so the default
            # fixture does too. Omitting it modelled a set whose every part was unreadable, which
            # nothing but a workbook-only pack actually is — and once "no cut pdf" became load
            # bearing (a part that can contribute no text is not PROPOSED as the priced bill),
            # that unrealistic default started deciding outcomes.
            #
            # An explicit `pdf_paths` still wins, including `{"01-x": ""}` — that is how a test
            # says "this part has no file", and it must keep meaning exactly that.
            if pdf_paths is None:
                pdf_paths = {p.part_id: f"{p.part_id}.pdf" for p in parts}
            cb_store.save_parts(conn, set_id, parts, pdf_paths)
            for part_id, context in (contexts or {}).items():
                cb_store.save_part_context(conn, set_id, part_id, context)
            if review_approved is not None:
                cb_store.set_review_approved(conn, set_id, review_approved)
        finally:
            conn.close()

    return _make
