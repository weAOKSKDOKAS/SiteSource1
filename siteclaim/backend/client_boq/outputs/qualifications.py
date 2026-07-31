"""T6 — the Letter of Qualifications: the assumptions our price depends on.

Deterministic assembly. Every line traces to a decision already made or a question already asked;
this generator states them, it does not invent them. Three sources, each tagged so no sentence is
free-floating:

* **Confirmed departures** — we priced on our position, not the clause as drafted.
* **Open queries** — we asked and had no answer, so we priced on a stated reading. This is what
  T4 made possible, and it is the honest version of what every contractor does anyway.
* **The approved scope of record** — inclusions and exclusions the human signed off.

Distinct from the Departure Schedule on purpose: **that document is about contract TERMS, this one
is about SCOPE and price**. The same open query legitimately appears in both, answering a
different question each time — "what is still unresolved?" versus "what did we assume in order to
put a number on it?"

Internal by default. Both reference tenders warn that qualifying a tender may disqualify it, so a
submission version is produced only on request and carries that warning quoted from the tender.
"""

from __future__ import annotations

from client_boq import models, store
from client_boq.outputs import AUDIENCE_INTERNAL, AUDIENCE_SUBMISSION
from client_boq.outputs.common import other_flags, qualification_warning, strategy_flags

SOURCE_DEPARTURE = "confirmed departure"
SOURCE_OPEN_QUERY = "unanswered query"
SOURCE_SCOPE = "approved scope"


def collect(set_id: str) -> dict:
    """Every qualification, each carrying the decision it came from."""
    conn = store.get_conn()
    try:
        record = store.load_set(conn, set_id)
        register = store.load_register(conn, set_id)
        scope = store.load_scope(conn, set_id)
        estimate = store.load_estimate(conn, set_id)
        rfis = store.load_rfis(conn, set_id)
        flags = strategy_flags(conn, set_id)
    finally:
        conn.close()
    if record is None:
        return {}

    assumptions: list[dict] = []
    if register is not None:
        for item in register.items:
            if item.status != models.STATUS_CONFIRMED:
                continue
            statement = item.proposed_position or item.amendment_proposal or item.rationale
            if not statement.strip():
                continue
            assumptions.append({
                "source": SOURCE_DEPARTURE, "ref": f"Register item {item.item}",
                "clause": item.clause, "statement": statement,
            })

    # An unanswered question is a priced assumption whether or not anyone writes it down. Writing
    # it down is the whole purpose of this document.
    for rfi in rfis:
        if not rfi.is_open():
            continue
        assumptions.append({
            "source": SOURCE_OPEN_QUERY, "ref": rfi.rfi_id, "clause": rfi.clause,
            "statement": (
                f"Our price assumes a reasonable interpretation of the following, on which we "
                f"sought clarification and had no answer before pricing: {rfi.question}"
            ),
        })

    inclusions, exclusions = [], []
    if scope is not None and scope.draft is not None:
        inclusions = [
            {"source": SOURCE_SCOPE, "statement": text}
            for text in getattr(scope.draft, "inclusions", []) or []
        ]
        exclusions = [
            {"source": SOURCE_SCOPE, "statement": text}
            for text in getattr(scope.draft, "exclusions", []) or []
        ]

    return {
        "set_id": set_id, "project": record["name"], "assumptions": assumptions,
        "inclusions": inclusions, "exclusions": exclusions, "flags": flags,
        "price": (estimate.totals.price if estimate is not None else None),
        "scope_approved": bool(scope and scope.approved),
        "register_approved": bool(register and register.approved),
        "open_queries": sum(1 for r in rfis if r.is_open()),
    }


def render_markdown(set_id: str, audience: str = AUDIENCE_INTERNAL) -> str:
    data = collect(set_id)
    if not data:
        return ""
    internal = audience == AUDIENCE_INTERNAL
    lines = [
        f"# Letter of Qualifications{'  (internal working copy)' if internal else ''}",
        "",
        f"**Project:** {data['project']}",
    ]
    if data["price"] is not None:
        lines.append(f"**Tender sum:** {data['price']:,.2f} (excluding GST)")
    lines.append("")

    if internal:
        warnings = []
        if not data["register_approved"]:
            warnings.append("the review register is not approved")
        if not data["scope_approved"]:
            warnings.append("the scope of record is not approved")
        if warnings:
            lines += [f"> **Not final:** {', and '.join(warnings)}.", ""]
        if data["open_queries"]:
            lines += [
                f"> **{data['open_queries']} query/queries are still with the client.** Each is "
                f"listed below as a priced assumption. If any is answered before submission, "
                f"replace the assumption with the answer.",
                "",
            ]

    lines += qualification_warning(data["flags"], audience)

    if not internal:
        lines += [
            "Dear Sirs,",
            "",
            "Our tender for the above is submitted on the basis of the qualifications set out "
            "below. These qualifications form part of our offer.",
            "",
        ]

    if data["assumptions"]:
        lines += ["## Qualifications and assumptions", ""]
        for index, entry in enumerate(data["assumptions"], start=1):
            citation = f" (clause {entry['clause']})" if entry.get("clause") else ""
            lines.append(f"{index}. {entry['statement']}{citation}")
            if internal:
                lines.append(f"   *source: {entry['source']}, {entry['ref']}*")
        lines.append("")
    else:
        lines += ["## Qualifications and assumptions", "",
                  "None. The tender is priced on the documents as issued.", ""]

    for heading, entries in (("Inclusions", data["inclusions"]),
                             ("Exclusions", data["exclusions"])):
        if entries:
            lines += [f"## {heading}", ""]
            lines += [f"- {e['statement']}" for e in entries]
            lines.append("")

    if not internal:
        lines += ["Yours faithfully,", ""]
    else:
        lines += other_flags(data["flags"])
    return "\n".join(lines)
