"""Stage 01 — ingest: TenderPackage -> ScopePackages.

Layer 2 (Claude) reads the four tender documents (Method of Measurement,
Particular Specification, Tender Addendum, Schedule of Rates) and splits the work
into one :class:`TradeWorkPackage` per trade — a scope summary, the relevant SoR
items, and ``source_refs`` naming which document each came from. The system prompt
forbids the model from pricing or judging a firm; it only splits and extracts.

Layer 1 then validates every returned trade against the canonical taxonomy
(``rules_engine.taxonomy``, which reads ``references/rubrics/trade_taxonomy.md``):
off-taxonomy trades are mapped to a canonical key or surfaced as unmapped — never
silently dropped. The taxonomy check is deterministic Python, not the model.

DEMO_MODE: ``complete_json`` short-circuits to a baked ``ScopePackages`` fixture and
never touches the network, exactly as the SiteClaim extract stage did.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Callable, Optional

from pydantic import ValidationError

from pipeline.concurrency import run_calls
from pipeline.llm_client import LLMClient
from rules_engine.taxonomy import CANONICAL_TRADES, validate_scope
from schemas.models import ScopePackages, SectionMeta, TenderPackage, TradeWorkPackage

# A large Schedule of Rates (SR-01 is 58 pages, Sections A-T, hundreds of items) cannot be
# extracted in one call — the JSON output exceeds max_tokens and truncates. So the text is
# chunked, extracted per chunk, and merged. Size a chunk so its expected JSON stays well
# under max_tokens (chunking, not a giant max_tokens ceiling, is what prevents truncation).
MAX_CHUNK_CHARS = 12000
# Cap the SoR rows sent per extraction call. A dense section (e.g. H at 59 items) fits within
# MAX_CHUNK_CHARS yet still produces more JSON than the model's output-token cap can hold in one
# response — so it is extracted across several calls and the items concatenated. This item/row
# cap, not a bigger max_tokens, is the primary guard against a truncated (EOF) JSON response.
MAX_ITEMS_PER_CHUNK = 30
# The output-token ceiling for an extraction call — headroom above the generic default so a
# normal row-batch fits comfortably; the batch cap above is the real fix, so this need not be
# large. Env-overridable if a provider's model caps lower.
_DEFAULT_INGEST_MAX_TOKENS = 16000


def _system_prompt() -> str:
    """Build the split instruction, embedding the canonical trades from the taxonomy.

    States the output shape by exact field name (not by schema title) and lists the
    valid trades read live from ``rules_engine.taxonomy`` — so a newer model does not
    guess field names (the observed Sonnet-5 drift was ``package_name`` instead of
    ``trade``) and the trade list never drifts from the taxonomy.
    """
    trades = ", ".join(sorted(CANONICAL_TRADES))
    return (
        "You are a quantity-surveying assistant for a Hong Kong main contractor. Read the "
        "tender documents (Method of Measurement, Particular Specification, Tender Addendum, "
        "Schedule of Rates) and SPLIT the works into trade packages. You ONLY split and "
        "extract scope — never price the work, never invent a quantity or rate, never judge "
        "or rank a subcontractor.\n\n"
        "Return ONE JSON object with EXACTLY these field names and no others:\n"
        '{"project_name": <string>, "packages": [\n'
        '  {"trade": <canonical trade>, "scope_summary": <string>, '
        '"sor_items": [{"item_ref": <string>, "description": <string>, "unit": <string>, '
        '"qty": <number>}], "source_refs": [<string naming the tender document>]}\n'
        "]}\n\n"
        f"`trade` MUST be exactly one of these canonical trades: {trades}. Put the "
        "descriptive sub-section name (e.g. \"Geotechnical Works\", \"Section 7\") in "
        "`scope_summary`, NOT in any other field. Never emit a `package_name` field. Emit "
        "exactly one package per canonical trade that appears in the tender — consolidate "
        "several sub-sections of the same trade into that trade's single package rather than "
        "one package per sub-section — and no package for a trade that is not present.\n\n"
        "Populate `sor_items` with EVERY priced row of the Schedule of Rates for that trade "
        "— one object per row — copying its item reference, description, unit, and quantity "
        "verbatim (include `qty` when the row states one). Do NOT collapse a section into a "
        "single summary item: `scope_summary` is the prose overview, `sor_items` is the "
        "row-by-row list. Never invent an item, a rate, or a quantity.\n\n"
        "`item_ref` MUST be the EXACT printed item code as it appears in the schedule "
        '(e.g. "A1a(a)", "M2", "H14"), copied character-for-character — NEVER the section '
        "letter fused with neighbouring text or an adjacent column value, and NEVER an "
        "invented or renumbered code. If a row has no printed item code, SKIP that row "
        "rather than fabricate a ref."
    )


def _user_prompt(tender: TenderPackage) -> str:
    docs = "\n".join(f"- {d.doc_type.value}: {d.filename}" for d in tender.documents)
    return (
        f"Project: {tender.project_name}\n"
        f"Description: {tender.description}\n"
        f"Tender documents:\n{docs}\n\n"
        "Split this tender into trade work packages."
    )


# ---------------------------------------------------------------------------
# Chunked extraction — split a large SoR text into a handful of pieces, extract each,
# and merge the items (deterministic; never splits mid-line / mid-item-row).
# ---------------------------------------------------------------------------
_SECTION_RE = re.compile(r"(?im)^\s*(?:section|part)\s+[A-Za-z0-9]")
_PAGE_RE = re.compile(r"(?m)^\[page \d+\]")

# The section code is the leading letters of an item_ref before the first digit/punctuation
# (`A1a(a)` -> `A`, `E10(l)` -> `E`, `BB7a` -> `BB`, `M-01` -> `M`).
_SECTION_CODE_RE = re.compile(r"^\s*([A-Za-z]+)")
# A section header the chunker sees — `SECTION A : PRELIMINARIES ITEMS`, two-letter
# `SECTION BA : GENERAL`, `SECTION K : (Not used)`. Captures the code and its title.
_SECTION_HEADER_RE = re.compile(r"(?im)^\s*(?:section|part)\s+([A-Za-z0-9]+)\s*[:.\-]\s*(.+?)\s*$")


def section_of(item_ref: str) -> str:
    """The SoR section code for an item_ref — its leading letters, upper-cased ('' if none)."""
    m = _SECTION_CODE_RE.match(item_ref or "")
    return m.group(1).upper() if m else ""


def _section_titles(text: str) -> dict[str, str]:
    """Map each section code to the title from its header (first occurrence wins)."""
    titles: dict[str, str] = {}
    for m in _SECTION_HEADER_RE.finditer(text or ""):
        code, title = m.group(1).upper(), m.group(2).strip()
        if code and title and code not in titles:
            titles[code] = title
    return titles


def annotate_sections(scope: ScopePackages, doc_text: str = "") -> ScopePackages:
    """Set each item's ``section`` (from its ref) and each package's ``sections`` metadata
    (code, header title if seen, item_count) — the routable unit made visible. Deterministic;
    a single-section package (every demo package) simply carries one section."""
    titles = _section_titles(doc_text)
    packages: list[TradeWorkPackage] = []
    for pkg in scope.packages:
        counts: dict[str, int] = {}
        order: list[str] = []
        items = []
        for it in pkg.sor_items:
            code = section_of(it.item_ref)
            items.append(it if it.section == code else it.model_copy(update={"section": code}))
            if code:
                if code not in counts:
                    order.append(code)
                counts[code] = counts.get(code, 0) + 1
        sections = [SectionMeta(code=c, title=titles.get(c, ""), item_count=counts[c]) for c in order]
        packages.append(pkg.model_copy(update={"sor_items": items, "sections": sections}))
    return scope.model_copy(update={"packages": packages})


def _split_on(text: str, pattern: re.Pattern) -> list[str]:
    """Split ``text`` at each ``pattern`` match, keeping each header with its block."""
    starts = [m.start() for m in pattern.finditer(text)]
    if not starts:
        return [text]
    blocks: list[str] = []
    if starts[0] > 0:
        blocks.append(text[: starts[0]])  # preamble before the first header
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        blocks.append(text[start:end])
    return [b for b in blocks if b.strip()]


def _split_into_blocks(text: str) -> list[str]:
    """Prefer Section-header boundaries when cleanly detectable (>=2), else page boundaries."""
    if len(_SECTION_RE.findall(text)) >= 2:
        return _split_on(text, _SECTION_RE)
    if len(_PAGE_RE.findall(text)) >= 2:
        return _split_on(text, _PAGE_RE)
    return [text]


def _cap_block(block: str, max_chars: int) -> list[str]:
    """Hard-split an over-long block on line boundaries — never mid-line."""
    if len(block) <= max_chars:
        return [block]
    pieces, current, size = [], [], 0
    for line in block.splitlines(keepends=True):
        if size + len(line) > max_chars and current:
            pieces.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        pieces.append("".join(current))
    return pieces


def _is_section_header(line: str) -> bool:
    """True when a line is a Section/Part header (so it carries trade context, not an item row)."""
    return bool(_SECTION_RE.match(line or ""))


def _row_batches(chunk: str, max_rows: int) -> list[str]:
    """Split one chunk into batches of at most ``max_rows`` non-blank rows so a dense section's
    JSON output never exceeds the model's token cap. A leading Section header is repeated on each
    batch, so every batch keeps its trade context. Returns ``[chunk]`` unchanged when it fits."""
    lines = chunk.splitlines()
    if sum(1 for ln in lines if ln.strip()) <= max_rows:
        return [chunk]
    header = lines[0] if lines and _is_section_header(lines[0]) else ""
    body = lines[1:] if header else lines
    batches: list[str] = []
    current: list[str] = []
    count = 0
    for line in body:
        current.append(line)
        if line.strip():
            count += 1
        if count >= max_rows:
            batches.append("\n".join(([header] if header else []) + current))
            current, count = [], 0
    if any(ln.strip() for ln in current):
        batches.append("\n".join(([header] if header else []) + current))
    return batches


def _chunk_text(text: str, max_chars: Optional[int] = None, max_rows: Optional[int] = None) -> list[str]:
    """Chunk ``text`` into pieces under ``max_chars`` AND ``max_rows`` on section/page/line
    boundaries. Never splits mid-line, so an item row is never cut in half. The row cap splits a
    dense section (many short rows) that fits the char budget but would overflow one JSON response."""
    max_chars = max_chars or MAX_CHUNK_CHARS
    max_rows = max_rows or MAX_ITEMS_PER_CHUNK
    if not text.strip():
        return []
    chunks, current, size = [], [], 0
    for block in _split_into_blocks(text):
        for piece in _cap_block(block, max_chars):
            if size + len(piece) > max_chars and current:
                chunks.append("\n".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece)
    if current:
        chunks.append("\n".join(current))
    # Second pass: cap each char-bounded chunk to a safe number of item rows per call.
    batched: list[str] = []
    for chunk in chunks:
        batched.extend(_row_batches(chunk, max_rows))
    return batched


def _merge_scopes(results: list[ScopePackages], tender: TenderPackage) -> ScopePackages:
    """Merge per-chunk results into one ScopePackages: group packages by trade, concatenate
    ``sor_items`` deduped by ``item_ref`` (unique across sections). ``project_name`` /
    ``scope_summary`` / ``source_refs`` are taken once, from their first appearance."""
    project_name = ""
    order: list[str] = []
    merged: dict[str, dict] = {}
    for scope in results:
        if scope.project_name and not project_name:
            project_name = scope.project_name
        for pkg in scope.packages:
            if pkg.trade not in merged:
                merged[pkg.trade] = {"scope_summary": pkg.scope_summary, "source_refs": [], "items": [], "seen": set()}
                order.append(pkg.trade)
            entry = merged[pkg.trade]
            if not entry["scope_summary"] and pkg.scope_summary:
                entry["scope_summary"] = pkg.scope_summary
            for ref in pkg.source_refs:
                if ref not in entry["source_refs"]:
                    entry["source_refs"].append(ref)
            for item in pkg.sor_items:
                key = (item.item_ref or "").strip()
                if key and key in entry["seen"]:
                    continue  # dedupe by non-empty item_ref; keep the first
                if key:
                    entry["seen"].add(key)
                entry["items"].append(item)
    packages = [
        TradeWorkPackage(
            trade=trade, scope_summary=merged[trade]["scope_summary"],
            sor_items=merged[trade]["items"], source_refs=merged[trade]["source_refs"],
        )
        for trade in order
    ]
    return ScopePackages(project_name=project_name or tender.project_name, packages=packages)


_CONTEXT_MAX_CHARS = 6000  # bounded background from non-SoR documents for the trade split

# A response that was cut off at the output-token cap surfaces as a JSON syntax error: pydantic
# v2 tags it ``json_invalid`` ("Invalid JSON: EOF while parsing…"); a raw ``json`` error is an
# "Expecting…"/"Unterminated…" ValueError. Either way splitting the batch is the right escalation.
_TRUNCATION_SIGNS = ("eof while parsing", "unterminated", "unexpected end", "expecting", "control character")


def ingest_max_tokens() -> int:
    """Output-token ceiling for an extraction call (env-overridable)."""
    try:
        return int(os.getenv("SITESOURCE_INGEST_MAX_TOKENS", str(_DEFAULT_INGEST_MAX_TOKENS)))
    except ValueError:
        return _DEFAULT_INGEST_MAX_TOKENS


def _is_truncation_error(exc: Exception) -> bool:
    """True when a parse failure looks like a cut-off / malformed JSON response (so the batch
    should be split and retried), not a schema-shape mismatch."""
    if isinstance(exc, ValidationError):
        try:
            if any(e.get("type") == "json_invalid" for e in exc.errors()):
                return True
        except Exception:  # noqa: BLE001 — never let error-classification raise
            pass
    msg = str(exc).lower()
    return "invalid json" in msg or any(sign in msg for sign in _TRUNCATION_SIGNS)


def _context_block(context: str) -> str:
    return (
        "\n\n=== Context documents (specifications, clarifications, method of "
        "measurement) — for scope and trade understanding ONLY; do NOT extract any "
        "priced item from this section ===\n" + context
    )


def _chunk_label(text: str) -> str:
    """A human name for a batch, for a per-section error message — the Section header if present."""
    m = _SECTION_HEADER_RE.search(text or "")
    if m:
        title = m.group(2).strip()
        return f"section {m.group(1).upper()}" + (f" ({title})" if title else "")
    m2 = re.search(r"(?im)^\s*(?:section|part)\s+([A-Za-z0-9]+)", text or "")
    if m2:
        return f"section {m2.group(1).upper()}"
    return "a Schedule-of-Rates batch"


def _extract_batch(
    client: LLMClient, system: str, base_user: str, *, rows_text: str,
    images: Optional[list[str]], extra: str, demo_fixture: Optional[str], max_tokens: int, label: str,
) -> tuple[list[ScopePackages], list[str]]:
    """Extract one batch of SoR rows (or the single scanned-pages call). Returns
    ``(scopes, errors)``. On a TRUNCATION parse failure the batch is split in half by rows and
    retried recursively down to a floor of one row; a floor unit that still truncates is surfaced
    as a per-section error (NOT raised), so one oversized batch never collapses the whole ingest.
    A non-truncation failure keeps the existing behaviour (propagates after complete_json's own
    corrective retry)."""
    user = base_user
    if rows_text:
        user += "\n\n=== Extracted tender document text ===\n" + rows_text
    elif images:
        user += "\n\n=== Attached scanned tender pages ==="
    if extra:
        user += extra
    try:
        scope = client.complete_json(
            system=system, user=user, target_model=ScopePackages,
            demo_fixture=demo_fixture, images=images, max_tokens=max_tokens, purpose="ingest-chunk",
        )
        return [scope], []
    except (ValidationError, ValueError) as exc:
        if not _is_truncation_error(exc):
            raise  # a genuine schema/other failure — unchanged behaviour
        rows = [ln for ln in (rows_text or "").splitlines() if ln.strip()]
        # Keep a leading Section header out of the row count and repeat it on each half, so the
        # split strictly shrinks the DATA rows (never loops on a header-only remainder).
        header = rows[0] if rows and _is_section_header(rows[0]) else ""
        data = rows[1:] if header else rows
        if images or len(data) <= 1:
            # A scanned-pages call, or a single row, cannot be split further — flag and skip it.
            return [], [f"{label}: the extractor's JSON was truncated and could not be split further, so this batch was skipped"]
        mid = len(data) // 2
        prefix = [header] if header else []
        left = "\n".join(prefix + data[:mid])
        right = "\n".join(prefix + data[mid:])
        left_scopes, left_errs = _extract_batch(
            client, system, base_user, rows_text=left, images=None, extra="",
            demo_fixture=demo_fixture, max_tokens=max_tokens, label=label,
        )
        right_scopes, right_errs = _extract_batch(
            client, system, base_user, rows_text=right, images=None, extra="",
            demo_fixture=demo_fixture, max_tokens=max_tokens, label=label,
        )
        return left_scopes + right_scopes, left_errs + right_errs


def _extract(
    client: LLMClient, tender: TenderPackage, doc_text: str, images: Optional[list[str]],
    demo_fixture: Optional[str], context_text: str = "",
    progress_cb: Optional[Callable[[int, int], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> ScopePackages:
    """Run the item-extraction prompt over the document and merge into one ScopePackages.

    Large text is chunked and row-capped (several small calls); any scanned pages go in a single
    vision call; a small or empty document (incl. the DEMO fixture) is a single call. Each batch
    self-heals a truncated response by splitting (``_extract_batch``); a batch that stays
    unparseable at the floor is reported via ``on_error(msg)`` — naming the section — and skipped,
    never failing the whole ingest. ``context_text`` (non-SoR documents) rides the first call as
    labelled background for the trade split and never yields a priced item. ``progress_cb(done,
    total)`` reports batch completions; both callbacks are side effects only.
    """
    system = _system_prompt()
    base_user = _user_prompt(tender)
    max_tokens = ingest_max_tokens()

    # The ordered units to extract: each text batch, then one vision call for scanned pages. An
    # empty document (DEMO fixture / tiny tender) is still one call.
    units: list[tuple[str, str, Optional[list[str]]]] = [("text", chunk, None) for chunk in _chunk_text(doc_text)]
    if images:
        units.append(("image", "", images))
    if not units:
        units.append(("empty", "", None))

    context = context_text.strip()[:_CONTEXT_MAX_CHARS]
    total = len(units)
    done_count = 0
    counter_lock = threading.Lock()
    if progress_cb:
        progress_cb(0, total)

    def _run_unit(indexed: tuple[int, tuple[str, str, Optional[list[str]]]]) -> list[ScopePackages]:
        idx, (kind, rows_text, imgs) = indexed
        extra = _context_block(context) if (idx == 0 and context) else ""  # background rides call 0
        label = _chunk_label(rows_text) if kind == "text" else ("scanned pages" if kind == "image" else "the tender")
        scopes, errors = _extract_batch(
            client, system, base_user, rows_text=rows_text, images=imgs, extra=extra,
            demo_fixture=demo_fixture, max_tokens=max_tokens, label=label,
        )
        if on_error:
            for err in errors:
                on_error(err)
        if progress_cb:
            nonlocal done_count
            with counter_lock:
                done_count += 1
                progress_cb(done_count, total)
        return scopes

    # Units are independent — run them bounded-concurrent (a 58-page SoR was ~7 min sequential).
    # run_calls preserves input order, so the chunk-order dedupe in _merge_scopes is unchanged; a
    # unit's own split-retries run inline within its slot, so there is no unbounded fan-out.
    result_lists = run_calls(_run_unit, list(enumerate(units)))
    all_scopes = [scope for scopes in result_lists for scope in (scopes or [])]
    return _merge_scopes(all_scopes, tender)


def ingest_tender(
    tender: TenderPackage,
    demo_fixture: Optional[str] = None,
    *,
    client: Optional[LLMClient] = None,
    images: Optional[list[str]] = None,
    doc_text: str = "",
    context_text: str = "",
    progress_cb: Optional[Callable[[int, int], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> ScopePackages:
    """Split ``tender`` into one :class:`TradeWorkPackage` per trade.

    In DEMO_MODE the split is read from ``demo_fixture``. Otherwise Layer 2 produces it
    text-first: ``doc_text`` (the Schedule-of-Rates text layer) is chunked on section/page
    boundaries and each chunk extracted separately, then merged — so a 58-page Schedule
    of Rates yields the full item list without truncation. Scanned pages (``images``) go
    in a single vision call. ``context_text`` is non-SoR document text (specs,
    clarifications, MoM) that informs the trade split but yields no priced items — the
    caller gates on the classified ``doc_type`` so a Method of Measurement never produces
    phantom items. ``project_name`` is taken from the tender; Layer 1 then normalises
    trades against the taxonomy before returning.
    """
    client = client or LLMClient()
    scope = _extract(
        client, tender, doc_text, images, demo_fixture,
        context_text=context_text, progress_cb=progress_cb, on_error=on_error,
    )
    normalised, unmapped = validate_scope(scope)
    if unmapped:
        # Surfaced, not dropped — a human reconciles these against the taxonomy.
        print(f"[ingest] unmapped trades (kept for review): {unmapped}")
    # Tag each item with its SoR section and roll up the per-package section metadata (the
    # routable unit). doc_text supplies the header titles on the live path; demo has none.
    return annotate_sections(normalised, doc_text)
