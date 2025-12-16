from __future__ import annotations

import json
import sys
from pathlib import Path

from botpack.agentic import AgenticRunner, load_scenario_json


def test_agentic_runner_supports_run_cmd_and_capture_var(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(
        json.dumps(
            {
                "id": "run_cmd_smoke",
                "name": "run_cmd smoke",
                "steps": [
                    {
                        "kind": "run_cmd",
                        "argv": [sys.executable, "-c", "print('abc')"],
                        "captureVar": "CAP",
                        "expectExitCode": 0,
                    },
                    {
                        "kind": "write_file",
                        "path": "out/cap.txt",
                        "content": "{CAP}",
                    },
                ],
                "checks": [
                    {"kind": "file_contains", "path": "out/cap.txt", "substr": "abc"},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    scenario = load_scenario_json(scenario_path)
    runner = AgenticRunner(mode="subprocess")
    res = runner.run_scenario(scenario, workdir=tmp_path / "work")
    assert res.ok is True
