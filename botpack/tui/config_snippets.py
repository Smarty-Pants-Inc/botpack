from __future__ import annotations

import json
import sys
from typing import Literal


TuiConfigName = Literal["codex", "coder", "amp"]


def _toml_array_str(xs: list[str]) -> str:
    return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in xs) + "]"


def codex_mcp_magic_number_snippet() -> str:
    py = sys.executable
    return (
        "[mcp_servers.mcp-magic-number]\n"
        f"command = {json.dumps(py, ensure_ascii=False)}\n"
        f"args = {_toml_array_str(['-m', 'botpack.mcp_magic_number_server'])}\n"
    )


def coder_mcp_magic_number_snippet() -> str:
    # just-every/code uses the same TOML shape as Codex.
    return codex_mcp_magic_number_snippet()


def amp_mcp_magic_number_snippet() -> str:
    py = sys.executable
    payload = {
        "amp": {
            "mcpServers": {
                "mcp-magic-number": {
                    "transport": "stdio",
                    "command": py,
                    "args": ["-m", "botpack.mcp_magic_number_server"],
                }
            }
        }
    }
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def snippet_for(tui: TuiConfigName) -> tuple[str, str]:
    """Return (format, snippet) for the given TUI."""

    if tui == "codex":
        return ("toml", codex_mcp_magic_number_snippet())
    if tui == "coder":
        return ("toml", coder_mcp_magic_number_snippet())
    if tui == "amp":
        return ("json", amp_mcp_magic_number_snippet())
    raise ValueError(f"unsupported tui: {tui}")
