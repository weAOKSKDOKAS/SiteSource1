"""Per-document index built at ingest (Layer 1, deterministic; pymupdf lazy-imported).

Beyond the trade routing that ``classify`` produces, the relevant-document assembler needs
structural facts about each uploaded original: its ``kind``, the spec section it self-declares
on page 1 (``SECTION 7 – GEOTECHNICAL WORKS`` / ``Appendix 7``), whether it carries a real
text layer, its page count, and — for a text-layer Particular Specification or appendix — a
``clause_index`` mapping each clause heading to the page it starts on. That index lets dispatch
slice a spec to only the clauses a firm's SoR section references, and fall back to whole-file
where the document is scanned or nothing resolves. Pure pymupdf + regex — no LLM, no network;
persisted with the run so dispatch can read it back.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from schemas.models import DocType, ScopePackages

_log = logging.getLogger(__name__)

# Page-1 self-declaration: "SECTION 7 – GEOTECHNICAL WORKS", "SECTION 26 - PRESERVATION …".
# The dash/colon separator is optional (a scanned header may drop the en-dash glyph); the
# title must start with a letter so a bare "SECTION 7" heading does not match with no title.
_SECTION_DECL = re.compile(r"SECTION\s+(\d+)\s*[–—:.\-]?\s*([A-Za-z][^\n]{1,79})", re.I)
# A COVER TITLE SET ON MORE THAN ONE LINE. `_SECTION_DECL`'s title group is `[^\n]`, so it stops at
# the first line break — and on CEDD ND/2025/04 that silently truncated three of the eleven
# specification titles at exactly the point the typesetter wrapped them:
#
#     SECTION 28 / Environmental Ground / Investigation  ->  "Environmental Ground"
#     SECTION 26 / Preservation and / Protection of Trees ->  "Preservation and"
#     SECTION 30 / Management / of Subcontractors         ->  "Management"
#
# A truncated title is worse than no title: it still matches, just against the wrong subject. "Site
# Safety Management" found "Management" and proposed the subcontractor-management section.
#
# The continuation is read CONSERVATIVELY, because a wrong title is worse than a short one. A line
# joins only if it still looks like part of a cover heading: short, no digits (a clause id or a page
# number ends a heading), starting with a letter, and not a phrase that is page furniture rather
# than the title. At most two lines, and the whole thing stays inside `_SECTION_DECL`'s own 80-char
# bound. Anything else — a blank line, body prose, `7.01 General` — stops the read.
_TITLE_MAX = 80
_TITLE_CONTINUATION_LINES = 2
_TITLE_MAX_WORDS = 6
# Lines that follow a cover title on a real pack but are NOT part of it. Written down here for the
# same reason `spec_match._GENERIC_WORDS` is: it is a judgement about documents, and it should be
# readable and arguable rather than buried in a regex.
_TITLE_FURNITURE = re.compile(
    r"^(?:particular|general)\s+(?:specification|preamble)s?$|^contract\s+no|^table\s+of\s+contents$"
    r"|^schedule\s+of\s+rates$|^bill\s+of\s+quantities$|^page\b|^rev(?:ision)?\b", re.I)
# THE CONSULTANT'S NAME, matched on the COMPANY FORM rather than on any particular firm.
# `SMM_S01-0.pdf`'s page-1 header block reads `Particular Preambles / Section 1 /
# AECOM-AtkinsRealis JV / - 1a -`, and the declaration in that block took the line below it as its
# title. A section title does not end in `JV`, `Ltd` or `& Partners`.
#
# Anchored at the END and applied with `search`, not `match`: the firm's own name comes first and is
# unbounded, so only the suffix is recognisable. This is the ONE-PAGE backstop — on a document with
# more than one page the consultant line repeats and `running_lines` catches it without a list.
_TITLE_ORG_SUFFIX = re.compile(
    r"(?:^|\s)(?:jv|ltd\.?|limited|llp|plc|inc\.?|n\.?v\.?)$|joint\s+venture$"
    r"|&\s+partners$|consult\w*\s+engineers$|\bpartnership$", re.I)
# AN AMENDMENT LEAD-IN IS NOT A DECLARATION. Page 1 of `GP&PP/…-SMM_S28-0.pdf` reads:
#
#     Particular Preambles / Section 28
#     Add the following new section after Section 27 :
#     SECTION 28
#     SITE SAFETY MANAGEMENT
#
# `_SECTION_DECL` matched the LEAD-IN — "…after Section 27 :" — and its trailing colon plus the
# next line made it look like a declaration with a title, so the document was indexed as section
# **27** titled "SECTION 28". Extraction order decides which match is leftmost, so this is not
# reliably visible: printed order gives 28 with a nonsense title; the order pymupdf actually
# produced gives 27. Bill 9 then asked for MM 28, found none, and the gate truthfully reported a
# missing document that was sitting in the pack under the wrong number.
#
# The distinction: A DECLARATION NAMES THIS DOCUMENT; A LEAD-IN NAMES ANOTHER SECTION AS A POSITION.
# The verb gives it away ("Add", "Replace", "Delete", "in lieu of") and so does the positional word
# in front of the number ("after Section 27", "following Section 30"). When both appear on a page,
# the document's own name wins.
_AMENDMENT_VERB = re.compile(
    r"\b(?:add|adds|added|insert\w*|replac\w*|delet\w*|substitut\w*|amend\w*|omit\w*|"
    r"supersed\w*)\b|\bin\s+lieu\s+of\b", re.I)
# Positional words, checked ONLY on the text preceding the number on its own line. A number reached
# through one of these is a place in another document, never this document's own identity.
_AMENDMENT_POSITION = re.compile(r"\b(?:after|before|following|preceding|under|to)\b|\bin\s+lieu\s+of\b", re.I)
_APPENDIX_DECL = re.compile(r"\bAppendix\s+(\d+(?:\.\d+)*)", re.I)
# An appendix COVER declares a BARE "Appendix N" (not a dotted sub-reference): "Appendix 7",
# "APPENDIX 7.pdf". The negative lookahead ``(?!\.\d)`` excludes an INLINE cross-reference like
# "Appendix 7.4.16", so a Particular Specification that merely cites an appendix is not mistaken for
# one. Used only to DECIDE kind (``_kind_for``); section extraction still uses ``_APPENDIX_DECL``.
_APPENDIX_COVER = re.compile(r"\bAppendix\s+(\d+)(?!\.\d)", re.I)
# A section number declared in the FILENAME. A fallback when a PS's page 1 lost its "SECTION n"
# header (a scanned cover, or a file that starts mid-section) so the clause index can still scope.
#
# TWO conventions, because a real issuer uses the second and the first could never match it:
#
# * ``PS-S07`` / ``GS-S26`` — "S" then the section digits. What this pattern was written for.
# * ``I-ND_2025_04-S_PS28-0.pdf`` — the section digits attached to ``PS``/``GS`` directly. CEDD
#   ND/2025/04 names every specification this way, and the old pattern matched NONE of them: in
#   ``S_PS28`` the lone ``S`` is followed by ``_``, and ``PS28``'s ``S`` is preceded by a letter.
#   So every PS on that pack resolved to an empty ``spec_section_number`` and was skipped, silently,
#   by ``relevant_docs``' PS branch — PS28 never reached an enquiry.
#
# ``PSA7.12`` is an APPENDIX to PS7, not PS7, and must not be claimed as one. Two guards keep them
# apart: the digits must follow ``PS``/``GS`` IMMEDIATELY (the ``A`` in ``PSA`` breaks the match),
# and a dotted continuation is rejected (``(?!\.\d)``), so ``PS7.12`` is not read as section 7
# either. ``S07.pdf`` still matches — the lookahead rejects only a dot followed by a DIGIT.
_FILENAME_SECTION = re.compile(r"(?:^|[^A-Za-z])(?:[PG]?S)0*(\d+)(?!\.\d)", re.I)
# THE APPENDIX FORM OF THE SAME CONVENTION: `PSA7.12` is Appendix 7.12 — an appendix TO section 7,
# not section 7. The `A` is the issuer's own marker and it is the only thing distinguishing the two
# names, which is why `_FILENAME_SECTION` refuses it and this pattern claims it.
#
# Group 1 is the SECTION the appendix belongs to (7), because that is what the appendix branch
# matches against `cited_appendices` — an appendix's section is legitimately its parent's.
_FILENAME_APPENDIX = re.compile(r"(?:^|[^A-Za-z])(?:PS|GS)A0*(\d+)", re.I)
# The SAME convention, but committing to WHICH specification. `_FILENAME_SECTION`'s `[PG]?S` is
# deliberately loose because it only has to recover a number; these two have to decide a KIND, and
# calling a General Specification section a Particular one would send the wrong document.
#
# They exist for the reissue case: `TA #1/S/PS/PS25/I-ND_2025_04-S_PS25-1.pdf` is Particular
# Specification section 25 at revision 1, filed under the addendum that issued it. The folder said
# "addendum" and won, so the document never met the `-0` it supersedes. A folder is not an identity
# — the same lesson `_own_name` records, and the reason both of these read the basename.
_FILENAME_PS_SECTION = re.compile(r"(?:^|[^A-Za-z])PS0*(\d+)(?!\.\d)", re.I)
_FILENAME_GS_SECTION = re.compile(r"(?:^|[^A-Za-z])GS0*(\d+)(?!\.\d)", re.I)


def _own_name(filename: str) -> str:
    """The file's OWN name, without the folders it was filed under.

    Every filename pattern here reads this, never the full path. On the real pack a Particular
    Specification appendix lives at `S/PS/PS7/I-ND_2025_04-S_PSA7.12-0.pdf`, and matching over the
    whole path found `PS7` IN THE FOLDER — so the appendix was handed
    `spec_section_number = "7"` and claimed to BE the section it merely belongs to. A document's
    identity must not depend on where somebody filed it.
    """
    return (filename or "").replace("\\", "/").rsplit("/", 1)[-1]


_GENERAL_SPEC = re.compile(r"General\s+Specification", re.I)
# The Particular Specification's own TABLE OF CONTENTS — `I-ND_2025_04-S_PS_Index-0.pdf`. It is not
# a specification section and must not be treated as one: `_FILENAME_SECTION` correctly finds no
# number in that basename, and a PS with no number is reported as unidentifiable, so before this the
# index raised that false alarm on every run of the pack.
#
# It is also the only place the pack states each PS section's TITLE. The sections themselves declare
# none on page 1 — which is why the filename fallback exists — so this document is the specification
# side of any title match.
_PS_INDEX_NAME = re.compile(r"(?:^|[^A-Za-z])PS[_\s-]?Index(?![A-Za-z])", re.I)
_PS_INDEX_PAGE1 = re.compile(r"Particular\s+Specification", re.I)
_TABLE_OF_CONTENTS = re.compile(r"Table\s+of\s+Contents|^\s*INDEX\s*$", re.I | re.M)
# The header row that opens the list: `SECTION   TITLE`. ANCHORED ON, rather than scanning the whole
# document, so a clause reference elsewhere in the pack cannot be read as an entry.
_TOC_HEADER = re.compile(r"^\s*SECTION\s+TITLE\s*$", re.I)
# One entry: a section number, irregular whitespace, then the title. The real pack's spacing is
# ragged (`  1        General`, ` 26        Preservation…`), so the gap is `\s+` and never a column.
#
# The title group is OPTIONAL, and that is deliberate. A line the index printed as a bare number is
# a row whose title did not come out — exactly the case the caller must REPORT — and requiring a
# title here would have made it match nothing and be dropped in silence with the running header.
# `(?!\S)` keeps a clause id out: in `7.28  Rotary drilling` the digits are followed by a dot, so
# there is no row to read.
_TOC_ROW = re.compile(r"^\s*(\d{1,3})(?!\S)\s*(.*?)\s*$")
# The Standard Method of Measurement, recovered from page 1 or the filename.
#
# `_kind_for` could reach `method_of_measurement` only from an explicit DocType, so a bridge part
# — which arrives as GENERAL, or as PARTICULAR_SPECIFICATION when its category is `specifications`
# — could never become one. On ND/2025/04 the SMM ships in `GP&PP/` as `SMM_*` files categorised
# `specifications`, so without this they would index as PS and the preamble slice would never fire.
#
# DELIBERATELY NARROW: the full "Standard Method of Measurement" title, or a bare SMM token. A PS
# that merely CITES the method of measurement in its preamble says "Method of Measurement" without
# "Standard", and must not be stolen.
_METHOD_OF_MEASUREMENT = re.compile(r"Standard\s+Method\s+of\s+Measurement|(?:^|[^A-Za-z])SMM(?![A-Za-z])", re.I)
# A tender addendum / clarification, same reasoning: reachable only from DocType.TENDER_ADDENDUM
# before this. The archive files these under `TA #1` / `TA #2` and categorises them `other` — an
# addendum is a KIND, not a category — so the folder in the part's title is the signal.
_ADDENDUM = re.compile(r"Tender\s+Addendum|Addendum\s+No|(?:^|[^A-Za-z])TA\s*#?\s*\d", re.I)
# A Schedule-of-Rates section header — "SECTION A : PRELIMINARIES ITEMS", "SECTION BA : GENERAL".
# LETTER codes (A, BA), unlike the numeric PS/GS `_SECTION_DECL`; the separator + a title are
# required so a bare "SECTION A" mention is not taken as a header. Mirrors the stage-01 ingest
# chunker header (`ingest._SECTION_HEADER_RE`) so the SoR page ranges index on the SAME section
# codes dispatch routes by. Group 1 = code (upper-cased at collection), group 2 = title.
_SOR_SECTION_HEADER = re.compile(r"(?im)^\s*(?:section|part)\s+([A-Za-z0-9]+)\s*[:.\-]\s*(.+?)\s*$")
# The BILL-OF-QUANTITIES header form, beside the Section form rather than folded into it — the
# Schedule-of-Rates pattern above is live and must keep matching exactly what it matches today.
# `Bill No. 1 - General and Preliminaries`, `BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS`,
# `Bill No.3 Laboratory Testing` (no separator). Mirrors `ingest._BILL_HEADER_RE` for the same
# reason the Section forms mirror: the guard must check against the vocabulary the extractor
# assigns. Group 1 = bill number, group 2 = title.
#
# THE TITLE IS OPTIONAL, AND THAT IS THE WHOLE FIX. CEDD ND/2025/04's bill headers carry no title on
# the header line — they are a bare `Bill No. 2` — so with `(.+?)` required the ONLY line that
# matched was the collection footer at the END of each bill:
#
#     'Bill No. 2'                                    -> no match
#     'Bill No. 2 - Total Carried to Grand Summary '  -> MATCH
#
# Every bill therefore "opened" after its own pages had passed, and the next `SECTION n` line found
# belonged to the following bill: Bill 6 got SMM 24, Bill 7 got 29, Bill 8 got 28, and Bill 9 was
# dropped entirely. A systematic off-by-one, invisible wherever consecutive bills share a section —
# which bills 2 to 6 do, all naming SMM 2, and that is why a fixture never caught it.
# `[^\S\n]` — whitespace that is NOT a newline — everywhere, so the title cannot come from the line
# BELOW. Plain `\s*` crosses a line break, and on a title-less header `Bill No. 2\n  1.1 Some item`
# it made the first ITEM ROW the bill's title. That predates the optional group (the required
# `(.+?)` did it too); it is the same hazard `_SECTION_DECL` had, in the other direction.
_BILL_SECTION_HEADER = re.compile(
    r"(?im)^[^\S\n]*bill[^\S\n]*(?:no\.?|number)?[^\S\n]*(\d{1,2})\b"
    r"[^\S\n]*[:.\-–—]?[^\S\n]*(.*?)[^\S\n]*$")
# What distinguishes the header from the footer in the real text: the footer says what it is. A bare
# `Bill No. n` opens a bill; `Bill No. n - Total Carried to Grand Summary` closes one, and is also
# not a bill TITLE — `_section_titles` was recording it as one, which fed the specification matcher
# a bill heading of "Total Carried to Grand Summary".
_BILL_COLLECTION = re.compile(
    r"total\s+carried|carried\s+(?:to|down|forward)|brought\s+forward|collection|summary", re.I)
# THE SMM SECTION A BILL IS MEASURED UNDER, printed on the bill's own pages.
#
# `SECTION 2 : GROUND INVESTIGATION` inside a Bill of Quantities is not a section OF the bill — it
# names the Standard Method of Measurement section the bill's items are measured under, and the
# corresponding `GP&PP/SMM_S02-0.pdf` ships in the pack. `_sor_section_markers` already sees these
# lines and DISCARDS them (`return bills or sections`), correctly, because they are not bill
# numbers; on CEDD ND/2025/04 it reported the bill's sections as ['1','2','24','28','29','3'] before
# that fix, which is exactly the set of SMM sections the bills cite.
#
# ⚠️ THIS ONE IS NUMBER-TO-NUMBER, AND THAT IS CORRECT — because BOTH numbers are SMM numbers. It is
# NOT the Particular Specification case, where a bill's number is an SMM number and a PS number is
# the specification's own: Bill 9 heads "SECTION 28" (SMM 28, Site Safety Management) while PS 28 is
# Environmental Ground Investigation. See `spec_match` for that side, which matches on TITLE and
# requires a human to confirm. Never merge the two rules.
#
# Numeric only: a LETTER code (`SECTION A`) is a Schedule-of-Rates section of the document itself.
_BILL_MM_REFERENCE = re.compile(r"(?im)^\s*section\s+(\d{1,3})\b")

# A PS/GS clause id: a dotted number with optional letter / bracket / trailing-letter suffixes
# (7.34, 7.34A, 7.39S, 7.41.(4)S, 7.72(6)S — the dot before the bracket is optional). Kept verbatim
# so a reference resolves to the exact amendment, and matches the same id ``doc_refs`` produces.
_CLAUSE_ID = r"\d+(?:\.\d+)*[A-Za-z]?(?:\.?\(\d+\))?[A-Za-z]?"
# PS amendment lead-ins carry the GS clause they amend: "Replace GS Clause 7.28 with the
# following:", "Add the following Clauses after GS Clause 7.30:". Indexed so a GS reference
# resolves to the page where its amendment begins.
_PS_LEADIN = re.compile(r"(?:Replace|Add)\b[^\n]*?GS\s+Clause\s+(\d+(?:\.\d+)*[A-Za-z]?)", re.I)
# MM preamble clause markers: "PB 71". A running-header noise line ("- PB/2 -") never matches —
# the marker must start the line and have digits immediately after PB.
_MM_MARKER = re.compile(r"^\s*PB\s*(\d+)\b", re.I)
# A clause id occurring ANYWHERE on a line (>= 1 dot, so a bare integer or a body "(1)" is not a
# candidate), anchored so it is not matched inside a longer number. HK GI spec pages are MULTI-COLUMN
# and both native extraction (pymupdf ``sort=True``) and OCR linearise them, dropping the clause id
# MID-LINE ("General requirements  7.77.2A  (1) Within 3 weeks …") — so headings must be found
# mid-line, not only at line start. Section scoping / noise rejection is applied by _accept_clause_id.
_LINE_CLAUSE = re.compile(r"(?<![\w.])\d+(?:\.\d+)+[A-Za-z]?(?:\.?\(\d+\))?[A-Za-z]?")
# A clause BODY signal immediately after a heading id — "(1)" / "(a)" / a capitalised body word. Its
# presence (with a short non-cue label before) distinguishes a mid-line heading from an inline
# cross-reference ("… reporting requirements indicated in Clauses 7.301A (4) …").
_BODY_SIGNAL = re.compile(r"\(\s*(?:\d+|[a-z])\s*\)|[A-Z]")


class DocIndexEntry(BaseModel):
    """The structural index for one uploaded original."""

    filename: str
    kind: str = "other"  # schedule_of_rates | method_of_measurement | particular_specification |
    #                      appendix | general_specification | clarification | other
    spec_section_number: str = ""   # "7" / "26" / "" (the section this doc IS, if it declares one)
    spec_section_title: str = ""
    text_layer: bool = False        # >= 1 page with a real text layer
    page_count: int = 0
    # clause id -> the 0-based pages it spans (its marker page to the page before the next
    # marker; ±1 is applied at slice time). Text-layer PS / appendix / GS / MM only.
    clause_index: dict[str, list[int]] = Field(default_factory=dict)
    # PS clause id -> appendix clause ids referenced WITHIN that clause's page span (e.g.
    # "7.07A" -> ["7.8.20"] from "refer to Appendix 7.8.20"). Lets dispatch pull the SEPARATE
    # appendix document a PS clause points to — the onward hop SoR item -> PS clause -> appendix.
    clause_onward_appendices: dict[str, list[str]] = Field(default_factory=dict)
    # bill number -> the SMM section numbers its own pages cite ("2" -> ["2"], "1" -> ["1", "3"]).
    # The one thing this issuer's bill DOES point at: it carries no Clause Ref column — page 9 of
    # `BQ/I-ND_2025_04_BQ-0.pdf` is `Item No. | Item Description | Quantity | Unit | Rate | Amount`
    # and that is this issuer's shape, permanently — but every bill page names the Method of
    # Measurement section it is measured under, and every one of those ships in `GP&PP/`.
    # Deterministic, no model, no operator confirmation. See `_BILL_MM_REFERENCE`.
    bill_mm_sections: dict[str, list[str]] = Field(default_factory=dict)
    # SoR section code (upper) -> the 0-based pages that section spans, so dispatch can slice the
    # ORIGINAL Schedule of Rates to a dispatched unit's own section pages (the priced-return sheet)
    # instead of a derived .xlsx. Text-layer schedule_of_rates only; ±1 is applied at slice time.
    sor_section_pages: dict[str, list[int]] = Field(default_factory=dict)
    # WHERE THE BYTES ARE, when ``filename`` is not one.
    #
    # `/ingest-upload` writes each original to `docs/<filename>` and indexes it under that same
    # filename, so `Workspace.doc_path(tender, filename)` finds it and this stays empty. The bridge
    # cannot: its documents are client_boq PARTS, indexed under the part's TITLE ("Schedule of
    # Rates") and living at the part's own cut-pdf path. `doc_path(tender, "Schedule of Rates")`
    # is not a file, `_attachment_bytes` returned None, and `assemble_firm_attachments` skipped
    # every attachment in silence — the drafts went out empty while the preview, which reads only
    # this index and never touches disk, showed the full set.
    #
    # An absolute path, not a copy: the part pdfs already exist, and duplicating a 232 MB pack into
    # `docs/` to make two names agree is paying disk to avoid saying where a file is.
    source_path: str = ""
    # WHERE `spec_section_title` CAME FROM: "" (none), "page_1" (the document's own SECTION n
    # declaration) or "ps_index" (the Particular Specification's table of contents). Provenance, not
    # a silent fill — a title the pack states about a document is weaker evidence than one the
    # document states about itself, and the gate must be able to say which it is showing.
    spec_section_title_source: str = ""
    # `section number -> title`, parsed from a PS INDEX document's table of contents. Non-empty on
    # the index entry alone; every other entry reads it through `apply_ps_index_titles`.
    ps_index_titles: dict[str, str] = Field(default_factory=dict)
    # Entries the index printed that could not be read cleanly — reported, never guessed.
    ps_index_unreadable: list[str] = Field(default_factory=list)


def parse_ps_index(pages: list[str]) -> tuple[dict[str, str], list[str]]:
    r"""``(section number -> title, rows that could not be read)`` from a PS table of contents.

    ANCHORED ON THE `SECTION  TITLE` HEADER ROW, not scanned over the document, so a clause
    reference or a numbered paragraph elsewhere in the pack can never be read as an entry.

    Reading stops at the first page after the header that contributes no entry. The real pack's
    list is one page, and a longer index that runs on is still followed to its end — but the
    specification body that comes after it is not, because its prose yields no rows.

    Every page carries the same running header (`Contract No. …`, `Particular Specification`) and
    footer (`AECOM-AtkinsRealis JV  PS/iii`); none of them start with a number, so none can match a
    row. Spacing between number and title is ragged in the source and is read as ``\s+``, never as
    a column.

    A row the rule cannot read is RETURNED, not filled with something plausible — a title invented
    here would become the specification side of a match nobody could check. That includes a row the
    index printed as a bare number: it is reported rather than dropped, which on a pack that footers
    its pages with a bare numeral would name a line that was never an entry. Reporting a line that
    turns out to be furniture is a question for the operator; dropping a section is a gap in the
    enquiry nobody sees.
    """
    titles: dict[str, str] = {}
    unreadable: list[str] = []
    started = False
    for page in pages:
        found_here = False
        for raw in (page or "").splitlines():
            if not started:
                started = bool(_TOC_HEADER.match(raw))
                continue
            line = raw.strip()
            if not line:
                continue
            m = _TOC_ROW.match(raw)
            if not m:
                # Running header/footer and anything else that is not an entry. Only a line that
                # OPENS with a number is a candidate, so this is not a silent drop of a real row.
                continue
            number, title = m.group(1).lstrip("0") or m.group(1), m.group(2).strip()
            if sum(c.isalpha() for c in title) < 2:
                unreadable.append(line)      # a number with no readable title — say so
                continue
            found_here = True
            titles.setdefault(number, title)
        if started and not found_here and titles:
            break                            # the list ended on the previous page
    return titles, unreadable


def _is_title_continuation(line: str, furniture: frozenset[str] = frozenset()) -> bool:
    """Whether ``line`` is more of the cover title above it, rather than what comes after it."""
    text = (line or "").strip()
    if not text or not text[0].isalpha():
        return False                       # blank, or a clause id / bullet — the heading has ended
    if text in furniture:
        return False                       # the running header — see `running_lines`
    if any(c.isdigit() for c in text):
        return False                       # "7.01 General", "Page 3 of 40" — body, not title
    if len(text) > _TITLE_MAX or len(text.split()) > _TITLE_MAX_WORDS:
        return False                       # a sentence, not a heading
    if _TITLE_FURNITURE.match(text) or _SECTION_DECL.match(text):
        return False                       # page furniture, or the NEXT section's declaration
    return True


def _is_furniture_title(title: str, furniture: frozenset[str] = frozenset()) -> bool:
    """Whether a captured "title" is page furniture rather than this section's name.

    THE RULE FOR A PAGE THAT DECLARES ITS SECTION TWICE. `SMM_S01-0.pdf`'s page 1 does:

        Contract No. ND/2025/04 / Ground Investigation Works … / Technopole (Phase 2) /
        Particular Preambles / Section 1 / AECOM-AtkinsRealis JV / - 1a - /
        SECTION 1 / PRELIMINARIES

    The first is the HEADER BLOCK naming the section as metadata, alongside the contract number and
    the consultant; the second is the document's own heading. The winner is NOT decided by position
    — extraction order is not the page's order, as `SECTION 28`'s amendment lead-in already showed,
    and the two orders here yield "AECOM-AtkinsRealis JV" and "Technopole (Phase 2)" respectively.

    It is decided by the TITLE: **a declaration whose title is page furniture is not a
    declaration**, and the scan moves on to the next candidate. That is order-independent, and it
    is the same shape as the amendment-lead-in skip beside it. Where two candidates both survive,
    the first still wins — but neither of them is furniture, so there is nothing to prefer between.

    Two sources of furniture, and both are needed. ``furniture`` is what REPEATS on every page
    (``running_lines``) and generalises to any pack; ``_TITLE_FURNITURE`` is the named forms, which
    still work on a one-page document where there is no repetition to observe.
    """
    text = (title or "").strip()
    return bool(text) and (text in furniture
                           or bool(_TITLE_FURNITURE.match(text))
                           or bool(_TITLE_ORG_SUFFIX.search(text)))


def running_lines(pages: list[str]) -> frozenset[str]:
    """Lines that appear on EVERY page of a document — its running header and footer.

    The same signal ``ingest.running_furniture`` uses on a bill, for the same reason and with the
    same argument behind it: content cannot distinguish a running header from a heading (the
    project title is prose with plenty of letters), so REPETITION is the only evidence available;
    and a line on every page discriminates nothing, so dropping it loses nothing.

    "Every page", not "more than one", because a genuine heading spans its own section's pages, not
    the whole document. Blank pages are ignored — they exclude everything and mean nothing — and a
    document with fewer than two readable pages has no furniture, because there is no repetition to
    observe.
    """
    common: Optional[set[str]] = None
    seen = 0
    for page in pages:
        lines = {ln.strip() for ln in (page or "").splitlines() if ln.strip()}
        if not lines:
            continue
        seen += 1
        common = lines if common is None else (common & lines)
    return frozenset(common or ()) if seen >= 2 else frozenset()


def _is_amendment_lead_in(page1: str, m: "re.Match") -> bool:
    """Whether this ``SECTION n`` match names ANOTHER section as a position, rather than naming
    this document. See ``_AMENDMENT_VERB`` for the case that made it necessary."""
    before = (page1 or "")[:m.start()].rsplit("\n", 1)[-1]
    if _AMENDMENT_VERB.search(before) or _AMENDMENT_POSITION.search(before):
        return True                              # "…new section after Section 27"
    # The captured "title" IS the lead-in, which happens when the number sits at a line end and the
    # instruction follows on the next. Only a VERB counts here: a positional word can legitimately
    # appear inside a real section title, an amendment verb effectively cannot.
    return bool(_AMENDMENT_VERB.search(m.group(2)))


def section_declaration(page1: str, furniture: frozenset[str] = frozenset()) -> tuple[str, str]:
    """``(section number, title)`` from a page-1 ``SECTION n`` declaration, WHOLE.

    The title is read past a line break where the cover set it on more than one line — see
    ``_TITLE_FURNITURE`` for what stops that read. A single-line declaration is byte-for-byte what
    ``_SECTION_DECL`` alone produced, so nothing that worked before reads differently now.

    AMENDMENT LEAD-INS ARE SKIPPED, not merely out-ranked: the first match that is a genuine
    declaration wins, wherever it falls in the extracted text. Extraction order is not the
    document's order — pymupdf sorts by position — so a rule that trusted "leftmost" gave section
    27 for a document titled SECTION 28 depending on how the page happened to linearise.
    """
    text = page1 or ""
    pos = 0
    while True:
        m = _SECTION_DECL.search(text, pos)
        if m is None:
            return "", ""
        if not _is_amendment_lead_in(text, m) and not _is_furniture_title(m.group(2), furniture):
            break
        # Resume just past the NUMBER, not past the whole match. A lead-in's captured "title" is
        # usually the genuine declaration on the next line — `…after Section 27 :\n\nSECTION 28` —
        # and skipping the whole match would swallow the very thing being looked for.
        pos = m.end(1)
    title = m.group(2).strip()
    # The match ends mid-line (the title group is `[^\n]`), so the remainder's FIRST element is the
    # tail of the line already read — usually empty. The continuation starts at the line after it.
    tail = (page1 or "")[m.end():]
    following = tail.split("\n")[1:]
    for line in following[:_TITLE_CONTINUATION_LINES]:
        if not _is_title_continuation(line, furniture):
            break
        joined = f"{title} {line.strip()}"
        if len(joined) > _TITLE_MAX:
            break
        title = joined
    return m.group(1), title


def kind_from_own_name(filename: str) -> Optional[str]:
    """The kind a file's OWN NAME declares, or ``None`` when it names no section.

    THE one rule, in one place. It was written out three times — the addendum branch, the ps_index
    guard, the `_effective_kind` override — and each copy answered a slightly different question.
    Blocking a DocType door without it turned a wrongly-typed General Specification into ``other``,
    which is dropped from every enquiry: refusing a bad answer is only half the job, the name has to
    give the right one.

    Order matters: ``PSA`` is checked before ``PS``, because `PSA1.12` contains neither a `PS1` nor
    a section 1 — it is an appendix TO section 1.
    """
    own = _own_name(filename)
    if _FILENAME_APPENDIX.search(own):
        return "appendix"
    if _FILENAME_PS_SECTION.search(own):
        return "particular_specification"
    if _FILENAME_GS_SECTION.search(own):
        return "general_specification"
    return None


def _kind_for(doc_type: DocType, page1: str, filename: str) -> str:
    """Refine the coarse DocType into the assembler's kind, reading the page-1 declaration."""
    hay = f"{page1}\n{filename}"
    # BEFORE every specification branch. The PS table of contents is not a specification section:
    # it declares no `SECTION n` of its own, so it reached the PS branch with no number and FIX A
    # reported it as an unidentifiable specification on every run of this pack. It is also the only
    # document that states the PS section TITLES, so it needs an identity a reader can find.
    #
    # The filename is the certain signal (`…-S_PS_Index-0.pdf`); the page-1 pair is the fallback for
    # an index named otherwise, and requires BOTH "Particular Specification" and a contents heading
    # so that a specification merely listing its own clauses is never stolen. Behind the same
    # no-competing-header guard the appendix-cover and General-Specification branches use: a document
    # that declares `SECTION n` on page 1 has said what it IS, and is never reclassified an index.
    #
    # AND behind the filename. That guard was missing and it cost PS 1 — 101 pages, titled "General",
    # long enough to carry its OWN table of contents on page 1 with the `SECTION 1` declaration
    # further in. Both revisions classified `ps_index`, so neither was enclosed, neither competed in
    # `_ps_revisions`, and a firm received twenty-five appendices of a section it never got. PS 27
    # declares `SECTION 27` on page 1 and was untouched, which is exactly the difference that showed
    # up on the pack. A file whose own name says which section it is has already answered the
    # question; a contents page inside it does not reopen it.
    own_name = _own_name(filename)
    # WHAT THE FILE'S OWN NAME SAYS IT IS. Kept separate per population, because a guard that is
    # right for one branch is wrong for another: an SMM file names neither a PS nor a GS section, a
    # General Specification file legitimately names a GS one, and only a PS file names a PS one.
    names_ps = bool(_FILENAME_PS_SECTION.search(own_name) or _FILENAME_APPENDIX.search(own_name))
    names_gs = bool(_FILENAME_GS_SECTION.search(own_name))
    names_a_section = names_ps or names_gs
    if _PS_INDEX_NAME.search(own_name) or (
        not names_a_section
        and _PS_INDEX_PAGE1.search(page1)
        and _TABLE_OF_CONTENTS.search(page1)
        and not _SECTION_DECL.search(page1)
    ):
        return "ps_index"
    # A HUMAN confirms which part is the bill, and a human's answer outranks a filename.
    if doc_type == DocType.SCHEDULE_OF_RATES:
        return "schedule_of_rates"
    # THE SAME OWN-NAME RULE, ON THE DOCTYPE DOORS. Both of these are AUTOMATIC classifications — a
    # category mapping or a classifier's guess — and both sat in front of every own-name guard, so
    # each reopened a defect that had already been closed behind them:
    #
    #   PS 1 arriving as METHOD_OF_MEASUREMENT  -> takes SMM 1's slot and SUPERSEDES the real one
    #                                              (exactly C18, through a different door)
    #   `TA #1/…-S_PS27-1.pdf` as TENDER_ADDENDUM -> a reissued specification section becomes a
    #                                              clarification and goes WHOLE to every firm,
    #                                              never meeting the `-0` it supersedes (C12)
    #
    # A file whose own name says which section it is has answered the question, and a coarse
    # DocType assigned upstream is weaker evidence than the name the issuer gave it. A genuine SMM
    # file and a genuine addendum LETTER name no section, so neither is touched.
    if doc_type in (DocType.METHOD_OF_MEASUREMENT, DocType.TENDER_ADDENDUM):
        by_name = kind_from_own_name(filename)
        if by_name is not None:
            return by_name          # the name decides, and it decides completely
        return ("method_of_measurement" if doc_type == DocType.METHOD_OF_MEASUREMENT
                else "clarification")
    # A genuine appendix COVER declares a BARE "Appendix N" (page 1 or filename) with no competing
    # SECTION header — NOT an inline "Appendix 7.4.16" cross-reference. An explicit PARTICULAR_
    # SPECIFICATION is reclassified appendix ONLY on such a cover, so a PS whose page-1 SECTION header
    # was lost (scanned / starts mid-section) and merely cites an appendix still indexes as a PS.
    # The issuer's own appendix marker, read off the file's OWN name. Needed because
    # `_APPENDIX_COVER` requires a BARE "Appendix N": a PSA file whose page 1 declares only the
    # dotted "Appendix 7.12" — or declares nothing at all — was classified
    # `particular_specification`, and then competed in `_ps_revisions` as if it WERE section 7's
    # specification. Verified against the real names.
    is_appendix_cover = (
        bool(_FILENAME_APPENDIX.search(_own_name(filename)))
        or (bool(_APPENDIX_COVER.search(hay)) and not _SECTION_DECL.search(page1))
    )
    # BEFORE the PS branch, and only these two, because a bridge part whose category is
    # `specifications` arrives as PARTICULAR_SPECIFICATION — which would otherwise claim the SMM
    # before it could be recognised. Both patterns are narrow enough that an ordinary PS citing
    # either does not match; see their definitions.
    # …AND NOT WHEN THE FILE'S OWN NAME SAYS IT IS A SPECIFICATION SECTION. The "deliberately
    # narrow" claim above was wrong about one document: PS 1 is *General*, 101 pages of general
    # preliminaries, and its clause 1.01 quotes the full title — "in accordance with the Standard
    # Method of Measurement". So `S/PS/PS1/…-S_PS1-1.pdf` classified `method_of_measurement`, was
    # enclosed on Builders Work as "Method of Measurement Section 1 (101 pages)", and — because it
    # then shared the MM population AND section number 1 with the real `GP&PP/…-SMM_S01-0.pdf` —
    # its `-1` revision SUPERSEDED the genuine SMM 1, which reached no enquiry at all.
    #
    # A phrase inside a document is weaker evidence than the name the issuer gave it. Same rule as
    # the `ps_index` and addendum guards: read the file's own name, and let it close the question.
    if _METHOD_OF_MEASUREMENT.search(hay) and not names_a_section:
        return "method_of_measurement"
    if _ADDENDUM.search(hay):
        # A REISSUED SPECIFICATION SECTION IS STILL A SPECIFICATION SECTION.
        #
        # The pack ships `TA #1/S/PS/PS25/I-ND_2025_04-S_PS25-1.pdf` — PS 25 at revision 1, filed
        # under the addendum that issued it. `_ADDENDUM` matched `TA #1` IN THE PATH, so it became
        # a clarification: it went WHOLE to every firm through that branch, and it never entered
        # `_ps_revisions`, so the `-0` it supersedes was enclosed beside it with nothing on the
        # gate to say which governs. One contest, two doors.
        #
        # The document's OWN NAME decides, never the folder. `S_PS25-1` is a Particular
        # Specification section; `S_PSA1.12-1` is an appendix to one; `S_GS7-1` is General. A
        # genuine addendum LETTER names no section, matches none of these, and stays a
        # clarification issued to everyone — which is exactly what it is.
        return kind_from_own_name(filename) or "clarification"
    # A GENERAL Specification whose page 1 declares itself and carries no `SECTION n` header of its
    # own. `_GENERAL_SPEC` is a loose pattern, so it is checked here against PAGE 1 ONLY and behind
    # the same no-competing-header guard the appendix cover uses — a Particular Specification that
    # merely cites the General Specification has a SECTION header and is never stolen.
    #
    # Needed for the same reason as the two above: a bridge part categorised `specifications`
    # arrives as PARTICULAR_SPECIFICATION, so the PS branch would claim the GS before the existing
    # `_GENERAL_SPEC` check below could ever see it — and a PS entry with no section number is then
    # skipped by the assembler entirely, so the General Specification reached no enquiry at all.
    # `not names_ps`, not `not names_a_section`: a General Specification file NAMES a GS section, so
    # the MM branch's guard would block the very branch this is. Only a PS name is disqualifying.
    if _GENERAL_SPEC.search(page1) and not _SECTION_DECL.search(page1) and not names_ps:
        return "general_specification"
    if doc_type == DocType.PARTICULAR_SPECIFICATION:
        return "appendix" if is_appendix_cover else "particular_specification"
    if is_appendix_cover:
        return "appendix"
    if _GENERAL_SPEC.search(hay):
        return "general_specification"
    return "other"


def _pages_text(data: bytes) -> Optional[list[str]]:
    """Per-page text via the OCR spine — the native text layer where a page has one, local
    tesseract OCR for scanned pages — so ``text_layer`` and the clause index build on scanned
    specs too, not just native-text ones. ``None`` when the input is not a readable PDF (or
    pymupdf is absent); a scanned page with no OCR available degrades to ``""`` (no false
    marker), exactly the pre-OCR behaviour."""
    from pipeline import ocr  # lazy: pymupdf / pytesseract stay optional for module import

    try:
        return ocr.page_texts(data)
    except ocr.NotAPdf:
        return None
    except Exception:  # noqa: BLE001 — no pymupdf / unreadable upload -> no index (whole-file fallback)
        return None


def _is_heading_occurrence(line: str, m: "re.Match", section_number: str) -> bool:
    """Whether the clause-id match ``m`` on ``line`` is a HEADING (it STARTS a clause), not an inline
    cross-reference. True when the id is at the line start (tolerating leading OCR punctuation), OR —
    the multi-column linearised case — it is preceded ONLY by a short label (<= 6 words) that is not a
    cue word, AND is immediately FOLLOWED by a clause-body signal ("(1)" / "(a)" / a capitalised word).
    So ``General requirements 7.77.2A (1) Within …`` is a heading, while ``… indicated in Clauses
    7.301A (4)`` (cue-preceded) and ``… value 7.5 metres`` (no body signal) are not."""
    before = line[: m.start()]
    if not before.strip(" \t=.:)|("):  # line start (leading punctuation tolerated) -> heading
        return True
    words = re.findall(r"[A-Za-z]+", before)
    if len(words) > 6:  # a long run of prose before the id -> a body mention, not a heading label
        return False
    if words and _clean_word(words[-1]) in _CUE_WORDS:  # "… in Clauses 7.301A" -> inline cross-reference
        return False
    return bool(_BODY_SIGNAL.match(line[m.end():].lstrip()))  # a clause body must start right after


def _page_line_markers(text: str, page_no: int, section_number: str) -> list[tuple[str, int]]:
    """Clause headings + amendment lead-ins on one page's text. A heading is a clause id at a line
    START, or MID-LINE where it starts a clause (multi-column pages linearise the id mid-line under
    both native extraction and OCR — see :func:`_is_heading_occurrence`). A matched id is kept only if
    :func:`_accept_clause_id` vouches for it (section scope; a bare ``0.5`` is rejected). Amendment
    lead-ins ("GS Clause 7.28") are explicit references and pass through unchanged. Runs on page TEXT,
    so it is engine-independent and covers multi-column native and scanned pages alike."""
    markers: list[tuple[str, int]] = []
    for line in text.splitlines():
        for m in _LINE_CLAUSE.finditer(line):
            cid = m.group(0)
            if _accept_clause_id(cid, section_number) and _is_heading_occurrence(line, m, section_number):
                markers.append((cid, page_no))
        for lm in _PS_LEADIN.finditer(line):
            markers.append((lm.group(1), page_no))
    return markers


def _spec_markers(pages: list[str], section_number: str) -> list[tuple[str, int]]:
    """``(clause_id, page)`` for a PS / appendix / GS doc: clause headings (line-start or mid-line,
    scoped to the doc's own section numbering when known, e.g. ``7.34A``), plus the GS clauses named
    in amendment lead-ins. In document order."""
    return [m for page_no, text in enumerate(pages) for m in _page_line_markers(text, page_no, section_number)]


def _sor_section_markers(pages: list[str]) -> list[tuple[str, int]]:
    """``(SECTION_CODE_upper, 0-based page)`` for every priced-document section header, in document
    order — fed to :func:`_spans` to map each section code to the pages it spans. A section header is
    a standalone row even in a multi-column SoR (it precedes the item table), so a line-start match is
    enough; a code repeated in a running header simply unions onto that section's page span.

    Both header families are scanned, and where a document declares BILL headers those are the only
    markers kept. That is not tidiness — it is the fix for the second half of the ND/2025/04 failure.
    ``_SOR_SECTION_HEADER``'s code class is ``[A-Za-z0-9]+``, so in a Bill of Quantities it happily
    matched the *specification* cross-references scattered through the preambles (``SECTION 24 :
    EARTHWORKS``) and reported the bill's sections as ``['1','2','24','28','29','3']``. Those are not
    bill numbers; ND/2025/04 has nine, numbered 1 to 9. When a document says ``Bill No. n`` it has
    told us its own vocabulary, and a ``SECTION n`` line inside it is pointing somewhere else.

    A Schedule of Rates carries no Bill headers, so it takes the first branch and its markers are
    byte-for-byte what they were."""
    bills: list[tuple[str, int]] = []
    sections: list[tuple[str, int]] = []
    for page_no, text in enumerate(pages):
        for line in text.splitlines():
            b = bill_header_number(line)
            if b:
                bills.append((b, page_no))
                continue
            m = _SOR_SECTION_HEADER.match(line)
            if m:
                sections.append((m.group(1).upper(), page_no))
    return bills or sections


# -- layout-aware spec markers (multi-column scanned PS / GS) ----------------
# HK GI Particular Specification pages are MULTI-COLUMN (a narrow label column, a clause-number
# column ~30% across, then the clause body). Under OCR the columns collapse onto one line, so the
# clause id lands MID-LINE fused with the body ("Standpipes in trial pits  7.278.2A  (1) When …")
# and the line-start scan above matches nothing. For a SCANNED PS/GS page we instead read the OCR
# word boxes and take the clause id that sits in the clause-number column, mirroring the SoR
# column recovery in ``ocr_table``. A native-text page keeps the line-start path unchanged.

_NATIVE_MIN = 20  # a page with fewer native chars than this is treated as scanned (as page_texts)
# A token that begins like a clause number ("7.278.2A", "7.279.", "=7.286A") — anchors the Pass-1
# clause-number column and is tolerant of the leading OCR punctuation seen in the documents.
_LOOSE_CLAUSE = re.compile(r"^[=.]*\d+\.\d")
# Words that, immediately before a clause id, mark it an INLINE cross-reference, not a heading
# ("… in Clause 7.278.1A", "General Specification Clause 7.73"). Compared in a stripped, lower form.
_CUE_WORDS = {
    "clause", "clauses", "subclause", "specification", "specifications", "general", "particular",
    "gs", "ps", "in", "under", "see", "refer", "reference", "ref", "per",
    "appendix", "appendices",  # "… in Appendix 7.4.16 …" is an onward reference, not a heading
    "to", "from", "of",        # "… pursuant to 7.301A", "requirements of 7.286A" — inline references
}


def _clean_word(text: str) -> str:
    """A word reduced to its lowercase letters for cue matching (``"Clause"``/``"Clause,"`` ->
    ``"clause"``, ``"sub-clause"`` -> ``"subclause"``)."""
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _accept_clause_id(cid: str, section_number: str) -> bool:
    """Whether a matched clause id is a real heading id, not marker noise. When the doc declares a
    section, that section vouches for its own ids (its leading group must equal the section). With no
    section, the id must show real clause structure — ``>= 2`` dots (``7.278.5``) or a letter suffix
    (``7.34A``) — so a bare decimal like ``0.5`` (an OCR'd quantity, or a stray number in prose) is
    rejected rather than indexed as a clause."""
    from pipeline.stage_03_dispatch.doc_refs import base_clause  # lazy: pure util

    if section_number:
        return base_clause(cid).split(".")[0] == str(section_number)
    return cid.count(".") >= 2 or bool(re.search(r"[A-Za-z]", cid))


def _canonical_heading(raw: str, section_number: str) -> Optional[str]:
    """Normalise a clause-number cell to the SAME canonical clause id the resolver's ``clause_of``
    produces (so index keys match referenced refs), dropping internal OCR spaces. ``None`` unless
    it is a dotted clause id and — when the doc declares a section — in that section."""
    from pipeline.stage_03_dispatch.doc_refs import clause_of  # lazy: pure util

    cid = clause_of((raw or "").replace(" ", ""))
    if not cid or "." not in cid:
        return None
    if not _accept_clause_id(cid, section_number):  # scope check, and reject bare decimals when unscoped
        return None
    return cid


def _clause_number_column(words: list[dict]) -> Optional[tuple[float, float]]:
    """The ``(left, right)`` x-band of the clause-number column, derived (never hardcoded) from the
    LEFTMOST cluster of clause-id-shaped token boxes on the page — an inline body reference clusters
    further right and is excluded. ``None`` when the page carries no clause-id token."""
    lrs = [(float(w["left"]), 2.0 * float(w["cx"]) - float(w["left"]))  # (left, right=left+width)
           for w in words if _LOOSE_CLAUSE.match(w.get("text") or "")]
    if not lrs:
        return None
    lefts = sorted(left for left, _ in lrs)
    gap = max(20.0, (lefts[-1] - lefts[0]) * 0.15)  # tolerant to page size; splits the columns
    cluster_max_left = lefts[0]
    for prev, cur in zip(lefts, lefts[1:]):
        if cur - prev > gap:
            break  # first big gap = the jump to the body column's inline refs
        cluster_max_left = cur
    col_left = lefts[0]
    col_right = max((r for left, r in lrs if col_left <= left <= cluster_max_left), default=cluster_max_left)
    pad = max(12.0, gap * 0.4)
    return (col_left - pad, col_right + pad)


def _row_heading(row: list[dict], band: tuple[float, float], section_number: str) -> Optional[str]:
    """The clause id for one row of word boxes: the contiguous run of tokens sitting in the
    clause-number ``band`` (so an OCR-split id ``7.279.`` + ``1A`` rejoins, while the body ``(1)`` a
    column over is excluded). ``None`` when no token is in the band, or the first band token is an
    inline reference (immediately preceded by a cue word like ``Clause`` / ``in``)."""
    lo, hi = band
    in_band = [i for i, w in enumerate(row) if lo <= float(w["cx"]) <= hi]
    if not in_band:
        return None
    first = in_band[0]
    if first > 0 and _clean_word(row[first - 1].get("text") or "") in _CUE_WORDS:
        return None  # "… in Clause 7.278.1A …" — an inline cross-reference, not a heading
    run = [first]
    for i in in_band[1:]:
        if i != run[-1] + 1:
            break  # only join tokens adjacent within the column (an OCR-split clause id)
        run.append(i)
    raw = "".join(row[i].get("text") or "" for i in run)
    return _canonical_heading(raw, section_number)


def _headings_from_words(words: list[dict], section_number: str) -> list[str]:
    """The clause-heading ids on one scanned page, from its OCR word boxes: find the clause-number
    column, then take the in-column clause id per row. Pure (no tesseract) — tests stub the word
    reader as ``test_ocr_table`` does."""
    from pipeline import ocr_table  # reuse the SoR row grouping; pure, no tesseract at import

    band = _clause_number_column(words)
    if band is None:
        return []
    ids: list[str] = []
    for row in ocr_table._group_rows(words):
        cid = _row_heading(row, band, section_number)
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def _open_pdf(data: bytes):
    import fitz  # PyMuPDF — lazy

    try:
        return fitz.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001 — unreadable -> caller degrades to the line-start path
        return None


def _column_headings(data: bytes, page_no: int, section_number: str) -> list[str]:
    """Clause-heading ids for one SCANNED spec page via CACHED word-box OCR (``ocr.page_words`` —
    served from the versioned cache, tesseract only on a miss).

    A configured-but-missing ENGINE (:class:`ocr.OcrEngineUnavailable`) PROPAGATES — it is a
    deployment fault, and swallowing it to ``[]`` would silently produce an empty clause index that
    reads as 'this page has no clauses'. Only a NARROW per-page glitch (no pytesseract installed at
    all, a rasterise error) degrades to no markers for THIS page (whole-file fallback)."""
    from pipeline import ocr

    try:
        words = ocr.page_words(data, page_no)
    except ocr.OcrEngineUnavailable:
        raise  # engine misconfiguration — fail loud, never a silent empty index
    except Exception:  # noqa: BLE001 — no pytesseract / a per-page rasterise glitch -> no markers here
        return []
    return _headings_from_words(words, section_number)


def _spec_markers_layout(data: bytes, pages: list[str], section_number: str) -> tuple[list[tuple[str, int]], int, int]:
    """``(markers, scanned_page_count, column_heading_count)`` for a PS / GS doc, LAYOUT-AWARE: every
    page runs the text heading scan (line-start AND mid-line — multi-column pages linearise the id
    mid-line); a scanned page ALSO reads its word boxes so the clause-number column is recovered,
    unioned with the text scan. Amendment lead-ins are read from the page text either way. The two
    counts feed the ingest engine-health signal (a scanned spec with a text layer but ZERO column
    headings is the live word-box symptom). With OCR off it is the text heading scan only."""
    from pipeline import ocr

    doc = _open_pdf(data) if ocr.ocr_enabled() else None
    if doc is None:
        return _spec_markers(pages, section_number), 0, 0  # OCR off / unreadable -> text heading scan
    markers: list[tuple[str, int]] = []
    n_scanned = 0
    n_column = 0
    try:
        for page_no, text in enumerate(pages):
            page = doc[page_no] if page_no < doc.page_count else None
            native = page.get_text("text", sort=True) if page is not None else text
            if page is None or len(native.strip()) >= _NATIVE_MIN:
                markers.extend(_page_line_markers(text, page_no, section_number))  # native page
            else:
                # Scanned page: the text heading scan over the OCR text already recovers a clause id
                # that OCR fused MID-LINE (the multi-column case) as well as a line-start id. The
                # word-box COLUMN path stays as a SECONDARY source (unioned) for pages where the OCR
                # text is poor but the column is recoverable — correctness no longer depends on it.
                # _page_line_markers also reads the amendment lead-ins from the OCR text.
                n_scanned += 1
                col = _column_headings(data, page_no, section_number)
                n_column += len(col)
                markers.extend((cid, page_no) for cid in col)
                markers.extend(_page_line_markers(text, page_no, section_number))
    finally:
        doc.close()
    return markers, n_scanned, n_column


def bill_header_number(line: str) -> Optional[str]:
    """The bill number this line OPENS, or ``None`` if it opens no bill.

    One rule, used everywhere a bill boundary is decided, so a header and a footer can never be told
    apart two different ways. A bare `Bill No. 9` opens Bill 9; `Bill No. 9 - Total Carried to Grand
    Summary` closes it and opens nothing.
    """
    m = _BILL_SECTION_HEADER.match(line or "")
    if not m or _BILL_COLLECTION.search(m.group(2) or ""):
        return None
    return m.group(1).lstrip("0") or m.group(1)


def bill_mm_sections(pages: list[str]) -> dict[str, list[str]]:
    """``bill number -> the SMM section numbers cited on that bill's pages``, in document order.

    A single forward pass: `Bill No. 2 : …` opens a bill, and every `SECTION n` line after it
    belongs to that bill until the next one. A `SECTION n` line before any bill header is ignored —
    it belongs to the document's front matter, not to a bill nobody has opened yet.

    Returns ``{}`` for a document that declares no bill headers at all, which is every Schedule of
    Rates: an SoR is sectioned by LETTER and cites no method of measurement this way, so the whole
    mechanism stays out of its path.
    """
    out: dict[str, list[str]] = {}
    current = ""
    for text in pages:
        for line in (text or "").splitlines():
            bill = bill_header_number(line)
            if bill:
                current = bill
                out.setdefault(current, [])
                continue
            mm = _BILL_MM_REFERENCE.match(line)
            if mm and current:
                number = mm.group(1).lstrip("0") or mm.group(1)
                if number not in out[current]:
                    out[current].append(number)
    return {k: v for k, v in out.items() if v}


def _mm_markers(pages: list[str]) -> list[tuple[str, int]]:
    """``("PB N", page)`` for each Method-of-Measurement preamble clause, in document order."""
    markers: list[tuple[str, int]] = []
    for page_no, text in enumerate(pages):
        for line in text.splitlines():
            m = _MM_MARKER.match(line)
            if m:
                markers.append((f"PB {m.group(1)}", page_no))
    return markers


def _onward_appendices(pages: list[str], clause_index: dict[str, list[int]]) -> dict[str, list[str]]:
    """For each PS clause, the appendix clause ids referenced within its page span — parsed from
    the page text with the SAME appendix regex the SoR resolver uses. Empty entries are dropped."""
    from pipeline.stage_03_dispatch.doc_refs import clause_of, extract_refs  # lazy: pure util, avoids a cycle

    out: dict[str, list[str]] = {}
    for clause_id, span in clause_index.items():
        text = "\n".join(pages[p] for p in span if 0 <= p < len(pages))
        apps = extract_refs(text).get("appendix", [])
        if apps:
            ids: list[str] = []
            for a in apps:
                cid = clause_of(a)  # "Appendix 7.8.20" -> "7.8.20"
                if cid and cid not in ids:
                    ids.append(cid)
            if ids:
                out[clause_id] = ids
    return out


def _spans(markers: list[tuple[str, int]], page_count: int) -> dict[str, list[int]]:
    """Turn ordered clause markers into ``clause_id -> [pages]``: each clause spans from its
    marker's page to the page BEFORE the next marker (at least its own page). A repeated id
    unions its spans. ±1 is applied later, at slice time, to catch a clause across a page break."""
    index: dict[str, list[int]] = {}
    for i, (clause_id, page) in enumerate(markers):
        next_page = markers[i + 1][1] if i + 1 < len(markers) else page_count
        end = next_page - 1 if next_page > page else page
        span = set(range(page, max(end, page) + 1))
        index[clause_id] = sorted(set(index.get(clause_id, [])) | span)
    return index


def build_doc_entry(filename: str, doc_type: DocType, data: bytes,
                    source_path: str = "") -> DocIndexEntry:
    """Structural index for one original. Non-PDF / unreadable -> text_layer False, no index.

    ``source_path`` records WHERE the bytes are for a caller whose ``filename`` is a label rather
    than a file in ``docs/`` — see the field's note. Omitted by ``/ingest-upload``, which saves
    under the name it indexes.
    """
    pages = _pages_text(data)
    if pages is None:
        return DocIndexEntry(filename=filename, kind=_kind_for(doc_type, "", filename),
                             source_path=source_path)
    page1 = pages[0] if pages else ""
    text_layer = any(p.strip() for p in pages)

    # What repeats on every page is the running header, not this section's title — measured across
    # the whole document, which is the one place that evidence exists. See `running_lines`.
    section_number, section_title = section_declaration(page1, running_lines(pages))
    if not section_number:
        app = _APPENDIX_COVER.search(page1)  # a real "Appendix 7" cover, not an inline "Appendix 7.4.16"
        if app:
            section_number, section_title = app.group(1), f"Appendix {app.group(1)}"
        else:
            own = _own_name(filename)
            app_fn = _FILENAME_APPENDIX.search(own)
            fn = _FILENAME_SECTION.search(own)
            if app_fn:      # `PSA7.12` — an appendix to section 7; the section is its PARENT'S
                section_number, section_title = app_fn.group(1), f"Appendix {app_fn.group(1)}"
            elif fn:  # page-1 header lost (scanned / mid-section) -> scope from the "PS-S07" filename
                section_number = fn.group(1)

    kind = _kind_for(doc_type, page1, filename)
    ps_index_titles: dict[str, str] = {}
    ps_index_unreadable: list[str] = []
    if kind == "ps_index" and text_layer:
        ps_index_titles, ps_index_unreadable = parse_ps_index(pages)
        if not ps_index_titles:
            _log.warning(
                "PS index %r has a text layer but no readable table of contents — the PS section "
                "titles will stay empty; check its layout rather than trusting the empty result",
                filename,
            )
    clause_index: dict[str, list[int]] = {}
    clause_onward: dict[str, list[str]] = {}
    sor_section_pages: dict[str, list[int]] = {}
    mm_by_bill: dict[str, list[str]] = {}
    if text_layer and kind == "schedule_of_rates":
        # Index the original SoR's section page ranges so dispatch can slice it to a unit's own
        # section (the priced-return sheet) rather than send a derived .xlsx.
        sor_section_pages = _spans(_sor_section_markers(pages), len(pages))
        # And WHICH MEASUREMENT RULES each bill is priced under — the one pointer this bill carries.
        mm_by_bill = bill_mm_sections(pages)
    elif text_layer and kind == "method_of_measurement":
        clause_index = _spans(_mm_markers(pages), len(pages))
    elif text_layer and kind in ("particular_specification", "general_specification"):
        # PS/GS pages are multi-column when scanned, so the clause id lands mid-line under OCR;
        # scan the word boxes column-aware (native pages keep the line-start path). Do NOT touch MM.
        markers, n_scanned, n_column = _spec_markers_layout(data, pages, section_number)
        clause_index = _spans(markers, len(pages))
        if not clause_index:
            # The doc WAS readable (text layer / OCR) yet produced no clause markers — surface it
            # rather than trust a silently-empty index: it will be sent WHOLE, and an empty index on
            # a readable spec usually means a broken OCR engine or unrecognised markers, not "no
            # clauses". No silent engine dependence.
            _log.warning(
                "PS/GS %r has a text layer but produced an EMPTY clause index (%d pages) — it will be "
                "sent whole; verify the OCR engine and clause markers rather than trusting the empty index",
                filename, len(pages),
            )
        elif n_scanned > 0 and n_column == 0:
            # Engine-health signal: the scanned pages produced NO word-box column headings (only
            # line-start / lead-in markers survived) — the live word-box symptom. Loud, not silent:
            # referenced clauses are still located from the cached text by the directed search at
            # dispatch, but the operator should check the OCR engine.
            _log.warning(
                "PS/GS %r: %d scanned page(s) but the word-box column path found NO headings — check "
                "the OCR engine; referenced clauses will be located from cached text at dispatch",
                filename, n_scanned,
            )
        # A PS clause may point onward to an appendix ("refer to Appendix 7.8.20"); record it now,
        # while the page text is in hand, so dispatch reads only the persisted index.
        clause_onward = _onward_appendices(pages, clause_index)
    elif text_layer and kind == "appendix":
        clause_index = _spans(_spec_markers(pages, section_number), len(pages))

    return DocIndexEntry(
        filename=filename, kind=kind, spec_section_number=section_number,
        spec_section_title=section_title, text_layer=text_layer, page_count=len(pages),
        clause_index=clause_index, clause_onward_appendices=clause_onward,
        sor_section_pages=sor_section_pages, bill_mm_sections=mm_by_bill, source_path=source_path,
        spec_section_title_source="page_1" if section_title else "",
        ps_index_titles=ps_index_titles, ps_index_unreadable=ps_index_unreadable,
    )


def _title_words(title: str) -> list[str]:
    """A title as a lowercase word list — the comparison ignores case, spacing and punctuation, and
    NOTHING else. Deliberately not ``spec_match``'s normaliser: that one drops function words and
    singularises, which is right for deciding whether two titles mean the same thing and wrong for
    deciding whether one is the other with the end cut off."""
    return re.findall(r"[a-z0-9]+", (title or "").lower())


def _is_truncation_of(short: str, full: str) -> bool:
    """Whether ``short`` is ``full`` with the end missing — a strict leading word-run.

    A PREFIX, not a subset. "Preservation and" is the start of "Preservation and Protection of
    Trees"; "Trees Preservation" is not, and is a different reading that this must not silently
    replace.
    """
    a, b = _title_words(short), _title_words(full)
    return bool(a) and len(a) < len(b) and b[:len(a)] == a


def apply_ps_index_titles(entries: list[DocIndexEntry]) -> list[DocIndexEntry]:
    """Fill ``spec_section_title`` from the PS index for sections that declare none themselves.

    On CEDD ND/2025/04 no Particular Specification declares `SECTION n — Title` on page 1 — which is
    why the section NUMBER has to come from the filename — so before this the specification side of
    any title match was empty. The pack's own index states every title, and nothing read it.

    A PAGE-1 DECLARATION WINS — UNLESS IT IS A TRUNCATION OF THE INDEX ENTRY. A title the document
    states about itself is stronger evidence than one another document states about it, and the fill
    is marked ``spec_section_title_source = "ps_index"`` so the gate can show which it is looking at.
    Never a silent fill.

    The exception is the whole of the second half of this function, and it was earned. Three of this
    pack's covers set the title on two lines, `_SECTION_DECL` stopped at the newline, and the
    resulting page-1 titles — "Environmental Ground", "Preservation and", "Management" — beat the
    complete index entries and went on to match the wrong specification. ``section_declaration`` now
    reads past the break, so this is belt-and-braces; but the index is the only place that can prove
    a declaration is short, and a title that is a strict subset of the index's is not a disagreement
    with it — it is the same title with the end missing. A GENUINE disagreement (neither contains
    the other) leaves the document's own words in place and is logged, because that is a fact about
    the pack for a person to look at, not a tie for this function to break.

    ---------------------------------------------------------------------------------------------
    PHASE 3 NOTE — THE MATCHER MUST STRIP `SECTION n` FROM THE BILL'S HEADING.

    These titles are the specification side of the bill-to-PS title match. The bill side arrives as
    `SECTION 2 - GROUND INVESTIGATION` — an SMM/bill number FUSED with a title — and that leading
    number must be discarded before matching, or the match silently becomes number-to-number, which
    the domain forbids.

    THIS PACK PROVES IT: **PS 28 is "Environmental Ground Investigation"**, while the bill headed
    "Ground Investigation" is **Bill 2**. 28 and 2 do not correspond. Match on the words.
    ---------------------------------------------------------------------------------------------
    """
    lookup: dict[str, str] = {}
    for entry in entries:
        lookup.update(entry.ps_index_titles)
    out: list[DocIndexEntry] = []
    for entry in entries:
        if entry.kind not in ("particular_specification", "appendix") or not entry.spec_section_number:
            out.append(entry)
            continue
        # PROVENANCE IS NEVER BLANK ON A TITLED ENTRY. An index persisted before this field existed
        # loads with an empty source, and the gate then reported "an undeclared source" for a title
        # that plainly came from page 1 — `build_doc_entry` sets a title from nowhere else.
        if entry.spec_section_title and not entry.spec_section_title_source:
            entry = entry.model_copy(update={"spec_section_title_source": "page_1"})
        indexed = lookup.get(entry.spec_section_number, "")
        if not indexed:
            out.append(entry)
            continue
        if not entry.spec_section_title:
            entry = entry.model_copy(update={"spec_section_title": indexed,
                                             "spec_section_title_source": "ps_index"})
        elif _is_truncation_of(entry.spec_section_title, indexed):
            entry = entry.model_copy(update={"spec_section_title": indexed,
                                             "spec_section_title_source": "ps_index"})
        elif _title_words(entry.spec_section_title) != _title_words(indexed):
            _log.warning(
                "PS %s declares %r on page 1 but the index calls it %r — neither contains the "
                "other, so the document's own words are kept; check which is right",
                entry.spec_section_number, entry.spec_section_title, indexed,
            )
        out.append(entry)
    return out


def section_number_disagreements(entries: list[DocIndexEntry]) -> list[tuple[str, str, str]]:
    """``(filename, indexed number, the number the FILENAME encodes)`` for every disagreement.

    THIS DEFECT CLASS IS SILENT BY CONSTRUCTION. `GP&PP/…-SMM_S28-0.pdf` was indexed as section
    **27** because an amendment lead-in on page 1 out-matched the document's own declaration, and
    nothing anywhere compared the two sources of identity. Bill 9 then asked for measurement section
    28, found none, and the gate reported it missing — a true statement about a false index.

    A cross-check, not a rule: the filename does not overrule page 1 (PS28's page 1 declares nothing
    at all, and the filename is its only evidence — the reverse case). It reports where the two
    disagree so a human can look, which is the only thing that catches the next one.
    """
    out: list[tuple[str, str, str]] = []
    for e in entries:
        if not e.spec_section_number or e.kind in ("appendix", "ps_index"):
            continue     # an appendix's number is its PARENT'S — a disagreement there means nothing
        m = _FILENAME_SECTION.search(_own_name(e.filename))
        if m and (m.group(1).lstrip("0") or m.group(1)) != e.spec_section_number:
            out.append((e.filename, e.spec_section_number, m.group(1).lstrip("0") or m.group(1)))
    return out


# What a filename token says the document's POPULATION is. Only tokens that settle it.
_NAME_KINDS = (
    (lambda n: bool(_FILENAME_APPENDIX.search(n)), ("appendix",)),
    (lambda n: bool(_FILENAME_PS_SECTION.search(n)), ("particular_specification", "appendix")),
    (lambda n: bool(_FILENAME_GS_SECTION.search(n)), ("general_specification",)),
    (lambda n: bool(_METHOD_OF_MEASUREMENT.search(n)), ("method_of_measurement",)),
)


def kind_disagreements(entries: list[DocIndexEntry]) -> list[tuple[str, str, str]]:
    """``(filename, indexed kind, the kind its NAME implies)`` where the two disagree.

    The number cross-check could not catch PS 1: it was indexed as section **1** and its filename
    encodes **1**, so the numbers agreed perfectly. What disagreed was the POPULATION — a
    Particular Specification labelled a Method of Measurement, which then contested the real SMM 1
    for section 1 and superseded it. Two documents sharing a number across two populations must
    never compete, and the only way to notice they are is to check the population too.
    """
    out: list[tuple[str, str, str]] = []
    for e in entries:
        name = _own_name(e.filename)
        for matches, allowed in _NAME_KINDS:
            if matches(name):
                if e.kind not in allowed:
                    out.append((e.filename, e.kind, allowed[0]))
                break        # the first token that settles it is the answer
    return out


def _report_disagreements(entries: list[DocIndexEntry]) -> None:
    for filename, indexed, from_name in section_number_disagreements(entries):
        _log.warning(
            "doc index: %r is indexed as section %s but its filename encodes %s — one of the two "
            "is wrong, and a document indexed under the wrong number is reported MISSING while it "
            "sits in the pack", filename, indexed, from_name,
        )
    for filename, indexed, from_name in kind_disagreements(entries):
        _log.warning(
            "doc index: %r is indexed as %s but its filename says %s — a document in the wrong "
            "population is enclosed under the wrong description AND contests the wrong documents "
            "for its section number", filename, indexed, from_name,
        )


def build_doc_index(docs: list[tuple[str, DocType, bytes]]) -> list[DocIndexEntry]:
    """Index every uploaded original: ``(filename, doc_type, bytes)`` -> entries."""
    return apply_ps_index_titles(
        [build_doc_entry(name, doc_type, data) for (name, doc_type, data) in docs])


class UnrecognisedItem(BaseModel):
    """An extracted item quarantined by the provenance backstop — its section is not one the
    Schedule of Rates itself declares, so it never became a real SoR item. Surfaced, never silently
    dropped, and never formed into a package."""

    item_ref: str
    description: str = ""
    section: str = ""
    reason: str = ""


def quarantine_unrecognised_items(
    scope: ScopePackages, sr_sections: set[str],
) -> tuple[ScopePackages, list[UnrecognisedItem]]:
    """Provenance backstop: drop any extracted item whose section is NOT one of the Schedule of
    Rates' OWN section codes — an item that exists in no SR section never was a real SoR item (a
    phantom from another document's item-like rows). Dropped items are returned FLAGGED — surfaced,
    never silently lost — and a package left with no items is dropped (never routed). Deterministic;
    the caller runs it only when the SR actually declared section headers to check against.

    Lives here, beside ``build_doc_index``, because ``sr_sections`` comes from that index: any
    caller that can build the index can apply the guard, so no ingest path has to ship weaker than
    ``/ingest-upload``.
    """
    from collections import Counter

    kept_packages = []
    unrecognised: list[UnrecognisedItem] = []
    for pkg in scope.packages:
        kept = []
        for it in pkg.sor_items:
            code = (it.section or "").strip().upper()
            if code in sr_sections:
                kept.append(it)
            else:
                unrecognised.append(UnrecognisedItem(
                    item_ref=it.item_ref, description=it.description or "", section=code,
                    reason=f"section {code or '—'} is not a Schedule-of-Rates section",
                ))
        if not kept:
            continue  # the whole package was unrecognised -> never routed
        counts = Counter((it.section or "").strip().upper() for it in kept)
        sections = [m.model_copy(update={"item_count": counts[m.code]}) for m in pkg.sections if counts.get(m.code)]
        kept_packages.append(pkg.model_copy(update={"sor_items": kept, "sections": sections}))
    return scope.model_copy(update={"packages": kept_packages}), unrecognised


# WHICH READER WROTE AN INDEX. Bump this whenever a change alters what indexing PRODUCES — a
# kind, a section number, a title, a page span. Not when selection at dispatch changes: that reads
# the index and can be fixed without rebuilding it.
#
# It exists because an index is written once and read for the life of a tender, and every recent
# fix changed what reading a document yields: the PS Index naming the sections, the amendment
# lead-in that made SMM 28 index itself as 27, PS 1 stealing the Method-of-Measurement slot, the
# bill header whose title came from its own collection footer, section titles taken from the page
# header. An index written before those carries their wrong answers with no way to tell — and the
# gate reported `stale: false`, because "stale" meant only "documents arrived since".
#
# The operator's symptom is "the PS is missing and some documents are not attached", on a tender
# whose index predates the fixes that would have found them. Saying so is the whole point.
DOC_INDEX_READER_VERSION = 6


def _meta_path(path):
    """The sidecar beside ``doc_index.json``.

    A sidecar rather than a header inside the file: `save_doc_index` writes a plain list and
    `load_doc_index` reads one, and adding a wrapper would make every reader learn a new shape to
    answer a question a second small file answers. Its ABSENCE is itself the signal — an index
    written before versioning existed is exactly the one most likely to be stale.
    """
    return path.with_name(path.name.replace(".json", ".meta.json"))


def index_reader_version(workspace, tender_id: str) -> Optional[int]:
    """The reader version that wrote this tender's index, or ``None`` when it predates versioning."""
    try:
        meta = json.loads(_meta_path(workspace.doc_index_path(tender_id)).read_text(encoding="utf-8"))
        value = meta.get("reader_version")
        return int(value) if value is not None else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def save_doc_index(workspace, tender_id: str, entries: list[DocIndexEntry]) -> None:
    path = workspace.doc_index_path(tender_id, create=True)
    path.write_text(json.dumps([e.model_dump() for e in entries], indent=2), encoding="utf-8")
    _meta_path(path).write_text(
        json.dumps({"reader_version": DOC_INDEX_READER_VERSION}, indent=2), encoding="utf-8")


def load_doc_index(workspace, tender_id: str) -> list[DocIndexEntry]:
    """The persisted index, with the cross-document title pass re-applied on READ.

    Re-applied rather than trusted from disk because the pass is deterministic, cheap and
    idempotent, and because an index written before it existed is otherwise stuck: the operator
    would have to re-split a 232 MB pack to get titles that are already sitting in the file. It also
    backfills the provenance a pre-``spec_section_title_source`` index has no column for.

    It cannot repair everything. An index written before the PS table of contents was recognised
    carries no ``ps_index_titles`` at all, so there is nothing to complete a truncated title FROM —
    that one does need a re-split, and the empty lookup makes the pass a no-op rather than a
    plausible guess.
    """
    path = workspace.doc_index_path(tender_id)
    if not path.is_file():
        return []
    try:
        entries = [DocIndexEntry(**d) for d in json.loads(path.read_text(encoding="utf-8"))]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    entries = apply_ps_index_titles(entries)
    _report_disagreements(entries)
    return entries
