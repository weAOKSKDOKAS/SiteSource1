"""Prompt 3 — human-edited enquiry drafts through the dispatch gate.

The person reviews the composed enquiry emails, edits any draft, and confirms;
the send (mock outbox in DEMO) carries EXACTLY the edited subject/body, matched
by (trade, firm). Untouched firms keep the composed text. Offline under the DEMO
autouse fixture.
"""

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def _shortlist_and_scope():
    case = client.get("/demo/hero").json()
    scope = client.post("/ingest", json={"tender": case["tender"]}).json()
    shortlist = client.post("/shortlist", json={"scope": scope}).json()
    return shortlist, scope, case


def test_draft_overrides_land_in_the_sent_bundles():
    shortlist, scope, case = _shortlist_and_scope()
    approvals = {"electrical": ["F-EL-02", "F-EL-04"]}

    # 1) compose without sending — the drafts the person reviews in the modal
    drafted = client.post("/dispatch", json={
        "shortlist": shortlist, "approvals": approvals,
        "scope": scope, "project_name": case["name"], "send": False,
    }).json()
    assert {b["firm_id"] for b in drafted["bundles"]} == {"F-EL-02", "F-EL-04"}
    assert all(b["status"] == "approved" for b in drafted["bundles"])
    composed = {b["firm_id"]: b for b in drafted["bundles"]}

    # 2) the person edits ONE draft; the send carries exactly the edited text
    edited_subject = "RFQ — Electrical package — please price by Friday [edited]"
    edited_body = "Dear team,\n\nPlease find our edited enquiry.\n\nBuying Team"
    sent = client.post("/dispatch", json={
        "shortlist": shortlist, "approvals": approvals,
        "scope": scope, "project_name": case["name"], "send": True,
        "draft_overrides": [
            {"trade": "electrical", "firm_id": "F-EL-02", "subject": edited_subject, "body": edited_body},
        ],
    }).json()
    by_firm = {b["firm_id"]: b for b in sent["bundles"]}
    assert by_firm["F-EL-02"]["email_subject"] == edited_subject
    assert by_firm["F-EL-02"]["email_body"] == edited_body
    assert by_firm["F-EL-02"]["status"] == "sent_mock"
    # the untouched firm keeps its composed draft
    assert by_firm["F-EL-04"]["email_subject"] == composed["F-EL-04"]["email_subject"]
    assert by_firm["F-EL-04"]["email_body"] == composed["F-EL-04"]["email_body"]


def test_blank_override_fields_keep_the_composed_value():
    shortlist, scope, case = _shortlist_and_scope()
    approvals = {"electrical": ["F-EL-02"]}
    drafted = client.post("/dispatch", json={
        "shortlist": shortlist, "approvals": approvals,
        "scope": scope, "project_name": case["name"], "send": False,
    }).json()
    composed = drafted["bundles"][0]

    sent = client.post("/dispatch", json={
        "shortlist": shortlist, "approvals": approvals,
        "scope": scope, "project_name": case["name"], "send": True,
        "draft_overrides": [
            {"trade": "electrical", "firm_id": "F-EL-02", "subject": "", "body": "Only the body was edited."},
        ],
    }).json()
    bundle = sent["bundles"][0]
    assert bundle["email_subject"] == composed["email_subject"]  # blank -> composed kept
    assert bundle["email_body"] == "Only the body was edited."
