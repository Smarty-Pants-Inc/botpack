from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


MatrixStatus = Literal["PASS", "FAIL", "PARTIAL", "N/A", "BLOCKED"]


def _ts_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("matrix-%Y%m%d-%H%M%S")


@dataclass(frozen=True)
class MatrixRun:
    run_dir: Path

    @staticmethod
    def create(*, out_root: Path) -> MatrixRun:
        rid = _run_id()
        run_dir = (out_root / rid).resolve()
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "results.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "generated_at": _ts_utc(),
                    "run_id": rid,
                    "entries": [],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return MatrixRun(run_dir=run_dir)

    @staticmethod
    def load(run_dir: Path) -> MatrixRun:
        return MatrixRun(run_dir=run_dir.resolve())

    def _results_path(self) -> Path:
        return self.run_dir / "results.json"

    def record(
        self,
        *,
        tui: str,
        feature: str,
        status: MatrixStatus,
        evidence: str = "",
        artifacts: str = "",
        notes: str = "",
    ) -> None:
        p = self._results_path()
        if not p.exists():
            raise FileNotFoundError(str(p))
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("results.json: expected object")
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("results.json: entries must be a list")
        entries.append(
            {
                "at": _ts_utc(),
                "tui": tui,
                "feature": feature,
                "status": status,
                "evidence": evidence,
                "artifacts": artifacts,
                "notes": notes,
            }
        )
        data["entries"] = entries

        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
