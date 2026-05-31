"""Security tests for the OAuth 2.0 flow.

These tests encode the security contract of the OAuth endpoints:

1. An anonymous attacker who knows only the public server URL must NOT be able
   to obtain the master bearer token (which grants full read/write/delete on the
   vault). This is the headline exploit.
2. The dynamic client registration endpoint must not leak the configured shared
   client secret in plaintext.
3. A *legitimate* client that proves possession of the configured client secret
   must still be able to complete the authorization_code + PKCE flow (regression
   guard so the real Claude integration keeps working after the fix).
"""

import base64
import hashlib
import secrets
from urllib.parse import urlparse, parse_qs

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from obsidian_vault_mcp import config
from obsidian_vault_mcp.oauth import oauth_routes


CONFIGURED_TOKEN = "super-secret-master-token"
CONFIGURED_CLIENT_ID = "the-real-client-id"
CONFIGURED_CLIENT_SECRET = "the-real-client-secret"


@pytest.fixture
def client(monkeypatch):
    """A TestClient over the real OAuth routes with known configured secrets."""
    monkeypatch.setattr(config, "VAULT_MCP_TOKEN", CONFIGURED_TOKEN)
    monkeypatch.setattr(config, "VAULT_OAUTH_CLIENT_ID", CONFIGURED_CLIENT_ID)
    monkeypatch.setattr(config, "VAULT_OAUTH_CLIENT_SECRET", CONFIGURED_CLIENT_SECRET)
    app = Starlette(routes=oauth_routes)
    return TestClient(app)


def _pkce_pair():
    """Generate a PKCE (verifier, S256 challenge) pair, attacker-style."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _get_auth_code(client, redirect_uri, challenge):
    """Drive /oauth/authorize and pull the issued code out of the redirect."""
    resp = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "anything",
            "redirect_uri": redirect_uri,
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    return parse_qs(urlparse(location).query)["code"][0]


def test_anonymous_attacker_cannot_obtain_bearer_token(client):
    """The core exploit: no credentials, full token.

    An attacker who knows only the URL drives authorize -> token using a PKCE
    pair they generated themselves and supplies NO client secret. The server
    must refuse to hand back the master bearer token.
    """
    redirect_uri = "https://attacker.example/callback"
    verifier, challenge = _pkce_pair()

    code = _get_auth_code(client, redirect_uri, challenge)

    resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            # NOTE: no client_secret -- attacker doesn't have one
        },
    )

    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    assert body.get("access_token") != CONFIGURED_TOKEN, (
        "VULNERABILITY: anonymous attacker obtained the master bearer token"
    )
    assert resp.status_code in (400, 401), resp.text


def test_wrong_client_secret_is_rejected(client):
    """Supplying an incorrect client_secret must not yield the token either."""
    redirect_uri = "https://attacker.example/callback"
    verifier, challenge = _pkce_pair()
    code = _get_auth_code(client, redirect_uri, challenge)

    resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": CONFIGURED_CLIENT_ID,
            "client_secret": "wrong-guess",
        },
    )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    assert body.get("access_token") != CONFIGURED_TOKEN
    assert resp.status_code in (400, 401), resp.text


def test_register_does_not_leak_configured_secret(client):
    """Dynamic registration must not echo the configured shared secret."""
    resp = client.post("/oauth/register", json={"client_name": "Attacker"})
    assert resp.status_code == 201, resp.text
    assert CONFIGURED_CLIENT_SECRET not in resp.text, (
        "VULNERABILITY: /oauth/register leaks the configured client secret"
    )


def test_legitimate_client_with_secret_succeeds(client):
    """Regression guard: the real flow (correct secret + valid PKCE) still works."""
    redirect_uri = "https://claude.ai/api/mcp/auth_callback"
    verifier, challenge = _pkce_pair()
    code = _get_auth_code(client, redirect_uri, challenge)

    resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": CONFIGURED_CLIENT_ID,
            "client_secret": CONFIGURED_CLIENT_SECRET,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"] == CONFIGURED_TOKEN
