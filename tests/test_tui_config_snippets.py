from __future__ import annotations

import sys

from botpack.tui.config_snippets import snippet_for


def test_snippet_for_codex_includes_python_and_module() -> None:
    fmt, s = snippet_for("codex")
    assert fmt == "toml"
    assert sys.executable in s
    assert "botpack.mcp_magic_number_server" in s


def test_snippet_for_amp_is_json() -> None:
    fmt, s = snippet_for("amp")
    assert fmt == "json"
    assert "mcpServers" in s
    assert "botpack.mcp_magic_number_server" in s
