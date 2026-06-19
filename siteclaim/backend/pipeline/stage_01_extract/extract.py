"""Stage 01 — extraction (Layer 2: Claude).

``extract_facts(source) -> ExtractedFacts`` reads messy :class:`SourceMaterial`
and produces typed facts with per-field provenance (confidence + source_span).
The model fills and records; it does not judge the law (that is Stage 02).

Layer 3 grounding is deliberately tight (the ICM principle): only the section(s)
of ``references/sopo_ordinance/overview.md`` that tell the model *which* facts
matter — the s.18 mandatory particulars, scope, and why service/notice facts are
needed — are loaded into the prompt.
"""

import json
from pathlib import Path

from schemas.models import ExtractedFacts, SourceMaterial

from pipeline.llm_client import LLMClient

_OVERVIEW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "references"
    / "sopo_ordinance"
    / "overview.md"
)

_client = LLMClient()


def _load_reference_sections(headings: list[str]) -> str:
    """Return the named ``## `` sections of the SOPO overview (tight grounding)."""
    text = _OVERVIEW_PATH.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = [line]
        elif current is not None:
            sections[current].append(line)
    out: list[str] = []
    for wanted in headings:
        for title, body in sections.items():
            if title.lower().startswith(wanted.lower()):
                out.append("\n".join(body).strip())
                break
    return "\n\n".join(out)


def _grounding() -> str:
    return _load_reference_sections(
        ["What makes a payment claim valid", "Scope"]
    )


_SYSTEM_TEMPLATE = """You are the extraction stage of SiteClaim, a tool that helps Hong Kong \
construction subcontractors draft payment claims under SOPO (the Construction Industry \
Security of Payment Ordinance, Cap. 652).

Your ONLY job is to read the user's messy source material and extract the facts a payment \
claim depends on. You are NOT deciding whether the claim is valid — a deterministic rules \
engine does that next.

Hard rules:
- Extract ONLY facts that are actually present in the source. NEVER invent, guess, or \
infer a value that is not supported by the text.
- For EVERY FactField, set `confidence` in [0,1] reflecting how sure you are, and set \
`source_span` to the exact phrase from the source you read the value from (or null if you \
are inferring/unsure). Leave `value` null when the fact is absent.
- Populate `service` (ServiceDetails) and `payment_response` (PaymentResponseFacts) ONLY \
when the source mentions how/when/on whom the claim was served, or what the respondent did.
- Money is decimal HKD; dates are ISO `YYYY-MM-DD`.
- Return STRICT JSON for the ExtractedFacts schema below. No prose, no markdown, no code fences.

Why these facts matter (SOPO grounding — for your understanding only, do not copy into output):
{grounding}

ExtractedFacts JSON schema:
{schema}
"""


def _system_prompt() -> str:
    schema = json.dumps(ExtractedFacts.model_json_schema(), indent=0)
    return _SYSTEM_TEMPLATE.format(grounding=_grounding(), schema=schema)


def _user_prompt(source: SourceMaterial) -> str:
    files = "\n".join(f"- {f.filename} ({f.content_type})" for f in source.docs.files)
    return (
        "SOURCE MATERIAL\n"
        f"Free-text description:\n{source.description or '(none provided)'}\n\n"
        f"Attached documents:\n{files or '(none)'}\n\n"
        "Extract the ExtractedFacts JSON now."
    )


def extract_facts(source: SourceMaterial) -> ExtractedFacts:
    """Extract typed, provenance-tagged facts from raw source material (Layer 2)."""
    demo_fixture = f"cases/{source.case_id}/extracted.json" if source.case_id else None
    return _client.complete_json(
        system=_system_prompt(),
        user=_user_prompt(source),
        target_model=ExtractedFacts,
        demo_fixture=demo_fixture,
    )
