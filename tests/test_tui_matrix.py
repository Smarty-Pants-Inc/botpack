from __future__ import annotations

import json
from pathlib import Path

from botpack.tui.matrix import MatrixRun


def test_matrix_run_create_and_record(tmp_path: Path) -> None:
    out_root = tmp_path / "dist" / "tests"
    mr = MatrixRun.create(out_root=out_root)

    p = mr.run_dir / "results.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert isinstance(data["entries"], list)

    mr.record(tui="opencode", feature="commands:hello", status="PASS", evidence="Hello")
    data2 = json.loads(p.read_text(encoding="utf-8"))
    assert len(data2["entries"]) == 1
    assert data2["entries"][0]["status"] == "PASS"
