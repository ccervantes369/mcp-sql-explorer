"""The HTTP door: who gets turned away, and what happens with no key at all."""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_server import TokenAuthMiddleware, main

TOKEN = "test-token-not-a-real-secret"


@pytest.fixture
def client():
    """The middleware in front of a stand-in app that says "reached".

    Testing it against a trivial app rather than the real MCP server keeps
    the question narrow: did the request get through the door, or not?
    """

    async def endpoint(request):
        return PlainTextResponse("reached")

    app = Starlette(routes=[Route("/mcp", endpoint, methods=["GET", "POST"])])
    app.add_middleware(TokenAuthMiddleware, token=TOKEN)
    return TestClient(app)


def test_a_correct_token_gets_through(client):
    response = client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.text == "reached"


def test_no_authorization_header_is_refused(client):
    response = client.get("/mcp")

    assert response.status_code == 401
    # The point is not only the status: the request must not have arrived.
    assert response.text != "reached"


def test_a_wrong_token_is_refused(client):
    response = client.get("/mcp", headers={"Authorization": "Bearer wrong-guess"})

    assert response.status_code == 401
    assert response.text != "reached"


def test_the_bearer_prefix_is_required(client):
    # The header is the whole comparison, so the bare token is not enough.
    response = client.get("/mcp", headers={"Authorization": TOKEN})

    assert response.status_code == 401


def test_a_prefix_of_the_token_is_refused(client):
    # Guarding against a comparison that only checks the start.
    response = client.get(
        "/mcp", headers={"Authorization": f"Bearer {TOKEN[:-1]}"}
    )

    assert response.status_code == 401


def test_http_mode_refuses_to_start_without_a_token(monkeypatch):
    """The whole point of failing closed: no token, no server."""
    monkeypatch.setenv("SQL_EXPLORER_TRANSPORT", "streamable-http")
    monkeypatch.delenv("SQL_EXPLORER_TOKEN", raising=False)

    with pytest.raises(ValueError, match="SQL_EXPLORER_TOKEN"):
        main()


def test_an_unknown_transport_is_rejected(monkeypatch):
    monkeypatch.setenv("SQL_EXPLORER_TRANSPORT", "carrier-pigeon")

    with pytest.raises(ValueError, match="Unknown transport"):
        main()
