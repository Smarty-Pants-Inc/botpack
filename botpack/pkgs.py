from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .lock import Lockfile
from .paths import botyard_dir, pkgs_dir, store_dir
from .store import StoredTree, store_materialize, tree_digest


@dataclass(frozen=True)
class PkgsResult:
    created: list[str]
    updated: list[str]
    removed: list[str]
    conflicts: list[str]


def _split_pkg_key(pkg_key: str) -> tuple[str, str]:
    name, ver = pkg_key.rsplit("@", 1)
    return name, ver


def _pkg_key_relpath(pkg_key: str) -> Path:
    """Human-readable package dir path.

    Example: "@acme/thing@1.2.3" -> "@acme/thing@1.2.3" (nested scope dir)
    """

    name, ver = _split_pkg_key(pkg_key)
    parts = [p for p in name.split("/") if p]
    if not parts:
        raise ValueError(f"invalid pkg key: {pkg_key!r}")
    leaf = parts[-1] + "@" + ver
    return Path(*parts[:-1], leaf)


def _state_path() -> Path:
    return botyard_dir() / "state" / "pkgs.json"


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {"version": 1, "paths": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            return {"version": 1, "paths": {}}
        if not isinstance(data.get("paths"), dict):
            data["paths"] = {}
        return data
    except Exception:
        return {"version": 1, "paths": {}}


def _write_state(state: dict, *, dry_run: bool) -> None:
    if dry_run:
        return
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _rm_any(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path)


def _prune_empty_parents(path: Path, *, stop: Path) -> None:
    cur = path.parent
    stop = stop.resolve()
    while True:
        if cur == stop or not str(cur).startswith(str(stop)):
            return
        try:
            cur.rmdir()
        except OSError:
            return
        cur = cur.parent


def _is_correct(dest: Path, *, integrity: str, store_path: Path) -> bool:
    if dest.is_symlink():
        try:
            target = os.readlink(dest)
        except OSError:
            return False
        # Normalize relative targets.
        resolved = (dest.parent / target).resolve() if not os.path.isabs(target) else Path(target).resolve()
        return resolved == store_path.resolve()
    if dest.is_dir():
        try:
            return tree_digest(dest) == integrity
        except Exception:
            return False
    return False


def materialize_pkgs(
    *,
    lock: Lockfile,
    mode: str,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> PkgsResult:
    """Materialize installed packages into `.botpack/pkgs/`.

    This creates stable, human-readable paths for referencing shared assets
    (e.g. scripts) without hardcoding a store digest.
    """

    root = pkgs_dir()

    state = _load_state()
    prev_paths: dict[str, dict] = state.get("paths") if isinstance(state.get("paths"), dict) else {}
    next_paths: dict[str, dict] = {}

    desired: dict[str, dict[str, str]] = {}
    for pkg_key, pkg in lock.packages.items():
        if not pkg.integrity:
            continue
        store_path = store_dir() / pkg.integrity
        if not store_path.exists():
            continue
        # IMPORTANT: do not resolve here; resolve() would collapse an existing symlink
        # and cause us to record the store path instead of the stable project-local path.
        dest = root / _pkg_key_relpath(pkg_key)
        desired[str(dest)] = {
            "pkg_key": pkg_key,
            "integrity": pkg.integrity,
        }

    created: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    conflicts: list[str] = []

    for dest_str in sorted(desired.keys()):
        spec = desired[dest_str]
        dest = Path(dest_str)
        integrity = spec["integrity"]
        store_path = store_dir() / integrity

        prev_entry = prev_paths.get(dest_str)
        owned = isinstance(prev_entry, dict)

        pre_exists = dest.exists() or dest.is_symlink()

        if pre_exists:
            if not owned and not force:
                conflicts.append(dest_str)
                if isinstance(prev_entry, dict):
                    next_paths[dest_str] = prev_entry
                continue
            if _is_correct(dest, integrity=integrity, store_path=store_path):
                next_paths[dest_str] = {"pkg_key": spec["pkg_key"], "integrity": integrity, "mode": prev_entry.get("mode") if isinstance(prev_entry, dict) else None}
                continue
            # Owned but drifted/wrong: treat as tool-managed and repair.

        if not dry_run:
            used = store_materialize(StoredTree(digest=integrity, path=store_path), dest, mode=mode)
        else:
            used = mode

        if pre_exists:
            updated.append(dest_str)
        else:
            created.append(dest_str)
        next_paths[dest_str] = {"pkg_key": spec["pkg_key"], "integrity": integrity, "mode": used}

    if clean:
        for dest_str in sorted(prev_paths.keys()):
            if dest_str in next_paths:
                continue
            prev_entry = prev_paths.get(dest_str)
            dest = Path(dest_str)
            if not isinstance(prev_entry, dict):
                continue
            if not (dest.exists() or dest.is_symlink()):
                continue
            integrity = prev_entry.get("integrity")
            store_path = store_dir() / integrity if isinstance(integrity, str) else None
            if store_path is not None and store_path.exists() and not force:
                # Refuse to delete if the directory was modified.
                if not _is_correct(dest, integrity=str(integrity), store_path=store_path):
                    conflicts.append(dest_str)
                    next_paths[dest_str] = prev_entry
                    continue
            if not dry_run:
                _rm_any(dest)
                _prune_empty_parents(dest, stop=root)
            removed.append(dest_str)

    state["version"] = 1
    state["paths"] = next_paths
    _write_state(state, dry_run=dry_run)

    return PkgsResult(created=created, updated=updated, removed=removed, conflicts=conflicts)
