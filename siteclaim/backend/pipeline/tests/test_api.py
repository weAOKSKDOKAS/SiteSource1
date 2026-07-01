"""API wiring — the five stage routes, the xlsx download, and the demo loaders,
exercised end to end through FastAPI's TestClient in DEMO_MODE (offline)."""

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health_reports_demo_mode():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True


def test_stage_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert {"/ingest", "/shortlist", "/dispatch", "/level", "/recommend", "/leveling.xlsx"} <= paths
    assert {"/ingest-upload", "/demo/cases", "/demo/{case_id}"} <= paths


def test_demo_loaders_return_tender_and_replies():
    ids = {c["id"] for c in client.get("/demo/cases").json()}
    assert {"clean", "hero", "messy"} <= ids
    case = client.get("/demo/messy").json()
    assert case["tender"]["documents"]
    assert case["hero_trade"] == "electrical"
    assert len(case["replies"]) == 4
    assert case["rationale_fixture"]
    assert client.get("/demo/nope").status_code == 404


def test_full_pipeline_through_the_api_catches_the_hero():
    case = client.get("/demo/messy").json()

    scope = client.post("/ingest", json={"tender": case["tender"]}).json()
    assert "electrical" in {p["trade"] for p in scope["packages"]}

    shortlist = client.post("/shortlist", json={"scope": scope}).json()
    electrical = shortlist["per_trade"]["electrical"]
    assert electrical[0]["firm"]["firm_id"] == "F-EL-02"
    gotcha = next(c for c in electrical if c["firm"]["firm_id"] == "F-EL-01")
    assert gotcha["recommended_against"] is True

    dispatch = client.post("/dispatch", json={
        "shortlist": shortlist, "approvals": {"electrical": ["F-EL-02"]},
        "scope": scope, "project_name": case["name"], "send": True,
    }).json()
    assert {b["firm_id"] for b in dispatch["bundles"]} == {"F-EL-02"}
    assert dispatch["bundles"][0]["status"] == "sent_mock"

    levelled = client.post("/level", json={"replies": case["replies"], "scope": scope}).json()
    messy = next(b for b in levelled if b["firm_id"] == "F-EL-03")
    assert messy["arithmetic_findings"] and messy["scope_gaps"]

    rec = client.post("/recommend", json={"levelled": levelled, "trade": "electrical"}).json()
    assert rec["recommended_firm_id"] == "F-EL-02"
    against = next(r for r in rec["ranked"] if r["firm_id"] == "F-EL-01")
    assert against["recommended_against"] is True
    assert rec["historical_band"] is not None


def test_leveling_xlsx_downloads():
    resp = client.get("/leveling.xlsx")
    assert resp.status_code == 200
    assert "spreadsheet" in resp.headers["content-type"]
    assert resp.content[:2] == b"PK"  # xlsx is a zip


def _run_scenario(case_id: str):
    case = client.get(f"/demo/{case_id}").json()
    scope = client.post("/ingest", json={"tender": case["tender"]}).json()
    levelled = client.post("/level", json={"replies": case["replies"], "scope": scope}).json()
    rec = client.post(
        "/recommend",
        json={"levelled": levelled, "trade": case["hero_trade"], "demo_fixture": case["rationale_fixture"]},
    ).json()
    return rec


def test_three_scenarios_reproduce_their_expected_outcome():
    clean = _run_scenario("clean")
    assert clean["recommended_firm_id"] == "F-JF-01"
    assert not any(r["recommended_against"] for r in clean["ranked"])  # confident, no flag

    hero = _run_scenario("hero")
    assert hero["recommended_firm_id"] == "F-EL-02"
    assert next(r for r in hero["ranked"] if r["firm_id"] == "F-EL-01")["recommended_against"] is True
    assert "winding-up" in hero["rationale"].lower()

    messy = _run_scenario("messy")
    assert messy["recommended_firm_id"] == "F-EL-02"
    assert next(r for r in messy["ranked"] if r["firm_id"] == "F-EL-01")["recommended_against"] is True


def test_scenarios_are_deterministic_on_repeat():
    for case_id in ("clean", "hero", "messy"):
        first = _run_scenario(case_id)
        second = _run_scenario(case_id)
        assert first["recommended_firm_id"] == second["recommended_firm_id"]
        assert [r["firm_id"] for r in first["ranked"]] == [r["firm_id"] for r in second["ranked"]]


def test_firms_is_a_paginated_register_with_real_emails():
    page = client.get("/firms").json()
    assert set(page) == {"items", "total", "limit", "offset"}
    assert page["total"] == 1410 and page["limit"] == 25 and page["offset"] == 0
    assert len(page["items"]) == 25  # server-side page, not the whole register
    # never the illustrative demo firms or the benchmark row
    assert all(not it["firm_id"].startswith("F-") for it in page["items"])
    assert all(it["firm_id"] != "tender-scheduled-rates" for it in page["items"])
    # the register shape the Database table reads
    sample = page["items"][0]
    assert {"name_en", "description", "enquiry_email", "registered_trades", "reg_date",
            "expiry_date", "trades", "public_flags"} <= set(sample)
    # the real register firms carry their real enquiry e-mail (Dispatch reads this);
    # a handful are redacted in the source ("[email protected]"), so allow a few
    reg = client.get("/firms?limit=100&q=limited").json()
    with_email = [it for it in reg["items"] if it["enquiry_email"]]
    assert len(with_email) >= 90
    assert sum("@" in it["enquiry_email"] and "[email" not in it["enquiry_email"] for it in with_email) >= 80


def test_firms_pagination_sorts_offsets_and_caps():
    p1 = client.get("/firms?limit=10&offset=0").json()
    p2 = client.get("/firms?limit=10&offset=10").json()
    assert p1["limit"] == 10 and len(p1["items"]) == 10
    names = [it["name_en"].lower() for it in p1["items"]]
    assert names == sorted(names)  # alphabetical by default
    assert p1["items"][0]["firm_id"] != p2["items"][0]["firm_id"]  # different page
    assert client.get("/firms?limit=999").json()["limit"] == 25   # disallowed -> default
    assert client.get("/firms?limit=100").json()["limit"] == 100  # hard cap honoured


def test_firms_search_and_demo_firms_resolve():
    res = client.get("/firms?q=DrilTech").json()
    dt = next(it for it in res["items"] if "DrilTech" in it["name_en"])
    assert dt["enquiry_email"] and dt["br_no"]  # merged from the register row
    assert any("Gold Ram" in it["name_en"] for it in client.get("/firms?q=Gold Ram").json()["items"])
    # a flagged firm still carries an http-citable reference
    soils = client.get("/firms?q=Soils %26 Materials").json()["items"]
    flags = [fl for it in soils for fl in it["public_flags"]]
    assert flags and all(fl["reference"].startswith("http") for fl in flags)


def test_coverage_counts_only_real_provenance_firms():
    cov = client.get("/coverage").json()
    # the claim counts the real CIC register (~1,366) plus the enforcement/offer
    # overlay — never the illustrative firms or the benchmark row
    assert cov["provenance"] == "public_register"
    assert cov["total_firms"] == 1410
    assert cov["flagged_firms"] == 47
    # the headline composition: CIC register + enforcement/offer overlay
    assert cov["register_count"] == 1365
    assert cov["overlay_count"] == 45
    assert cov["flagged_count"] == 47
    assert cov["register_count"] + cov["overlay_count"] == cov["total_firms"]
    # only the real flag types appear — the demo-only adjudication / distress filing
    # (whose references are illustrative placeholders) are excluded from the claim
    assert set(cov["flags_by_type"]) == {"debarment", "safety_prosecution", "winding_up"}
    assert "electrical" in cov["trades"]
    assert cov["registers"] >= 1 and cov["flag_sources"]
