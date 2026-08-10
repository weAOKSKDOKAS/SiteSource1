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
# The Bill-of-Quantities equivalent, ALONGSIDE `_SECTION_RE` rather than folded into it — the
# Schedule-of-Rates path is live and its pattern must keep matching exactly what it matches today.
# `Bill No. 1 …`, `BILL NO.2 …`, `Bill 3 …`.
_BILL_RE = re.compile(r"(?im)^\s*bill\s*(?:no\.?|number)?\s*\d")
_PAGE_RE = re.compile(r"(?m)^\[page \d+\]")

# The section code is the leading letters of an item_ref before the first digit/punctuation
# (`A1a(a)` -> `A`, `E10(l)` -> `E`, `BB7a` -> `BB`, `M-01` -> `M`).
_SECTION_CODE_RE = re.compile(r"^\s*([A-Za-z]+)")
# A section header the chunker sees — `SECTION A : PRELIMINARIES ITEMS`, two-letter
# `SECTION BA : GENERAL`, `SECTION K : (Not used)`. Captures the code and its title.
_SECTION_HEADER_RE = re.compile(r"(?im)^\s*(?:section|part)\s+([A-Za-z0-9]+)\s*[:.\-]\s*(.+?)\s*$")
# The Bill form of the same thing, again added BESIDE the Section form. Real documents vary in
# punctuation and case, and the separator is genuinely optional — all three of these occur:
#   `Bill No. 1 - General and Preliminaries`
#   `BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS`
#   `Bill No.3 Laboratory Testing`          <- no separator at all
# A title is required, exactly as the Section form requires one, so a bare `Bill No. 1` cross-
# reference in prose is not read as a header. Group 1 = bill number, group 2 = title.
# Mirrors `doc_index._BILL_SECTION_HEADER`, INCLUDING the optional title: a real bill header can be
# a bare `Bill No. 2`. `_headers` drops the empty title, so a title-less header simply contributes
# none — which is the truth about it — instead of the collection footer's words.
_BILL_HEADER_RE = re.compile(
    r"(?im)^[^\S\n]*bill[^\S\n]*(?:no\.?|number)?[^\S\n]*(\d{1,2})\b"
    r"[^\S\n]*[:.\-–—]?[^\S\n]*(.*?)[^\S\n]*$")


def section_of(item_ref: str) -> str:
    """The SoR section code for an item_ref — its leading letters, upper-cased ('' if none)."""
    m = _SECTION_CODE_RE.match(item_ref or "")
    return m.group(1).upper() if m else ""


# ---------------------------------------------------------------------------
# Two document families
# ---------------------------------------------------------------------------
# A Hong Kong SCHEDULE OF RATES numbers its items with a letter section code — `A1a(a)`, `E10(l)`,
# `BB7a`, `M-01`. A BILL OF QUANTITIES numbers them `<bill>.<item>` — `1.17`, `2.24`, `3.1` — with
# no letters anywhere. CEDD ND/2025/04 extracted 136 items correctly and every one was quarantined,
# because `section_of("1.17")` is '' and no numeric code could ever be valid.
#
# THE BILL IS THE SECTION. ND/2025/04 yields nine sections, `1` through `9` — not bill-plus-
# subsection: you do not sublet item 2.4 and self-perform item 2.5 of the same drilling operation.
# `route_units()` already splits a large package further by section when the thresholds are met, so
# finer grain stays available without redefining what a section is.
#
# The detection below is DETERMINISTIC — read off the item references themselves, with the
# document's own headers as corroboration. No LLM, no configuration flag, no user question.

# A bill reference: a small leading integer, a separator, then the item number. `\d{1,2}` is the
# bound the brief asks for — a bill number is a small positive integer, so `2025.1` (a date that
# reached the reference column) matches nothing and inherits the running bill instead of opening a
# section of its own. A BARE integer (`2`, `1(a)`) is deliberately NOT a bill reference: those are
# Schedule-of-Rates refs that lost their leading letter, which is the case fill-forward exists for.
_BILL_REF_RE = re.compile(r"^\s*(\d{1,2})\s*[.\-/]\s*\d")
_MAX_BILL = 99
# At least this many bill-shaped refs before a package can be read as a bill. One dotted ref in a
# schedule is noise; two or more, outnumbering the letter-prefixed ones, is a document.
_BILL_MIN_REFS = 2


def bill_of(item_ref: str) -> str:
    """The BQ bill number for an item_ref — the leading integer before the first separator
    (``1.17`` -> ``1``, ``24.2`` -> ``24``, ``01.3`` -> ``1``), ``''`` when the ref is not
    bill-shaped. The numeric counterpart of :func:`section_of`; neither ever sees the other's
    family, which is how the Schedule-of-Rates path stays byte-for-byte unchanged."""
    m = _BILL_REF_RE.match(item_ref or "")
    if not m:
        return ""
    code = m.group(1).lstrip("0")
    return code if code and int(code) <= _MAX_BILL else ""


def section_family(items: list) -> tuple[str, int, int]:
    """``(family, n_bill_refs, n_letter_refs)`` for one package — ``"bq"`` or ``"sor"``.

    Bill iff at least ``_BILL_MIN_REFS`` references are bill-shaped AND they outnumber the
    letter-prefixed ones. Everything else — including a package with no readable refs at all — is
    a Schedule of Rates, so the live path is what an ambiguous package falls back to, never the
    new one.

    The counts come back with the verdict rather than staying inside the helper: a package that
    carries BOTH forms is a real document problem, and the caller surfaces it (see
    :func:`annotate_sections`) instead of resolving it silently by majority vote."""
    n_bill = n_letter = 0
    for it in items:
        ref = getattr(it, "item_ref", "") or ""
        if bill_of(ref):
            n_bill += 1
        elif section_of(ref):
            n_letter += 1
    family = "bq" if (n_bill >= _BILL_MIN_REFS and n_bill > n_letter) else "sor"
    return family, n_bill, n_letter


# Valid SoR section codes: single letters A–Z, the two-letter BA–BF range the real schedules use,
# plus any code that actually appears as a ``SECTION X :`` header in the document (so a genuine
# ``SECTION HS`` header, should one ever exist, legitimises HS). Scanned-OCR corruptions — a digit
# read as a letter (``H5`` -> ``HS``) or a dropped leading letter (``H1(a)`` -> ``1(a)`` -> "") —
# are snapped back onto this set so one real section stops fragmenting into several.
_LETTERS = frozenset(chr(c) for c in range(ord("A"), ord("Z") + 1))
_TWO_LETTER_SECTIONS = frozenset({"BA", "BB", "BC", "BD", "BE", "BF"})
# The bill equivalent: 1 … 99. Bounded because a bill number is a small positive integer, not a
# year — the same bound `_BILL_REF_RE` applies, restated so a code from a Bill HEADER is checked too.
_BILL_CODES = frozenset(str(n) for n in range(1, _MAX_BILL + 1))


def _valid_section_codes(titles: dict[str, str], family: str = "sor") -> frozenset[str]:
    """The codes a section may resolve to. The ``"sor"`` default is the original letter set —
    untouched, and the letters are NOT widened for bills."""
    base = _BILL_CODES if family == "bq" else (_LETTERS | _TWO_LETTER_SECTIONS)
    return base | frozenset(titles)


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


def _resolve_code(item_ref: str, valid: frozenset[str], family: str) -> Optional[str]:
    """One item's section code before fill-forward, per family.

    SoR: the leading letters, prefix-snapped onto ``valid`` (``HS`` -> ``H``).

    BQ: the leading bill number, checked against ``valid`` and **never snapped**. A bill number
    has no prefix structure, so snapping ``24`` to its longest valid prefix would resolve it to
    bill ``2`` — silently moving bill 24's items into bill 2, which fill-forward would then spread
    down the rest of the bill. An unrecognised bill number resolves to ``None`` and inherits the
    running one, which is the honest answer."""
    if family == "bq":
        code = bill_of(item_ref)
        return code if code in valid else None
    return _snap_section(section_of(item_ref), valid)


def _normalise_sections(items: list, valid: frozenset[str], family: str = "sor") -> list[str]:
    """The corrected section code for each item, walking the package IN ORDER: a resolved code
    sets the running section; an unresolvable one (empty, or corrupt) inherits the running section
    (fill-forward). A leading run before any section resolves is back-filled from the first section
    that does. Fill-forward is family-INDEPENDENT and deliberately so: an item whose reference the
    extractor could not read belongs to the bill or section it sits inside, in either family.
    Deterministic — no LLM, and never an invented section: an all-unresolvable package keeps ''."""
    running = ""
    codes: list[str] = []
    for it in items:
        snapped = _resolve_code(getattr(it, "item_ref", ""), valid, family)
        if snapped:
            running = snapped
        codes.append(snapped or running)
    first = next((c for c in codes if c), "")
    return [c or first for c in codes] if first else codes


# A table-of-contents dot leader with its page number: "Photos ..................... 14". A
# contents page's SECTION lines match the header pattern, appear BEFORE the real headers, and
# first-occurrence-wins — so the artifact became the section's TITLE, and one routing card shipped
# as "Field Installations · Photos ……… 14" (seen on screen in the walkthrough). The words before
# the leader are the same words the real header carries, so stripping the leader keeps the title
# and loses the page number.
_TOC_LEADER_RE = re.compile(r"(?:\s*\.){3,}\s*\d{1,4}\s*$")


def _headers(pattern: re.Pattern, text: str) -> dict[str, str]:
    """``{code: title}`` for one header pattern over ``text`` — first occurrence of a code wins.

    A CARRIED-FORWARD line is not a title. `Bill No. 2 - Total Carried to Grand Summary` matches the
    header shape exactly, and on CEDD ND/2025/04 — whose real bill headers are a bare `Bill No. 2`
    with no title at all — it was the only line that DID match, so every bill was titled "Total
    Carried to Grand Summary". That title is what `spec_match` matches a specification against.

    A CONTENTS LINE is not a title either — see ``_TOC_LEADER_RE`` above.
    """
    from pipeline.stage_01_ingest.doc_index import _BILL_COLLECTION  # one owner for the phrase list

    titles: dict[str, str] = {}
    for m in pattern.finditer(text or ""):
        code, title = m.group(1).upper(), m.group(2).strip()
        title = _TOC_LEADER_RE.sub("", title).rstrip()
        if code and title and code not in titles and not _BILL_COLLECTION.search(title):
            titles[code] = title
    return titles


def _section_titles(text: str) -> dict[str, str]:
    """Map each section code to the title from its header (first occurrence wins).

    Both header forms are read. Where a code is declared by BOTH — only possible numerically, and
    only when a bill's preamble also cites a spec section — the BILL header wins: in a Bill of
    Quantities a ``SECTION 24 :`` line is a cross-reference to the specification, not a section of
    this document. A Schedule of Rates carries no Bill headers, so its titles are unchanged.

    "The bill header wins" HAS TO HOLD WHEN THE HEADER CARRIES NO TITLE, which is the real pack's
    shape. Overriding only where a bill header supplies a title left the cross-reference standing:
    Bill 3 is *Laboratory Testing* and names SMM 3, so it was titled **Site Clearance** — and that
    title is what ``spec_match`` matches a specification against. A number a bill has claimed is the
    bill's, titled or not; a ``SECTION n`` line inside it is pointing somewhere else."""
    titles = _headers(_SECTION_HEADER_RE, text)
    claimed = {m.group(1).upper() for m in _BILL_HEADER_RE.finditer(text or "")}
    if claimed:
        titles = {code: title for code, title in titles.items() if code not in claimed}
    titles.update(_headers(_BILL_HEADER_RE, text))
    return titles


def annotate_sections(
    scope: ScopePackages, doc_text: str = "",
    on_note: Optional[Callable[[str], None]] = None,
) -> ScopePackages:
    """Set each item's ``section`` (from its ref) and each package's ``sections`` metadata
    (code, header title if seen, item_count) — the routable unit made visible. Deterministic;
    a single-section package (every demo package) simply carries one section.

    The reference family is decided PER PACKAGE, from that package's own references (see
    :func:`section_family`), because one tender can carry both a Schedule of Rates and a Bill of
    Quantities. ``on_note`` receives a line for a package that mixes the two forms — a visible
    decision rather than a majority vote hidden in a helper."""
    titles = _section_titles(doc_text)
    packages: list[TradeWorkPackage] = []
    for pkg in scope.packages:
        family, n_bill, n_letter = section_family(pkg.sor_items)
        if on_note and n_bill and n_letter:
            kept, other = ("bill", "schedule") if family == "bq" else ("schedule", "bill")
            on_note(
                f"package {pkg.trade!r} mixes reference forms — {n_bill} bill-style "
                f"(<bill>.<item>) and {n_letter} schedule-style (letter-prefixed); read as the "
                f"{kept} family, so the {other}-style refs inherit the surrounding section rather "
                "than opening one of their own"
            )
        valid = _valid_section_codes(titles, family)
        # Repair each item's section code deterministically (snap OCR corruptions onto the valid
        # set, fill-forward a lost code) so one real section stops fragmenting into H / HS / '';
        # then roll up the section metadata from the CORRECTED codes.
        codes = _normalise_sections(pkg.sor_items, valid, family)
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


# ---------------------------------------------------------------------------
# The heading chain — an item's real description
# ---------------------------------------------------------------------------
# A bill's item cell rarely says what the item IS. Bill 6 of CEDD ND/2025/04:
#
#   column B   Instrument Installation        <- heading
#   column C     6.1  Standpipe
#   column B   Recording                      <- heading
#   column C     6.4  Standpipe
#
# 6.1 is INSTALLING a standpipe; 6.4 is RECORDING from one. Different work, different rate, and
# as extracted they were the same string. Bill 5 goes three deep: REPORT WORK -> Draft final
# report -> "laboratory tests". The chain above an item IS its description; the leaf alone is not.
#
# In the workbook that chain is which column the text sits in. In the PDF render it is leading
# whitespace — which only exists once the text is read in reading order, which is why this could
# not be built before `pdfops.page_text` started sorting.
#
# Everything below is DETERMINISTIC. The model never writes a chain, and a chain is never
# invented: where the indentation does not establish one, the item keeps its leaf text and says
# no heading was found.

# Lines that are structure, not content: the page markers page_text emits and the `=== label ===`
# block headers the ingest callers wrap each document in.
_SKIP_LINE = re.compile(r"^\s*(?:\[page \d+\]|={3,}.*={3,})\s*$")
# A heading is prose. These are the things at a heading's indent that are NOT one: a bare number,
# a currency/quantity cell, a unit, a rule of dashes, a carried-forward footer.
_NOT_HEADING = re.compile(
    r"^(?:[\d\s.,:;/()%$-]+|[A-Za-z]{1,3}|(?:carried|brought)\s+(?:to|from)\b.*|page\s+\d+.*)$",
    re.I,
)
_MAX_HEADING_CHARS = 90
_MAX_CHAIN_DEPTH = 4


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


# A schedule reference opens with one or two letters and then a DIGIT — `A1a(a)`, `E10(l)`,
# `BB7a`, `M-01`, `H1`. The digit is the whole point: `section_of` reads leading letters off a
# value already known to BE an item_ref, so as a line classifier it answers "yes" to every word
# in the document — `Instrument Installation` came back as section `INSTRUMENT` and every heading
# was read as an item. Bill references are left to `bill_of`, which is already strict.
_SOR_REF_HEAD = re.compile(r"^[A-Za-z]{1,2}-?\d")


def _leading_ref(line: str) -> str:
    """The item reference a line opens with, in EITHER family, or ``''`` when the line is prose."""
    token = line.strip().split(None, 1)
    if not token:
        return ""
    head = token[0].rstrip(".:)|")
    return head if (bill_of(head) or _SOR_REF_HEAD.match(head)) else ""


def _is_heading(text: str) -> bool:
    body = text.strip()
    if not body or len(body) > _MAX_HEADING_CHARS:
        return False
    if _NOT_HEADING.match(body):
        return False
    return sum(c.isalpha() for c in body) >= 2


_PAGE_MARKER = re.compile(r"^\s*\[page (\d+)\]\s*$")


def running_furniture(doc_text: str) -> set[str]:
    """Heading-shaped lines that appear on EVERY page — the running header, not the structure.

    A CEDD bill repeats its project title at the left margin on every page, above a repeated
    column-header row. Both are prose with plenty of letters, so ``_NOT_HEADING`` (which catches
    bare numbers, units, ``page N…`` and carried-forward footers) and ``_SKIP_LINE`` (which catches
    ``[page N]`` markers) both pass them — verified. NO CONTENT RULE CAN SEPARATE
    "Ground Investigation Works … (Phase 2)" from a genuine heading. The only signal is repetition.

    The harm is not that the title occupies a slot in the chain; it is that the title, sitting
    SHALLOWER than the section header, closes it on every page under the rule below. So
    ``SECTION 2 - GROUND INVESTIGATION`` and its subheading survived only for items on a section's
    first page, and every item after the page break carried page furniture where its scope should
    be — in a bill, where an item's real description IS its ancestor path, that is the description.

    THE RULE IS "ON EVERY PAGE", NOT "ON MORE THAN ONE". The obvious rule — a line that repeats
    across pages is furniture — would wrongly drop a genuine heading continued over a page break,
    which is the one thing that must not happen here. "Every page" cannot: a heading spans the pages
    of its own section, not the whole document.

    And where a line genuinely does appear on every page, dropping it loses nothing that
    DISCRIMINATES: every item in the document would carry it, so it separates no item from any
    other. That is what makes this safe rather than merely conservative.

    Needs at least two pages — in a single-page document every line is on "every page", and there
    is no page break for a heading to be lost across.
    """
    pages: list[set[str]] = []
    for raw in (doc_text or "").splitlines():
        if _PAGE_MARKER.match(raw):
            pages.append(set())
            continue
        body = raw.strip()
        if not body or _SKIP_LINE.match(raw) or _leading_ref(raw) or not _is_heading(body):
            continue
        if pages:
            pages[-1].add(body)
    if len(pages) < 2:
        return set()
    return set.intersection(*pages)


def heading_chains(doc_text: str) -> dict[str, list[str]]:
    """``item_ref -> the chain of headings above it``, read from indentation.

    One pass, one stack. A line with no item reference, sitting at a SHALLOWER indent than the
    items that follow it, is their heading; a new line at or left of a stacked heading's indent
    closes it. An item's chain is every open heading strictly shallower than the item itself —
    so an item at the same indent as the text above it inherits nothing, which is the honest
    answer rather than a guess.

    Running furniture is neither pushed nor allowed to close anything — see
    :func:`running_furniture`. Without that, a repeated left-margin page title destroyed the
    section heading at every page break.

    First occurrence wins, matching ``_section_titles``: a ref repeated in a running header or a
    collection page must not overwrite the chain from where the item was actually priced.
    """
    chains: dict[str, list[str]] = {}
    furniture = running_furniture(doc_text)
    stack: list[tuple[int, str]] = []   # (indent, heading text), outermost first
    for raw in (doc_text or "").splitlines():
        if not raw.strip() or _SKIP_LINE.match(raw):
            continue
        if raw.strip() in furniture:
            continue  # a running header closes nothing — it is not structure
        indent = _indent_of(raw)
        ref = _leading_ref(raw)
        if ref:
            if ref not in chains:
                chains[ref] = [text for depth, text in stack if depth < indent][-_MAX_CHAIN_DEPTH:]
            continue
        body = raw.strip()
        if not _is_heading(body):
            continue
        # A heading closes every open heading at or right of its own column.
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, body))
    return chains


def attach_heading_chains(
    scope: ScopePackages, doc_text: str,
    on_note: Optional[Callable[[str], None]] = None,
) -> ScopePackages:
    """Stamp each item's ``heading_path`` from the document's own indentation.

    The leaf ``description`` is left exactly as extracted — the chain is ADDITIONAL, never a
    replacement, so nothing downstream that reads a description loses what it had. An item the
    indentation says nothing about keeps an empty chain, and the count of those is reported
    rather than hidden: a package where no item found a heading usually means the render lost
    its reading order, which is a fact about the document worth seeing.
    """
    chains = heading_chains(doc_text)
    # `any(values)`, not `chains` — a document whose every item sits at the left margin produces
    # an entry per item and a chain for none of them. That is a FLAT document, not a package that
    # missed the structure, and reporting it would put a note on every schedule that has never had
    # indentation to lose.
    if not any(chains.values()):
        return scope
    packages: list[TradeWorkPackage] = []
    for pkg in scope.packages:
        items = []
        found = 0
        for it in pkg.sor_items:
            chain = chains.get((it.item_ref or "").strip(), [])
            if chain:
                found += 1
            items.append(it if list(it.heading_path) == chain else it.model_copy(update={"heading_path": chain}))
        if on_note and items and not found:
            on_note(
                f"package {pkg.trade!r}: no heading chain was found for any of its {len(items)} "
                "items, so each carries only the text in its own cell — two items that differ "
                "only by the heading above them will read identically"
            )
        packages.append(pkg.model_copy(update={"sor_items": items}))
    return scope.model_copy(update={"packages": packages})


_RECOVER_MAIN = re.compile(r"^\s*(?:Item:\s*)?([A-Z]{1,2}\d+)\b[)\.|:\s]*(.*)$")
_RECOVER_SUB = re.compile(r"^\s*(?:Item:\s*)?\(([a-z]{1,4})\)\s*[)\.|:\s]*(.*)$")
_ROMAN = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"})

# --- the same backstop for the OTHER reference family --------------------------------------------
# `_RECOVER_MAIN` requires ONE OR TWO LETTERS then digits, so it matches `G7` and `BB12` and
# nothing else. A Bill of Quantities numbers its items `1.17`, `2.24`, `7.2` — no letters anywhere
# — so `_ocr_item_inventory` returns {} for a bill, `recover_dropped_sor_items` exits on its
# `if not inv` line, and the completeness backstop that exists for a Schedule of Rates has never
# once run on a bill. `report_sequence_gaps` then NAMES the missing rows and nothing puts them back.
#
# That is the whole of the loss observed on CEDD ND/2025/04: bill 2 without 2.2, bill 7 without
# 7.2, bill 1 opening at 1.12. The rows are in the extracted text — they are dropped by the model
# on the chunk that carried them, which is precisely the failure this backstop was built for.
_BQ_REF_LINE = re.compile(r"^(\d{1,2}\s*[.\-/]\s*\d{1,3}[a-z]?)\b[)\.|:\s]*(.*)$", re.I)

# Page furniture, and the one shape that would otherwise recover an item out of its own footer:
# `1.12 to 1.18 carried to collection` opens with a real reference and is not a priced row.
_BQ_NOT_AN_ITEM = re.compile(
    r"^\s*(?:"
    r"(?:to\s+[\d.]+\s+)?(?:carried|brought)\s+(?:to|forward|down|from)\b"
    r"|collection\b|summary\b|total\b|sub[-\s]?total\b"
    r"|bill\s*(?:no\.?)?\s*\d"
    r"|item\s*(?:no\.?|description)\b"
    r"|page\b"
    r")",
    re.I,
)


def _bq_item_inventory(doc_text: str, bills: set) -> "dict[str, str]":
    """``item_ref -> description`` for every BILL row that leads a line, restricted to ``bills``.

    The restriction is the precision guard, and it is deliberately strict: only a bill the
    extraction ALREADY established is scanned for. A stray ``2.2`` in a document that produced no
    bill-2 items is a clause reference, a date fragment or a page number, and inventing an item
    from it would be exactly the phantom-item failure the gate upstream exists to prevent. The
    cost is that a bill dropped whole is not recovered — but nothing can see that hole from the
    inside either, and a warning nobody can act on is how a real signal gets ignored.

    First occurrence wins, matching ``heading_chains`` and ``_section_titles``: a reference
    repeated in a running header must not overwrite the row where the item was actually priced.
    """
    inv: dict[str, str] = {}
    if not bills:
        return inv
    for raw in (doc_text or "").splitlines():
        line = raw.strip()
        if not line or line[:1] == "=" or _SKIP_LINE.match(raw) or _BQ_NOT_AN_ITEM.match(line):
            continue
        m = _BQ_REF_LINE.match(line)
        if not m:
            continue
        ref = re.sub(r"\s+", "", m.group(1))
        if bill_of(ref) not in bills:
            continue
        rest = m.group(2).strip()
        # A row needs a description. `1.12   250.00   1,830.00` is the amount columns of a row
        # whose text sits elsewhere on the page, and `1.12 .......... 14` is a contents line.
        if sum(c.isalpha() for c in rest) < 2 or _BQ_NOT_AN_ITEM.match(rest):
            continue
        inv.setdefault(ref, rest[:80])
    return inv


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
    empty/absent ``doc_text`` (DEMO) is a no-op.

    BOTH reference families are covered. The letter family (``G7``) is the original; the bill
    family (``2.24``) was blind until a real bill lost rows to it — see ``_bq_item_inventory``.
    Each is read by its own reader and homed by its own key, so neither can see the other's refs
    and the Schedule-of-Rates path is byte-for-byte what it was."""
    have = {_norm_ref(it.item_ref) for p in scope.packages for it in p.sor_items}
    bills = {b for b in (bill_of(it.item_ref or "")
                         for p in scope.packages for it in p.sor_items) if b}
    inv = _ocr_item_inventory(doc_text)
    bq_inv = _bq_item_inventory(doc_text, bills)
    if not inv and not bq_inv:
        return scope
    missing = [(code, desc) for code, desc in inv.items() if _norm_ref(code) not in have]
    bq_missing = [(code, desc) for code, desc in bq_inv.items() if _norm_ref(code) not in have]
    if not missing and not bq_missing:
        return scope
    packages = [p.model_copy(update={"sor_items": list(p.sor_items)}) for p in scope.packages]

    def _home_by(key, value):
        best, best_n = None, -1
        for p in packages:
            n = sum(1 for it in p.sor_items if key(it.item_ref) == value)
            if n > best_n:
                best, best_n = p, n
        return best

    recovered: list[str] = []
    for code, desc in missing:
        sec = section_of(code)
        if not sec:
            continue
        home = _home_by(section_of, sec) or (packages[0] if packages else None)
        if home is None:
            continue
        home.sor_items.append(SorItem(item_ref=code, description=(desc or None), section=sec))
        recovered.append(code)
    for code, desc in bq_missing:
        bill = bill_of(code)
        # THE BILL IS THE SECTION (see the two-families note above), so a recovered row lands in
        # the package that owns most of its bill and carries that bill as its section — the same
        # answer `annotate_sections` would give it, reached without a second read.
        home = _home_by(bill_of, bill) or (packages[0] if packages else None)
        if home is None:
            continue
        home.sor_items.append(SorItem(item_ref=code, description=(desc or None), section=bill))
        recovered.append(code)
    if recovered:
        print(f"[ingest] recovered {len(recovered)} SoR rows the extractor dropped "
              f"(from OCR): {', '.join(recovered[:30])}{' …' if len(recovered) > 30 else ''}")
    return scope.model_copy(update={"packages": packages})


# ---------------------------------------------------------------------------
# Count fidelity — say so when items are missing
# ---------------------------------------------------------------------------
# The first live bill returned 136 of 162 items and said nothing. Silently returning 136 of 162
# is the worst outcome available: a priced return built on it is wrong in a way nobody can see.
#
# Detection is cheap where recovery is not. Within one bill the item numbers are a SEQUENCE, so
# `2.24` present with `2.25` and `2.26` absent is a hole that arithmetic can find with no model,
# no OCR and no second read of the document. This does not recover the missing rows — it refuses
# to let them go unmentioned, which is the part that was missing.
_MAX_REPORTED_GAP = 40   # a "gap" larger than this is a different bill, not a dropped row

_TAIL_NUM = re.compile(r"^\d{1,2}\s*[.\-/]\s*(\d+)$")


def _bill_item_number(ref: str) -> Optional[int]:
    """The item number within its bill (``2.24`` -> 24), or ``None`` for a non-bill ref."""
    m = _TAIL_NUM.match((ref or "").strip())
    return int(m.group(1)) if m else None


def sequence_gaps(scope: ScopePackages) -> dict[str, list[int]]:
    """``"<bill>" -> the item numbers missing from its run``, per bill, across the whole scope.

    Only the interior is reported. A bill whose numbering starts at 3 may simply begin there, and
    a bill's last item is unknowable from the inside — inventing either end would produce a
    warning nobody can act on, which is how a real signal gets ignored.
    """
    seen: dict[str, set[int]] = {}
    for pkg in scope.packages:
        for it in pkg.sor_items:
            bill = bill_of(it.item_ref or "")
            n = _bill_item_number(it.item_ref or "")
            if bill and n is not None:
                seen.setdefault(bill, set()).add(n)
    gaps: dict[str, list[int]] = {}
    for bill, numbers in seen.items():
        lo, hi = min(numbers), max(numbers)
        missing = [n for n in range(lo, hi + 1) if n not in numbers]
        # THE CAP IS ON A GAP, WHICH IS WHAT ITS OWN COMMENT ALWAYS SAID. It was applied to the
        # bill's whole SPAN (`hi - lo`), so any bill numbered past ~40 had its ENTIRE completeness
        # report suppressed — and a real bill is exactly that. On ND/2025/04 Bill 1 runs past item
        # 53 and its only missing row is item 53, so the one mechanism that reports dropped bill
        # rows was switched off on the one bill that had a gap. A guard that cannot match its input
        # is not a guard.
        #
        # A long RUN of consecutive missing numbers still means the numbering is not contiguous
        # (a different bill's block, a sub-numbered range) rather than dropped rows, so runs longer
        # than the cap are dropped and the shorter ones — the actual signal — are kept.
        kept = [n for run in _consecutive_runs(missing) if len(run) <= _MAX_REPORTED_GAP for n in run]
        if kept:
            gaps[bill] = kept
    return gaps


def _consecutive_runs(numbers: list[int]) -> list[list[int]]:
    """``[1, 2, 5, 9, 10]`` -> ``[[1, 2], [5], [9, 10]]``. Sorted input assumed."""
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


def report_sequence_gaps(
    scope: ScopePackages, on_note: Optional[Callable[[str], None]] = None,
) -> dict[str, list[int]]:
    """Report every interior hole in a bill's numbering. Returns them too, so a caller that wants
    to put them on a response rather than in a log can."""
    gaps = sequence_gaps(scope)
    if on_note:
        for bill in sorted(gaps, key=lambda b: int(b)):
            missing = gaps[bill]
            shown = ", ".join(f"{bill}.{n}" for n in missing[:12])
            more = f" and {len(missing) - 12} more" if len(missing) > 12 else ""
            on_note(
                f"bill {bill}: {len(missing)} item(s) are missing from the middle of its "
                f"numbering — {shown}{more}. They were priced in the document and did not come "
                "out of the extraction; this split is INCOMPLETE for that bill."
            )
    return gaps


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


def _split_on_bill_headers(text: str) -> list[str]:
    """Split at every line that OPENS a bill, keeping each header with its rows.

    Line-level and on the shared rule rather than `_split_on(text, _BILL_RE)`, because `_BILL_RE`
    cannot tell `Bill No. 9` from `Bill No. 9 - Total Carried to Grand Summary`. Splitting on the
    regex started a new block at every collection footer, so each bill produced a phantom trailing
    block named after the line that CLOSES it. On the shared rule the footer stays where it belongs
    — inside its own bill, as that bill's last line.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if _bill_number_of(line)]
    if not starts:
        return [text]
    bounds = ([0] if starts[0] > 0 else []) + starts
    blocks = ["".join(lines[a:b]) for a, b in zip(bounds, bounds[1:] + [len(lines)])]
    return [b for b in blocks if b.strip()]


def _bill_number_of(line: str) -> Optional[str]:
    """The bill this line OPENS, via the one shared rule (a collection footer opens nothing)."""
    from pipeline.stage_01_ingest.doc_index import bill_header_number

    return bill_header_number(line)


def declares_bills(text: str) -> bool:
    """True when ``text`` OPENS at least two bills — a Bill of Quantities, not a Schedule of Rates.

    Decided with :func:`doc_index.bill_header_number`, the one rule that tells a bill header from
    the collection footer that closes one, so a family cannot be decided two different ways in two
    places. A single bill is not enough: one `Bill No. 3` line in prose is a cross-reference, and
    the same threshold the boundary regexes use keeps it out.
    """
    from pipeline.stage_01_ingest.doc_index import bill_header_number

    seen = {n for n in (bill_header_number(ln) for ln in (text or "").splitlines()) if n}
    return len(seen) >= 2


def _split_into_blocks(text: str) -> list[str]:
    """Chunk on the boundary of the family this document actually belongs to.

    **A BILL OF QUANTITIES WAS CHUNKED ON ITS SPECIFICATION CROSS-REFERENCES.** Section was tried
    unconditionally first, on the stated belief that "a Bill of Quantities has no Section headers
    to find". It has dozens: this issuer prints `SECTION n : …` on EVERY bill page, naming the
    Standard Method of Measurement section the bill is measured under — the same line
    `doc_index.bill_mm_sections` reads as a cross-reference, ten for ten on the real pack. So the
    Bill branch never ran, and Bill 1's rows landed in a block headed `SECTION 3 : SITE CLEARANCE`.
    `_row_batches` then repeated that line as the header on every 30-row batch, handing the model a
    specification reference as each batch's context instead of `Bill No. 1`, and a failed batch was
    reported to the operator as "section 3 (SITE CLEARANCE)" — naming a document that contains none
    of the lost rows.

    The family is decided FIRST, the way `annotate_sections` and `section_family` already decide
    it: a `SECTION n` line inside a document that has said `Bill No. n` is pointing somewhere else.
    A Schedule of Rates declares no bills, so its path is byte-for-byte what it was.
    """
    if declares_bills(text):
        return _split_on_bill_headers(text)
    if len(_SECTION_RE.findall(text)) >= 2:
        return _split_on(text, _SECTION_RE)
    if len(_BILL_RE.findall(text)) >= 2:
        return _split_on(text, _BILL_RE)
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
    """True when a line is a Section/Part or Bill header (so it carries trade context, not an item
    row). Both callers use it to keep a header OUT of the row count and repeat it on each batch, so
    a bill's batches keep their bill context exactly as a schedule's keep their section."""
    return bool(_SECTION_RE.match(line or "") or _BILL_RE.match(line or ""))


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
    """A human name for a batch, for a per-section error message — the Section header if present.

    A batch that OPENS a bill is named by that bill, even though the bill's pages are covered in
    `SECTION n` measurement cross-references. Searching Section first told the operator a skipped
    batch was "section 3 (SITE CLEARANCE)" when the rows that went missing were Bill 1's — sending
    them to a specification that holds none of them.
    """
    for line in (text or "").splitlines():
        opened = _bill_number_of(line)
        if opened:
            b0 = _BILL_HEADER_RE.match(line)
            title = (b0.group(2).strip() if b0 else "")
            return f"bill {opened}" + (f" ({title})" if title else "")
        if line.strip():
            break  # only the batch's OWN leading header decides; a later line is a reference
    m = _SECTION_HEADER_RE.search(text or "")
    if m:
        title = m.group(2).strip()
        return f"section {m.group(1).upper()}" + (f" ({title})" if title else "")
    for line in (text or "").splitlines():
        # ...the shared rule again, so the fallback cannot name a batch after the collection footer
        # that CLOSES a bill rather than the header that opens one.
        opened = _bill_number_of(line)
        if opened:
            b = _BILL_HEADER_RE.match(line)
            title = (b.group(2).strip() if b else "")
            return f"bill {opened}" + (f" ({title})" if title else "")
    m2 = re.search(r"(?im)^\s*(?:section|part)\s+([A-Za-z0-9]+)", text or "")
    if m2:
        return f"section {m2.group(1).upper()}"
    b2 = re.search(r"(?im)^\s*bill\s*(?:no\.?|number)?\s*(\d{1,2})\b", text or "")
    if b2:
        return f"bill {b2.group(1)}"
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
    # An item's real description is the chain of headings above it, not the text in its own cell.
    # Deterministic, from the document's own indentation — see `heading_chains`.
    recovered = attach_heading_chains(recovered, doc_text, on_note=on_error)
    # Tag each item with its SoR section (or its BQ bill — the family is read per package from the
    # references themselves) and roll up the per-package section metadata (the routable unit).
    # doc_text supplies the header titles on the live path; demo has none. `on_error` carries the
    # mixed-family note; only this first call reports, because the second annotate below re-reads
    # the SAME references after consolidation and would say it twice.
    annotated = annotate_sections(recovered, doc_text, on_note=on_error)
    # Merge any section whose rows got scattered across trades back into one package (the section
    # is the routable unit), then refresh the per-package section metadata from the moved items.
    consolidated = consolidate_fragmented_sections(annotated)
    final = annotate_sections(consolidated, doc_text)
    # Last, on the finished scope: an interior hole in a bill's numbering means rows were priced
    # in the document and did not come out. Reported, never silently accepted.
    report_sequence_gaps(final, on_note=on_error)
    return final
