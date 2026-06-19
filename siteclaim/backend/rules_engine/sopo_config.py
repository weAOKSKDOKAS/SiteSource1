# ⚠️ STATUTORY PARAMETERS — VALIDATE EVERY VALUE WITH A QUANTITY SURVEYOR OR
# CONSTRUCTION LAWYER BEFORE RELYING ON OUTPUT. Values below are best-effort
# placeholders from secondary research.
#
# Provenance tiers (read before trusting anything):
#   * "# SOURCED (CIC FAQ ...) — cross-check Cap.652 text" = grounded in the
#     official CIC SOPO FAQ (cic.hk).
#   * "# SOURCED (law-firm summary) — cross-check ... Cap.652 text" = grounded in
#     a secondary law-firm summary. Both are SECONDARY — still cross-check the
#     enacted text before relying on them.
#   * "# UNVERIFIED ..." = best-effort placeholder, not yet sourced at all. Send
#     these to a QS / pull from e-legislation.
#   * References (e.g. "s.20", "Q36") are as given by the source and INDICATIVE.
#
# DAY-COUNT CONVENTION (legally load-bearing — the Ordinance mixes both):
#   *_DAYS          -> CALENDAR days (e.g. s.20 payment response). Compute with
#                      business_days.add_calendar_days.
#   *_WORKING_DAYS  -> WORKING days. Compute with business_days.add_working_days,
#                      which takes a MODE because the Ordinance uses TWO working-
#                      day definitions:
#                        - mode='adjudication' (CIC FAQ Q36): excludes Saturdays,
#                          general holidays (incl. Sundays) and black rainstorm /
#                          gale-warning days. Used for the s.24–s.42 adjudication
#                          timetable.
#                        - mode='part4' (CIC FAQ Q54): excludes general holidays
#                          and black rainstorm/gale days only — Saturdays COUNT.
#                          Used for the Part 4 suspension-notice period.
"""SiteClaim statutory parameters for SOPO — the Construction Industry Security
of Payment Ordinance (Cap. 652), Hong Kong.

This module is **Layer 1's single source of truth** for numbers and rules that
come from the statute. The deterministic Rules Engine imports these constants;
no other layer hard-codes a statutory value. Concentrating them here means a
quantity surveyor or construction lawyer can review one short, well-commented
file rather than hunting through the codebase.

Day arithmetic that consumes these constants lives in
:mod:`rules_engine.business_days`, which keeps CALENDAR-day and WORKING-day maths
explicitly separate and supports both working-day definitions (see the DAY-COUNT
CONVENTION header above).

Nothing in this module is legal advice. SOURCED values are grounded in secondary
sources (the CIC SOPO FAQ and law-firm summaries) and must still be cross-checked
against the enacted Cap.652 text; UNVERIFIED values are unconfirmed placeholders.
"""

from decimal import Decimal
from typing import Final

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
CONFIG_VERSION: Final[str] = "0.2.0-cic"  # bump when any value below changes
STATUTORY_SOURCE: Final[str] = (
    "Construction Industry Security of Payment Ordinance (Cap. 652), Hong Kong. "
    "Time bars, thresholds and s.18 content requirements SOURCED from the official "
    "CIC SOPO FAQ (cic.hk) and law-firm summaries; NOT yet verified against the "
    "e-legislation Cap.652 text."
)
COMMENCEMENT_DATE: Final[str] = "2025-08-28"  # applies to contracts entered on/after this date. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text

# Importable copy of the header warning so the API / UI can surface it at runtime
# and no client can quietly hide it from the user.
STATUTORY_WARNING: Final[str] = (
    "STATUTORY PARAMETERS ARE NOT VERIFIED AGAINST THE ENACTED ORDINANCE. "
    "Validate every value with a quantity surveyor or construction lawyer, and "
    "cross-check against the e-legislation Cap.652 text, before relying on output."
)

# ---------------------------------------------------------------------------
# Calendar / business-day definitions (inputs to business_days helpers)
# ---------------------------------------------------------------------------
# Python ``date.weekday()`` indices treated as NON-working under the ADJUDICATION
# working-day definition (5 = Sat, 6 = Sun). Part 4 uses a different rule — see
# business_days mode='part4' (Saturdays count there).
WEEKEND_DAYS: Final[tuple[int, ...]] = (5, 6)  # SOURCED (CIC FAQ Q36) — adjudication working days exclude Saturdays, general holidays (incl. Sundays), and black rainstorm/gale days

# Hong Kong General Holidays for 2026 (ISO date strings), consumed by
# deadlines.business_days_between for working-day arithmetic. These are the
# "general holidays" SOPO's working-day definition excludes. All 17 are listed —
# INCLUDING those falling on a Saturday — because the part4 working-day mode
# otherwise counts Saturdays, so a Saturday general holiday must still be excluded.
# Sundays are general holidays too, but are handled by WEEKEND_DAYS (weekday 6),
# not listed here. Black rainstorm / gale-warning days remain DYNAMIC and are
# supplied separately via business_days(..., weather_suspension_dates=...).
PUBLIC_HOLIDAYS: Final[tuple[str, ...]] = (
    "2026-01-01",  # New Year's Day
    "2026-02-17",  # Lunar New Year's Day
    "2026-02-18",  # 2nd day of Lunar New Year
    "2026-02-19",  # 3rd day of Lunar New Year
    "2026-04-03",  # Good Friday
    "2026-04-04",  # day following Good Friday
    "2026-04-06",  # day following Ching Ming (substitution)
    "2026-04-07",  # day following Easter Monday (additional substitution)
    "2026-05-01",  # Labour Day
    "2026-05-25",  # day following Birthday of the Buddha (substitution)
    "2026-06-19",  # Tuen Ng Festival
    "2026-07-01",  # HKSAR Establishment Day
    "2026-09-26",  # day following Mid-Autumn
    "2026-10-01",  # National Day
    "2026-10-19",  # day following Chung Yeung (substitution)
    "2026-12-25",  # Christmas Day
    "2026-12-26",  # first weekday after Christmas Day
)  # SOURCED (HK govt gazette, 16 May 2025) — General Holidays Ordinance (Cap. 149)

# ---------------------------------------------------------------------------
# SOURCED time bars — payment mechanism (CALENDAR days)
# ---------------------------------------------------------------------------
PAYMENT_RESPONSE_DAYS: Final[int] = 30  # s.20 (calendar days) — statutory max; contract may specify shorter. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
MAX_PAYMENT_DEADLINE_DAYS: Final[int] = 60  # (calendar days) — parties may agree earlier. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text

# ---------------------------------------------------------------------------
# SOURCED — payment dispute & set-off mechanics (CIC FAQ)
# ---------------------------------------------------------------------------
# A payment dispute arises (and the adjudication clock can start) on ANY of these.
PAYMENT_DISPUTE_TRIGGERS: Final[tuple[str, ...]] = (
    "no payment response served by the response deadline",
    "respondent disputes the claimed amount (in whole or in part)",
    "respondent admits an amount but fails to pay it in full by the payment deadline",
)  # CIC FAQ Q27 — SOURCED (CIC FAQ Q27) — cross-check Cap.652 text
# Failing to serve a payment response by the deadline forfeits the respondent's
# right to raise a set-off in the adjudication.
SET_OFF_FORFEIT_ON_NO_RESPONSE: Final[bool] = True  # SOURCED (CIC FAQ Q25) — cross-check Cap.652 text

# ---------------------------------------------------------------------------
# SOURCED — adjudication timetable (note CALENDAR vs WORKING per name)
# ---------------------------------------------------------------------------
ADJUDICATION_INIT_DAYS: Final[int] = 28  # s.24 (calendar days) — from date the payment dispute arises. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
ANB_SERVICE_WORKING_DAYS: Final[int] = 8  # s.25(3) (working days, adjudication) — if no/more-than-one ANB (Adjudicator Nominating Body) specified. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
ADJUDICATOR_APPOINTMENT_WORKING_DAYS: Final[int] = 7  # s.26(2) (working days, adjudication) — appoint adjudicator. SOURCED (CIC FAQ) — cross-check Cap.652 text
ADJUDICATION_SUBMISSION_WORKING_DAYS: Final[int] = 1  # Q36 (working days, adjudication) — claimant's submission after appointment. SOURCED (CIC FAQ Q36) — cross-check Cap.652 text
ADJUDICATION_RESPONSE_WORKING_DAYS: Final[int] = 20  # Q36 (working days, adjudication) — respondent's response. SOURCED (CIC FAQ Q36) — cross-check Cap.652 text
ADJUDICATION_REPLY_WORKING_DAYS: Final[int] = 2  # Q36 (working days, adjudication) — claimant's reply. SOURCED (CIC FAQ Q36) — cross-check Cap.652 text
DETERMINATION_WORKING_DAYS: Final[int] = 55  # s.42(5) / CIC FAQ Q36 (working days, adjudication) — after adjudicator appointed. SOURCED (CIC FAQ) — cross-check Cap.652 text
PAY_ADJUDICATED_AMOUNT_DAYS: Final[int] = 30  # s.43 / s.42(7) (calendar days) — if adjudicator unspecified. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
SET_ASIDE_DAYS: Final[int] = 14  # Q50 (calendar days) — to apply to set aside, after the determination is served. SOURCED (CIC FAQ Q50) — cross-check Cap.652 text

# ---------------------------------------------------------------------------
# SOURCED — suspension of work (Part 4; uses the part4 working-day definition)
# ---------------------------------------------------------------------------
SUSPEND_NOTICE_WORKING_DAYS: Final[int] = 5  # Q54 (working days, part4) — notice before lawfully suspending/slowing work. SOURCED (CIC FAQ Q54) — cross-check Cap.652 text

# ---------------------------------------------------------------------------
# SOURCED monetary thresholds (HKD)
# ---------------------------------------------------------------------------
THRESHOLD_CONSTRUCTION_HKD: Final[Decimal] = Decimal(5_000_000)  # main contract construction work. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
THRESHOLD_GOODS_SERVICES_HKD: Final[Decimal] = Decimal(500_000)  # related goods/services. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
COURT_ROUTING_THRESHOLD_HKD: Final[Decimal] = Decimal(3_000_000)  # >CFI / <District Court (Rules Cap.652A) — enforcement routing. SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
# Subcontracts in a covered contractual chain have no minimum value of their own.
SUBCONTRACT_HAS_OWN_THRESHOLD: Final[bool] = False  # SOURCED (CIC FAQ Q5/Q11) — subcontracts in a covered chain have no minimum value

# Convenience lookup keyed by ``schemas.models.ContractType`` values.
THRESHOLD_BY_CONTRACT_TYPE: Final[dict[str, Decimal]] = {
    "main_construction": THRESHOLD_CONSTRUCTION_HKD,  # SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
    "supply_goods_and_services": THRESHOLD_GOODS_SERVICES_HKD,  # SOURCED (law-firm summary) — cross-check against e-legislation Cap.652 text
    "subcontract_construction": Decimal(0),  # SOURCED (CIC FAQ Q5/Q11) — subcontracts in a covered chain have no minimum value
    "consultancy": THRESHOLD_GOODS_SERVICES_HKD,  # UNVERIFIED — classification unclear; confirm with Cap.652 text/QS
}

# ---------------------------------------------------------------------------
# SOURCED — mandatory payment-claim particulars (s.18 content requirements)
# ---------------------------------------------------------------------------
# Each entry is ``(key, human description)``; ``key`` is aligned to schema fields
# so Stage 02 can check presence deterministically.
MANDATORY_CLAIM_PARTICULARS: Final[tuple[tuple[str, str], ...]] = (
    ("in_writing", "the claim is in writing"),
    ("identifies_work", "identifies the construction work / related goods & services the payment relates to"),
    ("states_amount_and_basis", "states the claimed amount and how it is calculated"),
)  # s.18 / CIC FAQ Q17 — SOURCED (CIC FAQ Q17) — cross-check Cap.652 text

# ===========================================================================
# UNVERIFIED placeholders — NOT yet sourced. Send to a QS / pull from
# e-legislation, then move up into the SOURCED sections above.
# ===========================================================================
MIN_DAYS_BETWEEN_CLAIMS: Final[int] = 30  # (calendar days) — UNVERIFIED — confirm with Cap.652 text/QS
DEFAULT_REFERENCE_DATE_INTERVAL_DAYS: Final[int] = 30  # (calendar days) — UNVERIFIED — confirm with Cap.652 text/QS
DETERMINATION_EXTENSION_WORKING_DAYS: Final[int] = 10  # extra time by agreement — UNVERIFIED — confirm with Cap.652 text/QS
DEEMED_SERVICE_DAYS_BY_POST: Final[int] = 2  # (calendar days) added on postal service — UNVERIFIED — confirm with Cap.652 text/QS
PERMITTED_SERVICE_METHODS: Final[tuple[str, ...]] = (
    "personal_delivery",  # UNVERIFIED — confirm with Cap.652 text/QS
    "post_to_last_known_address",  # UNVERIFIED — confirm with Cap.652 text/QS
    "email_if_agreed",  # UNVERIFIED — confirm with Cap.652 text/QS
    "contractual_method",  # UNVERIFIED — confirm with Cap.652 text/QS
)

# ===========================================================================
# OPERATIONAL (non-statutory) — engineering thresholds, NOT law.
# ===========================================================================
# Below this LLM self-reported confidence, an extracted field is flagged for
# human review in Stage 02. Tunable product knob, not a legal value.
CONFIDENCE_REVIEW_THRESHOLD: Final[float] = 0.6  # operational, non-statutory


__all__ = [
    "CONFIG_VERSION",
    "STATUTORY_SOURCE",
    "COMMENCEMENT_DATE",
    "STATUTORY_WARNING",
    "WEEKEND_DAYS",
    "PUBLIC_HOLIDAYS",
    "PAYMENT_RESPONSE_DAYS",
    "MAX_PAYMENT_DEADLINE_DAYS",
    "PAYMENT_DISPUTE_TRIGGERS",
    "SET_OFF_FORFEIT_ON_NO_RESPONSE",
    "ADJUDICATION_INIT_DAYS",
    "ANB_SERVICE_WORKING_DAYS",
    "ADJUDICATOR_APPOINTMENT_WORKING_DAYS",
    "ADJUDICATION_SUBMISSION_WORKING_DAYS",
    "ADJUDICATION_RESPONSE_WORKING_DAYS",
    "ADJUDICATION_REPLY_WORKING_DAYS",
    "DETERMINATION_WORKING_DAYS",
    "PAY_ADJUDICATED_AMOUNT_DAYS",
    "SET_ASIDE_DAYS",
    "SUSPEND_NOTICE_WORKING_DAYS",
    "THRESHOLD_CONSTRUCTION_HKD",
    "THRESHOLD_GOODS_SERVICES_HKD",
    "COURT_ROUTING_THRESHOLD_HKD",
    "SUBCONTRACT_HAS_OWN_THRESHOLD",
    "THRESHOLD_BY_CONTRACT_TYPE",
    "MANDATORY_CLAIM_PARTICULARS",
    "MIN_DAYS_BETWEEN_CLAIMS",
    "DEFAULT_REFERENCE_DATE_INTERVAL_DAYS",
    "DETERMINATION_EXTENSION_WORKING_DAYS",
    "DEEMED_SERVICE_DAYS_BY_POST",
    "PERMITTED_SERVICE_METHODS",
    "CONFIDENCE_REVIEW_THRESHOLD",
]
