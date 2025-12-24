from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .matrix import MatrixRun, MatrixStatus
from .matrix_fixture import DEFAULT_FIXTURE, write_fixture_project


TuiName = Literal["opencode", "droid", "codex", "coder", "claude", "amp"]


@dataclass(frozen=True)
class RunConfig:
    out_root: Path
    tuis: tuple[TuiName, ...] = ("claude", "opencode", "codex", "coder", "droid", "amp")
    dry_run: bool = False
    reuse_wheel: bool = True
    per_tui_venv: bool = True


def _repo_root() -> Path:
    # <repo>/botpack/tui/matrix_run.py -> parents[2] == <repo>
    return Path(__file__).resolve().parents[2]


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_s: int = 300,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _detect_status(p: subprocess.CompletedProcess[str]) -> MatrixStatus:
    if p.returncode == 0:
        return "PASS"
    # Heuristic: missing auth/creds often presents as a login-required message.
    msg = (p.stdout or "") + "\n" + (p.stderr or "")
    low = msg.lower()
    if any(k in low for k in ["api key", "login", "authenticate", "unauthorized", "forbidden"]):
        return "BLOCKED"
    return "FAIL"


def _target_for_tui(tui: TuiName) -> str:
    if tui == "amp":
        return "amp"
    if tui == "droid":
        return "droid"
    return "claude"


def _venv_python(venv_dir: Path) -> Path:
    # Linux env.
    return venv_dir / "bin" / "python"


def _venv_botpack(venv_dir: Path) -> Path:
    return venv_dir / "bin" / "botpack"


def _pkgs_path(project_root: Path) -> Path:
    # Human-readable nested path per pkgs._pkg_key_relpath.
    return project_root / ".botpack" / "pkgs" / "@fixture" / "shared-pack@0.1.0"


def _target_root(project_root: Path, target: str) -> Path:
    if target == "claude":
        return project_root / ".claude"
    if target == "amp":
        return project_root / ".agents"
    if target == "droid":
        return project_root / ".factory"
    raise ValueError(f"unsupported target: {target}")


def _write_feature_result(
    *,
    tdir: Path,
    tui: str,
    feature: str,
    verdict: MatrixStatus,
    test_method: str,
    expected: str,
    actual_result: str,
    raw_output: str = "",
    notes: str = "",
    artifacts: list[str] | None = None,
) -> Path:
    p = tdir / f"{feature}.json"
    _write_json(
        p,
        {
            "tui": tui,
            "feature": feature,
            "test_method": test_method,
            "expected": expected,
            "actual_result": actual_result,
            "verdict": verdict,
            "raw_output": raw_output,
            "notes": notes,
            "artifacts": artifacts or [],
        },
    )
    return p


def _check_exists(paths: list[Path]) -> tuple[MatrixStatus, str, list[str]]:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        return ("FAIL", f"missing {len(missing)} path(s)", missing)
    return ("PASS", f"found {len(paths)} path(s)", [str(p) for p in paths])


def _build_wheel(*, out_dir: Path, dry_run: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if dry_run:
        # Placeholder path for tests.
        return out_dir / "botpack-DRYRUN-py3-none-any.whl"

    # Build using uv if available.
    p = _run(["uv", "build", "--wheel", "--out-dir", str(out_dir)], cwd=_repo_root(), timeout_s=600)
    if p.returncode != 0:
        raise RuntimeError(f"uv build failed: {p.stderr or p.stdout}")
    wheels = sorted(out_dir.glob("botpack-*.whl"))
    if not wheels:
        raise RuntimeError("uv build produced no wheel")
    return wheels[-1]


def _ensure_fresh_dir(path: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def run_matrix(cfg: RunConfig) -> Path:
    mr = MatrixRun.create(out_root=cfg.out_root.resolve())
    run_dir = mr.run_dir
    (run_dir / "suite.json").write_text(
        json.dumps(
            {
                "version": 1,
                "tuis": list(cfg.tuis),
                "dry_run": bool(cfg.dry_run),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    wheel_dir = run_dir / "_wheel"
    wheel = _build_wheel(out_dir=wheel_dir, dry_run=cfg.dry_run)

    for tui in cfg.tuis:
        _run_tui(mr=mr, run_dir=run_dir, tui=tui, wheel=wheel, dry_run=cfg.dry_run)

    return run_dir


def _record(
    mr: MatrixRun,
    *,
    tui: str,
    feature: str,
    status: MatrixStatus,
    evidence: str = "",
    artifacts: str = "",
    notes: str = "",
) -> None:
    mr.record(tui=tui, feature=feature, status=status, evidence=evidence, artifacts=artifacts, notes=notes)


def _run_tui(*, mr: MatrixRun, run_dir: Path, tui: TuiName, wheel: Path, dry_run: bool) -> None:
    tdir = run_dir / tui
    tdir.mkdir(parents=True, exist_ok=True)
    work = tdir / "work"
    project = work / "project"
    venv = work / "venv"
    store = work / "store"
    home = tdir / "home"
    codex_home = tdir / "codex_home"
    code_home = tdir / "code_home"

    if not dry_run:
        home.mkdir(parents=True, exist_ok=True)
        codex_home.mkdir(parents=True, exist_ok=True)
        code_home.mkdir(parents=True, exist_ok=True)

    _ensure_fresh_dir(work, dry_run=dry_run)
    _ensure_fresh_dir(project, dry_run=dry_run)
    _ensure_fresh_dir(store, dry_run=dry_run)

    # 1) Fresh venv + install
    if dry_run:
        _record(mr, tui=tui, feature="install:fresh", status="PASS", notes="dry-run")
        _record(mr, tui=tui, feature="install:wheel", status="PASS", notes="dry-run")
    else:
        p1 = _run(["uv", "venv", str(venv)], cwd=work, timeout_s=300)
        _write_text(tdir / "uv.venv.stdout", p1.stdout)
        _write_text(tdir / "uv.venv.stderr", p1.stderr)
        st1 = _detect_status(p1)
        _record(mr, tui=tui, feature="install:fresh", status=st1, artifacts=str(tdir))
        if p1.returncode != 0:
            return

        p2 = _run(["uv", "pip", "install", "--python", str(_venv_python(venv)), str(wheel)], cwd=work, timeout_s=600)
        _write_text(tdir / "uv.pip.install.stdout", p2.stdout)
        _write_text(tdir / "uv.pip.install.stderr", p2.stderr)
        st2 = _detect_status(p2)
        _record(mr, tui=tui, feature="install:wheel", status=st2, artifacts=str(tdir))
        if p2.returncode != 0:
            return

    py = str(_venv_python(venv))
    bp = str(_venv_botpack(venv))

    # 2) Fixture project
    if not dry_run:
        write_fixture_project(root=project, python_exe=py, spec=DEFAULT_FIXTURE)
        _record(mr, tui=tui, feature="fixture:write", status="PASS", artifacts=str(project))
    else:
        _record(mr, tui=tui, feature="fixture:write", status="PASS", notes="dry-run")

    env = {
        **dict(os.environ),
        "BOTPACK_ROOT": str(project),
        "BOTPACK_STORE": str(store),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        # Codex / Code use explicit home vars (do not always respect HOME).
        "CODEX_HOME": str(codex_home),
        "CODE_HOME": str(code_home),
        # Ensure the venv python is used when we shell out from config.
        "PATH": str((venv / "bin")) + ":" + os.environ.get("PATH", ""),
    }

    # 3) botpack install + sync
    target = _target_for_tui(tui)
    tgt_root = _target_root(project, target)
    if dry_run:
        _record(mr, tui=tui, feature="botpack:install", status="PASS", notes="dry-run")
        _record(mr, tui=tui, feature=f"botpack:sync:{target}", status="PASS", notes="dry-run")
    else:
        p3 = _run([bp, "install"], cwd=project, env=env, timeout_s=600)
        _write_text(tdir / "botpack.install.stdout", p3.stdout)
        _write_text(tdir / "botpack.install.stderr", p3.stderr)
        st3 = _detect_status(p3)
        _record(mr, tui=tui, feature="botpack:install", status=st3, artifacts=str(tdir))
        if p3.returncode != 0:
            return

        p4 = _run([bp, "sync", "--target", target], cwd=project, env=env, timeout_s=600)
        _write_text(tdir / "botpack.sync.stdout", p4.stdout)
        _write_text(tdir / "botpack.sync.stderr", p4.stderr)
        st4 = _detect_status(p4)
        _record(mr, tui=tui, feature=f"botpack:sync:{target}", status=st4, artifacts=str(tdir))
        if p4.returncode != 0:
            return

    # 3b) Verify materialized assets for the selected target (filesystem integration)
    # Note: this does NOT attempt to drive the interactive TUI; it verifies the on-disk
    # artifacts that the TUI would consume.
    if dry_run:
        _record(mr, tui=tui, feature=f"e2e:assets:{target}", status="PASS", notes="dry-run")
        _ = _write_feature_result(
            tdir=tdir,
            tui=tui,
            feature="skills",
            verdict="PASS",
            test_method="dry-run placeholder",
            expected="skills materialized into target root",
            actual_result="dry-run",
            notes="dry-run",
        )
        _ = _write_feature_result(
            tdir=tdir,
            tui=tui,
            feature="commands",
            verdict="PASS",
            test_method="dry-run placeholder",
            expected="commands materialized into target root",
            actual_result="dry-run",
            notes="dry-run",
        )
        _ = _write_feature_result(
            tdir=tdir,
            tui=tui,
            feature="agents",
            verdict="PASS",
            test_method="dry-run placeholder",
            expected="agents materialized into target root",
            actual_result="dry-run",
            notes="dry-run",
        )
        _ = _write_feature_result(
            tdir=tdir,
            tui=tui,
            feature="target-mcp",
            verdict="PASS",
            test_method="dry-run placeholder",
            expected="mcp.json materialized into target root",
            actual_result="dry-run",
            notes="dry-run",
        )
    else:
        # Expected fixture outputs.
        ws_prefix = "workspace"
        pkg_prefix = "fixture-shared-pack"

        exp_skill_paths = [
            tgt_root / "skills" / f"{ws_prefix}.fixture-skill" / "SKILL.md",
            tgt_root / "skills" / f"{pkg_prefix}.pkg-skill" / "SKILL.md",
        ]
        st, msg, art = _check_exists(exp_skill_paths)
        _record(mr, tui=tui, feature=f"e2e:skills:{target}", status=st, evidence=msg)
        _ = _write_feature_result(
            tdir=tdir,
            tui=tui,
            feature="skills",
            verdict=st,
            test_method=f"Verify expected SKILL.md files exist under {tgt_root}",
            expected="workspace + package skills exist with correct target prefixing",
            actual_result=msg,
            raw_output="\n".join(art),
            artifacts=art,
        )

        exp_cmd_paths = [
            tgt_root / "commands" / f"{ws_prefix}.hello.md",
            tgt_root / "commands" / f"{pkg_prefix}.pkg-hello.md",
        ]
        st, msg, art = _check_exists(exp_cmd_paths)
        _record(mr, tui=tui, feature=f"e2e:commands:{target}", status=st, evidence=msg)
        _ = _write_feature_result(
            tdir=tdir,
            tui=tui,
            feature="commands",
            verdict=st,
            test_method=f"Verify expected command markdown files exist under {tgt_root}",
            expected="workspace + package commands exist with correct target prefixing",
            actual_result=msg,
            raw_output="\n".join(art),
            artifacts=art,
        )

        exp_agent_paths = [
            tgt_root / "agents" / f"{ws_prefix}.echo.md",
            tgt_root / "agents" / f"{pkg_prefix}.pkg-agent.md",
        ]
        st, msg, art = _check_exists(exp_agent_paths)
        _record(mr, tui=tui, feature=f"e2e:agents:{target}", status=st, evidence=msg)
        _ = _write_feature_result(
            tdir=tdir,
            tui=tui,
            feature="agents",
            verdict=st,
            test_method=f"Verify expected agent markdown files exist under {tgt_root}",
            expected="workspace + package agents exist with correct target prefixing",
            actual_result=msg,
            raw_output="\n".join(art),
            artifacts=art,
        )

        mcp_json = tgt_root / "mcp.json"
        if mcp_json.exists():
            try:
                obj = json.loads(mcp_json.read_text(encoding="utf-8"))
                names = [s.get("name") for s in (obj.get("servers") or []) if isinstance(s, dict)]
                ok = "workspace/magic-number" in names and "@fixture/shared-pack/pkg-magic-number" in names
                st = "PASS" if ok else "FAIL"
                msg = "expected server names present" if ok else "expected server names missing"
                _record(mr, tui=tui, feature=f"e2e:mcp-json:{target}", status=st, evidence=msg)
                _ = _write_feature_result(
                    tdir=tdir,
                    tui=tui,
                    feature="target-mcp",
                    verdict=st,
                    test_method=f"Parse {mcp_json} and verify expected server names",
                    expected="workspace + package MCP servers present",
                    actual_result=msg,
                    raw_output="\n".join([str(n) for n in names]),
                    artifacts=[str(mcp_json)],
                )
            except Exception as e:
                _record(mr, tui=tui, feature=f"e2e:mcp-json:{target}", status="FAIL", evidence=str(e))
                _ = _write_feature_result(
                    tdir=tdir,
                    tui=tui,
                    feature="target-mcp",
                    verdict="FAIL",
                    test_method=f"Parse {mcp_json}",
                    expected="valid JSON",
                    actual_result=str(e),
                    artifacts=[str(mcp_json)],
                )
        else:
            _record(mr, tui=tui, feature=f"e2e:mcp-json:{target}", status="FAIL", evidence="missing mcp.json")
            _ = _write_feature_result(
                tdir=tdir,
                tui=tui,
                feature="target-mcp",
                verdict="FAIL",
                test_method="Verify mcp.json exists under target root",
                expected="mcp.json present",
                actual_result="missing",
                artifacts=[str(mcp_json)],
            )

    # 4) pkgs materialization
    if dry_run:
        _record(mr, tui=tui, feature="pkgs:materialize", status="PASS", notes="dry-run")
    else:
        p_pkgs = _pkgs_path(project)
        if p_pkgs.exists():
            _record(mr, tui=tui, feature="pkgs:materialize", status="PASS", evidence=str(p_pkgs))
        else:
            _record(mr, tui=tui, feature="pkgs:materialize", status="FAIL", evidence=str(p_pkgs))

    # 5) MCP smoke (server protocol correctness)
    if dry_run:
        _record(mr, tui=tui, feature="mcp:smoke", status="PASS", notes="dry-run")
    else:
        out = tdir / "mcp.smoke.json"
        p5 = _run([bp, "mcp", "smoke", "--out", str(out)], cwd=project, env=env, timeout_s=60)
        _write_text(tdir / "botpack.mcp.smoke.stdout", p5.stdout)
        _write_text(tdir / "botpack.mcp.smoke.stderr", p5.stderr)
        st5 = _detect_status(p5)
        _record(mr, tui=tui, feature="mcp:smoke", status=st5, artifacts=str(out))

    # 6) Home-config apply + TUI-specific checks
    if tui in {"codex", "coder", "amp"}:
        if dry_run:
            _record(mr, tui=tui, feature="tui:config-apply", status="PASS", notes="dry-run")
            _ = _write_feature_result(
                tdir=tdir,
                tui=tui,
                feature="home-config",
                verdict="PASS",
                test_method="dry-run placeholder",
                expected="home config updated",
                actual_result="dry-run",
                notes="dry-run",
            )
        else:
            if tui == "codex":
                cfg_path = codex_home / "config.toml"
            elif tui == "coder":
                cfg_path = code_home / "config.toml"
            else:
                cfg_path = home / ".config" / "amp" / "settings.json"

            p6 = _run([bp, "tui", "config", "apply", tui, "--path", str(cfg_path)], cwd=project, env=env, timeout_s=120)
            _write_text(tdir / f"botpack.tui.config.apply.{tui}.stdout", p6.stdout)
            _write_text(tdir / f"botpack.tui.config.apply.{tui}.stderr", p6.stderr)
            st6 = _detect_status(p6)
            _record(mr, tui=tui, feature="tui:config-apply", status=st6, artifacts=str(cfg_path))

            _ = _write_feature_result(
                tdir=tdir,
                tui=tui,
                feature="home-config",
                verdict=st6,
                test_method="botpack tui config apply + verify resulting config file",
                expected="config file updated with mcp-magic-number server",
                actual_result=f"exit={p6.returncode}",
                raw_output=(p6.stdout or "") + "\n" + (p6.stderr or ""),
                artifacts=[str(cfg_path)],
            )

            # Verify the config file contains the Botpack-managed server.
            if cfg_path.exists():
                content = cfg_path.read_text(encoding="utf-8")
                if "mcp-magic-number" in content:
                    _record(mr, tui=tui, feature="tui:mcp-config-written", status="PASS", evidence=str(cfg_path))
                else:
                    _record(mr, tui=tui, feature="tui:mcp-config-written", status="FAIL", evidence=str(cfg_path))
            else:
                _record(mr, tui=tui, feature="tui:mcp-config-written", status="FAIL", evidence=str(cfg_path))

            # Codex/Code can list configured servers via CLI.
            if tui == "codex":
                p7 = _run(["codex", "mcp", "list"], cwd=project, env=env, timeout_s=60)
                _write_text(tdir / "codex.mcp.list.stdout", p7.stdout)
                _write_text(tdir / "codex.mcp.list.stderr", p7.stderr)
                st7 = _detect_status(p7)
                ok = st7 == "PASS" and "mcp-magic-number" in (p7.stdout or "")
                _record(
                    mr,
                    tui=tui,
                    feature="tui:mcp-list",
                    status="PASS" if ok else st7,
                    evidence="contains mcp-magic-number" if ok else "missing mcp-magic-number",
                    artifacts=str(tdir / "codex.mcp.list.stdout"),
                )
            elif tui == "coder":
                p7 = _run(["coder", "mcp", "list"], cwd=project, env=env, timeout_s=60)
                _write_text(tdir / "coder.mcp.list.stdout", p7.stdout)
                _write_text(tdir / "coder.mcp.list.stderr", p7.stderr)
                st7 = _detect_status(p7)
                ok = st7 == "PASS" and "mcp-magic-number" in (p7.stdout or "")
                _record(
                    mr,
                    tui=tui,
                    feature="tui:mcp-list",
                    status="PASS" if ok else st7,
                    evidence="contains mcp-magic-number" if ok else "missing mcp-magic-number",
                    artifacts=str(tdir / "coder.mcp.list.stdout"),
                )
            else:
                _record(mr, tui=tui, feature="tui:mcp-list", status="N/A", notes="Amp CLI does not expose stable server listing in this environment")
    else:
        _record(mr, tui=tui, feature="tui:config-apply", status="N/A")
        _record(mr, tui=tui, feature="tui:mcp-config-written", status="N/A")
        _record(mr, tui=tui, feature="tui:mcp-list", status="N/A")
