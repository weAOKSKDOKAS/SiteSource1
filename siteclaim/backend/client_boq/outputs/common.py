"""Shared pieces for the output generators: the risk banner and the strategy-flag lookup."""

from __future__ import annotations

from client_boq import models, store
from client_boq.outputs import AUDIENCE_SUBMISSION


def strategy_flags(conn, set_id: str) -> list[dict]:
    """Every bidding-strategy condition found across the tender's parts, with its citation."""
    out: list[dict] = []
    for spec, _path, context in store.load_parts(conn, set_id):
        for flag in context.strategy_flags:
            out.append({**flag.model_dump(), "part_id": spec.part_id,
                        "source_doc": spec.source_doc})
    return out


def qualification_warning(flags: list[dict], audience: str) -> list[str]:
    """The banner a submission-bound document carries when the tender penalises qualifications.

    Quoted from the tender itself with its clause and page, so the reader can check it rather
    than take our word for it. Returns markdown lines, or nothing when there is nothing to warn
    about or the document is internal.
    """
    penalising = [f for f in flags if f["kind"] == models.RULE_QUALIFICATIONS_PENALISED]
    lines: list[str] = []
    if audience != AUDIENCE_SUBMISSION:
        return lines
    if not penalising:
        lines += [
            "> **Check before submitting.** No clause penalising qualifications was found in this "
            "tender, but the ingest may not have read every part. Confirm against the conditions "
            "of tender before this document leaves the office.",
            "",
        ]
        return lines

    lines.append("> ## Do not submit this without a decision")
    lines.append("> ")
    lines.append("> This tender penalises qualifying the bid:")
    lines.append("> ")
    for flag in penalising:
        citation = " ".join(part for part in (
            flag.get("clause", ""), f"page {flag['page']}" if flag.get("page") else "",
        ) if part)
        lines.append(f"> *\"{flag['quote']}\"*")
        lines.append("> ")
        lines.append(f"> — {flag.get('source_doc') or 'the tender documents'}"
                     + (f", {citation}" if citation else ""))
        lines.append("> ")
    lines.append("> Submitting this document is a commercial judgement with a real risk attached. "
                 "The safer route for anything still open is a written query before the cut-off, "
                 "where an answer amends the contract for every tenderer.")
    lines.append("")
    return lines


def other_flags(flags: list[dict]) -> list[str]:
    """The remaining strategy conditions, as a short internal briefing."""
    rest = [f for f in flags if f["kind"] != models.RULE_QUALIFICATIONS_PENALISED]
    if not rest:
        return []
    lines = ["## Other tender conditions affecting how this is submitted", ""]
    for flag in rest:
        citation = " ".join(part for part in (
            flag.get("clause", ""), f"page {flag['page']}" if flag.get("page") else "",
        ) if part)
        lines.append(f"- **{flag['kind']}**"
                     + (f" ({citation})" if citation else "")
                     + f': "{flag["quote"]}"')
    lines.append("")
    return lines
