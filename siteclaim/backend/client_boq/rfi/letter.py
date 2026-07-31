"""Assemble a numbered query letter from a batch of RFIs.

Bucket: **Det (assemble) + AI (covering prose only)**. The questions are the human's own words,
reproduced verbatim; the numbering, the citations and the structure are code. The model writes the
salutation, the opening paragraph and the sign-off, and nothing else — a query letter that
paraphrased the question would ask the client something other than what was meant.
"""

from __future__ import annotations

from client_boq.models import RFIItem, RFILetterDraft
from pipeline.llm_client import LLMClient, demo_mode

DEMO_FIXTURE = "cases/client_boq/rfi_letter.json"

_SYSTEM = (
    "You are a contracts administrator for a construction contractor, writing the covering prose "
    "of a formal tender query letter to the issuing consultant. You write ONLY the salutation, one "
    "short opening paragraph, and a short closing. You never write, restate, summarise or reorder "
    "the questions themselves — those are supplied separately and must reach the client exactly as "
    "written. Keep it plain, courteous and brief. Return ONLY JSON matching the schema."
)

_INSTRUCTION = """Write the covering prose for a tender query letter.

- salutation: e.g. "Dear Sirs,".
- opening: one or two sentences. State that we are tendering for the named contract, that we have
  reviewed the tender documents, and that we should be grateful for clarification of the numbered
  points below before the query cut-off. Do not preview or summarise the questions.
- closing: one sentence asking for a written response, plus a sign-off line.

Context for the letter:
"""


def _cover(project: str, ref: str, count: int) -> RFILetterDraft:
    """The covering prose. Falls back to a plain, correct wrapper if the model is unavailable —
    a query letter must still go out on the day the cut-off falls."""
    client = LLMClient()
    try:
        if demo_mode():
            return client.complete_json(
                system=_SYSTEM, user=_INSTRUCTION, target_model=RFILetterDraft,
                demo_fixture=DEMO_FIXTURE, purpose="client_boq-rfi-letter",
            )
        return client.complete_json(
            system=_SYSTEM,
            user=(
                f"{_INSTRUCTION}\nProject: {project}\nOur reference: {ref}\n"
                f"Number of questions: {count}\n"
            ),
            target_model=RFILetterDraft, purpose="client_boq-rfi-letter",
        )
    except Exception:  # noqa: BLE001 — prose is a nicety; the questions are the letter
        return RFILetterDraft(
            salutation="Dear Sirs,",
            opening=(
                f"We are tendering for {project} and have reviewed the tender documents. "
                f"We should be grateful for your clarification of the {count} point(s) below "
                f"before the query cut-off."
            ),
            closing="We should be grateful for your written response. Yours faithfully,",
        )


def render_letter(project: str, ref: str, items: list[RFIItem]) -> str:
    """The letter as markdown: covering prose, then the questions, numbered and cited.

    Each question carries the clause and page it concerns, so the client can find what is being
    asked about without guessing — the same courtesy the reference tender's own clarification
    letters extend, and the thing that makes an answer matchable when it comes back.
    """
    cover = _cover(project, ref, len(items))
    lines = [
        f"# {ref}",
        "",
        f"**Project:** {project}",
        f"**Number of queries:** {len(items)}",
        "",
        cover.salutation,
        "",
        cover.opening,
        "",
        "## Queries",
        "",
    ]
    for item in items:
        citation = ", ".join(
            part for part in (
                f"Clause {item.clause}" if item.clause else "",
                f"page {item.page}" if item.page else "",
            ) if part
        )
        lines.append(f"**{item.number}.** {citation}" if citation else f"**{item.number}.**")
        if item.context:
            lines.append("")
            lines.append(f"> {item.context}")
        lines.append("")
        lines.append(item.question)      # verbatim, never paraphrased
        lines.append("")
    lines += [cover.closing, ""]
    return "\n".join(lines)
