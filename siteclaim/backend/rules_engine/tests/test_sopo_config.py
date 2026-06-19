"""Smoke tests for the statutory config module.

These deliberately do **not** assert the legal *correctness* of any value — that
requires a quantity surveyor or construction lawyer (see the module header). They
guard the module's *shape* and pin the SOURCED values so an accidental edit is
caught: the warning is present, the grounded periods/thresholds hold their
sourced numbers, the calendar/working-day naming convention is consistent, and
the s.18 mandatory-particulars list holds its three CIC-FAQ items.

Run from the ``backend/`` directory:  ``pytest``
"""

from decimal import Decimal

from rules_engine import sopo_config as cfg


def test_warning_constant_is_loud() -> None:
    text = cfg.STATUTORY_WARNING.upper()
    assert "VALIDATE" in text or "CROSS-CHECK" in text


def test_sourced_periods_hold_their_grounded_values() -> None:
    # Pin the SOURCED numbers — see sopo_config for sources/sections.
    assert cfg.PAYMENT_RESPONSE_DAYS == 30  # s.20
    assert cfg.MAX_PAYMENT_DEADLINE_DAYS == 60
    assert cfg.ADJUDICATION_INIT_DAYS == 28  # s.24
    assert cfg.ANB_SERVICE_WORKING_DAYS == 8  # s.25(3)
    assert cfg.ADJUDICATOR_APPOINTMENT_WORKING_DAYS == 7  # s.26(2)
    assert cfg.ADJUDICATION_SUBMISSION_WORKING_DAYS == 1  # Q36
    assert cfg.ADJUDICATION_RESPONSE_WORKING_DAYS == 20  # Q36
    assert cfg.ADJUDICATION_REPLY_WORKING_DAYS == 2  # Q36
    assert cfg.DETERMINATION_WORKING_DAYS == 55  # s.42(5) / Q36 — WORKING days
    assert cfg.PAY_ADJUDICATED_AMOUNT_DAYS == 30  # s.43 / s.42(7)
    assert cfg.SET_ASIDE_DAYS == 14  # Q50 (calendar)
    assert cfg.SUSPEND_NOTICE_WORKING_DAYS == 5  # Q54 (part4)


def test_determination_is_now_working_days_only() -> None:
    # Phase 0c renamed DETERMINATION_DAYS -> DETERMINATION_WORKING_DAYS.
    assert not hasattr(cfg, "DETERMINATION_DAYS")
    assert "DETERMINATION_WORKING_DAYS" in cfg.__all__


def test_periods_are_positive_ints() -> None:
    for value in (
        cfg.PAYMENT_RESPONSE_DAYS,
        cfg.MAX_PAYMENT_DEADLINE_DAYS,
        cfg.ADJUDICATION_INIT_DAYS,
        cfg.ANB_SERVICE_WORKING_DAYS,
        cfg.ADJUDICATOR_APPOINTMENT_WORKING_DAYS,
        cfg.ADJUDICATION_SUBMISSION_WORKING_DAYS,
        cfg.ADJUDICATION_RESPONSE_WORKING_DAYS,
        cfg.ADJUDICATION_REPLY_WORKING_DAYS,
        cfg.DETERMINATION_WORKING_DAYS,
        cfg.PAY_ADJUDICATED_AMOUNT_DAYS,
        cfg.SET_ASIDE_DAYS,
        cfg.SUSPEND_NOTICE_WORKING_DAYS,
    ):
        assert isinstance(value, int) and value > 0


def test_working_day_constants_are_named_consistently() -> None:
    # The calendar/working distinction is legally load-bearing: every constant
    # whose name ends in _WORKING_DAYS must be an int, and the mode-aware helper
    # that consumes them must exist.
    from rules_engine import business_days

    working = {n for n in dir(cfg) if n.endswith("_WORKING_DAYS")}
    assert {
        "ANB_SERVICE_WORKING_DAYS",
        "ADJUDICATOR_APPOINTMENT_WORKING_DAYS",
        "DETERMINATION_WORKING_DAYS",
        "SUSPEND_NOTICE_WORKING_DAYS",
    } <= working
    assert all(isinstance(getattr(cfg, n), int) for n in working)
    assert hasattr(business_days, "add_working_days")
    assert hasattr(business_days, "add_calendar_days")


def test_sourced_thresholds_are_positive_decimals() -> None:
    assert cfg.THRESHOLD_CONSTRUCTION_HKD == Decimal(5_000_000)
    assert cfg.THRESHOLD_GOODS_SERVICES_HKD == Decimal(500_000)
    assert cfg.COURT_ROUTING_THRESHOLD_HKD == Decimal(3_000_000)
    for v in (
        cfg.THRESHOLD_CONSTRUCTION_HKD,
        cfg.THRESHOLD_GOODS_SERVICES_HKD,
        cfg.COURT_ROUTING_THRESHOLD_HKD,
    ):
        assert isinstance(v, Decimal) and v > 0


def test_subcontract_has_no_minimum_value() -> None:
    assert cfg.SUBCONTRACT_HAS_OWN_THRESHOLD is False
    assert cfg.THRESHOLD_BY_CONTRACT_TYPE["subcontract_construction"] == Decimal(0)


def test_threshold_lookup_covers_known_contract_types() -> None:
    assert "main_construction" in cfg.THRESHOLD_BY_CONTRACT_TYPE
    assert all(isinstance(v, Decimal) for v in cfg.THRESHOLD_BY_CONTRACT_TYPE.values())


def test_mandatory_particulars_s18_encoded() -> None:
    keys = [key for key, _description in cfg.MANDATORY_CLAIM_PARTICULARS]
    assert keys == ["in_writing", "identifies_work", "states_amount_and_basis"]


def test_payment_dispute_triggers_present() -> None:
    assert len(cfg.PAYMENT_DISPUTE_TRIGGERS) == 3
    assert cfg.SET_OFF_FORFEIT_ON_NO_RESPONSE is True
