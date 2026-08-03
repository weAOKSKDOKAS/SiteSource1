"""Repo-level test fixtures — a developer's ``.env`` must never change a test result.

``api.py`` calls ``load_dotenv(backend/.env)`` at import, so a developer's local file leaks into
every test that imports the app. Three of its variables genuinely change outcomes:

* ``SITESOURCE_DB`` — points the suite at the live 140-firm database instead of the packaged demo
  one, so the illustrative ``F-EL-*`` firms the shortlist and dispatch tests assert on vanish.
* ``ANTHROPIC_MODEL`` — changes which model the LLM seam reports it would route to.
* ``GMAIL_TEST_RECIPIENT`` — overrides every draft recipient, which is exactly what the dispatch
  recipient tests assert is NOT happening by default.

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
is unaffected.
"""

import os

from pipeline.llm_client import ANTHROPIC_MODEL

# What a local .env can use to change what the suite reports, each mapped to the value that means
# "as if unset" for the code that actually reads it. Set — not deleted — so api.py's
# load_dotenv(override=False) finds them present and leaves them alone.
_NEUTRALISED = {
    "SITESOURCE_DB": "",              # empty -> the packaged demo sitesource.db
    "GMAIL_TEST_RECIPIENT": "",       # empty -> no draft-recipient override
    "ANTHROPIC_MODEL": ANTHROPIC_MODEL,  # absent-default, so restate the default itself
}

for _var, _neutral in _NEUTRALISED.items():
    os.environ[_var] = _neutral
