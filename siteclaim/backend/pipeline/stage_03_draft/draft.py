"""Stage 03 — drafting (Layer 2: Claude, grounded in the CIC template + s.18).

``draft_claim(facts, validity) -> ClaimDraft`` produces a payment-claim document:
structured fields (mapped straight from the typed facts) plus a human-presentable
``rendered_markdown`` formatted like a real claim.

Behaviour (baked into the live system prompt AND the offline renderer):
  * Use ONLY facts from ExtractedFacts. A missing or low-confidence mandatory field
    becomes a clearly marked ``[⚠️ … — confirm before filing]`` placeholder, never
    invented content.
  * Respect the ValidityReport: a FATAL check puts a prominent "NOT FILEABLE" banner
    at the top of the document, stating the claim is not yet fileable and why. The
    LLM does NOT re-judge the law — the findings are passed in as constraints.
  * Formal, legal-document register; English.

DEMO_MODE renders deterministically from the typed facts (drafting from structured
facts is deterministic templating — no network, no canned fixture). The live path
uses the LLM for natural-language drafting quality.

TODO(i18n): support Traditional Chinese (bilingual zh-HK) output in a later phase —
many HK subcontractors will want a bilingual claim. Do NOT implement now.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

from rules_engine import sopo_config
from schemas.models import ClaimDraft, ExtractedFacts, FactField, Severity, ValidityReport

from pipeline.llm_client import LLMClient, demo_mode

_REFS = Path(__file__).resolve().parent.parent.parent / "references"
_TEMPLATE_PATH = _REFS / "cic_templates" / "payment_claim_template.md"
_OVERVIEW_PATH = _REFS / "sopo_ordinance" / "overview.md"

_THRESHOLD = sopo_config.CONFIDENCE_REVIEW_THRESHOLD
_STATUTORY_STATEMENT = (
    "This payment claim is made under the Construction Industry Security of Payment "
    "Ordinance (Cap. 652)."
)
_PLACEHOLDER_PREFIX = "[⚠️"

_client = LLMClient()


# ---------------------------------------------------------------------------
# Cell helpers — render a FactField as text, or a flagged placeholder
# ---------------------------------------------------------------------------
def _hkd(amount: Decimal) -> str:
    return f"HKD {amount:,.2f}"


def _cell(field: FactField, label: str, fmt: Callable[[object], str] = str) -> str:
    """Render a FactField value, or a placeholder if missing / low-confidence."""
    if field.value is None:
        return f"{_PLACEHOLDER_PREFIX} MISSING: {label} — confirm before filing]"
    if field.confidence < _THRESHOLD:
        return f"{_PLACEHOLDER_PREFIX} UNVERIFIED ({field.confidence:.2f}): {fmt(field.value)} — {label}; confirm before filing]"
    return fmt(field.value)


def _party_cell(field: FactField, label: str) -> str:
    if field.value is None:
        return f"{_PLACEHOLDER_PREFIX} MISSING: {label} — confirm before filing]"
    name = field.value.name
    if field.confidence < _THRESHOLD:
        return f"{_PLACEHOLDER_PREFIX} UNVERIFIED ({field.confidence:.2f}): {name} — {label}; confirm before filing]"
    return name


def _is_placeholder(cell: str) -> bool:
    return cell.startswith(_PLACEHOLDER_PREFIX)


# ---------------------------------------------------------------------------
# Structured fields (deterministic mapping from facts)
# ---------------------------------------------------------------------------
def _structured(facts: ExtractedFacts) -> ClaimDraft:
    claimant = facts.parties.claimant.value
    respondent = facts.parties.respondent.value
    contract_reference = None
    if claimant and respondent:
        contract_reference = f"Subcontract between {claimant.name} and {respondent.name}"
    basis = "Sum of the itemised particulars below." if facts.line_items else None
    return ClaimDraft(
        claimant_name=claimant.name if claimant else None,
        respondent_name=respondent.name if respondent else None,
        contract_reference=contract_reference,
        reference_date=facts.reference_date.value,
        claimed_amount=facts.claimed_amount.value,
        currency="HKD",
        line_items=list(facts.line_items),
        basis_of_calculation=basis,
        statutory_statement=_STATUTORY_STATEMENT,
        supporting_doc_refs=list(facts.supporting_doc_refs),
        rendered_markdown="",  # set by _render_markdown
    )


def _fatal_checks(validity: ValidityReport):
    return [c for c in validity.checks if c.severity is Severity.FATAL and not c.passed]


def _banner(validity: ValidityReport, placeholder_count: int) -> str:
    fatals = _fatal_checks(validity)
    if fatals:
        lines = [
            "> # ⛔ NOT FILEABLE",
            "> **This claim has a fatal defect and must NOT be served as-is.** Fix the following first:",
            ">",
        ]
        for c in fatals:
            lines.append(f"> - **{c.name}** (`{c.sopo_reference}`): {c.explanation}")
        return "\n".join(lines)
    if placeholder_count:
        return (
            f"> ## ⚠️ DRAFT — not ready to file\n"
            f"> {placeholder_count} mandatory field(s) are missing or low-confidence "
            f"(marked `{_PLACEHOLDER_PREFIX} …]` below). Confirm them before serving."
        )
    return (
        "> ## ✅ Ready for review\n"
        "> No fatal defects; all mandatory fields are present and confident. "
        "A person must still approve this before it is served (Stage 05)."
    )


def _deadline_note(validity: ValidityReport) -> str:
    ds = validity.deadlines
    if ds is None or not ds.deadlines:
        return ""
    soonest = min(ds.deadlines, key=lambda d: d.due_date)
    return (
        f"\n*Key deadline: **{soonest.name.replace('_', ' ')}** by **{soonest.due_date}** "
        f"({soonest.business_days_remaining:+d} business days). See the full deadline set.*"
    )


def _line_items_table(facts: ExtractedFacts) -> str:
    if not facts.line_items:
        return f"{_PLACEHOLDER_PREFIX} MISSING: itemised particulars — confirm before filing]"
    rows = [
        "| # | Description | Qty | Unit | Rate | Amount (HKD) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, li in enumerate(facts.line_items, start=1):
        amount = f"{li.amount:,.2f}" if li.amount is not None else "—"
        rows.append(
            f"| {i} | {li.description} | {li.quantity or '—'} | {li.unit or '—'} | {li.rate or '—'} | {amount} |"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Rendered markdown document
# ---------------------------------------------------------------------------
def _render_markdown(facts: ExtractedFacts, validity: ValidityReport, draft: ClaimDraft) -> str:
    cells = {
        "reference_date": _cell(facts.reference_date, "reference date"),
        "claimant": _party_cell(facts.parties.claimant, "claimant"),
        "respondent": _party_cell(facts.parties.respondent, "respondent"),
        "contract_sum": _cell(facts.contract_sum, "contract sum", _hkd),
        "work_period": _cell(
            facts.work_period,
            "claim period (work period)",
            lambda wp: f"{wp.start or '?'} to {wp.end or '?'}",
        ),
        "claimed_amount": _cell(facts.claimed_amount, "claimed amount", _hkd),
        "served_on": _cell(facts.service.served_on, "party served on"),
        "service_method": _cell(facts.service.method, "method of service"),
        "date_served": _cell(facts.service.date_served, "date of service"),
    }
    contract_id = draft.contract_reference or f"{_PLACEHOLDER_PREFIX} MISSING: contract identification — confirm before filing]"
    if facts.parties.claimant.value is None or facts.parties.respondent.value is None:
        contract_id = f"{_PLACEHOLDER_PREFIX} MISSING: contract identification — confirm before filing]"

    placeholder_count = sum(1 for v in cells.values() if _is_placeholder(v))
    if _is_placeholder(contract_id):
        placeholder_count += 1

    claimant_role = facts.parties.claimant.value.role if facts.parties.claimant.value else ""
    respondent_role = facts.parties.respondent.value.role if facts.parties.respondent.value else ""
    contract_type = facts.contract_type.value.value if facts.contract_type.value else "—"
    docs = "\n".join(f"  {i}. {ref}" for i, ref in enumerate(facts.supporting_doc_refs, 1)) or (
        f"{_PLACEHOLDER_PREFIX} MISSING: supporting documents — attach and index before filing]"
    )
    claim_date = facts.service.date_served.value or facts.reference_date.value or draft.generated_at.date()

    md = [
        _banner(validity, placeholder_count),
        "",
        "---",
        "",
        "# PAYMENT CLAIM",
        "**Made under the Construction Industry Security of Payment Ordinance (Cap. 652)**",
        "",
        f"**Date of this claim:** {claim_date}  ",
        f"**Reference date:** {cells['reference_date']}",
        "",
        "## 1. Parties",
        "",
        "| | Name | Role |",
        "| --- | --- | --- |",
        f"| **Claimant** | {cells['claimant']} | {claimant_role or '—'} |",
        f"| **Respondent** | {cells['respondent']} | {respondent_role or '—'} |",
        "",
        "## 2. The contract",
        "",
        f"- **Contract identification:** {contract_id}",
        f"- **Contract type:** {contract_type}",
        f"- **Contract sum:** {cells['contract_sum']}",
        f"- **Work period covered by this claim:** {cells['work_period']}",
        "",
        "## 3. Amount claimed",
        "",
        f"> **Total claimed (this claim): {cells['claimed_amount']}**",
        "",
        "## 4. Particulars and basis of calculation",
        "",
        f"{draft.basis_of_calculation or (_PLACEHOLDER_PREFIX + ' MISSING: basis of calculation — confirm before filing]')}",
        "",
        _line_items_table(facts),
        "",
        "## 5. Supporting documents",
        "",
        docs,
        "",
        "## 6. Statutory statement",
        "",
        f"> {draft.statutory_statement}",
        "",
        "## 7. Service",
        "",
        f"- **Served on:** {cells['served_on']}",
        f"- **Method of service:** {cells['service_method']}",
        f"- **Date served:** {cells['date_served']}",
        "",
        "---",
        "",
        "*Generated by SiteClaim as a DRAFT for human review (Stage 05). Not legal advice; "
        "not served until approved.*"
        + _deadline_note(validity),
        "*TODO(i18n): a Traditional Chinese (bilingual) rendering is planned for a later phase.*",
    ]
    return "\n".join(md)


def _render_demo_draft(facts: ExtractedFacts, validity: ValidityReport) -> ClaimDraft:
    draft = _structured(facts)
    draft.rendered_markdown = _render_markdown(facts, validity, draft)
    return draft


# ---------------------------------------------------------------------------
# Live (LLM) path — system / user prompts; unexercised in DEMO_MODE
# ---------------------------------------------------------------------------
def _s18_section() -> str:
    text = _OVERVIEW_PATH.read_text(encoding="utf-8")
    out: list[str] = []
    grabbing = False
    for line in text.splitlines():
        if line.startswith("## "):
            grabbing = line[3:].strip().lower().startswith("what makes a payment claim valid")
        if grabbing:
            out.append(line)
    return "\n".join(out).strip()


def _system_prompt() -> str:
    return (
        "You are the drafting stage of SiteClaim. Draft a Hong Kong SOPO (Cap. 652) "
        "payment claim from the supplied facts, following the CIC template's structure and "
        "including every mandatory particular.\n\n"
        "Rules:\n"
        "- Use ONLY the supplied facts. NEVER invent content. If a mandatory field is missing "
        f"or low-confidence (confidence < {_THRESHOLD}), insert a clearly marked placeholder "
        "like '[⚠️ MISSING: claim period — confirm before filing]'.\n"
        "- You do NOT judge the law. The ValidityReport is a CONSTRAINT: if it has any fatal "
        "check, put a prominent 'NOT FILEABLE' banner at the very top stating the claim is not "
        "yet fileable and why (quote the fatal checks).\n"
        "- Produce BOTH the structured ClaimDraft fields AND a rendered_markdown document "
        "(header, parties, contract identification, amount claimed, itemised particulars, "
        "supporting-document index, statutory statement, service, date).\n"
        "- Formal legal-document register, English. Return STRICT JSON for the ClaimDraft schema.\n\n"
        "CIC payment-claim template (follow this structure):\n"
        f"{_TEMPLATE_PATH.read_text(encoding='utf-8')}\n\n"
        "Mandatory-particulars grounding (s.18):\n"
        f"{_s18_section()}\n\n"
        "ClaimDraft JSON schema:\n"
        f"{json.dumps(ClaimDraft.model_json_schema(), indent=0)}"
    )


def _validity_constraints(validity: ValidityReport) -> str:
    fatals = _fatal_checks(validity)
    warnings = [c for c in validity.checks if c.severity is Severity.WARNING]
    lines = [f"has_fatal={validity.has_fatal}"]
    for c in fatals:
        lines.append(f"FATAL {c.name} ({c.sopo_reference}): {c.explanation}")
    for c in warnings:
        lines.append(f"WARNING {c.name} ({c.sopo_reference}): {c.explanation}")
    return "\n".join(lines)


def _user_prompt(facts: ExtractedFacts, validity: ValidityReport) -> str:
    return (
        "EXTRACTED FACTS:\n"
        f"{facts.model_dump_json(indent=2)}\n\n"
        "VALIDITY CONSTRAINTS (do not re-derive; treat as given):\n"
        f"{_validity_constraints(validity)}\n\n"
        "Draft the ClaimDraft JSON now."
    )


def draft_claim(facts: ExtractedFacts, validity: ValidityReport) -> ClaimDraft:
    """Draft a payment claim (structured + rendered_markdown) from validated facts."""
    if demo_mode():
        return _render_demo_draft(facts, validity)
    return _client.complete_json(
        system=_system_prompt(),
        user=_user_prompt(facts, validity),
        target_model=ClaimDraft,
    )
