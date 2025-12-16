from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ScenarioSpecError(ValueError):
    pass


def _expect_dict(v: Any, *, ctx: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ScenarioSpecError(f"{ctx}: expected object")
    return v


def _expect_list(v: Any, *, ctx: str) -> list[Any]:
    if not isinstance(v, list):
        raise ScenarioSpecError(f"{ctx}: expected array")
    return v


def _expect_str(v: Any, *, ctx: str) -> str:
    if not isinstance(v, str):
        raise ScenarioSpecError(f"{ctx}: expected string")
    return v


def _expect_int(v: Any, *, ctx: str) -> int:
    if not isinstance(v, int):
        raise ScenarioSpecError(f"{ctx}: expected integer")
    return v


@dataclass(frozen=True)
class StepSpec:
    """A scenario step.

    Supported kinds:
      - mkdir: create a directory
      - write_file: write a UTF-8 text file
      - run: execute botpack CLI (python -m botpack.cli or direct invocation)
      - run_cmd: execute an arbitrary command (used for uv-based E2E)
      - capture_file: read a file into the step result stdout (for deterministic assertions)
    """

    kind: str
    path: str | None = None
    content: str | None = None
    argv: list[str] | None = None
    expect_exit_code: int | None = None
    cwd: str | None = None
    env: dict[str, str] | None = None
    capture_var: str | None = None


@dataclass(frozen=True)
class CheckSpec:
    """A deterministic rubric check."""

    kind: str
    path: str | None = None
    substr: str | None = None
    schema: dict[str, Any] | None = None
    step: int | None = None
    stream: str | None = None  # stdout|stderr|combined


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    name: str
    steps: list[StepSpec]
    checks: list[CheckSpec]


def load_scenario_json(path: str | Path) -> ScenarioSpec:
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ScenarioSpecError(f"unable to read scenario: {p}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ScenarioSpecError(f"invalid JSON in scenario: {p}") from e

    obj = _expect_dict(data, ctx="scenario")
    sid = _expect_str(obj.get("id"), ctx="scenario.id")
    name = _expect_str(obj.get("name"), ctx="scenario.name")

    steps_raw = _expect_list(obj.get("steps"), ctx="scenario.steps")
    checks_raw = _expect_list(obj.get("checks"), ctx="scenario.checks")

    steps: list[StepSpec] = []
    for i, s in enumerate(steps_raw):
        tbl = _expect_dict(s, ctx=f"scenario.steps[{i}]")
        kind = _expect_str(tbl.get("kind"), ctx=f"scenario.steps[{i}].kind")

        cwd = tbl.get("cwd")
        if cwd is not None:
            cwd = _expect_str(cwd, ctx=f"scenario.steps[{i}].cwd")

        env_raw = tbl.get("env")
        env: dict[str, str] | None = None
        if env_raw is not None:
            env_tbl = _expect_dict(env_raw, ctx=f"scenario.steps[{i}].env")
            env = {k: _expect_str(v, ctx=f"scenario.steps[{i}].env.{k}") for k, v in env_tbl.items()}

        if kind == "mkdir":
            spath = _expect_str(tbl.get("path"), ctx=f"scenario.steps[{i}].path")
            steps.append(StepSpec(kind=kind, path=spath, cwd=cwd, env=env))
            continue

        if kind == "write_file":
            spath = _expect_str(tbl.get("path"), ctx=f"scenario.steps[{i}].path")
            content = _expect_str(tbl.get("content"), ctx=f"scenario.steps[{i}].content")
            steps.append(StepSpec(kind=kind, path=spath, content=content, cwd=cwd, env=env))
            continue

        if kind == "run":
            argv_raw = _expect_list(tbl.get("argv"), ctx=f"scenario.steps[{i}].argv")
            argv = [_expect_str(a, ctx=f"scenario.steps[{i}].argv") for a in argv_raw]
            expect_exit_code = tbl.get("expectExitCode")
            if expect_exit_code is not None:
                expect_exit_code = _expect_int(expect_exit_code, ctx=f"scenario.steps[{i}].expectExitCode")
            steps.append(
                StepSpec(kind=kind, argv=argv, expect_exit_code=expect_exit_code, cwd=cwd, env=env)
            )
            continue

        if kind == "run_cmd":
            argv_raw = _expect_list(tbl.get("argv"), ctx=f"scenario.steps[{i}].argv")
            argv = [_expect_str(a, ctx=f"scenario.steps[{i}].argv") for a in argv_raw]
            expect_exit_code = tbl.get("expectExitCode")
            if expect_exit_code is not None:
                expect_exit_code = _expect_int(expect_exit_code, ctx=f"scenario.steps[{i}].expectExitCode")
            capture_var = tbl.get("captureVar")
            if capture_var is not None:
                capture_var = _expect_str(capture_var, ctx=f"scenario.steps[{i}].captureVar")
            steps.append(
                StepSpec(
                    kind=kind,
                    argv=argv,
                    expect_exit_code=expect_exit_code,
                    cwd=cwd,
                    env=env,
                    capture_var=capture_var,
                )
            )
            continue

        if kind == "capture_file":
            spath = _expect_str(tbl.get("path"), ctx=f"scenario.steps[{i}].path")
            steps.append(StepSpec(kind=kind, path=spath, cwd=cwd, env=env))
            continue

        raise ScenarioSpecError(f"scenario.steps[{i}].kind: unsupported kind {kind!r}")

    checks: list[CheckSpec] = []
    for i, c in enumerate(checks_raw):
        tbl = _expect_dict(c, ctx=f"scenario.checks[{i}]")
        kind = _expect_str(tbl.get("kind"), ctx=f"scenario.checks[{i}].kind")
        step = tbl.get("step")
        if step is not None:
            step = _expect_int(step, ctx=f"scenario.checks[{i}].step")
        stream = tbl.get("stream")
        if stream is not None:
            stream = _expect_str(stream, ctx=f"scenario.checks[{i}].stream")

        if kind in {"file_exists", "file_contains", "json_schema"}:
            cpath = _expect_str(tbl.get("path"), ctx=f"scenario.checks[{i}].path")
            substr = tbl.get("substr")
            if substr is not None:
                substr = _expect_str(substr, ctx=f"scenario.checks[{i}].substr")
            schema = tbl.get("schema")
            if schema is not None:
                schema = _expect_dict(schema, ctx=f"scenario.checks[{i}].schema")
            checks.append(CheckSpec(kind=kind, path=cpath, substr=substr, schema=schema, step=step, stream=stream))
            continue

        if kind == "output_contains":
            substr = _expect_str(tbl.get("substr"), ctx=f"scenario.checks[{i}].substr")
            if step is None:
                raise ScenarioSpecError(f"scenario.checks[{i}].step: required for output_contains")
            if stream is None:
                raise ScenarioSpecError(f"scenario.checks[{i}].stream: required for output_contains")
            checks.append(CheckSpec(kind=kind, substr=substr, step=step, stream=stream))
            continue

        raise ScenarioSpecError(f"scenario.checks[{i}].kind: unsupported kind {kind!r}")

    return ScenarioSpec(id=sid, name=name, steps=steps, checks=checks)
