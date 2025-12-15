from __future__ import annotations

from pathlib import Path

from botpack.agentic import AgenticRunner, load_scenario_json


FIXTURES = Path(__file__).parent / "fixtures" / "botpack_agentic"


def test_agentic_runner_direct_mode_runs_fixtures_and_writes_report(tmp_path: Path) -> None:
    scenarios = [
        load_scenario_json(FIXTURES / "catalog_sync_happy.json"),
        load_scenario_json(FIXTURES / "trust_gated_mcp.json"),
    ]

    runner = AgenticRunner(mode="direct")
    report_path = tmp_path / "report.json"
    report = runner.run_and_write_report(scenarios, work_root=tmp_path / "work", report_path=report_path)

    assert report_path.exists()
    assert report["version"] == 1
    assert report["ok"] is True

    got_ids = [s["id"] for s in report["scenarios"]]
    assert got_ids == ["catalog_sync_happy", "trust_gated_mcp"]
    assert all(s["ok"] is True for s in report["scenarios"])


def test_agentic_runner_subprocess_mode_can_execute_cli(tmp_path: Path) -> None:
    scenario = load_scenario_json(FIXTURES / "catalog_sync_happy.json")
    runner = AgenticRunner(mode="subprocess")

    res = runner.run_scenario(scenario, workdir=tmp_path / "case")
    assert res.ok is True
