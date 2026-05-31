"""Startup safety tests for the server entry point.

The server must never serve the vault without authentication. If the
authenticated app cannot be constructed, startup must fail closed (exit
non-zero) rather than fall back to an unauthenticated transport.
"""

from unittest.mock import Mock

import pytest

from obsidian_vault_mcp import server


def test_app_build_failure_fails_closed(tmp_path, monkeypatch):
    """If building the authenticated app raises, main() must exit, not serve.

    Specifically it must NOT fall back to mcp.run(), which would expose the
    vault with no bearer-token enforcement.
    """
    # A valid-looking vault and token so we get past the early guards.
    monkeypatch.setattr(server, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(server, "VAULT_MCP_TOKEN", "a-token")

    # Force construction of the authenticated Starlette app to fail.
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated app build failure")

    monkeypatch.setattr(server.mcp, "streamable_http_app", _boom)

    # Guard rails: if either of these gets called we've served unauthenticated.
    unauth_run = Mock()
    monkeypatch.setattr(server.mcp, "run", unauth_run)

    with pytest.raises(SystemExit) as exc_info:
        server.main()

    assert exc_info.value.code != 0
    unauth_run.assert_not_called()
