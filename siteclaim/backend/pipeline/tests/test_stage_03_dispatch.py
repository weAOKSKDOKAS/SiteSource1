"""Stage 03 dispatch — only approved firms, each with only its trade's documents,
emails composed (baked in DEMO_MODE), and a mock outbox that touches no network."""

import pytest

from db import seed, store
from db.outbox import read_outbox, send_mock
from pipeline.stage_01_ingest.ingest import ingest_tender
from pipeline.stage_02_shortlist.shortlist import shortlist
from pipeline.stage_03_dispatch.dispatch import build_dispatch
from schemas.models import DispatchSet, DispatchStatus, ScopePackages, TenderPackage

_SCOPE_FIXTURE = "cases/clean/scope_packages.json"
_DISPATCH_FIXTURE = "cases/clean/dispatch.json"


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("dispatch") / "test.db"
    seed.build_database(db_path)
    connection = store.get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def scope() -> ScopePackages:
    return ingest_tender(TenderPackage(project_name="Kwun Tong Commercial Tower", description=""), demo_fixture=_SCOPE_FIXTURE)


@pytest.fixture
def shortlisted(conn, scope):
    return shortlist(scope, conn=conn)


def _dispatch(shortlisted, scope, approvals):
    return build_dispatch(
        shortlisted, approvals, demo_fixture=_DISPATCH_FIXTURE,
        scope=scope, project_name=scope.project_name,
    )


def test_only_approved_shortlisted_firms_get_a_bundle(shortlisted, scope):
    approvals = {"electrical": ["F-EL-02"], "fire_services": ["F-FS-01"], "joinery_fitting_out": []}
    ds = _dispatch(shortlisted, scope, approvals)
    assert {(b.trade, b.firm_id) for b in ds.bundles} == {("electrical", "F-EL-02"), ("fire_services", "F-FS-01")}


def test_approving_a_non_shortlisted_firm_is_ignored(shortlisted, scope):
    ds = _dispatch(shortlisted, scope, {"electrical": ["F-EL-99"]})
    assert ds.bundles == []


def test_each_bundle_carries_only_its_trade_documents(shortlisted, scope):
    approvals = {"electrical": ["F-EL-02"], "fire_services": ["F-FS-01"]}
    ds = _dispatch(shortlisted, scope, approvals)
    by_trade = {b.trade: b for b in ds.bundles}

    electrical_items = {f"SoR {i.item_ref}" for i in next(p for p in scope.packages if p.trade == "electrical").sor_items}
    fire_items = {f"SoR {i.item_ref}" for i in next(p for p in scope.packages if p.trade == "fire_services").sor_items}

    el_refs = set(by_trade["electrical"].bundle_doc_refs)
    assert "electrical — scope & SoR package" in el_refs
    assert electrical_items <= el_refs           # the electrical firm gets the electrical SoR …
    assert not (fire_items & el_refs)            # … and none of the fire-services items


def test_emails_are_composed_specific_to_trade_and_project(shortlisted, scope):
    ds = _dispatch(shortlisted, scope, {"electrical": ["F-EL-02"]})
    bundle = ds.bundles[0]
    assert bundle.status is DispatchStatus.APPROVED
    assert "Electrical" in bundle.email_subject and "Kwun Tong" in bundle.email_subject
    assert bundle.email_body.strip()


def test_unbaked_firm_falls_back_to_offline_template(shortlisted, scope):
    # F-EL-03 is shortlisted but not in the baked dispatch fixture -> deterministic template.
    ds = _dispatch(shortlisted, scope, {"electrical": ["F-EL-03"]})
    bundle = ds.bundles[0]
    assert bundle.firm_id == "F-EL-03"
    assert "RFQ — Electrical package" in bundle.email_subject


def test_send_mock_records_to_outbox_and_flips_status(shortlisted, scope, tmp_path):
    ds = _dispatch(shortlisted, scope, {"electrical": ["F-EL-02"], "fire_services": ["F-FS-01"]})
    outbox = tmp_path / "outbox.json"
    sent = send_mock(ds, outbox_path=outbox)

    assert all(b.status is DispatchStatus.SENT_MOCK for b in sent.bundles)
    records = read_outbox(outbox)
    assert {r["firm_id"] for r in records} == {"F-EL-02", "F-FS-01"}
    assert all(r["sent_at"] for r in records)  # timestamped


def test_dispatch_set_wraps_a_bare_bundle_list():
    # Live drift: the model returns a bare top-level array of bundles instead of the
    # {"bundles": [...]} envelope. The content is right, only the envelope is wrong.
    bare = (
        '[{"firm_id": "castco-testing-centre-limited-b6e5", "firm_name": "Castco Testing Centre Limited", '
        '"trade": "ground_investigation", "email_subject": "RFQ — Ground Investigation", '
        '"email_body": "Dear Castco, ... Kind regards, Buying Team"}]'
    )
    ds = DispatchSet.model_validate_json(bare)
    assert len(ds.bundles) == 1
    assert ds.bundles[0].firm_id == "castco-testing-centre-limited-b6e5"
    assert ds.bundles[0].trade == "ground_investigation" and ds.bundles[0].email_subject.startswith("RFQ")


def test_dispatch_set_object_payload_still_parses():
    # The shim is a no-op when the model already returns the correct envelope.
    obj = '{"bundles": [{"firm_id": "f1", "firm_name": "F1 Ltd", "trade": "electrical", "email_subject": "S", "email_body": "B"}]}'
    ds = DispatchSet.model_validate_json(obj)
    assert len(ds.bundles) == 1 and ds.bundles[0].firm_id == "f1"


# -- email compose is batched (<=6 per call), a failed batch degrades to templates -----
import re  # noqa: E402
import threading  # noqa: E402

from pydantic import ValidationError  # noqa: E402

import pipeline.stage_03_dispatch.dispatch as dispatch_mod  # noqa: E402
from schemas.models import DispatchBundle  # noqa: E402


class _BatchClient:
    """Records each compose batch's size; composes bundles for the firms named in the
    prompt, or raises for a batch containing ``fail_if_contains`` (a truncated response)."""

    def __init__(self, fail_if_contains: str | None = None):
        self.batch_sizes: list[int] = []
        self._lock = threading.Lock()
        self._fail = fail_if_contains

    def complete_json(self, *, user, target_model, **_):
        fids = re.findall(r"\(([^)]+)\)", user)  # "- Firm 0 (F-EL-00) — trade: electrical"
        with self._lock:
            self.batch_sizes.append(len(fids))
        if self._fail and self._fail in fids:
            raise RuntimeError("truncated JSON")
        return DispatchSet(bundles=[
            DispatchBundle(firm_id=f, firm_name=f, trade="electrical", email_subject=f"S-{f}", email_body="B")
            for f in fids
        ])


def _scaffold(n: int):
    return [("electrical", f"F-EL-{i:02d}", f"Firm {i}", []) for i in range(n)]


def test_compose_emails_batches_to_at_most_six_and_composes_all(monkeypatch):
    monkeypatch.setattr(dispatch_mod, "demo_mode", lambda: False)  # exercise the live compose path
    client = _BatchClient()

    emails = dispatch_mod._compose_emails(_scaffold(13), "Proj X", None, client)

    assert sorted(client.batch_sizes) == [1, 6, 6]           # 13 -> bounded batches of <=6
    assert len(emails) == 13
    assert all(subj.startswith("S-") for (subj, _body) in emails.values())  # every firm model-composed


def test_a_failed_compose_batch_falls_back_to_templates_without_failing_dispatch(monkeypatch):
    monkeypatch.setattr(dispatch_mod, "demo_mode", lambda: False)
    client = _BatchClient(fail_if_contains="F-EL-07")  # the second batch (firms 6,7) fails

    emails = dispatch_mod._compose_emails(_scaffold(8), "Proj X", None, client)

    assert len(emails) == 8                                    # nothing dropped
    assert emails[("electrical", "F-EL-00")][0] == "S-F-EL-00"  # first batch model-composed
    subj, _body = emails[("electrical", "F-EL-07")]
    assert subj == "RFQ — Electrical package — Proj X"        # failed batch -> deterministic template


class FakeSDKError(Exception):
    """A non-transient provider/SDK error — a bad or unfunded API key's AuthenticationError, or a
    missing SDK's ImportError, which `llm_client._retry` re-raises as-is. Crucially it is NONE of
    RuntimeError / FileNotFoundError / ValidationError / ValueError, so the old narrow compose catch
    let it escape and 500 `POST /dispatch/drafts`."""


class _RaisingClient:
    def complete_json(self, **_):
        raise FakeSDKError("401 Unauthorized — bad or unfunded API key")


def test_a_non_transient_compose_error_never_fails_the_dispatch(shortlisted, scope, monkeypatch):
    # The regression Fix 1 closes: a dead API key (or a missing SDK's ImportError) is none of the
    # four types the compose catch used to name, so it escaped `_compose_batch`, propagated through
    # build_dispatch, and turned the endpoint into a 500 — contradicting the module's own contract.
    assert not issubclass(FakeSDKError, (RuntimeError, FileNotFoundError, ValidationError, ValueError))
    monkeypatch.setattr(dispatch_mod, "demo_mode", lambda: False)  # force the live compose path

    ds = _dispatch_with_client(shortlisted, scope, {"electrical": ["F-EL-02"]}, _RaisingClient())

    assert isinstance(ds, DispatchSet)                         # a DispatchSet, not a raised exception
    bundle = next(b for b in ds.bundles if b.firm_id == "F-EL-02")
    tmpl_subject, tmpl_body = dispatch_mod._template_email(bundle.firm_name, "electrical", scope.project_name)
    assert bundle.email_body == tmpl_body                      # the deterministic template body …
    assert bundle.email_subject.startswith(tmpl_subject)       # … and its subject (before the ref tag)
    assert "[SiteSource Ref:" in bundle.email_subject          # a real dispatched bundle, not a bare compose


def _dispatch_with_client(shortlisted, scope, approvals, client):
    return build_dispatch(
        shortlisted, approvals, scope=scope, project_name=scope.project_name, client=client,
    )
