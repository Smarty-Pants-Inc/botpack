from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .catalog import generate_and_write_catalog
from .errors import BotyardConfigError
from .fetch import FetchError
from .lock import LockfileError
from .sync import sync


def _find_botpack_project_root(start: Path) -> Path | None:
    """Find the nearest parent containing a botpack workspace manifest.

    Prefer `botpack.toml`, but also accept legacy `botyard.toml`.
    """

    cur = start.resolve()
    for p in (cur, *cur.parents):
        if (p / "botpack.toml").exists() or (p / "botyard.toml").exists():
            return p
    return None


def _default_manifest_for_root(root: Path) -> Path | None:
    new = root / "botpack.toml"
    if new.exists():
        return new
    old = root / "botyard.toml"
    if old.exists():
        return old
    return None


def _apply_root_selection(args: argparse.Namespace) -> None:
    """Select a BOTPACK_ROOT for this CLI invocation.

    Precedence:
      1) Explicit CLI flags: --root / --global / --profile
      2) An explicit --manifest path (use its parent)
      3) Existing environment variables (BOTPACK_ROOT/BOTYARD_ROOT/SMARTY_ROOT)
      4) Auto-detect by walking up from cwd to find botpack.toml/botyard.toml
      5) Fallback to cwd

    If we auto-detect a manifest, also thread it into args.manifest (when present)
    so downstream code resolves relative paths from the manifest parent rather
    than the current working directory.
    """

    explicit_root: Path | None = getattr(args, "root", None)
    global_mode: bool = bool(getattr(args, "global_mode", False))
    profile: str | None = getattr(args, "profile", None)

    if explicit_root is not None and (global_mode or profile):
        raise ValueError("--root cannot be combined with --global/--profile")

    root: Path
    if explicit_root is not None:
        root = Path(explicit_root).expanduser().resolve()
    elif global_mode or profile:
        # Global environments live under ~/.botpack/profiles/<profile>/.
        prof = profile or "default"
        root = (Path.home() / ".botpack" / "profiles" / prof).resolve()
    else:
        manifest: Path | None = getattr(args, "manifest", None)
        if manifest is not None:
            root = Path(manifest).expanduser().resolve().parent
        else:
            env_root = (
                os.environ.get("BOTPACK_ROOT")
                or os.environ.get("BOTYARD_ROOT")
                or os.environ.get("SMARTY_ROOT")
            )
            if env_root:
                root = Path(env_root).expanduser().resolve()
            else:
                detected = _find_botpack_project_root(Path.cwd())
                root = (detected or Path.cwd()).resolve()

    # Create explicitly selected roots so `--global/--profile/--root` work from a clean machine.
    if explicit_root is not None or global_mode or profile:
        root.mkdir(parents=True, exist_ok=True)

    os.environ["BOTPACK_ROOT"] = str(root)

    # If a manifest exists at the selected root, thread it through to avoid
    # resolving workspace/dep paths relative to cwd.
    if hasattr(args, "manifest") and getattr(args, "manifest", None) is None:
        default_manifest = _default_manifest_for_root(root)
        if default_manifest is not None:
            setattr(args, "manifest", default_manifest)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="botpack",
        description="Cargo for agent assets - dependency + materialization toolchain",
    )
    root_group = p.add_mutually_exclusive_group(required=False)
    root_group.add_argument("--root", type=Path, default=None, help="Explicit project root")
    root_group.add_argument("--global", dest="global_mode", action="store_true", help="Use global environment")
    p.add_argument("--profile", type=str, default=None, help="Global profile name")

    # cmd is NOT required - no args prints brief status
    sub = p.add_subparsers(dest="cmd", required=False)

    # -------------------------------------------------------------------------
    # DX-contract commands (v0.3)
    # -------------------------------------------------------------------------

    # botpack status - universal health surface
    st = sub.add_parser("status", help="Universal status surface (root, lock, targets, conflicts, trust)")
    st.add_argument("--manifest", type=Path, default=None)
    st.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    # botpack launch - primary entry point
    launch = sub.add_parser(
        "launch",
        help="Launch a TUI (attempts install+sync, falls back to last-known-good)",
    )
    launch.add_argument("target", nargs="?", default=None, help="Target to launch (claude, amp, droid, letta-code)")
    launch.add_argument("--agent", type=str, default=None, help="Agent name/preset to use")
    launch.add_argument("--manifest", type=Path, default=None)
    launch.add_argument("--dry-run", action="store_true", help="Prepare but don't actually launch")
    launch.add_argument("--env-file", type=Path, default=None, help="Source this file before launch")
    launch.add_argument("--env-cmd", type=str, default=None, help="Bash snippet to run before launch")
    launch.add_argument("--model", type=str, default=None, help="Model override for TUI")
    launch.add_argument("--droid-args", type=str, default=None, help="Extra args for droid")
    launch.add_argument("--no-sync", action="store_true", help="Skip install+sync, launch immediately")
    launch.add_argument("--repo-root", type=Path, default=None, help="Repository root for TUI")

    # botpack explain - deep dive for specific issues
    explain = sub.add_parser("explain", help="Deep dive explanation for a specific issue ID")
    explain.add_argument("issue_id", help="Issue ID from status output (e.g., conflict:abc123, trust:def456)")
    explain.add_argument("--manifest", type=Path, default=None)

    # Letta integration
    letta = sub.add_parser("letta", help="Letta integration (drift-aware, PR-first)")
    letta_sub = letta.add_subparsers(dest="letta_cmd", required=True)

    letta_status = letta_sub.add_parser("status", help="Show Letta drift status")
    letta_status.add_argument("--json", dest="json_output", action="store_true")

    letta_diff = letta_sub.add_parser("diff", help="Show detailed Letta diff")
    letta_diff.add_argument("--json", dest="json_output", action="store_true")

    letta_pull = letta_sub.add_parser("pull", help="Capture Letta drift to a Git branch/commit")
    letta_pull.add_argument("--dry-run", action="store_true")
    letta_pull.add_argument("--branch", type=str, default=None)
    letta_pull.add_argument("--json", dest="json_output", action="store_true")

    letta_push = letta_sub.add_parser("push", help="Deploy Git-managed Letta state to Letta")
    letta_push.add_argument("--dry-run", action="store_true")
    letta_push.add_argument("--force", action="store_true")
    letta_push.add_argument("--json", dest="json_output", action="store_true")

    letta_bootstrap = letta_sub.add_parser("bootstrap", help="Create/bind a Letta agent instance")
    letta_bootstrap.add_argument("--name", type=str, default=None)
    letta_bootstrap.add_argument("--template", type=str, default=None)
    letta_bootstrap.add_argument("--json", dest="json_output", action="store_true")

    # -------------------------------------------------------------------------
    # Existing commands
    # -------------------------------------------------------------------------

    mig = sub.add_parser("migrate", help="Migrate legacy workspace layouts")
    mig_sub = mig.add_subparsers(dest="migrate_cmd", required=True)
    mig_smarty = mig_sub.add_parser("from-smarty", help="Copy .smarty into .botpack/workspace")
    mig_smarty.add_argument("--force", action="store_true")

    ag = sub.add_parser("agentic", help="Run agentic rubric-based scenarios")
    ag_sub = ag.add_subparsers(dest="agentic_cmd", required=True)
    ag_run = ag_sub.add_parser("run", help="Run scenario JSON files and write a report")
    ag_run.add_argument("--scenario", type=Path, action="append", default=[])
    ag_run.add_argument("--scenarios-dir", type=Path, default=None)
    ag_run.add_argument("--work-root", type=Path, default=None)
    ag_run.add_argument("--report", type=Path, default=None)
    ag_run.add_argument("--mode", choices=["direct", "subprocess"], default="subprocess")

    tui = sub.add_parser("tui", help="TUI/tmux helpers and lightweight test matrix artifacts")
    tui_sub = tui.add_subparsers(dest="tui_cmd", required=True)

    tm = tui_sub.add_parser("tmux", help="Run a TUI in an isolated tmux server and capture transcripts")
    tm.add_argument("tui", choices=["opencode", "droid", "codex", "coder", "claude", "amp"])
    tm.add_argument("action", choices=["start", "attach", "send", "sendkey", "peek", "kill", "status"])
    tm.add_argument("args", nargs=argparse.REMAINDER)
    tm.add_argument("--repo-root", type=Path, default=None)
    tm.add_argument("--sock", type=str, default=None)
    tm.add_argument("--sess", type=str, default=None)
    tm.add_argument("--art", type=Path, default=None)
    tm.add_argument("--no-reuse", action="store_true")
    tm.add_argument("--env-file", type=Path, default=None)
    tm.add_argument("--env-cmd", type=str, default=None)
    tm.add_argument("--model", type=str, default=None)
    tm.add_argument("--agent", type=str, default=None)
    tm.add_argument("--droid-args", type=str, default=None)

    mx = tui_sub.add_parser("matrix", help="Create/update a simple TUI test matrix results.json")
    mx_sub = mx.add_subparsers(dest="matrix_cmd", required=True)

    mx_new = mx_sub.add_parser("new", help="Create a new matrix run directory")
    mx_new.add_argument("--out-root", type=Path, default=Path("dist/tests"))

    mx_start = mx_sub.add_parser("start", help="Start a TUI tmux session scoped to a matrix run")
    mx_start.add_argument("--run-dir", type=Path, required=True)
    mx_start.add_argument("tui", choices=["opencode", "droid", "codex", "coder", "claude", "amp"])
    mx_start.add_argument("--repo-root", type=Path, default=None)
    mx_start.add_argument("--env-file", type=Path, default=None)
    mx_start.add_argument("--env-cmd", type=str, default=None)
    mx_start.add_argument("--model", type=str, default=None)
    mx_start.add_argument("--agent", type=str, default=None)
    mx_start.add_argument("--droid-args", type=str, default=None)

    mx_send = mx_sub.add_parser("send", help="Send text to an existing matrix TUI session")
    mx_send.add_argument("--run-dir", type=Path, required=True)
    mx_send.add_argument("tui", choices=["opencode", "droid", "codex", "coder", "claude", "amp"])
    mx_send.add_argument("text", nargs=argparse.REMAINDER)

    mx_peek = mx_sub.add_parser("peek", help="Capture the current screen of a matrix TUI session")
    mx_peek.add_argument("--run-dir", type=Path, required=True)
    mx_peek.add_argument("tui", choices=["opencode", "droid", "codex", "coder", "claude", "amp"])

    mx_kill = mx_sub.add_parser("kill", help="Kill a matrix TUI session")
    mx_kill.add_argument("--run-dir", type=Path, required=True)
    mx_kill.add_argument("tui", choices=["opencode", "droid", "codex", "coder", "claude", "amp"])

    mx_rec = mx_sub.add_parser("record", help="Append a feature result entry to results.json")
    mx_rec.add_argument("--run-dir", type=Path, required=True)
    mx_rec.add_argument("--tui", type=str, required=True)
    mx_rec.add_argument("--feature", type=str, required=True)
    mx_rec.add_argument("--status", choices=["PASS", "FAIL", "PARTIAL", "N/A", "BLOCKED"], required=True)
    mx_rec.add_argument("--evidence", type=str, default="")
    mx_rec.add_argument("--artifacts", type=str, default="")
    mx_rec.add_argument("--notes", type=str, default="")

    mx_run = mx_sub.add_parser("run", help="Run a full fresh-install E2E matrix and record results")
    mx_run.add_argument("--out-root", type=Path, default=Path("dist/tests"))
    mx_run.add_argument(
        "--tui",
        action="append",
        default=[],
        choices=["opencode", "droid", "codex", "coder", "claude", "amp"],
        help="Limit run to specific TUIs (repeatable)",
    )
    mx_run.add_argument("--dry-run", action="store_true", help="Do not execute subprocesses (unit-test mode)")

    cfg = tui_sub.add_parser("config", help="Home-config helpers (print snippets or apply managed edits)")
    cfg_sub = cfg.add_subparsers(dest="config_cmd", required=False)

    # Back-compat: `botpack tui config <tui>` prints.
    cfg.add_argument("legacy_tui", nargs="?", choices=["codex", "coder", "amp"], default=None)

    cfg_print = cfg_sub.add_parser("print", help="Print a home-config snippet")
    cfg_print.add_argument("tui", choices=["codex", "coder", "amp"])
    cfg_print.add_argument("--out", type=Path, default=None)

    cfg_apply = cfg_sub.add_parser("apply", help="Apply snippet to a home-config file safely")
    cfg_apply.add_argument("tui", choices=["codex", "coder", "amp"])
    cfg_apply.add_argument("--path", type=Path, default=None)
    cfg_apply.add_argument("--dry-run", action="store_true")
    cfg_apply.add_argument("--backup", action="store_true")
    cfg_apply.add_argument("--force", action="store_true")

    add = sub.add_parser("add", help="Add a dependency to botpack.toml")
    add.add_argument("name", help="Either a package name (with --git/--path) or name@versionSpec")
    add.add_argument("--manifest", type=Path, default=None)
    src = add.add_mutually_exclusive_group(required=False)
    src.add_argument("--path", dest="dep_path")
    src.add_argument("--git", dest="git_url")
    add.add_argument("--rev", default=None)

    get = sub.add_parser("get", help="One-line install: add + install + sync")
    get.add_argument("name", help="Either a package name (with --git/--path) or name@versionSpec")
    get.add_argument("--manifest", type=Path, default=None)
    get.add_argument("--lockfile", type=Path, default=None)
    get.add_argument("--offline", action="store_true")
    get.add_argument("--target", default="claude")
    gsrc = get.add_mutually_exclusive_group(required=False)
    gsrc.add_argument("--path", dest="dep_path")
    gsrc.add_argument("--git", dest="git_url")
    get.add_argument("--rev", default=None)

    rem = sub.add_parser("remove", help="Remove a dependency from botpack.toml")
    rem.add_argument("name")
    rem.add_argument("--manifest", type=Path, default=None)

    cat = sub.add_parser("catalog", help="Generate .botpack/catalog.json")
    cat.add_argument("--manifest", type=Path, default=None)

    s = sub.add_parser("sync", help="Materialize workspace assets into a target runtime")
    s.add_argument("--target", default="claude")
    s.add_argument("--manifest", type=Path, default=None)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--clean", action="store_true")
    s.add_argument("--force", action="store_true")

    d = sub.add_parser("doctor", help="Basic environment checks")
    d.add_argument("--manifest", type=Path, default=None)

    ins = sub.add_parser("install", help="Resolve + fetch dependencies and write botpack.lock")
    ins.add_argument("--manifest", type=Path, default=None)
    ins.add_argument("--lockfile", type=Path, default=None)
    ins.add_argument("--offline", action="store_true")

    upd = sub.add_parser("update", help="Alias for install (refresh botpack.lock)")
    upd.add_argument("--manifest", type=Path, default=None)
    upd.add_argument("--lockfile", type=Path, default=None)
    upd.add_argument("--offline", action="store_true")

    pre = sub.add_parser("prefetch", help="Fetch deps into cache/store and write/update lockfile")
    pre.add_argument("--manifest", type=Path, default=None)
    pre.add_argument("--lockfile", type=Path, default=None)
    pre.add_argument("--offline", action="store_true")

    audit = sub.add_parser("audit", help="List lockfile packages requiring trust that are not trusted")
    audit.add_argument("--lockfile", type=Path, default=None)

    trust = sub.add_parser("trust", help="Manage trust decisions")
    trust_sub = trust.add_subparsers(dest="trust_cmd", required=True)
    allow = trust_sub.add_parser("allow", help="Allow capabilities for a package")
    allow.add_argument("pkg")
    allow.add_argument("--exec", dest="allow_exec", action="store_true")
    allow.add_argument("--mcp", dest="allow_mcp", action="store_true")
    allow.add_argument("--integrity", default=None)
    revoke = trust_sub.add_parser("revoke", help="Revoke trust for a package")
    revoke.add_argument("pkg")

    ls = sub.add_parser("list", help="List workspace assets and installed packages")
    ls.add_argument("--manifest", type=Path, default=None)
    ls.add_argument("--lockfile", type=Path, default=None)

    info = sub.add_parser("info", help="Show workspace + lockfile summary")
    info.add_argument("--manifest", type=Path, default=None)
    info.add_argument("--lockfile", type=Path, default=None)

    tree = sub.add_parser("tree", help="Show dependency + install tree")
    tree.add_argument("--manifest", type=Path, default=None)
    tree.add_argument("--lockfile", type=Path, default=None)

    why = sub.add_parser("why", help="Explain why a package is present")
    why.add_argument("pkg")
    why.add_argument("--manifest", type=Path, default=None)
    why.add_argument("--lockfile", type=Path, default=None)

    v = sub.add_parser("verify", help="Verify lockfile entries against the content-addressed store")
    v.add_argument("--lockfile", type=Path, required=True)

    pr = sub.add_parser("prune", help="Delete unreferenced store entries")
    pr.add_argument("--lockfile", type=Path, required=True)
    pr.add_argument("--dry-run", action="store_true")

    mcp = sub.add_parser("mcp", help="MCP utilities")
    mcp_sub = mcp.add_subparsers(dest="mcp_cmd", required=True)
    mcp_smoke = mcp_sub.add_parser("smoke", help="Run a read-only smoke test against a stdio MCP server")
    mcp_smoke.add_argument("--command", type=str, default=None)
    mcp_smoke.add_argument("--args", action="append", default=[])
    mcp_smoke.add_argument("--server-name", type=str, default=None)
    mcp_smoke.add_argument("--cwd", type=Path, default=None)
    mcp_smoke.add_argument("--out", type=Path, default=None)

    logs = sub.add_parser("logs", help="Logs helpers")
    logs_sub = logs.add_subparsers(dest="logs_cmd", required=True)
    logs_grep = logs_sub.add_parser("grep", help="Grep across known TUI logs")
    logs_grep.add_argument("--pattern", required=True)
    logs_grep.add_argument("--tui", default="all", choices=["all", "claude", "opencode", "codex", "coder", "droid", "amp"])
    logs_grep.add_argument("--max-hits", type=int, default=50)
    logs_grep.add_argument("--since", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _apply_root_selection(args)

    try:
        return _run(args)
    except BotyardConfigError as e:
        print(f"error: {e}")
        return 2
    except LockfileError as e:
        print(f"error: {e}")
        return 2
    except PermissionError as e:
        print(f"error: {e}")
        return 6
    except FetchError as e:
        print(f"error: {e}")
        return 4
    except Exception as e:  # pragma: no cover
        print(f"error: {e}")
        return 1


def _run(args: argparse.Namespace) -> int:
    # Handle no-args case: print brief status summary
    if args.cmd is None:
        from .cli_status import collect_status, format_brief_status

        info = collect_status()
        print(format_brief_status(info), end="")
        return 0

    # -------------------------------------------------------------------------
    # DX-contract commands (v0.3)
    # -------------------------------------------------------------------------

    if args.cmd == "status":
        from .cli_status import collect_status, format_brief_status, format_full_status

        info = collect_status(manifest_path=args.manifest)
        if getattr(args, "json_output", False):
            import json as json_mod
            # Convert to JSON-serializable format
            out = {
                "root": str(info.root),
                "manifest": str(info.manifest_path) if info.manifest_path else None,
                "manifest_exists": info.manifest_exists,
                "lock": str(info.lock_path) if info.lock_path else None,
                "lock_exists": info.lock_exists,
                "lock_version": info.lock_version,
                "packages_count": info.packages_count,
                "targets": {
                    name: {
                        "exists": ts.exists,
                        "paths_count": ts.paths_count,
                        "conflicts": ts.conflicts,
                    }
                    for name, ts in info.targets.items()
                },
                "conflicts": info.all_conflicts,
                "trust_gates": [
                    {"pkg_key": g.pkg_key, "needs_exec": g.needs_exec, "needs_mcp": g.needs_mcp, "issue_id": g.issue_id}
                    for g in info.trust_gates
                ],
                "letta_drift": info.letta_drift,
                "warnings": info.warnings,
                "errors": info.errors,
                "has_issues": info.has_issues,
            }
            print(json_mod.dumps(out, indent=2, sort_keys=True))
        else:
            print(format_full_status(info), end="")
        return 0

    if args.cmd == "launch":
        from .cli_status import prepare_launch, format_launch_warnings
        from .tui.tmux import TmuxSession

        # Determine target
        target = args.target
        if target is None:
            # Try to get default from manifest
            try:
                from .config import parse_botyard_toml_file

                cfg = parse_botyard_toml_file(args.manifest)
                target = cfg.entry.target or "claude"
                if args.agent is None and cfg.entry.agent:
                    args.agent = cfg.entry.agent
            except Exception:
                target = "claude"

        # Map target names to TUI names
        target_to_tui = {
            "claude": "claude",
            "amp": "amp",
            "droid": "droid",
            "letta-code": "coder",  # Letta Code uses coder TUI for now
            "opencode": "opencode",
            "codex": "codex",
            "coder": "coder",
        }
        tui_name = target_to_tui.get(target, target)

        # Prepare launch (install + sync)
        if not getattr(args, "no_sync", False):
            result = prepare_launch(target=target, manifest_path=args.manifest)
            if result.warnings:
                print(format_launch_warnings(result), end="")

        if getattr(args, "dry_run", False):
            print(f"Would launch target: {target} (tui: {tui_name})")
            if args.agent:
                print(f"Agent: {args.agent}")
            return 0

        # Actually launch the TUI
        repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd().resolve()
        sess = TmuxSession.ensure(
            tui=tui_name,
            repo_root=repo_root,
            reuse_latest=False,
        )
        sess.start(
            env_file=args.env_file,
            env_cmd=args.env_cmd,
            model=args.model,
            agent=args.agent,
            droid_args=args.droid_args,
        )
        print(f"Launched {target} in tmux session: {sess.sess}")
        print(f"Artifacts: {sess.art_dir}")
        print(f"\nTo attach: tmux -L {sess.sock} attach -t {sess.sess}")
        return 0

    if args.cmd == "explain":
        from .cli_status import explain_issue

        output = explain_issue(str(args.issue_id), manifest_path=args.manifest)
        print(output, end="")
        return 0

    if args.cmd == "letta":
        from dataclasses import asdict

        from .letta.client import create_letta_client
        from .letta.workflows import (
            letta_bootstrap,
            letta_diff,
            letta_pull,
            letta_push,
            letta_status,
        )

        client = create_letta_client()

        if args.letta_cmd == "status":
            res = letta_status(client=client)
            if getattr(args, "json_output", False):
                print(json.dumps(asdict(res), indent=2, sort_keys=True))
            else:
                print(f"Letta URL: {res.letta_url}")
                print(f"Reachable: {res.letta_reachable}")
                print(f"Managed blocks: {res.managed_blocks}")
                print(f"Has drift: {res.has_drift}")
                for a in res.recommended_actions:
                    print(f"- {a}")
            return 0

        if args.letta_cmd == "diff":
            res = letta_diff(client=client)
            if getattr(args, "json_output", False):
                print(json.dumps(asdict(res), indent=2, sort_keys=True))
            else:
                print(res.message)
                if res.diff is not None:
                    for item in res.diff.items:
                        print(f"- {item.address} ({item.direction})")
            return 0

        if args.letta_cmd == "pull":
            res = letta_pull(client=client, branch_name=args.branch, dry_run=bool(args.dry_run))
            if getattr(args, "json_output", False):
                print(json.dumps(asdict(res), indent=2, sort_keys=True))
            else:
                print(res.message)
            return 0 if res.ok else 1

        if args.letta_cmd == "push":
            res = letta_push(client=client, force=bool(args.force), dry_run=bool(args.dry_run))
            if getattr(args, "json_output", False):
                print(json.dumps(asdict(res), indent=2, sort_keys=True))
            else:
                print(res.message)
            return 0 if res.ok else 1

        if args.letta_cmd == "bootstrap":
            res = letta_bootstrap(client=client, agent_name=args.name, template_id=args.template)
            if getattr(args, "json_output", False):
                print(json.dumps(asdict(res), indent=2, sort_keys=True))
            else:
                print(res.message)
            return 0 if res.ok else 1

        raise AssertionError(f"unhandled letta cmd: {args.letta_cmd}")

    # -------------------------------------------------------------------------
    # Existing commands
    # -------------------------------------------------------------------------

    if args.cmd == "agentic":
        if args.agentic_cmd != "run":
            raise AssertionError(f"unhandled agentic cmd: {args.agentic_cmd}")

        from . import paths
        from .agentic import AgenticRunner, load_scenario_json

        scenario_paths: list[Path] = [Path(p) for p in (args.scenario or [])]
        if not scenario_paths:
            if args.scenarios_dir is None:
                raise ValueError("agentic run: must provide --scenario or --scenarios-dir")
            scenario_paths = sorted(Path(args.scenarios_dir).glob("*.json"))

        scenarios = [load_scenario_json(p) for p in scenario_paths]

        work_root = Path(args.work_root) if args.work_root is not None else (paths.botyard_dir() / "agentic-work")
        report_path = Path(args.report) if args.report is not None else (work_root / "report.json")

        runner = AgenticRunner(mode=str(args.mode))
        report = runner.run_and_write_report(scenarios, work_root=work_root, report_path=report_path)

        print(str(report_path))
        return 0 if report.get("ok") is True else 1

    if args.cmd == "tui":
        from .tui.matrix import MatrixRun
        from .tui.tmux import TmuxSession

        repo_root = Path(args.repo_root).resolve() if getattr(args, "repo_root", None) is not None else Path.cwd().resolve()

        if args.tui_cmd == "tmux":
            tui_name = args.tui
            sess = TmuxSession.ensure(
                tui=tui_name,
                repo_root=repo_root,
                sock=args.sock,
                sess=args.sess,
                art_dir=args.art,
                reuse_latest=not bool(args.no_reuse),
            )

            if args.action == "start":
                sess.start(
                    env_file=args.env_file,
                    env_cmd=args.env_cmd,
                    model=args.model,
                    agent=args.agent,
                    droid_args=args.droid_args,
                )
                print(str(sess.art_dir))
                return 0
            if args.action == "attach":
                sess.attach()
                return 0
            if args.action == "send":
                text = " ".join(args.args or []).strip()
                sess.send(text)
                return 0
            if args.action == "sendkey":
                sess.sendkey(*(args.args or []))
                return 0
            if args.action == "peek":
                print(sess.peek(), end="")
                return 0
            if args.action == "kill":
                sess.kill()
                return 0
            if args.action == "status":
                print(sess.status(), end="")
                return 0
            raise AssertionError(f"unhandled tmux action: {args.action}")

        if args.tui_cmd == "config":
            from .tui.config_snippets import snippet_for
            from .tui.home_config import apply_mcp_magic_number_home_config

            # Legacy: `botpack tui config <tui>`
            if args.config_cmd is None and getattr(args, "legacy_tui", None) is not None:
                _fmt, text = snippet_for(str(args.legacy_tui))
                print(text, end="")
                return 0

            if args.config_cmd == "print":
                _fmt, text = snippet_for(str(args.tui))
                if args.out is not None:
                    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.out).write_text(text, encoding="utf-8")
                print(text, end="")
                return 0

            if args.config_cmd == "apply":
                res = apply_mcp_magic_number_home_config(
                    tui=str(args.tui),
                    path=Path(args.path).expanduser().resolve() if args.path is not None else None,
                    dry_run=bool(args.dry_run),
                    backup=bool(args.backup),
                    force=bool(args.force),
                )
                if res.status == "conflict":
                    print(f"conflict: {res.message}")
                    return 2
                if res.status == "error":
                    print(f"error: {res.message}")
                    return 1
                # ok
                print(str(res.path))
                return 0

            raise AssertionError(f"unhandled config cmd: {args.config_cmd}")

        if args.tui_cmd == "matrix":
            run_dir = Path(getattr(args, "run_dir", repo_root)).resolve() if hasattr(args, "run_dir") else None

            def session_json_path(run_dir: Path, tui: str) -> Path:
                return run_dir / tui / "session.json"

            if args.matrix_cmd == "new":
                mr = MatrixRun.create(out_root=Path(args.out_root).resolve())
                print(str(mr.run_dir))
                return 0

            if args.matrix_cmd == "start":
                if run_dir is None:
                    raise ValueError("matrix start: missing --run-dir")
                t = args.tui
                art = run_dir / t / "tmux"
                s = TmuxSession.ensure(tui=t, repo_root=repo_root, art_dir=art, reuse_latest=False)
                s.start(
                    env_file=args.env_file,
                    env_cmd=args.env_cmd,
                    model=args.model,
                    agent=args.agent,
                    droid_args=args.droid_args,
                )
                sp = session_json_path(run_dir, t)
                sp.parent.mkdir(parents=True, exist_ok=True)
                sp.write_text(
                    json.dumps({"tui": t, "sock": s.sock, "sess": s.sess, "art": str(s.art_dir)}, sort_keys=True, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
                print(str(s.art_dir))
                return 0

            if args.matrix_cmd in {"send", "peek", "kill"}:
                if run_dir is None:
                    raise ValueError(f"matrix {args.matrix_cmd}: missing --run-dir")
                t = args.tui
                sp = session_json_path(run_dir, t)
                if not sp.exists():
                    raise FileNotFoundError(str(sp))
                data = json.loads(sp.read_text(encoding="utf-8"))
                s = TmuxSession.ensure(
                    tui=t,
                    repo_root=repo_root,
                    sock=str(data.get("sock")),
                    sess=str(data.get("sess")),
                    art_dir=Path(str(data.get("art"))),
                    reuse_latest=False,
                )

                if args.matrix_cmd == "send":
                    text = " ".join(args.text or []).strip()
                    s.send(text)
                    return 0
                if args.matrix_cmd == "peek":
                    print(s.peek(), end="")
                    return 0
                if args.matrix_cmd == "kill":
                    s.kill()
                    return 0

            if args.matrix_cmd == "record":
                mr = MatrixRun.load(run_dir)
                mr.record(
                    tui=str(args.tui),
                    feature=str(args.feature),
                    status=str(args.status),
                    evidence=str(args.evidence or ""),
                    artifacts=str(args.artifacts or ""),
                    notes=str(args.notes or ""),
                )
                return 0

            if args.matrix_cmd == "run":
                from .tui.matrix_run import RunConfig, run_matrix

                tuis = tuple(args.tui) if args.tui else ("claude", "opencode", "codex", "coder", "droid", "amp")
                cfg = RunConfig(out_root=Path(args.out_root).resolve(), tuis=tuis, dry_run=bool(args.dry_run))
                out_dir = run_matrix(cfg)
                print(str(out_dir))
                return 0

            raise AssertionError(f"unhandled matrix cmd: {args.matrix_cmd}")

        raise AssertionError(f"unhandled tui cmd: {args.tui_cmd}")

    if args.cmd == "migrate":
        if args.migrate_cmd == "from-smarty":
            from .migrate import migrate_from_smarty
            from .paths import work_root

            root = work_root().resolve()
            try:
                migrate_from_smarty(root=root, force=bool(args.force))
            except FileNotFoundError as e:
                print(f"error: legacy workspace not found: {e}")
                return 1
            return 0

        raise AssertionError(f"unhandled migrate cmd: {args.migrate_cmd}")

    if args.cmd == "add":
        from .config import botyard_manifest_path
        from .manifest import parse_add_spec
        from .manifest_edit import add_git_dependency, add_path_dependency, add_semver_dependency

        manifest = args.manifest or botyard_manifest_path()
        if args.dep_path:
            add_path_dependency(manifest, name=str(args.name), dep_path=str(args.dep_path))
        elif args.git_url:
            add_git_dependency(manifest, name=str(args.name), url=str(args.git_url), rev=args.rev)
        else:
            name, spec = parse_add_spec(str(args.name))
            add_semver_dependency(manifest, name=name, spec=spec)
        return 0

    if args.cmd == "get":
        from .config import botyard_manifest_path
        from .install import install
        from .manifest import parse_add_spec
        from .manifest_edit import add_git_dependency, add_path_dependency, add_semver_dependency

        manifest = args.manifest or botyard_manifest_path()
        if args.dep_path:
            add_path_dependency(manifest, name=str(args.name), dep_path=str(args.dep_path))
        elif args.git_url:
            add_git_dependency(manifest, name=str(args.name), url=str(args.git_url), rev=args.rev)
        else:
            name, spec = parse_add_spec(str(args.name))
            add_semver_dependency(manifest, name=name, spec=spec)

        install(manifest_path=manifest, lock_path=args.lockfile, offline=bool(args.offline))

        res = sync(target=str(args.target), manifest_path=manifest)
        return 2 if res.conflicts else 0

    if args.cmd == "remove":
        from .config import botyard_manifest_path
        from .manifest_edit import remove_dependency

        manifest = args.manifest or botyard_manifest_path()
        remove_dependency(manifest, name=str(args.name))
        return 0

    if args.cmd == "catalog":
        generate_and_write_catalog(manifest_path=args.manifest)
        return 0

    if args.cmd == "sync":
        res = sync(
            target=str(args.target),
            manifest_path=args.manifest,
            dry_run=bool(args.dry_run),
            clean=bool(args.clean),
            force=bool(args.force),
        )
        # For now, treat conflicts as a non-zero exit.
        return 2 if res.conflicts else 0

    if args.cmd == "doctor":
        from .doctor import run_doctor

        res = run_doctor(manifest_path=args.manifest)
        for w in res.warnings:
            print(f"warning: {w}")
        return 0 if res.ok else 1

    if args.cmd == "install":
        from .install import install

        install(manifest_path=args.manifest, lock_path=args.lockfile, offline=bool(args.offline))
        return 0

    if args.cmd == "update":
        from .install import install

        install(manifest_path=args.manifest, lock_path=args.lockfile, offline=bool(args.offline))
        return 0

    if args.cmd == "prefetch":
        from .prefetch import prefetch

        prefetch(manifest_path=args.manifest, lock_path=args.lockfile, offline=bool(args.offline))
        return 0

    if args.cmd == "audit":
        from .install import default_lock_path
        from .lock import load_lock
        from .trust import check_package_trust

        lock_path = args.lockfile or default_lock_path()
        lf = load_lock(lock_path)

        problems: list[str] = []
        for pkg_key in sorted(lf.packages.keys()):
            pkg = lf.packages[pkg_key]
            needs_exec = bool(pkg.capabilities.get("exec"))
            needs_mcp = bool(pkg.capabilities.get("mcp"))
            if not (needs_exec or needs_mcp):
                continue
            decision = check_package_trust(
                pkg_key=pkg_key,
                integrity=pkg.integrity,
                needs_exec=needs_exec,
                needs_mcp=needs_mcp,
            )
            if not decision.ok:
                problems.append(decision.reason or f"{pkg_key}: not trusted")

        for r in problems:
            print(r)

        return 0 if not problems else 6

    if args.cmd == "trust":
        from .config import trust_path
        from .trust_edit import trust_allow, trust_revoke

        p = trust_path()
        if args.trust_cmd == "allow":
            if not (bool(args.allow_exec) or bool(args.allow_mcp) or args.integrity):
                raise ValueError("trust allow: must specify at least one of --exec, --mcp, --integrity")
            trust_allow(
                p,
                pkg_key=str(args.pkg),
                allow_exec=True if args.allow_exec else None,
                allow_mcp=True if args.allow_mcp else None,
                integrity=args.integrity,
            )
            return 0
        if args.trust_cmd == "revoke":
            trust_revoke(p, pkg_key=str(args.pkg))
            return 0
        raise AssertionError(f"unhandled trust cmd: {args.trust_cmd}")

    if args.cmd == "list":
        from .introspect import build_list_output

        print(build_list_output(manifest_path=args.manifest, lock_path=args.lockfile), end="")
        return 0

    if args.cmd == "info":
        from .introspect import build_info_output

        print(build_info_output(manifest_path=args.manifest, lock_path=args.lockfile), end="")
        return 0

    if args.cmd == "tree":
        from .introspect import build_tree_output

        print(build_tree_output(manifest_path=args.manifest, lock_path=args.lockfile), end="")
        return 0

    if args.cmd == "why":
        from .introspect import build_why_output

        print(
            build_why_output(pkg=str(args.pkg), manifest_path=args.manifest, lock_path=args.lockfile),
            end="",
        )
        return 0

    if args.cmd == "verify":
        from .verify import verify_lockfile

        res = verify_lockfile(lock_path=args.lockfile)
        for e in res.errors:
            print(f"error: {e}")
        return 0 if res.ok else 1

    if args.cmd == "prune":
        from .prune import prune_store

        res = prune_store(lock_path=args.lockfile, dry_run=bool(args.dry_run))
        for r in res.removed:
            print(r)
        return 0

    if args.cmd == "mcp":
        from .mcp_smoke import run_smoke

        if args.mcp_cmd != "smoke":
            raise AssertionError(f"unhandled mcp cmd: {args.mcp_cmd}")

        res = run_smoke(
            cmd=args.command,
            args=list(args.args or []) or None,
            server_name=args.server_name,
            cwd=Path(args.cwd).resolve() if args.cwd is not None else None,
        )
        payload = json.dumps(res.to_dict(), sort_keys=True, indent=2) + "\n"
        if args.out is not None:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0 if res.ok else 1

    if args.cmd == "logs":
        from .logs_grep import grep

        if args.logs_cmd != "grep":
            raise AssertionError(f"unhandled logs cmd: {args.logs_cmd}")

        results = grep(pattern=str(args.pattern), tui=str(args.tui), max_hits=int(args.max_hits), since=args.since)
        total = 0
        for tui, hits in results:
            print(f"=== {tui} ({len(hits)} hits) ===")
            for h in hits:
                print(f"{h.path}: {h.line}")
                total += 1
        if total == 0:
            print("No matches.")
        return 0

    raise AssertionError(f"unhandled cmd: {args.cmd}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
