"""A server crash reaches the screen as a sentence, not as "Failed to fetch".

THE FAILURE THIS PINS, observed live on the Route tab: an unhandled exception in a handler became
a 500 with no CORS headers — Starlette routes a bare ``Exception`` to the OUTERMOST middleware,
outside ``CORSMiddleware`` — so the browser refused to show the response to the page and the
estimator read "Failed to fetch" about a server crash. An error with no noun in it: nothing to do,
nothing to report, and the person concludes the software is broken in some total way.

``api.py``'s ``@app.exception_handler(Exception)`` is the fix: a JSON 500 whose sentence a person
can act on, carrying the CORS header by hand because this response never passes through the
middleware that would add it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api import app

_BOOM_PATH = "/very-unlikely-test-only-boom"


def _with_boom_route():
    """A throwaway route that raises — registered for one test, removed after.

    The handler's job is to dress ANY crash; a route built to crash is the honest probe, and
    breaking a real endpoint to simulate one would test the breakage, not the dressing.
    """
    async def boom():
        raise RuntimeError("deliberate: the handler under test must dress this")

    app.add_api_route(_BOOM_PATH, boom, methods=["GET"], include_in_schema=False)
    return lambda: app.router.routes.remove(
        next(r for r in app.router.routes if getattr(r, "path", "") == _BOOM_PATH))


def test_an_unhandled_error_is_a_sentence_with_cors_headers_not_a_failed_fetch():
    remove = _with_boom_route()
    try:
        # raise_server_exceptions=False is the browser's view: the response, not the traceback.
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(_BOOM_PATH)

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "server" in detail and "Try the action once more" in detail
        assert "RuntimeError" not in detail, "the traceback belongs in the log, not on the screen"
        # The header the browser needs before it will show the body to the page at all. Absent,
        # the page sees a network error and the words above are never read by anyone.
        assert resp.headers.get("access-control-allow-origin") == "*"
    finally:
        remove()


def test_the_handler_does_not_swallow_deliberate_http_refusals():
    """A 409 gate refusal is a designed message, not a crash — it must pass through untouched."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/bridge/never-touched-set/scope")
    assert resp.status_code in (404, 409)
    assert "Try the action once more" not in resp.json()["detail"]


def test_tests_that_assert_on_raises_still_see_the_exception():
    """Starlette re-raises after the handler runs, so the default TestClient still surfaces the
    exception — the suite's existing raises-based tests are unaffected by the handler."""
    import pytest

    remove = _with_boom_route()
    try:
        client = TestClient(app)  # raise_server_exceptions=True, the default
        with pytest.raises(RuntimeError, match="deliberate"):
            client.get(_BOOM_PATH)
    finally:
        remove()
