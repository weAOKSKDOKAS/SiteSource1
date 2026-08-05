# Handoff — the costing engine, and how to merge it into `main`

**Branch:** `from-client-to-tender-BOQ`, five commits (`4d8b214`..`38ca718`)
**Base:** `origin/main` at `aba35ab`
**Written:** 2026-08-05
**For:** whoever performs the merge. You do not need to have seen the work to follow this.

> **Before anything else — rotate the credentials.** The Anthropic, DeepSeek, OpenAI/ChatGPT and
> Google client-secret values were pasted in plaintext during the session that produced this branch.
> Nothing here commits them (`siteclaim/backend/.env` is gitignored and a scan of every added line
> found only the `sk-ant-...` placeholder in a docs example), but they were exposed and should be
> rotated regardless.

---

## 1 · What arrived

A costing engine for the client's own Bill of Quantities: read their workbook, build a cost model
underneath it, and emit a workbook that still calculates when the app is switched off.

Twenty-seven modules under `client_boq/boq/`, ~7,300 lines, plus the routes over them, folder ingest,
the OpenAI provider, and five frontend screens. **No module in `boq/` makes a model call** — it is
openpyxl, arithmetic and clauses.

The rule the package is built on, and the one to apply when deciding anything about it later:

> If two good estimators would get the same answer, it is clerical and the app does it.
> If two good estimators would disagree, it is judgement and the app asks.

### The numbers it produces, so you can tell whether the merge broke it

Run against the real CEDD ND/2025/04 tender, 164 bill lines:

```
by source:  placeholder 89 · prelim 10 · built 27 · lab 26 · client 12

TOTAL              HK$ 24,606,451   PROVISIONAL
  nobody chose     HK$  7,097,420   (89 lines, stand-ins)
  actually priced  HK$ 17,509,031
  still red        0
```

If your merged tree gives a different total on the same tender, something in the merge is wrong.
`still red` must stay 0 and `PROVISIONAL` must stay true until somebody prices those 89 lines.

---

## 2 · The merge, measured

Not predicted — run with `git merge-tree --write-tree origin/main HEAD`.

**Ten files conflict. Everything else auto-merges**, including `client_boq/router.py`, which is the
single largest change on the branch (+1,902) and merges clean. Do not let its size alarm you.

| Conflicting file | hunks | What it is |
|---|---|---|
| `frontend/src/client_boq/App.tsx` | 9 | mostly adjacent import lines; two real ones |
| `frontend/src/client_boq/chrome.tsx` | 4 | both sides added tabs |
| `frontend/src/client_boq/api.ts` | 3 | both sides appended API functions |
| `frontend/src/client_boq/nav/routes.ts` | 3 | **main's version is better — see below** |
| `frontend/src/client_boq/nav/NavSidebar.tsx` | 2 | both sides added nav entries |
| `frontend/src/client_boq/tabs/Documents.tsx` | 2 | adjacent additions |
| `frontend/src/client_boq/tabs/Price.tsx` | 2 | adjacent additions |
| `frontend/src/client_boq/types.ts` | 1 | both appended a type block at the same point |
| `backend/client_boq/ingest/run.py` | 1 | pure adjacency |
| `backend/conftest.py` | 1 | **add/add, two designs — see below** |

Auto-merging cleanly: `backend/api.py`, `backend/client_boq/router.py`,
`frontend/.../ui.tsx`, `Register.tsx`, `tokens.css`.

### 2.1 · `backend/conftest.py` — the one that needs a decision

Both sides independently wrote this file, for the same reason: a developer's `.env` must not change
what the suite reports. They chose different mechanisms, and **neither is a superset of the other.**

| | `main` | this branch |
|---|---|---|
| Mechanism | **sets** vars to `""` | **deletes** vars + `SITESOURCE_SKIP_DOTENV` in `api.py` |
| `SITESOURCE_DB` | ✅ | ✅ |
| `ANTHROPIC_MODEL` | ✅ restates the absent-default | ✅ (deleted) |
| `GMAIL_TEST_RECIPIENT` | ✅ | ❌ |
| `DEMO_MODE`, `SITESOURCE_LLM_LOG` | ❌ | ✅ |
| OpenAI / DeepSeek / `EXTRACTION_PROVIDER` | ❌ | ✅ |
| Thread-pool DB backstop | ❌ | ✅ |

**Resolution: take main's mechanism, this branch's coverage.**

Main's set-to-empty is the better mechanism and should be the base, because `load_dotenv` defaults
to `override=False` and therefore skips any key already present in `os.environ` — so setting a key
to `""` neutralises it without needing a hook in `api.py` at all. Deleting a key leaves `.env` free
to set it, which is why this branch needed `SITESOURCE_SKIP_DOTENV`.

**One value must not be blanked.** `ANTHROPIC_MODEL` is read as
`os.getenv("ANTHROPIC_MODEL", ANTHROPIC_MODEL)` — a default-**if-absent** pattern — so `""` is
honoured as a real (empty) model name and `test_default_provider_is_anthropic` fails. Its neutral
value is the module's own default, imported rather than repeated. Main's file already does this
correctly; keep it exactly.

So the merged `_NEUTRALISED` dict is main's, extended with:

```python
"DEMO_MODE": "",
"SITESOURCE_LLM_LOG": "",
"EXTRACTION_PROVIDER": "",
"OPENAI_API_KEY": "", "OPENAI_MODEL": "",
"CHATGPT_API_KEY": "", "CHATGPT_MODEL": "",
"DEEPSEEK_API_KEY": "", "DEEPSEEK_MODEL": "",
```

Then **carry this branch's session-DB backstop across verbatim** — the `tempfile.mkdtemp` +
`shutil.copyfile` block at the bottom of our version. It is not stylistic. Per-test fixtures point
`SITESOURCE_DB` at a temp file with `monkeypatch`, which unsets it the moment the test ends; ingest
runs on a **thread pool** and reads the variable at call time on that thread, so a job still working
after its test finished finds no override and falls through to the committed `db/sitesource.db`.
Measured 2026-08-03: two document sets and a part revision were written into a database under
version control. Note it must copy the seeded DB rather than create an empty one — the procurement
suite reads real seeded rows and 45 tests fail against a blank file.

If you keep main's mechanism (recommended), **the `api.py` change in commit `38ca718` becomes dead
and should be reverted** — it is four lines guarding the `load_dotenv` call.

### 2.2 · `nav/routes.ts` — take main's, it is better

Do not resolve this one by keeping both sides. Main derives `SCREENS` and `TAB_IDS` from their
source lists; this branch hand-maintains them as literal arrays. Main's is strictly better and its
commit explains why: a hand-maintained array only catches a *removed* screen (the `TabId[]`
annotation rejects an unknown string); an *added* one compiles cleanly against a stale array and
then `parseHash` silently drops its deep link — invisible until somebody shares the URL.

**Take main's derived form, then make sure the sources it derives from contain our entries** —
`outputs` in the screens list, and `site` / `price` / `offer` in `chrome.tsx`'s `TABS`.

### 2.3 · The other eight

All are two sides appending different things near the same line. Keep both, in this order:

* **`chrome.tsx`** — union the `TabId` union and the `TABS` array. Main adds `route` and `sourcing`;
  this branch adds `site`. Both belong. Check the resulting tab order reads as a workflow.
* **`App.tsx`** — seven of the nine hunks are import lines (`Projects` vs `Outputs`,
  `SourcingTab` vs `SiteTab`): keep both. The two real ones are in the upload flow around line 285,
  where this branch added the folder path beside the existing single-PDF path.
* **`types.ts`, `api.ts`, `NavSidebar.tsx`, `Documents.tsx`, `Price.tsx`** — keep both blocks.
* **`ingest/run.py`** — main added a `Count` callback type and changed `run_split`'s signature; this
  branch added `run_folder_inspect` at the same point. Keep both; they do not interact.

### 2.4 · Do not lose the wiring

Main restructured the shell in *"ui (phase 8): one shell — the desk is the app"*. Four screens from
this branch must be registered in **main's** structure, not this branch's:

`tabs/Costing.tsx` · `tabs/Site.tsx` · `tabs/ScheduleEditor.tsx` · `screens/Outputs.tsx`

They are new files, so git will merge them silently and they will simply never render if you forget.
After merging, confirm each is reachable from `nav/routes.ts` and `NavSidebar.tsx`.

---

## 3 · Sequence the merge, or you will do it twice

`origin/client_boq` is **13 commits ahead of `main` and unmerged** (the "FIX n" series). It touches
`conftest.py`, `api.py`, `client_boq/router.py`, `types.ts`, `api.ts`, `App.tsx`, `Documents.tsx`,
`Register.tsx`, `Price.tsx` — the same files as this branch.

Merging this branch against that one produces **eleven** conflicts instead of ten (it adds
`Register.tsx`), including the same `conftest.py` add/add.

**Recommendation: land `client_boq` into `main` first, then merge this branch onto the result.**
Otherwise `conftest.py` and the frontend conflicts get resolved twice, against two different bases,
and the second resolution has to re-derive the first.

---

## 4 · Two workbook readers now exist. This is not a conflict, it is a decision

Git will merge these silently because they are different files. Somebody should still know.

| | `pipeline/stage_01_ingest/workbook.py` (main) | `client_boq/boq/reader.py` (this branch) |
|---|---|---|
| Emits | `SorItem[]` | `ClientBill` / `BillItem[]` |
| Consumer | routing, packages, the split report | the costing engine |
| Model calls | none | none |

Both read the same CEDD workbook and independently discovered the same facts about it: that the
heading chain is *which column* the text occupies rather than how it is indented; that `=E8*G8`
versus `=G38` is what distinguishes a measured rate from a lump sum; and that every Bill 9 rate is
employer-fixed under the Pay for Safety Scheme, so an engine that generates one is wrong by
definition.

**Recommendation: leave both.** They emit different shapes for different consumers and merging them
would couple routing to costing. But log the duplication, because the next person to find two
readers of the same file will reasonably assume one is dead code and delete it. If they ever
converge, the shared part is the *reading* — reference rendering through `number_format`, the
column-depth heading chain, the lump-versus-rate test — not the emitted shape.

---

## 5 · Where the judgement numbers live

The engine ships **dummy figures, loudly flagged**, so the output reads end to end before anybody
has priced anything. Two tables, both in `client_boq/boq/model.py`, both editable at runtime with no
file edit and no restart:

| Table | What it is | Where you change it |
|---|---|---|
| `_PRELIM` | 9 site resources — office, vehicle, store, telephone, environmental, trip tickets, waste sorting, comms, prints. All ship at rate **0.0**, deliberately: a visible blank, never an invented number. | Price tab → *Still to price* → **1 · WHAT IS STANDING ON SITE** |
| `_PLACEHOLDER` | 13 stand-ins keyed on the **unit** of a line (`item`, `nr`, `m`, `m3`, `mth`, `nr-wk`, …) so they fill in any bill, not just this one. | Price tab → *Still to price* → **2 · THE PLACEHOLDERS** |

`use_placeholders` switches the stand-ins off entirely and puts the red back. Note the distinction
the code relies on: **"I want none" is said with that switch, not with an empty list** — an empty
list is indistinguishable from a field nobody wrote, which is why `placeholders` uses a
`default_factory` returning the standard table so models saved before the feature existed gain it.

**A warning about sizing them.** The first pass used a plausible HK$3,000/week for standpipe
readings. This bill carries 2,451 of them: HK$7.35M on one line, and a HK$72.8M total. A stand-in
that swamps the real work is worse than a red line, because red is honest. `placeholder_total` and
`provisional` exist so the invented money is always separable — keep them wired to whatever UI you
end up with.

---

## 6 · Known-open, carried forward

**The review stage cannot summarise a large tender.** Its summarising call sends the whole parsed
set in one request. On ND/2025/04 it ran 2h19m and then died:

```
429 · Requested 674,656 tokens · Limit 200,000 TPM
```

Untouched by this branch and out of its scope, but it will bite the next live run on any tender of
this size. The fix is chunk-and-reduce in the summarising stage, not a bigger limit.

---

## 7 · Verifying the merge

```bash
cd siteclaim/backend  && ./.venv/Scripts/python -m pytest -q
cd siteclaim/frontend && npm run build          # tsc --noEmit && vite build
```

This branch is green at its tip: **1,579 passed, 5 skipped**, frontend build clean (693 modules).
Note that the five commits are themed for *review*, not for bisection — `router.py` and `models.py`
each carry work from more than one theme because a file cannot be in two commits, so an intermediate
commit is not guaranteed green. The tip is.

Then, on the merged tree, re-run the live costing on `nd-2025-04` and check the figures in §1 still
hold. If `still red` is no longer 0, the placeholder table did not survive the merge; if the total
moved, look at `boq/costing.py` first.

### Standing constraints

* `siteclaim/backend/.env` is gitignored and no key is ever committed.
* **Do not run the seed.**
* `db/sitesource.db` and `db/sitesource_live.db` are committed and must not be mutated — a live run
  points `SITESOURCE_DB` at `fixtures/out/live_run.db`, which is gitignored.
* The OneDrive tender corpus is **read-only**. Never modify, move or rename anything in it.
