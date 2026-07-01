"""Load and fuse the real CIC Registered Subcontractors register (CSV) with the
curated records (offers, awards, enforcement flags).

The CSV (``seed_data/source/RSRC_01_combined.csv``) is the authoritative real
register: one firm per row, each with a real enquiry e-mail and its registered
trades. This module parses it (BOM + CRLF + quoted fields handled by the stdlib
``csv`` reader with ``utf-8-sig``), maps the CIC trade groups/specialties onto the
platform taxonomy, writes a short factual description, and **merges** the curated
firms (Sixense / Kai Wai / Gold Ram / DrilTech and the enforcement-flagged firms)
onto their matching register row by company name — so a curated firm keeps its
``firm_id``, flags, awards and offer while gaining the register's e-mail/BR/address.

Curated firms that are not on the register (e.g. an enforcement-flagged firm that
isn't a registered subcontractor, or the two specialist GI firms) are kept as their
own ``public_register`` rows — the risk/offer overlay. Plain curated rows with no
flags and no offer are dropped, superseded by the real register.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from rules_engine.taxonomy import normalize as _normalize_trade

# The four curated demo firms always survive (their offers drive the drainage demo),
# even when they are not present on the CIC register.
DEMO_FIRM_IDS = {
    "sixense-limited-5d2c",
    "kai-wai-engineering-survey-and-geophysics-limited-3f7b",
    "gold-ram-engineering-development-limited-9bbd",
    "driltech-ground-engineering-limited-a721",
}

# CIC trade group (the words after the dotted code) -> canonical taxonomy key.
_GROUP_CANONICAL = {
    "foundation and piling": "foundation_substructure",
    "general civil works": "external_works",  # refined by specialty below
    "other structural and civil trades": "structural",
    "electrical": "electrical",
    "shutters/doors fabrication and installation": "joinery_fitting_out",
    "other e&m trades": "mechanical_plumbing",
    "joinery and carpentry": "joinery_fitting_out",
    "window fabrication and installation": "joinery_fitting_out",
    "marble, granite and stone work": "builders_work",
    "heating, ventilation, and air-conditioning": "mechanical_plumbing",
    "temporary protective and safety measures": "builders_work",
    "miscellaneous cleaning services": "external_works",
    "lift and escalators": "mechanical_plumbing",
    "fire services installation": "fire_services",
    "other finishing trades and components": "builders_work",
}

_NOTABLE_SPECIALTIES = ("ground investigation", "road drainage and sewer", "geophysical", "ground penetrating radar")


def norm_name(name: str | None) -> str:
    """Normalised join key: lowercase alphanumerics only."""
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "firm"


def expand_trades(canon: set[str]) -> set[str]:
    """A ground-investigation firm does the GI *field work* — field testing and field
    installations — so it is discoverable across those two sub-trades. Geophysical
    survey is **not** implied by ground investigation: it comes only from a genuine
    geophysical specialty (see :func:`_canonical_for`), so the geophysical pool stays
    the firms that actually do that work rather than every GI contractor."""
    canon = set(canon)
    if "ground_investigation" in canon:
        canon |= {"field_testing", "field_installations"}
    return canon


def _canonical_for(group: str, specialty: str) -> set[str]:
    """Map one registered "group :: specialty" onto the platform taxonomy. The
    specialty drives the mapping so each firm lands in the sections it genuinely does:
    geophysical methods -> geophysical_survey; GI field work -> ground_investigation
    (then field testing + installations via :func:`expand_trades`); soil/rock and
    materials testing -> field_testing; drainage/sewer -> a *separate* drainage_works
    trade; geotechnical works -> its own geotechnical_works trade. None of drainage or
    geotechnical works is routed into the three GI sections."""
    g, s = group.strip().lower(), specialty.strip().lower()
    out: set[str] = set()
    base = _GROUP_CANONICAL.get(g)
    if base:
        out.add(base)
    # genuine geophysical methods -> geophysical_survey (and ONLY these)
    if any(k in s for k in ("geophys", "penetrating radar", "gpr", "resistivity", "seismic", "televiewer")):
        out.add("geophysical_survey")
    # ground investigation field work -> field testing + field installations (via expand)
    if "ground investigation" in s:
        out.add("ground_investigation")
    # laboratory / in-situ testing -> field testing
    if any(k in s for k in (
        "soil and rock testing", "construction materials testing", "materials testing",
        "loading test", "pile loading test",
    )):
        out.add("field_testing")
    # drainage / sewer -> its own trade, never a GI section
    if "road drainage" in s or "sewer" in s or "drainage" in s:
        out.add("drainage_works")
    # geotechnical works -> its own trade (do NOT auto-route into the GI sections)
    if "geotechnical works" in s:
        out.add("geotechnical_works")
    if not out:  # fall back to the taxonomy normaliser, then a general-civil default
        n = _normalize_trade(group) or _normalize_trade(specialty)
        out.add(n or "external_works")
    return out


def direct_trades(registered: list[dict]) -> set[str]:
    """The canonical trades a firm's **registered specialties** map to *directly*,
    before the ground-investigation discovery expansion. Used by the shortlist scorer
    to tell an exact specialty match (e.g. a materials-testing lab in field_testing)
    from an incidental one (a GI contractor surfaced in field_testing via expansion)."""
    out: set[str] = set()
    for rt in registered or []:
        out |= _canonical_for(rt.get("group", ""), rt.get("specialty", ""))
    return out


def parse_trades(raw: str) -> tuple[list[dict], list[str]]:
    """Parse the pipe-separated "Code :: Specialty" cell into structured trades and
    the canonical taxonomy keys (expanded for discovery)."""
    registered: list[dict] = []
    canon: set[str] = set()
    for part in (raw or "").split("|"):
        part = part.strip()
        if not part:
            continue
        left, _, specialty = part.partition("::")
        left, specialty = left.strip(), specialty.strip()
        m = re.match(r"^(\d[\d.]*)\s+(.*)$", left)
        code, group = (m.group(1), m.group(2).strip()) if m else ("", left)
        registered.append({"code": code, "group": group, "specialty": specialty})
        canon |= _canonical_for(group, specialty)
    return registered, sorted(expand_trades(canon))


def describe(registered_trades: list[dict], reg_date: str) -> str:
    """A short, factual description generated only from register data (no marketing)."""
    groups: list[str] = []
    for t in registered_trades:
        g = t["group"].strip()
        if g and g not in groups:
            groups.append(g)
    if not groups:
        groups = ["construction works"]
    if len(groups) == 1:
        head = groups[0]
    elif len(groups) == 2:
        head = f"{groups[0]} and {groups[1]}"
    else:
        head = f"{groups[0]}, {groups[1]} and {len(groups) - 2} other trade group(s)"
    highlight = ""
    for t in registered_trades:
        s = t["specialty"].strip()
        if s and any(n in s.lower() for n in _NOTABLE_SPECIALTIES):
            highlight = f" ({s.lower()})"
            break
    since = f" Registered since {reg_date}." if reg_date else ""
    return f"CIC-registered subcontractor for {head}{highlight}.{since}"


def _empty_extras() -> dict:
    return {"public_flags": [], "award_history": [], "projects": [], "report_text": [], "closeout_summary": ""}


_JUNK_NAMES = {"(company name not in english)"}


def load_csv_register(path: Path) -> list[dict]:
    """Read the register CSV into unified firm dicts (provenance ``public_register``)."""
    if not path.is_file():
        return []
    firms: list[dict] = []
    seen_br: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("Company Name") or "").strip()
            if not name or name.lower() in _JUNK_NAMES:
                continue
            br = (row.get("Business Registration No.") or "").strip()
            if br and br in seen_br:  # dedupe by Business Registration No.
                continue
            if br:
                seen_br.add(br)
            rs = (row.get("RS No.") or "").strip()
            registered_trades, canon = parse_trades(row.get("Registered Trades (Code :: Specialty)") or "")
            reg_date = (row.get("Date of Registration") or "").strip()
            firms.append({
                "firm_id": rs or _slug(name),
                "name_en": name,
                "name_zh": None,
                "registered_grade": "CIC Registered Subcontractor",
                "value_band": None,
                "registers": ["CIC Registered Subcontractors Scheme"],
                "trades": canon,
                "registered_trades": registered_trades,
                "description": describe(registered_trades, reg_date),
                "enquiry_email": (row.get("Office E-mail") or "").strip(),
                "br_no": br,
                "address": (row.get("Registered Address") or "").strip(),
                "phone": (row.get("Office Contact Number") or "").strip(),
                "fax": (row.get("Office Fax Number") or "").strip(),
                "reg_date": reg_date,
                "expiry_date": (row.get("Expiry Date of Current Registration") or "").strip(),
                "provenance": "public_register",
                **_empty_extras(),
            })
    return firms


def _canon_curated(trades: list[str]) -> list[str]:
    out: set[str] = set()
    for t in trades or []:
        out.add(_normalize_trade(t) or t)
    return sorted(expand_trades(out))


def _curated_description(c: dict) -> str:
    bits = []
    if c.get("registered_grade"):
        bits.append(str(c["registered_grade"]))
    if c.get("public_flags"):
        bits.append("public enforcement record on file")
    elif c.get("award_history"):
        bits.append(f"{len(c['award_history'])} public award record(s)")
    return ". ".join(b[0].upper() + b[1:] for b in bits if b) + ("." if bits else "")


def _curated_firm(c: dict, eos: dict, provenance: str) -> dict:
    """A curated record as its own row (not on the register): demo firms, the
    enforcement overlay, and the illustrative/benchmark rows."""
    return {
        "firm_id": c["firm_id"],
        "name_en": c.get("name_en") or c["firm_id"],
        "name_zh": c.get("name_zh"),
        "registered_grade": c.get("registered_grade"),
        "value_band": c.get("value_band"),
        "registers": c.get("registers", []),
        "trades": _canon_curated(c.get("trades", [])),
        "registered_trades": [],
        "description": _curated_description(c),
        "enquiry_email": (c.get("enquiry_email") or "").strip(),
        "br_no": "", "address": "", "phone": "", "fax": "", "reg_date": "", "expiry_date": "",
        "provenance": provenance,
        "profile": c.get("profile"),
        "public_flags": c.get("public_flags", []),
        "award_history": c.get("award_history", []),
        "projects": eos.get("projects", []),
        "report_text": eos.get("report_text", []),
        "closeout_summary": eos.get("closeout_summary", ""),
    }


def _merge(c: dict, row: dict, eos: dict) -> dict:
    """A curated firm fused onto its register row: keep the curated id/flags/awards/
    offer, take the register's e-mail/BR/address/dates/registered-trades, union trades."""
    trades = sorted(expand_trades(set(_canon_curated(c.get("trades", []))) | set(row["trades"])))
    registers = list(dict.fromkeys((c.get("registers", []) or []) + row["registers"]))
    return {
        "firm_id": c["firm_id"],
        "name_en": c["name_en"],
        "name_zh": c.get("name_zh") or row.get("name_zh"),
        "registered_grade": c.get("registered_grade") or row["registered_grade"],
        "value_band": c.get("value_band"),
        "registers": registers,
        "trades": trades,
        "registered_trades": row["registered_trades"],
        "description": row["description"],
        "enquiry_email": row["enquiry_email"],
        "br_no": row["br_no"], "address": row["address"], "phone": row["phone"], "fax": row["fax"],
        "reg_date": row["reg_date"], "expiry_date": row["expiry_date"],
        "provenance": "public_register",
        "profile": c.get("profile"),
        "public_flags": c.get("public_flags", []),
        "award_history": c.get("award_history", []),
        "projects": eos.get("projects", []),
        "report_text": eos.get("report_text", []),
        "closeout_summary": eos.get("closeout_summary", ""),
    }


def merge_register(register: list[dict], curated_real: list[dict], eos_by_id: dict[str, dict]) -> list[dict]:
    """Fuse curated public_register records onto the CSV register. Returns the full
    list of public_register firm dicts (register rows + the kept overlay)."""
    by_name = {}
    for r in register:
        by_name.setdefault(norm_name(r["name_en"]), r)

    firms: list[dict] = []
    consumed: set[str] = set()  # register firm_ids consumed by a curated merge
    for c in curated_real:
        eos = eos_by_id.get(c["firm_id"], {})
        row = by_name.get(norm_name(c["name_en"]))
        if row is not None and row["firm_id"] not in consumed:
            consumed.add(row["firm_id"])
            firms.append(_merge(c, row, eos))
        elif c.get("public_flags") or c["firm_id"] in DEMO_FIRM_IDS:
            firms.append(_curated_firm(c, eos, "public_register"))
        # else: plain curated row with no flag/offer — superseded by the register, dropped
    for r in register:
        if r["firm_id"] not in consumed:
            firms.append(r)
    return firms


def illustrative_firm(rec: dict, eos: dict) -> dict:
    """An illustrative/benchmark record (F-* demo firms, the benchmark row)."""
    return _curated_firm(rec, eos, "illustrative")
