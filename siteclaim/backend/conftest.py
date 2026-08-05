"""Root test configuration: the suite must not depend on whether LIVE is configured.

`api.py` calls `load_dotenv(backend/.env)` at import, which is right for running the app and wrong
for running the tests. The moment a developer creates a real `.env` — which is exactly what you do
to run a tender for real — every test that imports `api` inherits `DEMO_MODE=false`, a
`SITESOURCE_DB` pointing somewhere else, and whatever `ANTHROPIC_MODEL` is set there.

Measured on 2026-08-01, the first time this repo had a `.env`: **10 tests failed**, including
`test_default_provider_is_anthropic` (asserting the code default `claude-sonnet-4-6` against the
env's `claude-sonnet-5`) and five demo-pipeline tests that assume DEMO. Every one of them passed
again with the file moved aside. The tests were not wrong and the `.env` was not wrong — nothing
had ever said which of the two owned the environment.

This file settles it: the tests do. `SITESOURCE_SKIP_DOTENV` is read by `api.py` and set here at
import time, before pytest imports any test module (and therefore before anything imports `api`).
A test that wants one of these values sets it explicitly with `monkeypatch`, which is the only way
an environment should ever reach a test — the same lesson as trap 1c, where a test asserted a
package was absent and broke as soon as someone legitimately installed it.
"""

import atexit
import os
import shutil
import sqlite3
import tempfile

os.environ["SITESOURCE_SKIP_DOTENV"] = "1"

# Defensive: if anything already imported `api` (a stray plugin, an IDE runner), the .env values
# are in os.environ by now. Drop the ones that decide test outcomes, restoring "as if no .env".
for _key in ("DEMO_MODE", "SITESOURCE_DB", "SITESOURCE_LLM_LOG", "ANTHROPIC_MODEL",
             "ANTHROPIC_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_API_KEY", "EXTRACTION_PROVIDER",
             # Every provider's vars belong here, or the failure this file exists to prevent comes
             # straight back the first time somebody puts a real key in .env.
             "OPENAI_MODEL", "OPENAI_API_KEY", "CHATGPT_MODEL", "CHATGPT_API_KEY"):
    os.environ.pop(_key, None)

# --- the backstop, and why it is not paranoia ------------------------------------------------
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
