"""Spec for the tender desk backend — the team, per-set metadata, and the home-screen counts.

Named profiles, not auth: the ``X-CBOQ-Actor`` header names a team member so ownership and
verdicts carry attribution, and an absent header degrades to "" rather than 401 — there is no
security boundary in this app to enforce, only honesty about who acted.

The desk's derived facts have one rule: they must agree with what the gates refuse. ``blocked``
is not a status somebody typed; it is computed from the same counts the 409s are built on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

fitz = pytest.importorskip("fitz")  # PyMuPDF


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _binder(pages: int = 12) -> bytes:
    doc = fitz.open()
    for i in range(1, pages + 1):
        doc.new_page().insert_text((72, 100), f"Binder page {i} of {pages}", fontsize=11)
    doc.set_toc([
        [1, "Conditions of Tender", 1],
        [1, "Scope of Works", 5],
        [1, "Pricing Schedule", 9],
    ])
    data = doc.tobytes()
    doc.close()
    return data


def _upload(client: TestClient, name: str, actor: str = "") -> str:
    headers = {"X-CBOQ-Actor": actor} if actor else {}
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": name},
        files={"files": ("binder.pdf", _binder(), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]["set_id"]


# ---------------------------------------------------------------------------
# The team
# ---------------------------------------------------------------------------
class TestTeam:
    def test_add_and_list(self, client: TestClient):
        resp = client.post("/client-boq/team", json={"name": "Rebecca Lam"})
        assert resp.status_code == 200
        member = resp.json()["member"]
        assert member["member_id"]                      # derived from the name
        assert member["initials"] == "RL"               # derived when not given
        roster = client.get("/client-boq/team").json()
        assert [m["name"] for m in roster["members"]] == ["Rebecca Lam"]

    def test_a_member_archives_rather_than_deletes(self, client: TestClient):
        member = client.post("/client-boq/team", json={"name": "Kwan Ho"}).json()["member"]
        client.post(f"/client-boq/team/{member['member_id']}",
                    json={"name": "Kwan Ho", "archived": True})
        # Gone from the roster, still on the record.
        assert client.get("/client-boq/team").json()["count"] == 0
        everyone = client.get("/client-boq/team", params={"include_archived": True}).json()
        assert everyone["count"] == 1 and everyone["members"][0]["archived"] is True

    def test_a_member_needs_a_name(self, client: TestClient):
        assert client.post("/client-boq/team", json={"name": "  "}).status_code == 422

    def test_unknown_member_404s_on_update(self, client: TestClient):
        assert client.post("/client-boq/team/nobody", json={"name": "X"}).status_code == 404


# ---------------------------------------------------------------------------
# Desk metadata on a set
# ---------------------------------------------------------------------------
class TestSetMeta:
    def test_upload_stamps_the_uploader_as_owner(self, client: TestClient):
        set_id = _upload(client, "meta-owner", actor="r-lam")
        row = next(s for s in client.get("/client-boq/sets").json()["sets"]
                   if s["set_id"] == set_id)
        assert row["meta"]["owner_id"] == "r-lam"
        assert row["meta"]["last_touched_by"] == "r-lam"

    def test_anonymous_upload_still_works(self, client: TestClient):
        set_id = _upload(client, "meta-anon")
        row = next(s for s in client.get("/client-boq/sets").json()["sets"]
                   if s["set_id"] == set_id)
        assert row["meta"]["owner_id"] == ""            # honest: nobody said who they were

    def test_ownership_can_be_handed_off(self, client: TestClient):
        set_id = _upload(client, "meta-handoff", actor="r-lam")
        resp = client.post(f"/client-boq/sets/{set_id}/meta", json={"owner_id": "k-ho"},
                           headers={"X-CBOQ-Actor": "k-ho"})
        assert resp.json()["meta"]["owner_id"] == "k-ho"

    def test_archiving_takes_it_off_the_shelf_but_not_the_record(self, client: TestClient):
        set_id = _upload(client, "meta-archive")
        client.post(f"/client-boq/sets/{set_id}/meta", json={"archived": True})
        shelf = [s["set_id"] for s in client.get("/client-boq/sets").json()["sets"]]
        assert set_id not in shelf
        everyone = [s["set_id"] for s in
                    client.get("/client-boq/sets", params={"include_archived": True}).json()["sets"]]
        assert set_id in everyone

    def test_an_outcome_other_than_live_implies_archived(self, client: TestClient):
        set_id = _upload(client, "meta-outcome")
        meta = client.post(f"/client-boq/sets/{set_id}/meta",
                           json={"outcome": "lost"}).json()["meta"]
        assert meta["outcome"] == "lost" and meta["archived"] is True

    def test_a_nonsense_outcome_is_refused(self, client: TestClient):
        set_id = _upload(client, "meta-badoutcome")
        assert client.post(f"/client-boq/sets/{set_id}/meta",
                           json={"outcome": "maybe"}).status_code == 422

    def test_meta_on_an_unknown_set_404s(self, client: TestClient):
        assert client.post("/client-boq/sets/no-such-set/meta",
                           json={"client": "X"}).status_code == 404


# ---------------------------------------------------------------------------
# The home-screen counts, and blocked
# ---------------------------------------------------------------------------
class TestCounts:
    def test_fresh_upload_is_blocked_on_its_manifest(self, client: TestClient):
        """Uploaded but unapproved: nothing can run, and the shelf must say so."""
        set_id = _upload(client, "counts-fresh")
        row = next(s for s in client.get("/client-boq/sets").json()["sets"]
                   if s["set_id"] == set_id)
        assert row["gates"]["manifest"] is False and row["parts"] == 0
        assert row["blocked"] is True

    def test_counts_track_the_register(self, client: TestClient):
        set_id = _upload(client, "counts-register")
        client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
        client.post("/client-boq/ingest/split", json={"set_id": set_id})
        client.post("/client-boq/review/run",
                    data={"project_name": "counts-register", "set_id": set_id})
        row = next(s for s in client.get("/client-boq/sets").json()["sets"]
                   if s["set_id"] == set_id)
        register = client.get(f"/client-boq/review/register/{set_id}").json()["register"]
        undecided_expected = sum(
            1 for i in register["items"]
            if i["status"] not in ("confirmed", "dismissed", "query", "citation_failed")
        )
        failed_expected = sum(1 for i in register["items"] if i["status"] == "citation_failed")
        assert row["counts"]["undecided"] == undecided_expected
        assert row["counts"]["citation_failed"] == failed_expected

    def test_a_verdict_records_who_gave_it(self, client: TestClient):
        set_id = _upload(client, "counts-verdict")
        client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
        client.post("/client-boq/ingest/split", json={"set_id": set_id})
        client.post("/client-boq/review/run",
                    data={"project_name": "counts-verdict", "set_id": set_id})
        items = client.get(f"/client-boq/review/register/{set_id}").json()["register"]["items"]
        decidable = next(i for i in items if i["status"] != "citation_failed")
        client.post("/client-boq/review/approve",
                    json={"set_id": set_id, "approved": False,
                          "decisions": {str(decidable["item"]): "dismissed"}},
                    headers={"X-CBOQ-Actor": "r-lam"})
        after = client.get(f"/client-boq/review/register/{set_id}").json()["register"]["items"]
        decided = next(i for i in after if i["item"] == decidable["item"])
        assert decided["status"] == "dismissed"
        assert decided["decided_by"] == "r-lam"

    def test_touch_tracking_moves_with_work(self, client: TestClient):
        set_id = _upload(client, "counts-touch", actor="r-lam")
        client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id},
                    headers={"X-CBOQ-Actor": "k-ho"})
        row = next(s for s in client.get("/client-boq/sets").json()["sets"]
                   if s["set_id"] == set_id)
        assert row["meta"]["last_touched_by"] == "k-ho"
        assert row["meta"]["last_touched_at"]
