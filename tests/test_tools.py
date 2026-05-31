"""Integration tests for tool functions."""

import json

import pytest

from obsidian_vault_mcp.tools.read import vault_read, vault_batch_read
from obsidian_vault_mcp.tools.write import vault_write, vault_batch_frontmatter_update
from obsidian_vault_mcp.tools.search import vault_search
from obsidian_vault_mcp.tools.manage import vault_list, vault_delete


def test_vault_read_returns_frontmatter(vault_dir):
    """vault_read returns parsed frontmatter."""
    result = json.loads(vault_read("test-note.md"))
    assert "error" not in result
    assert result["frontmatter"]["status"] == "active"
    assert result["frontmatter"]["type"] == "note"
    assert "test note" in result["content"]


def test_vault_write_creates_file(vault_dir):
    """vault_write creates a new file."""
    result = json.loads(vault_write("tools-test.md", "---\ntitle: Test\n---\n\nContent."))
    assert result["created"] is True
    assert result["size"] > 0
    assert (vault_dir / "tools-test.md").exists()


def test_vault_write_merge_frontmatter(vault_dir):
    """vault_write with merge_frontmatter preserves existing fields."""
    result = json.loads(vault_write(
        "test-note.md",
        "---\npriority: high\n---\n\nUpdated body.",
        merge_frontmatter=True,
    ))
    assert "error" not in result

    read_result = json.loads(vault_read("test-note.md"))
    assert read_result["frontmatter"]["status"] == "active"  # preserved
    assert read_result["frontmatter"]["priority"] == "high"  # new


def test_vault_read_serializes_datetime_frontmatter(vault_dir):
    """Frontmatter date/datetime values must serialize as ISO strings, not crash.

    PyYAML parses `created: 2024-01-15` into a datetime.date, which is not JSON
    serializable by default. vault_read must still return the note (with the date
    rendered as an ISO string), not an "Object of type datetime ..." error.
    """
    (vault_dir / "dated-note.md").write_text(
        "---\ncreated: 2024-01-15\nupdated: 2024-01-15 09:30:00\n---\n\nDated note.\n"
    )
    result = json.loads(vault_read("dated-note.md"))
    assert "error" not in result
    assert result["frontmatter"]["created"] == "2024-01-15"
    assert result["frontmatter"]["updated"].startswith("2024-01-15T09:30:00")


def test_vault_batch_read_serializes_datetime_frontmatter(vault_dir):
    """vault_batch_read must not crash on frontmatter date values."""
    (vault_dir / "dated-note.md").write_text(
        "---\ncreated: 2024-01-15\n---\n\nDated note.\n"
    )
    result = json.loads(vault_batch_read(["dated-note.md"]))
    assert result["found"] == 1
    assert result["files"][0]["frontmatter"]["created"] == "2024-01-15"


def test_vault_search_serializes_datetime_frontmatter(vault_dir):
    """vault_search must not crash when a match's frontmatter excerpt has a date."""
    (vault_dir / "dated-note.md").write_text(
        "---\ncreated: 2024-01-15\n---\n\nUniqueHomelabToken content.\n"
    )
    result = json.loads(vault_search("UniqueHomelabToken"))
    assert "error" not in result
    assert result["total_matches"] >= 1
    match = next(m for m in result["results"] if m["path"] == "dated-note.md")
    assert match["frontmatter_excerpt"]["created"] == "2024-01-15"


def test_vault_search_finds_text(vault_dir):
    """vault_search finds text in files."""
    result = json.loads(vault_search("test note"))
    assert result["total_matches"] >= 1
    assert result["results"][0]["path"] == "test-note.md"


def test_vault_batch_read_handles_missing(vault_dir):
    """vault_batch_read returns errors for missing files without failing."""
    result = json.loads(vault_batch_read(
        ["test-note.md", "nonexistent.md"],
        include_content=True,
    ))
    assert result["found"] == 1
    assert result["missing"] == 1
    assert "error" in result["files"][1]


def test_vault_list_returns_items(vault_dir):
    """vault_list returns directory contents."""
    result = json.loads(vault_list(""))
    assert result["total"] >= 2
    names = [item["name"] for item in result["items"]]
    assert "test-note.md" in names
    assert ".obsidian" not in names


def test_vault_delete_requires_confirm(vault_dir):
    """vault_delete without confirm=true returns error."""
    vault_write("delete-me.md", "temp content")
    result = json.loads(vault_delete("delete-me.md", confirm=False))
    assert "error" in result
    assert (vault_dir / "delete-me.md").exists()  # still there
