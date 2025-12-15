from __future__ import annotations

"""Introspection helpers for `botpack list` and related commands."""

from pathlib import Path

from .assets import scan_assets
from .config import parse_botyard_toml_file
from .install import default_lock_path as _default_install_lock_path
from .lock import load_lock


def build_list_output(*, manifest_path: Path | None = None, lock_path: Path | None = None) -> str:
    cfg = parse_botyard_toml_file(manifest_path)
    root = Path.cwd() if manifest_path is None else manifest_path.parent

    ws = Path(cfg.workspace.dir)
    if not ws.is_absolute():
        ws = (root / ws).resolve()

    idx = scan_assets(ws)

    # Lockfile is optional.
    lockfile_path = lock_path or _default_install_lock_path()
    packages: list[str] = []
    if lockfile_path.exists():
        lf = load_lock(lockfile_path)
        packages = sorted(lf.packages.keys())

    lines: list[str] = []
    lines.append("Workspace")
    lines.append(f"  Skills ({len(idx.skills)})")
    for s in idx.skills:
        lines.append(f"    - {s.id}")
    lines.append(f"  Commands ({len(idx.commands)})")
    for c in idx.commands:
        lines.append(f"    - {c.id}")
    lines.append(f"  Agents ({len(idx.agents)})")
    for a in idx.agents:
        lines.append(f"    - {a.id}")

    lines.append("")
    lines.append(f"Installed packages ({len(packages)})")
    for k in packages:
        lines.append(f"  - {k}")

    return "\n".join(lines) + "\n"


def build_info_output(*, manifest_path: Path | None = None, lock_path: Path | None = None) -> str:
    cfg = parse_botyard_toml_file(manifest_path)
    root = Path.cwd() if manifest_path is None else manifest_path.parent

    ws = Path(cfg.workspace.dir)
    if not ws.is_absolute():
        ws = (root / ws).resolve()

    lockfile_path = lock_path or _default_install_lock_path()
    pkg_count = 0
    if lockfile_path.exists():
        pkg_count = len(load_lock(lockfile_path).packages)

    lines: list[str] = []
    lines.append("Botpack")
    lines.append(f"  workspace: {ws}")
    lines.append(f"  dependencies: {len(cfg.dependencies)}")
    lines.append(f"  lockfile: {lockfile_path}")
    lines.append(f"  installedPackages: {pkg_count}")
    return "\n".join(lines) + "\n"


def build_tree_output(*, manifest_path: Path | None = None, lock_path: Path | None = None) -> str:
    cfg = parse_botyard_toml_file(manifest_path)
    lockfile_path = lock_path or _default_install_lock_path()

    installed: list[str] = []
    if lockfile_path.exists():
        installed = sorted(load_lock(lockfile_path).packages.keys())

    lines: list[str] = []
    lines.append("Dependencies")
    for name in sorted(cfg.dependencies.keys()):
        lines.append(f"  - {name}")
    lines.append("")
    lines.append("Installed")
    for k in installed:
        lines.append(f"  - {k}")
    return "\n".join(lines) + "\n"


def build_why_output(
    *,
    pkg: str,
    manifest_path: Path | None = None,
    lock_path: Path | None = None,
) -> str:
    cfg = parse_botyard_toml_file(manifest_path)
    lockfile_path = lock_path or _default_install_lock_path()
    installed = []
    if lockfile_path.exists():
        installed = sorted(load_lock(lockfile_path).packages.keys())

    lines: list[str] = []
    lines.append(f"Why: {pkg}")
    if pkg in cfg.dependencies:
        lines.append("  - direct dependency in botpack.toml")
    matches = [k for k in installed if k.startswith(pkg + "@")]
    if matches:
        for k in matches:
            lines.append(f"  - installed as {k}")
    if len(lines) == 1:
        lines.append("  - not found")
    return "\n".join(lines) + "\n"
