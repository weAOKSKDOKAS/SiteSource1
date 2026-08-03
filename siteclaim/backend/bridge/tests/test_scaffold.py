"""Phase 1 — the bridge package exists, imports cleanly, and is mounted on the app.

Structure only: every function is still a stub. What these assert is that the seam is wired —
the modules import without touching a database or a network, and the router's paths are on the
app's OpenAPI schema (``app.openapi()``, never ``app.routes``: FastAPI's lazy ``include_router``
puts an ``_IncludedRouter`` wrapper in ``app.routes`` and breaks that style of assertion — see
CLAUDE.md trap 1).
"""

import importlib

import pytest

BRIDGE_MODULES = [
    "bridge",
    "bridge.identity",
    "bridge.parts",
    "bridge.scope",
    "bridge.decisions",
    "bridge.router",
]

EXPECTED_PATHS = {
    "/bridge/{set_id}/bq-candidates",
    "/bridge/{set_id}/bq-part",
    "/bridge/{set_id}/scope",
    "/bridge/{set_id}/route/analyze",
    "/bridge/{set_id}/route/confirm",
}


@pytest.mark.parametrize("name", BRIDGE_MODULES)
def test_every_bridge_module_imports(name):
    assert importlib.import_module(name) is not None


def test_the_bridge_router_is_mounted_on_the_app():
    import api

    paths = set(api.app.openapi()["paths"])          # openapi(), not app.routes (trap 1)
    assert EXPECTED_PATHS <= paths


def test_the_scope_endpoint_carries_both_verbs():
    import api

    methods = {m.lower() for m in api.app.openapi()["paths"]["/bridge/{set_id}/scope"]}
    assert {"get", "post"} <= methods


def test_no_stub_survives_now_that_every_phase_has_landed():
    # This started life as the inverse — a list of stubs asserted to raise NotImplementedError —
    # and shrank by one entry per phase. Now that the last one is implemented, the useful assertion
    # is that none came back: a NotImplementedError left in a shipped path would be a 500 on an
    # endpoint that looks wired.
    import bridge.decisions
    import bridge.identity
    import bridge.parts
    import bridge.router
    import bridge.scope

    for mod in (bridge.identity, bridge.parts, bridge.scope, bridge.decisions, bridge.router):
        source = open(mod.__file__, encoding="utf-8").read()
        assert "NotImplementedError" not in source, f"{mod.__name__} still carries a stub"


def test_the_bridge_never_imports_the_gmail_path():
    # The bridge carries a tender into routing; it sends nothing. Importing the Gmail seam here
    # would be the first step toward a dispatch side-effect nobody asked for.
    import bridge.decisions
    import bridge.identity
    import bridge.parts
    import bridge.router
    import bridge.scope

    for mod in (bridge.identity, bridge.parts, bridge.scope, bridge.decisions, bridge.router):
        source = open(mod.__file__, encoding="utf-8").read()
        assert "gmail" not in source.lower()
