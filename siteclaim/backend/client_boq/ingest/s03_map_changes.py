"""INGEST stage 03 — read an addendum and propose which parts it supersedes.

Bucket: **AI propose -> GATE**. An addendum arrives as a covering letter carrying a table of
changes, plus the replacement documents themselves. This stage reads both and proposes a mapping
from each replacement file to the part it supersedes. It commits nothing.

Two rules, both taken from the real package rather than from first principles:

* **The change table is advisory.** Tender Addendum No.1 of ND/2025/04 states its own remarks
  are "neither exhaustive nor guaranteed to be accurate" and that the tenderer must check the
  actual replacement pages. So the extracted table navigates a human to the right pages; the
  replacement document is the authority. The gate shows both.
* **An unmatched replacement is surfaced, never guessed.** Attaching a replacement to the wrong
  part would silently supersede a document nobody amended, which is worse than asking.
"""

from __future__ import annotations

from client_boq.ingest import pdfops
from client_boq.models import AddendumPlan, PartSpec, ProposedMapping
from pipeline.llm_client import LLMClient, demo_mode
from client_boq.llm import make_client


def _unmatched(filename: str) -> ProposedMapping:
    """An explicit 'no match proposed' row, so an unmapped file is still visible at the gate."""
    return ProposedMapping(
        filename=filename, part_id="",
        reason="no match proposed; map this to a part by hand or it will not be applied",
    )

DEMO_FIXTURE = "cases/client_boq/ingest_addendum_plan.json"

# Enough of each document to identify it. An addendum replacement announces itself on its first
# page; reading further is paying to confirm what the header already said.
HEAD_CHARS = 1500

_SYSTEM = (
    "You are a construction tender document analyst. A tender addendum has been issued against a "
    "tender you already hold. You are given the addendum letter, the replacement documents it "
    "shipped, and the parts of the tender as currently held. You report what the addendum says it "
    "changed, and which held part each replacement file supersedes. "
    "You never decide that a change is acceptable, and you never guess a match. "
    "Return ONLY JSON matching the schema."
)

_INSTRUCTION = """Read this addendum and map its replacement documents onto the parts we hold.

Return:
- ref: the addendum's own reference, as printed, e.g. "Tender Addendum No. 1".
- changes: one entry per row of the addendum's own table of changes, with the document it names,
  the pages it names as printed, and what it says changed. Copy what the addendum says. Do not
  interpret, correct, or expand it.
- mappings: one entry per REPLACEMENT FILE listed below, giving the part_id of the held part it
  supersedes. Match on the document's identity — its title, its reference, its numbering — not on
  the order the files happen to be listed in. If nothing matches with confidence, leave part_id
  empty and say why in reason. An empty part_id is a correct and useful answer.
- notes: anything a human checking this mapping should know.

=== THE TENDER AS WE HOLD IT ===
"""


def _digest(parts: list[PartSpec], letter_text: str,
            replacements: list[tuple[str, str]]) -> str:
    lines = ["parts currently held:"]
    for part in parts:
        lines.append(
            f"  part_id={part.part_id}  rev={part.rev}  category={part.category}  "
            f"pages={part.start}-{part.end}  source={part.source_doc}  title={part.title}"
        )
    lines += ["", "=== THE ADDENDUM LETTER ===", letter_text[:12000] or "(no readable letter)"]
    lines += ["", "=== REPLACEMENT FILES SHIPPED WITH IT ==="]
    for filename, head in replacements:
        lines.append(f"\n--- {filename} ---\n{head}")
    return "\n".join(lines)


def plan_addendum(
    parts: list[PartSpec],
    letter: tuple[str, bytes] | None,
    replacements: list[tuple[str, bytes]],
    ref: str = "",
) -> AddendumPlan:
    """Propose what the addendum changed and which parts its replacements supersede.

    Degrades rather than fails: if the planning call returns nothing usable, every replacement
    comes back unmatched for the human to map by hand, which is a slower gate but never a lost
    addendum.
    """
    client = make_client()  # app-wide model setting applied here (client_boq/llm.py)

    if demo_mode():
        plan = client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION, target_model=AddendumPlan,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-ingest-addendum",
        )
    else:
        letter_text = ""
        if letter is not None:
            letter_text = pdfops.page_text(letter[1], 1, 20)
        heads = [
            (filename, pdfops.page_text(data, 1, 2)[:HEAD_CHARS])
            for filename, data in replacements
        ]
        plan = client.complete_json(
            system=_SYSTEM,
            user=_INSTRUCTION + _digest(parts, letter_text, heads),
            target_model=AddendumPlan, purpose="client_boq-ingest-addendum",
        )

    known = {part.part_id for part in parts}
    supplied = [filename for filename, _data in replacements]

    # Keep only mappings that name a file we actually received and a part we actually hold. A
    # mapping onto something that does not exist is not a near miss to be repaired; it is a
    # proposal to supersede the wrong document.
    cleaned = []
    for mapping in plan.mappings:
        if mapping.filename not in supplied:
            continue
        if mapping.part_id and mapping.part_id not in known:
            mapping = mapping.model_copy(update={
                "part_id": "",
                "reason": (mapping.reason + " (proposed a part this set does not hold)").strip(),
            })
        cleaned.append(mapping)

    # Every replacement must appear at the gate, matched or not, or a file could be uploaded and
    # then quietly dropped.
    seen = {mapping.filename for mapping in cleaned}
    for filename in supplied:
        if filename not in seen:
            cleaned.append(_unmatched(filename))

    return plan.model_copy(update={"ref": plan.ref or ref, "mappings": cleaned})
