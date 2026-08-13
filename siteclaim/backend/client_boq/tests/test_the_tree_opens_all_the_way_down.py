"""The derivation tree opens all the way down — the working screen's data promise.

The module's own honesty check was the measure of this gap: the endpoint fed `trace_rate` a
hollow breakdown, so every response's build-up node was childless and self-flagged "a bare
number with nothing behind it", and the divisor leaf flagged beside it. The data was there all
along — `load_bill_rates` parses the stored build-up and the endpoint dropped it. These tests
pin the filled tree:

* the build-up node's children ARE the stored resource lines (display of the lines' own
  documented arithmetic — qty ÷ productivity = hours, hours × rate — never a re-pricing);
* the divisor cites the bill's own page (`page_ref`), because in THIS engine the divisor is the
  bill's quantity and the bill is the document that says so;
* each failing node carries its OWN `problem` in place, so the renderer paints the failing line
  red instead of leaving the reader to hunt through a strip;
* the margin's owner is the MODEL's provenance, not whichever person last touched the rate row.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    pytest.importorskip("openpyxl")
    from api import app

    return TestClient(app)


def _import_and_build(client, tmp_path) -> str:
    from client_boq.tests._bqfixture import build_bill_workbook

    path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
    with open(path, "rb") as fh:
        assert client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": (path.name, fh.read(), "application/vnd.ms-excel")},
        ).status_code == 200
    ref = next(i["full_ref"] for i in client.get(f"{BASE}/boq/{SET}").json()["items"]
               if not i["is_parent"] and not i["pre_priced"] and i["qty"])
    build = {
        "item_id": ref, "description": ref, "category": "direct", "unit": "sum",
        "lines": [
            {"description": "Driller", "inline_rate": 2000.0, "qty": 10.0, "unit": "hr"},
            {"description": "Rig", "inline_rate": 500.0, "qty": 40.0, "unit": "hr",
             "productivity": 2.0},
        ],
    }
    assert client.post(f"{BASE}/boq/rate", headers={"X-CBOQ-Actor": "SW"},
                       json={"set_id": SET, "full_ref": ref,
                             "build_up": build}).status_code == 200
    return ref


def _nodes(root) -> list[dict]:
    out = [root]
    for child in root.get("children", []):
        out.extend(_nodes(child))
    return out


class TestTheBuildUpHasChildren:
    def test_the_stored_lines_are_the_trees_terms(self, client, tmp_path):
        ref = _import_and_build(client, tmp_path)
        trace = client.get(f"{BASE}/price/{SET}/trace/{ref}").json()["trace"]
        build_up = next(n for n in _nodes(trace["root"]) if n["label"] == "build-up")
        labels = {c["label"] for c in build_up["children"]}
        assert labels == {"Driller", "Rig"}
        rig = next(c for c in build_up["children"] if c["label"] == "Rig")
        # 40 hr work ÷ 2.0 productivity = 20 hours × 500 — the line's own documented arithmetic.
        assert rig["value"] == pytest.approx(10_000.0)
        assert "500" in rig["formula"] and "20" in rig["formula"]

    def test_a_filled_build_up_no_longer_flags_itself_bare(self, client, tmp_path):
        ref = _import_and_build(client, tmp_path)
        trace = client.get(f"{BASE}/price/{SET}/trace/{ref}").json()["trace"]
        assert not any("'build-up'" in p for p in trace["problems"]), (
            "the terms were always there — with them supplied, the honesty check goes quiet")


class TestTheDivisorCitesTheBill:
    def test_the_quantity_leaf_names_the_bills_own_page(self, client, tmp_path):
        ref = _import_and_build(client, tmp_path)
        trace = client.get(f"{BASE}/price/{SET}/trace/{ref}").json()["trace"]
        divisor = trace["root"]["children"][-1]
        assert divisor["origin"] == "document", "the bill IS the document that says the quantity"
        assert "the bill's own quantity" in divisor["cite"]["label"]
        assert not any("claims a document" in p for p in trace["problems"])


class TestProblemsPaintTheirOwnLine:
    def test_a_failing_node_carries_its_reason_in_place(self):
        from client_boq.boq import trace as boq_trace
        from client_boq.boq.allocate import RateBreakdown

        trace = boq_trace.trace_rate(
            RateBreakdown(full_ref="2.4", label="x", rate=10.0, cost=100.0, divisor=10.0,
                          divisor_label="m"),
            description="x", unit="m", qty=10.0, amount=100.0)
        divisor = trace.root.children[-1]
        assert divisor.problem and "bare number" in divisor.problem
        assert divisor.problem in trace.problems, "the strip and the line agree by construction"

    def test_a_supported_node_carries_no_problem(self, client, tmp_path):
        ref = _import_and_build(client, tmp_path)
        trace = client.get(f"{BASE}/price/{SET}/trace/{ref}").json()["trace"]
        divisor = trace["root"]["children"][-1]
        assert divisor["problem"] == ""


class TestTheMarginOwnerIsProvenance:
    def test_the_library_model_is_named_when_no_own_model_exists(self, client, tmp_path):
        ref = _import_and_build(client, tmp_path)
        trace = client.get(f"{BASE}/price/{SET}/trace/{ref}",
                           params={"margin_pct": 10.0}).json()["trace"]
        margin = next(n for n in _nodes(trace["root"]) if "margin" in n["label"])
        assert margin["owner"] == "the library model", (
            "the app does not record which person set a model input — naming the rate row's "
            "author here was a different person's name on somebody else's decision")
