"""BOQ — the specification's own index, turned into a lookup.

Bucket: **Deterministic**. A parser over a table of contents; no model, no inference.

WHY THIS EXISTS
---------------
Pricing one bill line means reading the clauses that govern it, and a Particular Specification runs to
a dozen sections and forty-odd appendices. Reading it end to end is not the job; finding the eight
clauses that bear on *drilling* is.

The specification already carries the map — a clause-level table of contents with page references, and
unlike the drawings it is real text:

    SECTION 7   GEOTECHNICAL WORKS
      7.01A  Access scaffolding                                            PS7/1
      7.01B  Moving Rigs                                                   PS7/2
      7.07B  Groundwater ...                                               PS7/2

Parsed once, it resolves a clause reference to a section, a title and a page — so when the Method of
Measurement's item coverage cites ``PS Clause 7.30S``, the app can put that page on screen instead of
leaving somebody to hunt for it.

That is the whole contribution: the chain **bill item → item coverage → cited clause → page** is
mechanical at every step, so walking it is exactly the dull, reliable work worth automating.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

# "SECTION 7" on its own line, with the section title on the next non-empty one.
_SECTION = re.compile(r"^SECTION\s+(\d+[A-Z]?)$", re.IGNORECASE)
# "7.01B", "1.12E", "2.09", "7.279C" — a clause. Also "Appendix 1.21A".
_CLAUSE = re.compile(r"^(\d+\.\d+[A-Z]*)$")
_APPENDIX = re.compile(r"^(Appendix\s+[\d.]+[A-Z]?)$", re.IGNORECASE)
# "PS7/2", "PS1/14", "PSA1.23/ 1" — a page reference, which terminates an entry.
_PAGE = re.compile(r"^(PS[A-Z]?[\d.]*\s*/\s*\d+)$", re.IGNORECASE)


class ClauseEntry(BaseModel):
    """One line of the index."""

    ref: str = ""                 # "7.01B" or "Appendix 1.12"
    title: str = ""
    page: str = ""                # "PS7/2"; blank where the index prints none
    section: str = ""             # "7"
    section_title: str = ""       # "GEOTECHNICAL WORKS"

    def document_hint(self) -> str:
        """Which specification file this clause lives in, from its page reference.

        ``PS7/2`` → ``PS7``; ``PSA1.12/3`` → ``PSA1.12``. Used to open the right file, and honest about
        being a hint: the index prints no page for some entries.
        """
        if not self.page:
            return f"PS{self.section}" if self.section else ""
        return self.page.split("/")[0].strip()


class DocumentMap(BaseModel):
    """The parsed index, and whatever could not be parsed."""

    source: str = ""
    entries: list[ClauseEntry] = Field(default_factory=list)
    sections: dict[str, str] = Field(default_factory=dict)     # "7" -> "GEOTECHNICAL WORKS"
    notes: list[str] = Field(default_factory=list)

    def index(self) -> dict[str, ClauseEntry]:
        return {entry.ref.upper(): entry for entry in self.entries}

    def resolve(self, ref: str) -> Optional[ClauseEntry]:
        """Find a clause by reference, tolerating the ways a document cites one.

        ``PS Clause 7.30S``, ``clause 7.30S``, ``7.30S`` and ``7.30`` all reach the same place — the
        last by falling back to the nearest parent, because a citation to ``7.30`` when the index only
        lists ``7.30S`` should not come back empty.
        """
        cleaned = re.sub(r"^\s*(ps\s+)?clause\s+", "", ref.strip(), flags=re.IGNORECASE).strip()
        cleaned = cleaned.rstrip(".,;:").upper()
        direct = self.index().get(cleaned)
        if direct is not None:
            return direct
        # A citation to the numbered parent of a lettered clause.
        candidates = [e for e in self.entries if e.ref.upper().startswith(cleaned)]
        return sorted(candidates, key=lambda e: len(e.ref))[0] if candidates else None

    def in_section(self, section: str) -> list[ClauseEntry]:
        return [e for e in self.entries if e.section == str(section)]


def parse_index(text: str, *, source: str = "") -> DocumentMap:
    """Parse a Particular Specification table of contents.

    The layout is ``ref`` / ``title`` (possibly wrapped over lines) / ``page``. An entry with no page
    is kept, not dropped — the index genuinely prints none for some appendices, and losing them would
    make the map quietly incomplete.
    """
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("[BLANK")]

    document = DocumentMap(source=source)
    section = section_title = ""
    pending_ref = ""
    title_parts: list[str] = []
    awaiting_section_title = False

    def flush(page: str = "") -> None:
        nonlocal pending_ref, title_parts
        if pending_ref:
            document.entries.append(ClauseEntry(
                ref=pending_ref, title=" ".join(title_parts).strip(), page=page,
                section=section, section_title=section_title))
        pending_ref, title_parts = "", []

    for line in lines:
        matched_section = _SECTION.match(line)
        if matched_section:
            flush()
            section = matched_section.group(1)
            section_title = ""
            awaiting_section_title = True
            continue

        if awaiting_section_title:
            # The line after "SECTION 7" is its title, unless it is already the next clause.
            awaiting_section_title = False
            if not (_CLAUSE.match(line) or _APPENDIX.match(line)):
                section_title = line
                document.sections[section] = section_title
                continue
            document.sections[section] = ""

        matched_page = _PAGE.match(line)
        if matched_page and pending_ref:
            flush(re.sub(r"\s+", "", matched_page.group(1)))
            continue

        matched_ref = _CLAUSE.match(line) or _APPENDIX.match(line)
        if matched_ref:
            flush()                       # the previous entry simply had no page printed
            pending_ref = re.sub(r"\s+", " ", matched_ref.group(1)).strip()
            continue

        if pending_ref:
            title_parts.append(line)
        # Anything else is a running header or a part/heading banner; carried in neither direction.

    flush()

    if not document.entries:
        document.notes.append(
            "no clause entries found — the index may be a scan rather than text, or laid out "
            "differently on this contract")

    # Two sections carrying the same banner is a defect in the index, not in the reading of it. It
    # happens: on the reference contract SECTION 28 is headed "PAYMENT OF WAGES OF THE SITE WORKERS",
    # which is section 29's title, while its own clauses (28.02 "Particulars of Environmental Ground
    # Investigation", 28.05 "Environmental Borehole Drilling") and the contents page both say
    # Environmental Ground Investigation. Reported rather than silently corrected — guessing which of
    # the client's two statements is the true one is not this parser's job.
    seen: dict[str, str] = {}
    for number, title in document.sections.items():
        if not title:
            continue
        if title in seen:
            document.notes.append(
                f"sections {seen[title]} and {number} are both headed {title!r} in the index. One of "
                f"them is mislabelled — check the clauses beneath each against the contents page")
        else:
            seen[title] = number

    return document
