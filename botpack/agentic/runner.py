from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Literal

from .models import CheckSpec, ScenarioSpec, StepSpec
from .schema import validate_json_schema


RunnerMode = Literal["direct", "subprocess"]


@dataclass(frozen=True)
class StepResult:
    kind: str
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int | None = None
    message: str | None = None


@dataclass(frozen=True)
class CheckResult:
    kind: str
    ok: bool
    message: str | None = None


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    name: str
    ok: bool
    steps: list[StepResult]
    checks: list[CheckResult]


def _pkg_root_for_subprocess() -> str:
    # This file lives at: <project_root>/botpack/agentic/runner.py
    # runner.py -> agentic/ -> botpack/ -> <project_root>
    return str(Path(__file__).resolve().parents[2])


class _Env:
    def __init__(self, updates: dict[str, str]):
        self._updates = updates
        self._old: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for k, v in self._updates.items():
            self._old[k] = os.environ.get(k)
            os.environ[k] = v

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        for k, old in self._old.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


class _Cwd:
    def __init__(self, path: Path):
        self._path = path
        self._old = Path.cwd()

    def __enter__(self) -> None:
        os.chdir(self._path)

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        os.chdir(self._old)


class AgenticRunner:
    def __init__(self, *, mode: RunnerMode = "direct"):
        self._mode = mode

    def run_scenario(self, scenario: ScenarioSpec, *, workdir: Path) -> ScenarioResult:
        workdir = workdir.resolve()
        workdir.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        # Always override to keep runs isolated/deterministic.
        env["BOTPACK_ROOT"] = str(workdir)
        env["BOTPACK_STORE"] = str(workdir / "store")
        # Back-compat for legacy environment variables.
        env["BOTYARD_ROOT"] = env["BOTPACK_ROOT"]
        env["BOTYARD_STORE"] = env["BOTPACK_STORE"]

        step_results: list[StepResult] = []

        for step in scenario.steps:
            if step.kind == "mkdir":
                step_results.append(self._run_mkdir(step, workdir=workdir))
                continue
            if step.kind == "write_file":
                step_results.append(self._run_write_file(step, workdir=workdir))
                continue
            if step.kind == "capture_file":
                step_results.append(self._run_capture_file(step, workdir=workdir))
                continue
            if step.kind == "run":
                step_results.append(self._run_cli(step, workdir=workdir, env=env))
                continue
            step_results.append(StepResult(kind=step.kind, ok=False, message=f"unsupported step kind {step.kind!r}"))

        check_results = self._evaluate_checks(scenario.checks, workdir=workdir, steps=step_results)
        ok = all(s.ok for s in step_results) and all(c.ok for c in check_results)
        return ScenarioResult(
            id=scenario.id,
            name=scenario.name,
            ok=ok,
            steps=step_results,
            checks=check_results,
        )

    def run_and_write_report(
        self,
        scenarios: list[ScenarioSpec],
        *,
        work_root: Path,
        report_path: Path,
    ) -> dict[str, Any]:
        results: list[ScenarioResult] = []
        for s in scenarios:
            res = self.run_scenario(s, workdir=work_root / s.id)
            results.append(res)

        report = {
            "version": 1,
            "ok": all(r.ok for r in results),
            "scenarios": [self._scenario_result_to_dict(r) for r in results],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return report

    def _run_mkdir(self, step: StepSpec, *, workdir: Path) -> StepResult:
        assert step.path is not None
        try:
            (workdir / step.path).mkdir(parents=True, exist_ok=True)
            return StepResult(kind=step.kind, ok=True)
        except Exception as e:  # pragma: no cover
            return StepResult(kind=step.kind, ok=False, message=str(e))

    def _run_write_file(self, step: StepSpec, *, workdir: Path) -> StepResult:
        assert step.path is not None
        assert step.content is not None
        try:
            p = (workdir / step.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(step.content, encoding="utf-8")
            return StepResult(kind=step.kind, ok=True)
        except Exception as e:  # pragma: no cover
            return StepResult(kind=step.kind, ok=False, message=str(e))

    def _run_capture_file(self, step: StepSpec, *, workdir: Path) -> StepResult:
        assert step.path is not None
        p = workdir / step.path
        if not p.exists():
            return StepResult(kind=step.kind, ok=False, message=f"missing: {step.path}")
        try:
            return StepResult(kind=step.kind, ok=True, stdout=p.read_text(encoding="utf-8"))
        except Exception as e:  # pragma: no cover
            return StepResult(kind=step.kind, ok=False, message=str(e))

    def _run_cli(self, step: StepSpec, *, workdir: Path, env: dict[str, str]) -> StepResult:
        assert step.argv is not None
        t0 = monotonic()

        if self._mode == "subprocess":
            cmd = [sys.executable, "-m", "botpack.cli", *step.argv]
            # Ensure importable even when cwd is a temp directory.
            py_path = env.get("PYTHONPATH")
            pkg_root = _pkg_root_for_subprocess()
            env2 = dict(env)
            env2["PYTHONPATH"] = pkg_root if not py_path else (pkg_root + os.pathsep + py_path)
            p = subprocess.run(cmd, cwd=str(workdir), env=env2, capture_output=True, text=True)
            dur = int((monotonic() - t0) * 1000)
            ok = True
            msg = None
            if step.expect_exit_code is not None and p.returncode != step.expect_exit_code:
                ok = False
                msg = f"expected exit {step.expect_exit_code}, got {p.returncode}"
            return StepResult(
                kind=step.kind,
                ok=ok,
                stdout=p.stdout,
                stderr=p.stderr,
                exit_code=p.returncode,
                duration_ms=dur,
                message=msg,
            )

        # direct
        try:
            from botpack.cli import main as by_main
            import io
            from contextlib import redirect_stderr, redirect_stdout

            out = io.StringIO()
            err = io.StringIO()
            with _Env({"BOTPACK_ROOT": env["BOTPACK_ROOT"], "BOTPACK_STORE": env["BOTPACK_STORE"]}), _Cwd(workdir):
                with redirect_stdout(out), redirect_stderr(err):
                    rc = by_main(list(step.argv))
        except SystemExit as e:
            rc = int(getattr(e, "code", 1) or 0)
            out = io.StringIO("")
            err = io.StringIO(str(e))
        except Exception as e:  # pragma: no cover
            rc = 1
            out = io.StringIO("")
            err = io.StringIO(repr(e))

        dur = int((monotonic() - t0) * 1000)
        ok = True
        msg = None
        if step.expect_exit_code is not None and rc != step.expect_exit_code:
            ok = False
            msg = f"expected exit {step.expect_exit_code}, got {rc}"
        return StepResult(
            kind=step.kind,
            ok=ok,
            stdout=out.getvalue(),
            stderr=err.getvalue(),
            exit_code=rc,
            duration_ms=dur,
            message=msg,
        )

    def _evaluate_checks(self, checks: list[CheckSpec], *, workdir: Path, steps: list[StepResult]) -> list[CheckResult]:
        out: list[CheckResult] = []
        for c in checks:
            if c.kind == "file_exists":
                assert c.path is not None
                p = workdir / c.path
                out.append(CheckResult(kind=c.kind, ok=p.exists(), message=None if p.exists() else f"missing: {c.path}"))
                continue

            if c.kind == "file_contains":
                assert c.path is not None
                assert c.substr is not None
                p = workdir / c.path
                if not p.exists():
                    out.append(CheckResult(kind=c.kind, ok=False, message=f"missing: {c.path}"))
                    continue
                text = p.read_text(encoding="utf-8")
                ok = c.substr in text
                out.append(CheckResult(kind=c.kind, ok=ok, message=None if ok else f"{c.path}: missing substring"))
                continue

            if c.kind == "output_contains":
                assert c.substr is not None
                assert c.step is not None
                assert c.stream is not None
                if c.step < 0 or c.step >= len(steps):
                    out.append(CheckResult(kind=c.kind, ok=False, message=f"invalid step index {c.step}"))
                    continue
                sr = steps[c.step]
                hay = ""
                if c.stream == "stdout":
                    hay = sr.stdout
                elif c.stream == "stderr":
                    hay = sr.stderr
                elif c.stream == "combined":
                    hay = sr.stdout + sr.stderr
                else:
                    out.append(CheckResult(kind=c.kind, ok=False, message=f"invalid stream {c.stream!r}"))
                    continue
                ok = c.substr in hay
                out.append(CheckResult(kind=c.kind, ok=ok, message=None if ok else "substring not found"))
                continue

            if c.kind == "json_schema":
                assert c.path is not None
                assert c.schema is not None
                p = workdir / c.path
                if not p.exists():
                    out.append(CheckResult(kind=c.kind, ok=False, message=f"missing: {c.path}"))
                    continue
                try:
                    instance = json.loads(p.read_text(encoding="utf-8"))
                except Exception as e:
                    out.append(CheckResult(kind=c.kind, ok=False, message=f"invalid JSON: {e}"))
                    continue
                errs = validate_json_schema(instance, c.schema)
                out.append(CheckResult(kind=c.kind, ok=(len(errs) == 0), message="; ".join(errs) if errs else None))
                continue

            out.append(CheckResult(kind=c.kind, ok=False, message=f"unsupported check kind {c.kind!r}"))

        return out

    def _scenario_result_to_dict(self, r: ScenarioResult) -> dict[str, Any]:
        return {
            "id": r.id,
            "name": r.name,
            "ok": r.ok,
            "steps": [
                {
                    "kind": s.kind,
                    "ok": s.ok,
                    "stdout": s.stdout,
                    "stderr": s.stderr,
                    "exitCode": s.exit_code,
                    "durationMs": s.duration_ms,
                    "message": s.message,
                }
                for s in r.steps
            ],
            "checks": [
                {
                    "kind": c.kind,
                    "ok": c.ok,
                    "message": c.message,
                }
                for c in r.checks
            ],
        }
