"""REVIEW stage 01 — ingest the client's document set.

Bucket (client_boq_layer_mapping.md tasks 1a/1c): **Deterministic + AI**. Deterministic text/page
extraction reuses ``pipeline.documents.extract_document`` (pymupdf + Tesseract); the AI half
structures the extracted text into typed clauses with **stable clause ids** and page/locus
references — the identities s08 later verifies citations against. Reading, not deciding.

Two ways in:

* **From an ingested set** (the normal path once a tender has been through ``/ingest``): walk
  the approved parts, read each part's own pages, and structure them a part at a time. Each
  clause then carries the part it came from, so a citation points at a page range rather than
  a filename.
* **From raw uploads** (a single small document with nothing to split): the original path,
  unchanged.

The part-at-a-time path exists because the raw path cannot survive a real tender binder. It
concatenated every document into one prompt against an 8,000-token output ceiling, and
``extract_document`` silently stops at page 200 — so a 411-page binder lost half its pages and
then truncated. Splitting first turns one impossible call into a dozen ordinary ones.

DEMO stays fully offline: ``complete_json`` short-circuits to the fixture ``ParsedDocumentSet`` and
no extraction/network runs (the fixture already *is* a structured parse). The caller (``run.py``)
assigns the set identity and persists the result; this stage only produces the parse.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from client_boq.models import ClauseItem, ParsedDocumentSet, PartSpec, RawUpload
from pipeline.concurrency import run_calls
from pipeline.documents import extract_document
from pipeline.llm_client import LLMClient, demo_mode
from client_boq.llm import make_client
from pipeline.workspace import Workspace

DEMO_FIXTURE = "cases/client_boq/review_ingest.json"

# One part's text is still too big for one call when the part is a 100-page appendix set, so
# chunk it. Mirrors the procurement ingest's MAX_CHUNK_CHARS, which exists for the same reason.
MAX_CHUNK_CHARS = 12000

_SYSTEM = (
    "You are a construction contract analyst. You read tender/contract documents and structure them "
    "into individual clauses for downstream review. You extract; you never judge, score, or decide. "
    "Return ONLY JSON matching the schema."
)

_INSTRUCTION = (
    "Structure the following contract document set into clauses.\n"
    "For every clause return: clause_id (the reference exactly as printed, e.g. '9.9' or '4.8.6'), "
    "ref (the printed label), heading (short title if present), text (the clause's full text), "
    "source_doc (the document filename it came from), and page (1-based page number if known).\n"
    "Preserve clause ids verbatim — later stages cite them. Do not invent clauses, do not merge "
    "distinct clauses, and do not drop any. Return {\"clauses\": [...]} plus the document names.\n\n"
    "=== DOCUMENTS ===\n"
)


def _chunk(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on page boundaries so a clause is never cut in half mid-sentence.

    ``extract_document`` and ``pdfops.page_text`` both prefix each page with ``[page N]``, which
    gives a natural, content-independent seam to break on.
    """
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n[page "):
        piece = block if not chunks and not current else "\n\n[page " + block
        if current and len(current) + len(piece) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current.strip():
        chunks.append(current)
    return chunks


def _structure(client: LLMClient, body: str, label: str,
               on_note: Optional[Callable[[str], None]] = None) -> list[ClauseItem]:
    """One structuring call. A chunk that fails is REPORTED and skipped, never fatal — losing one
    chunk of one part must not lose the whole document set.

    "Reported" was a claim this function did not keep. It returned ``[]`` and said nothing, and the
    caller's comment asserted "the gap is already reported elsewhere" — which was not true either:
    `on_note` existed on `ingest_from_parts` and had four call sites, all about deferred, skipped or
    non-contractual parts, and none about a chunk that failed.

    What that cost: a rate-limit or timeout storm during a review yields a register assembled from
    fewer clauses than the pack contains, **indistinguishable from a pack with fewer departures**.
    That register can then be approved, and the bid brief reads "nothing on the register is
    unresolved and the review is approved" — a BID recommendation resting on clauses nobody read.

    An unread chunk is now a sentence, and it names the part and the chunk so the re-run is
    targeted rather than a whole document set re-read.
    """
    try:
        parsed = client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION + body, target_model=ParsedDocumentSet,
            purpose=f"client_boq-review-ingest-{label}",
        )
    except Exception as exc:  # noqa: BLE001 — a failed chunk is a gap, not a crash
        if on_note:
            on_note(
                f"chunk {label} could not be structured ({type(exc).__name__}: {exc}). Its clauses "
                f"are NOT in the register, and nothing downstream can tell that from a part with "
                f"no clauses in it. Re-run the review to read it."
            )
        return []
    return list(parsed.clauses)


# Categories the review does NOT read for contractual positions.
#
# A bill of quantities has no contractual clauses. Reading one for them produced six structuring
# calls that each returned exactly 8,000 output tokens — two retried and still at the ceiling —
# and a register whose findings were "No letter of offer in the document set" and "No tender
# clarifications in the document set": true, and useless, because the set contained only a bill.
# A drawing set is geometry; its text layer is title blocks and annotations.
#
# A SKIP-list rather than an allow-list, deliberately. Every other category can carry a
# contractual position — safety requirements are obligations, bid forms carry the form of tender —
# and `other` is the honestly-uncategorised bucket, so excluding it would silently drop a
# contractual document the classifier failed to place, which is the exact failure this module
# exists to prevent. A skip-list also means a category added to PART_CATEGORIES later is read by
# default rather than dropped by omission. Spending a call is cheaper than losing a clause.
NON_CONTRACTUAL_CATEGORIES = frozenset({"pricing", "drawings"})

# Categories that CAN carry a contractual position but, on a real government pack, are dominated by
# material that cannot. Skipped BY DEFAULT and read on request — never dropped by omission.
#
# The evidence. CEDD ND/2025/04 extracted to 206 parts. 35 are drawings and 4 are bills, so the old
# skip-list left 167 to read, of which roughly 150 are `specifications` — 38 lab-testing appendices
# under S/PS/PS31, 28 geotechnical under S/PS/PS7, 25 under S/PS/PS1, and so on. Borehole logs and
# test-result schedules are DATA. A departure register concerns the conditions of contract, and
# reading 150 appendices for departures is where a 34-minute review goes.
#
# But `specifications` is too coarse a category to condemn wholesale, which is exactly why this is
# a second set and not four more members of the first. GP&PP is the General and Particular
# Preambles — the Standard Method of Measurement rules, which say what a rate must include, and
# that is commercial. The Particular Specification body carries real obligations: defects periods,
# testing regimes, attendance. Those are departures by any practical definition. So the honest
# statement is "usually not worth 150 calls", not "never contractual", and the operator decides per
# tender rather than the code deciding once.
#
# STILL A SKIP-LIST, deliberately, and this is the whole argument for the shape. An allow-list —
# read only contract-conditions, contract-data, tender-conditions, bid-forms, tender-instructions —
# would be faster to write and would silently omit any category added to PART_CATEGORIES later.
# Its failure mode is a MISSING FINDING: invisible, and discovered when somebody is caught by a
# clause nobody reviewed. A skip-list's failure mode is a SLOW RUN: visible, and discovered in 34
# minutes. Prefer the failure you can see. A category added next month is still read by default.
OPTIONAL_CATEGORIES = frozenset({"specifications"})


def skip_set(*, include_specifications: bool = False) -> frozenset[str]:
    """Which categories one review run will not read.

    The DEFAULT of this function skips specifications; the default of ``ingest_from_parts`` does
    not. That is not an inconsistency — it is where the policy lives. The stage keeps the contract
    it always had, so every existing caller and test behaves exactly as before; the decision about
    what a REQUEST means belongs at the boundary that interprets the request.
    """
    if include_specifications:
        return NON_CONTRACTUAL_CATEGORIES
    return NON_CONTRACTUAL_CATEGORIES | OPTIONAL_CATEGORIES


def effective_category(part: PartSpec, context: Optional[object] = None) -> tuple[str, str]:
    """``(category, whose)`` for one part — the INTERPRETED category when there is one.

    There are two categories in this system and they are not equally good.

    ``PartSpec.category`` comes from the planning call, which is shown a digest — filename, page
    count, bookmark outline, the draft split, the printed contents — and **no body text at all**.
    ``PartContext.category`` comes from the interpreter, which has read the part's pages and its
    images. On the first real bill of quantities the planner said ``other`` and the skip-list let a
    26-page pricing document through to be read as a contract, ten minutes and a dozen
    ceiling-hitting calls later.

    The interpreted answer was there the whole time — persisted to ``client_boq_part_contexts``,
    returned by ``store.load_parts`` as the third element of every tuple, and thrown away by both
    consumers. This function is the correction: prefer the reader over the guesser.

    An UNREADABLE part is the one case where the interpreter's answer is worth nothing — it did not
    read anything, so its category is its own default — and the planner's guess stands instead.
    """
    interpreted = (getattr(context, "category", "") or "").strip().lower()
    if context is not None and getattr(context, "readable", False) and interpreted:
        return interpreted, "interpreted"
    return (part.category or "").strip().lower(), "planned"


def ingest_from_parts(
    parts: list[tuple[PartSpec, str]], project_name: str = "",
    *, on_note: Optional[Callable[[str], None]] = None,
    contexts: Optional[dict] = None,
    count_cb: Optional[Callable[[int, int], None]] = None,
    skip_categories: frozenset[str] = NON_CONTRACTUAL_CATEGORIES,
) -> ParsedDocumentSet:
    """Structure an already-split set, one part at a time.

    ``parts`` pairs each part with the path of its cut PDF. Reading the part's own file means
    the 200-page extraction cap applies per part instead of per binder, so nothing is dropped.

    ``contexts`` maps ``part_id`` to that part's interpreted :class:`PartContext`. Passed
    ALONGSIDE ``parts`` rather than folded into the tuple so the existing two-tuple signature keeps
    working; a caller that has no contexts gets exactly the old behaviour.

    A part is skipped when its category — the interpreted one where there is one, see
    :func:`effective_category` — is in :data:`NON_CONTRACTUAL_CATEGORIES`, and the skip is REPORTED
    with which category decided it. A silent skip and a silent read are equally opaque. When every
    part is skipped the set carries no contractual document at all, and that is said plainly rather
    than left to be inferred from a register full of findings about documents nobody uploaded.
    """
    from client_boq.ingest import pdfops  # local import: keeps the review path light

    client = make_client()  # app-wide model setting applied here (client_boq/llm.py)
    clauses: list[ClauseItem] = []
    doc_names: list[str] = []

    # One pass, two lists — partitioned by identity rather than by re-filtering, so two parts that
    # happen to compare equal cannot land in both.
    readable: list[tuple[PartSpec, str]] = []
    skipped: list[tuple[PartSpec, str, str]] = []   # (part, category, whose)
    for part, pdf_path in parts:
        category, whose = effective_category(part, (contexts or {}).get(part.part_id))
        if category in skip_categories:
            skipped.append((part, category, whose))
        else:
            readable.append((part, pdf_path))

    # Two REASONS to skip, reported separately because they are different statements and the
    # difference is the whole point of the design. A bill was never going to be read. A
    # specification was deferred by this run's settings and one click brings it back.
    deferred = [x for x in skipped if x[1] not in NON_CONTRACTUAL_CATEGORIES]
    skipped = [x for x in skipped if x[1] in NON_CONTRACTUAL_CATEGORIES]
    if on_note and deferred:
        by_category: dict[str, int] = {}
        for _p, cat, _w in deferred:
            by_category[cat] = by_category.get(cat, 0) + 1
        breakdown = ", ".join(f"{n} {cat}" for cat, n in sorted(by_category.items()))
        names = ", ".join(f"{p.part_id} ({cat})" for p, cat, _w in deferred[:8])
        more = f" and {len(deferred) - 8} more" if len(deferred) > 8 else ""
        on_note(
            f"{len(deferred)} part(s) were NOT read on this run because their category is read "
            f"only on request — {breakdown}. Named here rather than dropped: {names}{more}. On a "
            "real government pack this category is mostly appendices — borehole logs, test "
            "schedules — which carry no contractual position, and reading them is most of a long "
            "run. It is not a claim that they carry none: the preambles are the measurement rules "
            "and the specification body carries obligations. Re-run with specifications included "
            "to read them."
        )
    if on_note and skipped:
        # Naming WHICH category decided it, because the two disagree and that disagreement is the
        # whole of this defect: a reader who sees a skip has to be able to tell whether a document
        # was skipped on evidence or on a guess.
        # `{part_id} ({category})` first and unchanged, then the authority — a superset of what
        # this note said before, so a reader (and a test) looking for the old shape still finds it.
        names = ", ".join(
            f"{p.part_id} ({cat}) on the "
            + ("interpreter's reading" if whose == "interpreted" else "planner's guess")
            for p, cat, whose in skipped[:8]
        )
        more = f" and {len(skipped) - 8} more" if len(skipped) > 8 else ""
        on_note(
            f"{len(skipped)} part(s) were NOT read for contractual positions — {names}{more}. A "
            "bill of quantities carries priced items, not clauses, and a drawing set carries "
            "geometry; reading them for contractual positions produces padding, not findings."
        )
    if on_note and parts and not readable and deferred:
        # A different statement entirely, and getting it wrong here would be the worst kind of
        # wrong: telling someone to upload conditions of contract they already uploaded, because
        # this run chose not to read them. The documents are present. They were deferred.
        on_note(
            "Nothing was read on this run. Every part of this set is either pricing/drawings or a "
            "category read only on request, so the register has no contractual document to report "
            "on — but the documents ARE here. Re-run with specifications included to read them."
        )
    elif on_note and parts and not readable:
        on_note(
            "This set contains NO contractual document — every part is pricing or drawings. The "
            "review has nothing to read, so it reports nothing. A finding that a letter of offer "
            "or a clarification is absent would be true and useless: neither was ever uploaded. "
            "Upload the conditions of contract, the specification or the tender conditions to "
            "review them."
        )

    # ---- PHASE A: local, sequential, fast. Read every part and build the flat task list. --------
    #
    # Splitting the loop in two is what makes both the concurrency and the progress possible. The
    # old single loop could only ever count PARTS, because a part's chunk count is not known until
    # its text has been read — and it read and called in the same breath. So the strip sat on 0/33
    # for minutes at a time while a 40-page part went through eight sequential model calls, and
    # `count_cb(index, len(readable))` fired once per part with the index BEFORE the work, so the
    # last part's calls all happened under a bar reading 32/33.
    #
    # Reading first costs a few seconds of local PDF text extraction and yields the real
    # denominator: the number of model calls this run will make.
    tasks: list[tuple[PartSpec, str, int, str]] = []      # (part, source, chunk_no, framed body)
    for part, pdf_path in readable:
        source = part.source_doc or pdf_path
        if source not in doc_names:
            doc_names.append(source)      # first-seen in INPUT order, exactly as before
        path = Path(pdf_path)
        if not pdf_path or not path.is_file():
            continue
        data = path.read_bytes()
        text = pdfops.page_text(data, 1, part.page_count())
        if not text.strip():
            continue  # a scanned part contributes no clauses; ingest already flagged it
        for chunk_no, chunk in enumerate(_chunk(text), start=1):
            tasks.append((part, source, chunk_no, (
                f"=== {source} — part {part.n:02d} {part.title} "
                f"(source pages {part.start}-{part.end}) ===\n{chunk}"
            )))

    if count_cb is not None:
        count_cb(0, len(tasks))           # the honest denominator, known only now

    # ---- PHASE B: the model calls, overlapped four at a time. ------------------------------------
    #
    # `run_calls` is the procurement chunked-extraction fan-out, reused rather than re-invented:
    # it preserves INPUT order (`ThreadPoolExecutor.map`), runs a single item inline with no pool
    # at all — so the DEMO one-call path is byte-identical — and bounds concurrency at 4.
    #
    # Four, not more. It is the number already proven against these providers in procurement
    # ingest, and DeepSeek's rate limits are not documented anywhere we can point at. A fan-out
    # that trips a 429 is slower than the sequential run it replaced, because every retry is a
    # fresh minute.
    #
    # `_structure` swallows its own exceptions and returns `[]`. That must stay INSIDE the worker:
    # `run_calls` re-raises the first exception `map` sees, so an exception escaping here would
    # take the whole batch down — where today one bad chunk is one gap in one part. `LLMClient`
    # builds its SDK clients under `_clients_lock`, so concurrent first-calls are already safe.
    done_lock = threading.Lock()
    done_count = 0

    def _one(task: tuple[PartSpec, str, int, str]) -> list[ClauseItem]:
        nonlocal done_count
        part, _source, chunk_no, body = task
        try:
            return _structure(client, body, f"{part.part_id}-{chunk_no}", on_note)
        finally:
            # In `finally`, so a chunk that fails still advances the bar. Progress measures calls
            # COMPLETED, not calls that succeeded; a bar that stalls on a failure would report the
            # run as hung when it is merely lossy. The gap itself is reported by `_structure`,
            # which is where the failure is known — this comment used to say it was reported
            # "elsewhere", and it was reported nowhere.
            with done_lock:
                done_count += 1
                if count_cb is not None:
                    count_cb(done_count, len(tasks))

    results = run_calls(_one, tasks)

    # Stitched back in input order, so clause ordering is identical to the sequential run.
    for (part, source, _chunk_no, _body), found in zip(tasks, results):
        for clause in found:
            clause.part_id = part.part_id
            if not clause.source_doc:
                clause.source_doc = source
            clauses.append(clause)

    if count_cb is not None and tasks:
        count_cb(len(tasks), len(tasks))
    return ParsedDocumentSet(name=project_name, documents=doc_names, clauses=clauses)


def ingest_review_documents(
    uploads: list[RawUpload], project_name: str = "", *, workspace: Optional[Workspace] = None,
) -> ParsedDocumentSet:
    """Extract and structure the document set into a :class:`ParsedDocumentSet`.

    Live: save each original to the Workspace, extract its text, then one AI structuring pass. DEMO:
    return the fixture parse offline. Set identity/persistence are the caller's job.
    """
    client = make_client()  # app-wide model setting applied here (client_boq/llm.py)
    if demo_mode():
        # Offline: the fixture is the structured parse. No file read, no network.
        return client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION, target_model=ParsedDocumentSet,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-review-ingest",
        )

    # Live: persist originals and extract text per document.
    doc_names: list[str] = []
    blocks: list[str] = []
    for filename, content_type, data in uploads:
        name = filename or "document"
        doc_names.append(name)
        if workspace is not None and project_name:
            workspace.save_upload(project_name, name, data)
        text, _page_images = extract_document(data, content_type, table_aware=True)
        blocks.append(f"=== {name} ===\n{text}")

    user = _INSTRUCTION + "\n\n".join(blocks) + f"\n\nDocument names: {doc_names}"
    parsed = client.complete_json(
        system=_SYSTEM, user=user, target_model=ParsedDocumentSet,
        purpose="client_boq-review-ingest",
    )
    if not parsed.documents:
        parsed = parsed.model_copy(update={"documents": doc_names})
    return parsed
