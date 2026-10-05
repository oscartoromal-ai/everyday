import base64
import hashlib
import hmac

import jwt
import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import create_app


@pytest.fixture
def client(db) -> TestClient:
    app = create_app()

    def override() -> object:
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_unknown_host_rejected(client) -> None:
    response = client.get("/", headers={"Host": "evil.example.com"})
    assert response.status_code == 421


def test_cross_origin_unsafe_request_rejected(client) -> None:
    client.get("/")
    client.headers["X-CSRF"] = client.cookies.get("csrf", "")
    response = client.post(
        "/ui/tasks/quick-add",
        data={"title": "x"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


def test_unsafe_request_without_csrf_rejected(client) -> None:
    client.get("/")  # cookie present, but no header echoed
    response = client.post("/ui/tasks/quick-add", data={"title": "x"})
    assert response.status_code == 403


def test_csrf_double_submit_allows_request(client) -> None:
    client.get("/")
    token = client.cookies.get("csrf", "")
    response = client.post(
        "/ui/tasks/quick-add", data={"title": "guarded"}, headers={"X-CSRF": token}
    )
    assert response.status_code == 200
    assert "guarded" in response.text


def test_same_origin_allowed(client) -> None:
    client.get("/")
    token = client.cookies.get("csrf", "")
    response = client.post(
        "/ui/tasks/quick-add",
        data={"title": "same origin"},
        headers={"X-CSRF": token, "Origin": "http://testserver"},
    )
    assert response.status_code == 200


def test_the_api_takes_json_from_a_client_without_a_cookie(client) -> None:
    # An agent's one call: no cookie, no token, a JSON body.
    response = client.post("/api/tasks", json={"title": "From an agent"})
    assert response.status_code == 201
    # A form or plain text, which a page elsewhere could send, still needs the token.
    assert client.post("/api/tasks", data={"title": "x"}).status_code == 403
    assert client.post(
        "/api/tasks", content='{"title": "x"}', headers={"Content-Type": "text/plain"}
    ).status_code == 403
    # And JSON from another site's page is refused by its Origin.
    refused = client.post(
        "/api/tasks", json={"title": "x"}, headers={"Origin": "https://evil.example.com"}
    )
    assert refused.status_code == 403
    # The pages' own paths keep needing the token, JSON or not.
    assert client.post("/ui/notebook/2026-10-04", json={}).status_code == 403


def test_mcp_exempt_from_csrf(app_db) -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            },
            headers={"accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200


def test_jwt_library_rejects_known_forgeries() -> None:
    """pyjwt comes in through mcp, which verifies tokens with it; the version
    locked must have the fixes for its advisories (PYSEC-2026-4147, -4143)."""
    token = jwt.encode({"sub": "oscar"}, "a-secret-of-thirty-two-bytes-long", algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(token + "!!!!", "a-secret-of-thirty-two-bytes-long", algorithms=["HS256"])

    # Signed with an empty key, as anyone can.
    signing_input = token.rsplit(".", 1)[0]
    mac = hmac.new(b"", signing_input.encode(), hashlib.sha256).digest()
    forged = f"{signing_input}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"
    with pytest.raises(jwt.PyJWTError):
        jwt.decode(
            forged, jwt.PyJWK({"kty": "oct", "k": ""}, algorithm="HS256"), algorithms=["HS256"]
        )
