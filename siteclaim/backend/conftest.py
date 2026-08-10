"""Repo-level test fixtures — a developer's ``.env`` must never change a test result.

``api.py`` calls ``load_dotenv(backend/.env)`` at import, so a developer's local file leaks into
every test that imports the app. The variables below genuinely change outcomes:

* ``SITESOURCE_DB`` — points the suite at the live 140-firm database instead of the packaged demo
  one, so the illustrative ``F-EL-*`` firms the shortlist and dispatch tests assert on vanish.
* ``ANTHROPIC_MODEL`` — changes which model the LLM seam reports it would route to.
* ``GMAIL_TEST_RECIPIENT`` — overrides every draft recipient, which is exactly what the dispatch
  recipient tests assert is NOT happening by default.
* ``DEMO_MODE``, ``EXTRACTION_PROVIDER`` and every provider's key/model pair — a configured LIVE
  environment flips demo-pipeline tests and provider-routing tests. Every provider belongs in the
  list, or the failure this file exists to prevent comes straight back the first time somebody
  puts a real key in ``.env``. (Measured 2026-08-01, the first day this repo had a ``.env``:
  10 tests failed; every one passed again with the file moved aside.)

The neutralisation has to be a **set to empty**, not a delete, and it has to happen at **module
import time**:

* ``load_dotenv`` defaults to ``override=False``, so it skips any key already present in
  ``os.environ``. Deleting a key would leave ``.env`` free to set it; setting it to ``""`` makes
  ``load_dotenv`` leave it alone. (Verified against the installed python-dotenv, not assumed.)
* pytest imports the rootdir ``conftest.py`` before it imports any test module, and therefore
  before anything imports ``api`` — which is the only moment early enough to win.

The neutral VALUE differs per variable, and guessing costs a failing test:

* ``SITESOURCE_DB`` and ``GMAIL_TEST_RECIPIENT`` are read as ``os.getenv(key, "").strip()`` and
  treated as "unset" when empty (``db/store.py::get_connection`` falls back to ``DEFAULT_DB_PATH``;
  ``client_boq/store.py::get_conn`` falls back to its gitignored DEMO scratch DB; the draft
  recipient override is simply off). For those, ``""`` is the documented off switch.
* ``ANTHROPIC_MODEL`` is read as ``os.getenv("ANTHROPIC_MODEL", ANTHROPIC_MODEL)`` — a
  default-**if-absent** pattern, so ``""`` would be honoured as a real (empty) model name and
  ``test_default_provider_is_anthropic`` fails. Its neutral value is the module's own default,
  imported here rather than repeated so the two cannot drift.

A test that genuinely wants a different database still sets it per-test via ``monkeypatch`` (see
``client_boq/tests/conftest.py`` and ``bridge/tests/conftest.py``), which runs long after this and
is unaffected. The session-DB backstop at the bottom exists for the moment AFTER that monkeypatch
is undone — see its own comment.
"""

import atexit
import os
import shutil
import sqlite3
import tempfile

from pipeline.llm_client import ANTHROPIC_MODEL

# What a local .env can use to change what the suite reports, each mapped to the value that means
# "as if unset" for the code that actually reads it. Set — not deleted — so api.py's
# load_dotenv(override=False) finds them present and leaves them alone.
_NEUTRALISED = {
    "SITESOURCE_DB": "",              # empty -> the packaged demo sitesource.db (superseded below)
    "GMAIL_TEST_RECIPIENT": "",       # empty -> no draft-recipient override
    "ANTHROPIC_MODEL": ANTHROPIC_MODEL,  # absent-default, so restate the default itself
    # A configured LIVE .env must not leak into the suite: demo mode, logging, and every
    # provider's routing/key/model variables are neutralised the same way.
    "DEMO_MODE": "",
    "SITESOURCE_LLM_LOG": "",
    "EXTRACTION_PROVIDER": "",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "",
    "CHATGPT_API_KEY": "",
    "CHATGPT_MODEL": "",
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_MODEL": "",
    # The review→routing/estimate gate. The SHIPPED default is `soft` (a deliberate V1 demo
    # departure — see client_boq/gates.py); the SUITE pins `hard`, and the difference is
    # intentional in both directions.
    #
    # Pinning hard here keeps every existing gate test asserting the LOCKED decision, unedited —
    # a gate whose enforcement is only ever exercised in a mode nobody runs is a gate that has
    # quietly stopped being tested. Soft mode is then tested where it is the actual subject
    # (`bridge/tests/test_review_gate_soft.py`), by monkeypatching this back, so both modes have
    # real coverage rather than the default having all of it and the fallback none.
    #
    # It also belongs here on this file's own principle: a developer with REVIEW_GATE=soft in
    # their .env would otherwise flip six tests without touching a line of code.
    "REVIEW_GATE": "hard",
    # The bid gate, pinned the OTHER way — and the asymmetry is deliberate, not an oversight.
    #
    # REVIEW_GATE pins `hard` so the locked decision stays exercised by the whole suite. BID_GATE
    # pins `soft` because its hard mode is a NEW precondition on a seam that already has hundreds
    # of tests: every one of them was written before a bid decision existed, so pinning hard here
    # would 409 them all for failing to record something that did not exist when they were
    # written. That is not the gate being tested, it is the gate being imposed retroactively.
    #
    # Hard mode is tested where it is the subject (`bridge/tests/test_bid_gate.py`), by
    # monkeypatching this back — the same shape as the review gate's soft tests, mirrored.
    #
    # It is pinned rather than left unset for this file's own reason: a developer with
    # BID_GATE=hard in their .env would otherwise fail a large part of the suite without touching
    # a line of code.
    "BID_GATE": "soft",
}

for _var, _neutral in _NEUTRALISED.items():
    os.environ[_var] = _neutral

# --- the session-DB backstop, and why it is not paranoia -------------------------------------
#
# Per-test fixtures point SITESOURCE_DB at a throwaway file with `monkeypatch`, which unsets it the
# moment the test ends. Ingest runs on a THREAD POOL, and `store.get_conn()` reads the variable at
# call time on that thread — so a job still working after its test finished finds no override, no
# DEMO_MODE either, and falls through to the default: the committed `db/sitesource.db`.
#
# That is not hypothetical. Measured on 2026-08-03, the first day a folder ingest ran
# asynchronously: two document sets and a part revision were written straight into the committed
# database, which had never held a single client_boq row. Making the tests wait for their jobs
# fixes those tests; it does not fix the next test anybody writes.
#
# So the suite gets a session-wide default of its own. A leaked thread now lands here instead of in
# a file under version control — the difference between an invisible mistake and a temp file nobody
# ever looks at.
# A COPY of the seeded database, not an empty file: the procurement suite reads real seeded rows
# from it, and handing those tests a blank file fails 45 of them for a reason that has nothing to do
# with what they are testing. Same content, different inode — reads work, writes go nowhere that
# matters.
_SESSION_DB_DIR = tempfile.mkdtemp(prefix="sitesource-tests-")
_SESSION_DB = os.path.join(_SESSION_DB_DIR, "session.db")
_SEEDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "sitesource.db")
if os.path.isfile(_SEEDED):
    shutil.copyfile(_SEEDED, _SESSION_DB)
else:
    sqlite3.connect(_SESSION_DB).close()  # db.store.get_connection requires a real file
os.environ["SITESOURCE_DB"] = _SESSION_DB
atexit.register(shutil.rmtree, _SESSION_DB_DIR, True)
