"""The brain — one strong model that reads everything and PROPOSES, never disposes.

The owner's design, taken as three recorded decisions (docs/client_boq/site_brain_plan.md §1):
one model reads the whole tender and is the place understanding lives; it dispatches focused
reads; and it is **propose-only** — every approval, verdict and number stays a human click.

HOW PROPOSE-ONLY IS ENFORCED — structurally, not by prompt:

* :class:`RawBriefing` (what the model is asked for) has **no field** for a verdict, a rate, a
  class or a gate flag — the same guarantee `DepartureProposal` gives the review. There is
  nowhere to put the thing the brain must not produce.
* A proposed action is only ever an ``action_id`` into :data:`ACTIONS` — a fixed registry of
  screens a person can go to. :func:`validate` drops an id the registry does not carry (and says
  so in ``stripped``), and the TAB the button navigates to comes from the registry, never from
  the model. The brain cannot invent a destination, and the destination is only ever a screen —
  the gated endpoint behind it still takes a human click, with the actor header on it.
* Citations are validated against the ground exactly as the chat's are: a claim citing nothing
  that was supplied is stripped and reported.

The subagent reads are the same model called with a NARROW slice of the ground (one family
each) — legals, scope, site, costing — so each read has room to be thorough, and the synthesis
sees their findings beside the whole ground. Every call carries a ``demo_fixture``: DEMO runs
fully offline, per the plan's fourth decision.
"""

from __future__ import annotations

from pydantic import Field

from client_boq.boq.ask import Citation, Ground
from client_boq.models import NullTolerant

# ---------------------------------------------------------------------------
# The action registry — every move the brain may propose, and where it lives
# ---------------------------------------------------------------------------
#: action_id -> (tab, label). THE WHITELIST IS THE POINT: an action is a reference to a screen,
#: the screen owns the consequential click, and the registry is the only source of destinations.
ACTIONS: dict[str, tuple[str, str]] = {
    "approve_manifest": ("documents", "Approve the split manifest"),
    "upload_correction": ("documents", "Upload a readable copy / correction"),
    "run_review": ("register", "Run (or re-run) the review"),
    "decide_register": ("register", "Decide the open register lines"),
    "answer_rfis": ("register", "Record the client's answers to open queries"),
    "approve_register": ("register", "Approve the departure register"),
    "decide_bid": ("bid", "Take the bid/no-bid decision"),
    "accept_scope_fallbacks": ("scope", "Decide the unaccepted scope fallbacks"),
    "approve_scope": ("scope", "Approve the estimate scope"),
    "confirm_schedule": ("site", "Confirm the station schedule reading"),
    "classify_holes": ("site", "Class the unclassed holes"),
    "register_sheets": ("site", "Register a site-plan sheet (two grid marks)"),
    "pick_road_access": ("site", "Pick the road-access point"),
    "group_holes": ("site", "Group the holes that drill alike"),
    "review_carried_rates": ("price", "Look at the carried rates the revision changed"),
    "decide_conditions": ("price", "Decide the recorded site conditions"),
    "split_rig_moves": ("price", "Price the rig moves per class of site"),
    "settle_sweep": ("price", "Route the sweep's unbilled costs"),
    "price_items": ("price", "Price the unpriced items"),
    "review_offer": ("offer", "Review the offer letter and workbook"),
}


class RawAction(NullTolerant):
    """One proposed next action. An id into the registry, the model's reasoning, and what it
    leans on — NOTHING else. No verdict, no value, no destination of its own."""

    action_id: str = ""
    reasoning: str = ""
    citations: list[Citation] = Field(default_factory=list)


class RawBriefing(NullTolerant):
    """What the model is asked for. Deliberately has no field for a verdict, a rate, a class,
    or a gate flag — there is nowhere to put the kind of output the brain must not produce."""

    understanding: str = ""
    disagreements: list[str] = Field(default_factory=list)
    proposed_actions: list[RawAction] = Field(default_factory=list)
    cannot_assess: str = ""


class Action(NullTolerant):
    """A validated action: the registry supplied the tab and the label, never the model."""

    action_id: str = ""
    tab: str = ""
    label: str = ""
    reasoning: str = ""
    citations: list[Citation] = Field(default_factory=list)


class Briefing(NullTolerant):
    """The validated briefing the store persists and the screen renders."""

    understanding: str = ""
    disagreements: list[str] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    cannot_assess: str = ""
    #: What validation removed, named — a fabricated citation or an invented action reads
    #: exactly like a real one, and the only defence is saying one was removed.
    stripped: list[str] = Field(default_factory=list)
    #: Which ground families each subagent read, and the one-line finding counts — the
    #: briefing's own receipts.
    reads: list[str] = Field(default_factory=list)


class RawFindings(NullTolerant):
    """One focused read's return: findings, each citing the slice it was given."""

    findings: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts + fixtures
# ---------------------------------------------------------------------------
READ_SYSTEM = (
    "You are reading ONE slice of a construction tender's assembled ground for a Hong Kong "
    "contractor's estimating team. Report findings a person should weigh: risks, gaps, "
    "disagreements between sources, and things already decided that later work must respect. "
    "Quote figures only from the ground; cite by the source label in brackets. You have no "
    "authority: no verdicts, no rates, no classifications — findings only."
)

SYNTH_SYSTEM = (
    "You are the tender's brain: you read EVERYTHING the tender knows and produce a briefing "
    "for the person running it. Three parts. UNDERSTANDING: what this tender is and where it "
    "stands, in plain prose, citing source labels. DISAGREEMENTS: every place two sources are "
    "in tension (a bill count against a schedule count, a condition against a register line). "
    "PROPOSED ACTIONS: the next moves, EACH as an action_id chosen ONLY from the registry "
    "below, with your reasoning and citations. You cannot approve, decide, price or classify "
    "anything — every action is a screen a person will open, and the registry is the complete "
    "list of destinations. An action_id not in the registry will be discarded.\n\n"
    "THE REGISTRY:\n"
    + "\n".join(f"  {action_id} — {label}" for action_id, (_tab, label) in ACTIONS.items())
)

#: One fixture per call the orchestrator makes — DEMO runs fully offline (plan §1 decision 4).
READ_FIXTURES = {
    "legals": "cases/client_boq/brain_read_legals.json",
    "scope": "cases/client_boq/brain_read_scope.json",
    "site": "cases/client_boq/brain_read_site.json",
    "costing": "cases/client_boq/brain_read_costing.json",
}
SYNTH_FIXTURE = "cases/client_boq/brain_briefing.json"

#: Which ground families each focused read receives. Narrow on purpose: a read with room to be
#: thorough beats one model drowning in everything at once — and the synthesis still sees all.
READ_SLICES = {
    "legals": {"meta", "gates", "register", "summary", "parts", "rfis"},
    "scope": {"meta", "gates", "scope", "parts", "rfis"},
    "site": {"meta", "site", "photos", "conditions", "log"},
    "costing": {"meta", "gates", "costing", "bill", "sweep", "conditions"},
}


def synthesis_user(ground: Ground, findings: dict[str, "RawFindings"]) -> str:
    """The synthesis call's user message: the whole ground, then each read's findings."""
    blocks = [ground.as_prompt()]
    for name, found in findings.items():
        if not found.findings:
            continue
        blocks.append(f"FINDINGS FROM THE {name.upper()} READ:\n"
                      + "\n".join(f"  - {f[:500]}" for f in found.findings[:20]))
    blocks.append("Produce the briefing.")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Validation — the anti-laundering pass, same contract as the chat's
# ---------------------------------------------------------------------------
def validate(raw: dict, ground: Ground) -> Briefing:
    """Strip what the ground cannot support and what the registry does not carry — loudly."""
    briefing = Briefing(
        understanding=str(raw.get("understanding") or ""),
        disagreements=[str(d) for d in (raw.get("disagreements") or []) if str(d).strip()],
        cannot_assess=str(raw.get("cannot_assess") or ""),
    )
    for entry in raw.get("proposed_actions") or []:
        entry = entry if isinstance(entry, dict) else {}
        action_id = str(entry.get("action_id") or "").strip()
        registered = ACTIONS.get(action_id)
        if registered is None:
            briefing.stripped.append(
                f"a proposed action was removed: {action_id or '(no id)'!r} is not in the "
                f"registry — the brain cannot invent a destination")
            continue
        tab, label = registered
        citations, dropped = _grounded_citations(entry.get("citations") or [], ground)
        briefing.stripped.extend(dropped)
        briefing.actions.append(Action(
            action_id=action_id, tab=tab, label=label,
            reasoning=str(entry.get("reasoning") or ""), citations=citations))
    return briefing


def _grounded_citations(entries: list, ground: Ground) -> tuple[list[Citation], list[str]]:
    kept: list[Citation] = []
    dropped: list[str] = []
    for entry in entries:
        entry = entry if isinstance(entry, dict) else {}
        source = str(entry.get("source") or "")
        if source in ground.sources:
            kept.append(Citation(source=source, quote=str(entry.get("quote") or "")[:400]))
        else:
            dropped.append(
                f"a citation was removed: {source or '(no source)'!r} is not among the "
                f"sources that were supplied")
    return kept, dropped
