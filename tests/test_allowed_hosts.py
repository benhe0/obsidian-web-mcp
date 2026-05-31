"""Tests for building the DNS-rebinding allowed_hosts list from config."""

from obsidian_vault_mcp.server import _build_allowed_hosts

LOCALHOST_HOSTS = {"127.0.0.1:*", "localhost:*", "[::1]:*"}


def test_localhost_always_allowed_when_no_hostname():
    """With no configured hostname, only the localhost entries are allowed."""
    hosts = _build_allowed_hosts("")
    assert set(hosts) == LOCALHOST_HOSTS


def test_none_hostname_is_localhost_only():
    """A missing (None) hostname behaves like an empty one."""
    hosts = _build_allowed_hosts(None)
    assert set(hosts) == LOCALHOST_HOSTS


def test_configured_hostname_is_added():
    """A configured hostname is appended alongside the localhost entries."""
    hosts = _build_allowed_hosts("vault-mcp.example.com")
    assert "vault-mcp.example.com" in hosts
    assert LOCALHOST_HOSTS.issubset(set(hosts))


def test_empty_string_is_not_added_as_a_host():
    """An empty hostname must never end up as an allowed host entry."""
    hosts = _build_allowed_hosts("")
    assert "" not in hosts
