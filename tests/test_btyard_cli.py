from __future__ import annotations

from botpack.cli import main


def test_by_cli_doctor_runs() -> None:
    assert main(["doctor"]) == 0
