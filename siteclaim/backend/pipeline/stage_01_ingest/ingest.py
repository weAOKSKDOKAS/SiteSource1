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
from rules_engine.taxonomy import CANONICAL_TRADES, section_specialty, validate_scope
from schemas.models import ScopePackages, SectionMeta, SorItem, TenderPackage, TradeWorkPackage

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
        '"qty": <number>, "clause_refs": [<string>]}], '
        '"source_refs": [<string naming the tender document>]}\n'
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
        "rather than fabricate a ref.\n\n"
        "`clause_refs` MUST be the specification references printed in that row's \"Clause "
        "Ref\" (or \"Reference\") column, each copied VERBATIM as its own string and kept "
        "with its kind prefix — General Specification clauses (\"GS 7.34\"), Particular "
        "Specification clauses (\"PS 7.34A\", \"PS 7.37A\", including any letter / bracket / "
        "\"S\" suffix such as \"7.41.(4)S\"), and Method-of-Measurement preamble clauses "
        "(\"PB 71\"). Copy the references; do NOT judge, resolve, or invent one. Use an empty "
        "list when the row cites none."
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


# Valid SoR section codes: single letters A–Z, the two-letter BA–BF range the real schedules use,
# plus any code that actually appears as a ``SECTION X :`` header in the document (so a genuine
# ``SECTION HS`` header, should one ever exist, legitimises HS). Scanned-OCR corruptions — a digit
# read as a letter (``H5`` -> ``HS``) or a dropped leading letter (``H1(a)`` -> ``1(a)`` -> "") —
# are snapped back onto this set so one real section stops fragmenting into several.
_LETTERS = frozenset(chr(c) for c in range(ord("A"), ord("Z") + 1))
_TWO_LETTER_SECTIONS = frozenset({"BA", "BB", "BC", "BD", "BE", "BF"})


def _valid_section_codes(titles: dict[str, str]) -> frozenset[str]:
    return _LETTERS | _TWO_LETTER_SECTIONS | frozenset(titles)


def _snap_section(raw: str, valid: frozenset[str]) -> Optional[str]:
    """The valid section code for a raw code: itself if valid, else its LONGEST valid prefix
    (``HS`` -> ``H``, ``BAX`` -> ``BA``), else ``None`` (unresolvable — the caller fills forward)."""
    if not raw:
        return None
    if raw in valid:
        return raw
    for end in range(len(raw) - 1, 0, -1):  # longest valid prefix wins (BA before B)
        if raw[:end] in valid:
            return raw[:end]
    return None


def _normalise_sections(items: list, valid: frozenset[str]) -> list[str]:
    """The corrected section code for each item, walking the package IN ORDER: a valid or
    prefix-snapped code sets the running section; an unresolvable one (empty, or corrupt with no
    valid prefix) inherits the running section (fill-forward). A leading run before any section
    resolves is back-filled from the first section that does. Deterministic — no LLM, and never an
    invented section: an all-unresolvable package keeps ''."""
    running = ""
    codes: list[str] = []
    for it in items:
        snapped = _snap_section(section_of(getattr(it, "item_ref", "")), valid)
        if snapped:
            running = snapped
        codes.append(snapped or running)
    first = next((c for c in codes if c), "")
    return [c or first for c in codes] if first else codes


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
    valid = _valid_section_codes(titles)
    packages: list[TradeWorkPackage] = []
    for pkg in scope.packages:
        # Repair each item's section code deterministically (snap OCR corruptions onto the valid
        # set, fill-forward a lost code) so one real section stops fragmenting into H / HS / '';
        # then roll up the section metadata from the CORRECTED codes.
        codes = _normalise_sections(pkg.sor_items, valid)
        items = [
            it if it.section == code else it.model_copy(update={"section": code})
            for it, code in zip(pkg.sor_items, codes)
        ]
        counts: dict[str, int] = {}
        order: list[str] = []
        for code in codes:
            if code:
                if code not in counts:
                    order.append(code)
                counts[code] = counts.get(code, 0) + 1
        # Each section's specialty pool for the shortlist: derived deterministically from the
        # header title (geophysical / field installations / field testing), else the package's own
        # trade — never an LLM call, never dropped.
        sections = [
            SectionMeta(
                code=c, title=titles.get(c, ""), item_count=counts[c],
                section_trade=section_specialty(titles.get(c, "")) or pkg.trade,
            )
            for c in order
        ]
        packages.append(pkg.model_copy(update={"sor_items": items, "sections": sections}))
    return scope.model_copy(update={"packages": packages})


_RECOVER_MAIN = re.compile(r"^\s*(?:Item:\s*)?([A-Z]{1,2}\d+)\b[)\.|:\s]*(.*)$")
_RECOVER_SUB = re.compile(r"^\s*(?:Item:\s*)?\(([a-z]{1,4})\)\s*[)\.|:\s]*(.*)$")
_ROMAN = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"})


def _ocr_item_inventory(doc_text: str) -> "dict[str, str]":
    """Every SoR item code that appears at the START of a line in the (OCR/native) SoR text, mapped
    to a short description — reconstructing nested codes (``G3`` -> ``G3(d)`` -> ``G3(d)(i)``) from a
    running parent. Deterministic; skips ``SECTION …`` headers. This is the completeness ground truth
    the LLM extraction is checked against — the OCR captures every ruled row even when the model
    drops some."""
    valid = _LETTERS | _TWO_LETTER_SECTIONS
    inv: dict[str, str] = {}
    main = ""       # e.g. "G7" — only set to a code whose section is a real SoR section
    letter = ""     # e.g. "(a)" — the current alpha sub-item under `main`
    for raw in (doc_text or "").splitlines():
        line = raw.strip()
        if not line or line[:1] == "=" or re.match(r"(?i)^(?:Item:\s*)?(?:section|part)\b", line):
            continue
        m = _RECOVER_MAIN.match(line)
        if m and section_of(m.group(1)) in valid:
            # A real item code (section A-Z / BA-BF). Excludes clause-ref prefixes that also look
            # like codes — PB 145 (preamble), GS 7.72 / PS 7.34A (spec clauses), SR/… headers.
            main, letter = m.group(1).upper(), ""
            inv.setdefault(main, m.group(2).strip()[:80])
            continue
        s = _RECOVER_SUB.match(line)
        if s and main:
            token = s.group(1).lower()
            is_roman = token in _ROMAN
            if not (is_roman or len(token) == 1):
                continue  # OCR noise like "(iti)" — not a clean alpha letter or roman numeral
            if is_roman and letter:                   # nested roman: G3(d)(i)
                code = f"{main}{letter}({token})"
            else:                                     # alpha sub-item: G7(a); update running letter
                letter = f"({token})"
                code = f"{main}{letter}"
            inv.setdefault(code, s.group(2).strip()[:80])
    return inv


def _norm_ref(ref: str) -> str:
    """Canonical form of an item_ref for matching OCR inventory against extracted items —
    upper-cased, whitespace removed (``g3 (d)(i)`` -> ``G3(D)(I)``)."""
    return re.sub(r"\s+", "", (ref or "")).upper()


def recover_dropped_sor_items(scope: ScopePackages, doc_text: str) -> ScopePackages:
    """Deterministic completeness backstop (Layer 1): a scanned SoR is OCR'd row-for-row, but the
    LLM structuring step sometimes DROPS ruled rows (observed: whole items G7-G10, G17 and sub-items
    like G3(f) missing while the OCR clearly holds them). Any item code the OCR text carries that the
    extracted scope lacks is added back as a :class:`SorItem` (code + OCR description), so no priced
    row is silently lost. Additive only - never removes or renames an extracted item; a code already
    present (in any package) is left untouched. Rows are added to the package that already owns the
    most of that section's items, else the first package. No LLM, no DB.

    Only fires when the SoR text actually leads lines with item codes (the OCR/native SoR shape); an
    empty/absent ``doc_text`` (DEMO) is a no-op."""
    inv = _ocr_item_inventory(doc_text)
    if not inv:
        return scope
    have = {_norm_ref(it.item_ref) for p in scope.packages for it in p.sor_items}
    # A code that is the PARENT of another code is a section/description header, not a priced row:
    # a SoR header like "J5 Mobilise …" carries no rate — its children J5(a)/J5(b) do. Recovering a
    # header would duplicate an already-extracted sub-item's row (the J5/J6/J8 doubling), so only
    # LEAF codes (no child in the OCR inventory or the extracted set) are recovered.
    universe = have | {_norm_ref(c) for c in inv}

    def _is_header(norm_code: str) -> bool:
        prefix = norm_code + "("
        return any(d != norm_code and d.startswith(prefix) for d in universe)

    missing = [(code, desc) for code, desc in inv.items()
               if _norm_ref(code) not in have and not _is_header(_norm_ref(code))]
    if not missing:
        return scope
    packages = [p.model_copy(update={"sor_items": list(p.sor_items)}) for p in scope.packages]

    def _home_for(sec: str):
        best, best_n = None, -1
        for p in packages:
            n = sum(1 for it in p.sor_items if section_of(it.item_ref) == sec)
            if n > best_n:
                best, best_n = p, n
        return best

    recovered: list[str] = []
    for code, desc in missing:
        sec = section_of(code)
        if not sec:
            continue
        home = _home_for(sec) or (packages[0] if packages else None)
        if home is None:
            continue
        home.sor_items.append(SorItem(item_ref=code, description=(desc or None), section=sec))
        recovered.append(code)
    if recovered:
        print(f"[ingest] recovered {len(recovered)} SoR rows the extractor dropped "
              f"(from OCR): {', '.join(recovered[:30])}{' …' if len(recovered) > 30 else ''}")
    return scope.model_copy(update={"packages": packages})


def consolidate_fragmented_sections(scope: ScopePackages) -> ScopePackages:
    """Deterministic Layer-1 repair: when one SoR SECTION's rows get scattered across several
    trade packages (the LLM sometimes assigns a stray row a different trade — e.g. a "Flowmeter"
    line in Section G tagged mechanical_plumbing, or Section H split between field_installations
    and its parent ground_investigation), merge that section's items back into ONE package. The
    section is the routable unit, so a section must live in exactly one package.

    The target trade for a fragmented section is the section header's GI specialty
    (``section_specialty`` — the same deterministic signal ``section_trade`` already uses) when it
    names one AND a package with that trade already holds part of the section; otherwise the trade
    holding the most of the section's items. A section that already sits in a single package is
    left untouched, so a clean split (every demo/building tender) is unaffected. No LLM, no DB."""
    from collections import Counter

    packages = [p.model_copy(update={"sor_items": list(p.sor_items)}) for p in scope.packages]

    def _sec(it) -> str:
        return (getattr(it, "section", "") or "").strip().upper()

    # Section header title from the rolled-up metadata (annotate_sections set these).
    title_of: dict[str, str] = {}
    for p in packages:
        for s in p.sections:
            if s.code and s.title and s.code not in title_of:
                title_of[s.code] = s.title

    # Which package index holds how many items of each section.
    holders: dict[str, Counter] = {}
    for i, p in enumerate(packages):
        for code, n in Counter(_sec(it) for it in p.sor_items if _sec(it)).items():
            holders.setdefault(code, Counter())[i] += n

    for code, by_pkg in holders.items():
        if len(by_pkg) < 2:
            continue  # already in one package — nothing to merge, zero effect on a clean split
        holder_trades = {packages[i].trade for i in by_pkg}
        specialty = section_specialty(title_of.get(code, ""))
        if specialty and specialty in holder_trades:
            target_trade = specialty
        else:
            # the trade holding the most of this section's items (ties -> first seen)
            target_idx = by_pkg.most_common(1)[0][0]
            target_trade = packages[target_idx].trade
        target = next(p for p in packages if p.trade == target_trade)
        # Move every out-of-target item of this section into the target, preserving order.
        moved: list = []
        for p in packages:
            if p.trade == target_trade:
                continue
            keep = [it for it in p.sor_items if _sec(it) != code]
            moved += [it for it in p.sor_items if _sec(it) == code]
            p.sor_items[:] = keep
        if moved:
            target.sor_items.extend(moved)

    # Drop packages emptied by the moves; keep original order otherwise.
    packages = [p for p in packages if p.sor_items]
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
    # Completeness backstop: add back any SoR row the OCR captured but the LLM structuring dropped
    # (a scanned schedule's ruled rows — G7-G10, G17, G3(f) … — must never be silently lost).
    recovered = recover_dropped_sor_items(normalised, doc_text)
    # Tag each item with its SoR section and roll up the per-package section metadata (the
    # routable unit). doc_text supplies the header titles on the live path; demo has none.
    annotated = annotate_sections(recovered, doc_text)
    # Merge any section whose rows got scattered across trades back into one package (the section
    # is the routable unit), then refresh the per-package section metadata from the moved items.
    consolidated = consolidate_fragmented_sections(annotated)
    return annotate_sections(consolidated, doc_text)
