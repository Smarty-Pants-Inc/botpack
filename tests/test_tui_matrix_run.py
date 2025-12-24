from __future__ import annotations

import json
from pathlib import Path

from botpack.tui.matrix_run import RunConfig, run_matrix


def test_tui_matrix_run_dry_run_creates_results(tmp_path: Path) -> None:
    out_root = tmp_path / "dist"
    run_dir = run_matrix(RunConfig(out_root=out_root, tuis=("claude",), dry_run=True))

    assert run_dir.exists()
    assert (run_dir / "results.json").exists()
    assert (run_dir / "suite.json").exists()

    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    entries = data.get("entries") or []
    assert any(e.get("tui") == "claude" and e.get("feature") == "install:fresh" for e in entries)
    assert any(e.get("tui") == "claude" and e.get("feature") == "botpack:install" for e in entries)

    # Per-TUI feature artifacts (placeholders in dry-run).
    assert (run_dir / "claude" / "skills.json").exists()
    assert (run_dir / "claude" / "commands.json").exists()
    assert (run_dir / "claude" / "agents.json").exists()
    assert (run_dir / "claude" / "target-mcp.json").exists()
