from __future__ import annotations

from pathlib import Path

from botpack.mcp_smoke import run_smoke


def test_mcp_smoke_default_ok(tmp_path: Path) -> None:
    res = run_smoke(cwd=tmp_path)
    assert res.ok is True
    assert res.tools_count >= 1
    assert res.server
