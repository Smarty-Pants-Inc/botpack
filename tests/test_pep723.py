"""Unit tests for PEP 723 parsing utilities."""

from __future__ import annotations

import pytest

from botpack.pep723 import Pep723ScriptMetadata, extract_pep723_script_toml, parse_pep723_script


def test_no_header_returns_none() -> None:
    src = """#!/usr/bin/env python3
print('hello')
"""
    assert extract_pep723_script_toml(src) is None
    assert parse_pep723_script(src) is None


def test_parse_single_line_dependencies() -> None:
    src = """# /// script
# requires-python = ">=3.10"
# dependencies = ["rich", "httpx>=0.27"]
# ///

print('ok')
"""

    meta = parse_pep723_script(src)
    assert isinstance(meta, Pep723ScriptMetadata)
    assert meta.requires_python == ">=3.10"
    assert list(meta.dependencies) == ["rich", "httpx>=0.27"]
    assert "requires-python" in meta.raw_toml


def test_parse_multiline_dependencies_with_comments_and_spacing() -> None:
    # Mix of "# " and "#" prefixing should be accepted.
    src = """# /// script
#requires-python = ">=3.11"
# dependencies = [
#   "rich",
#   "httpx>=0.27",  # comment
# ]
# ///
"""

    meta = parse_pep723_script(src)
    assert meta is not None
    assert meta.requires_python == ">=3.11"
    assert list(meta.dependencies) == ["rich", "httpx>=0.27"]


def test_missing_end_marker_raises() -> None:
    src = """# /// script
# requires-python = ">=3.10"
# dependencies = []
"""
    with pytest.raises(ValueError, match="end marker"):
        extract_pep723_script_toml(src)


def test_non_comment_line_inside_block_raises() -> None:
    src = """# /// script
requires-python = ">=3.10"
# ///
"""
    with pytest.raises(ValueError, match="must be comments"):
        parse_pep723_script(src)


def test_dependencies_must_be_array() -> None:
    src = """# /// script
# dependencies = "rich"
# ///
"""
    with pytest.raises(ValueError, match="dependencies must be a TOML array"):
        parse_pep723_script(src)


def test_dependencies_must_be_strings() -> None:
    src = """# /// script
# dependencies = ["rich", 123]
# ///
"""
    with pytest.raises(ValueError, match="only strings"):
        parse_pep723_script(src)
