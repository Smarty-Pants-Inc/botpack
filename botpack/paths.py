from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def work_root() -> Path:
    root = (
        os.environ.get("BOTPACK_ROOT")
        or os.environ.get("BOTYARD_ROOT")
        or os.environ.get("SMARTY_ROOT")
        or str(repo_root())
    )
    return Path(root).resolve()


def botyard_dir() -> Path:
    root = work_root()
    new = root / ".botpack"
    old = root / ".botyard"
    # Prefer the new directory if it exists, otherwise fall back to legacy.
    return new if new.exists() or not old.exists() else old


def store_dir() -> Path:
    override = os.environ.get("BOTPACK_STORE") or os.environ.get("BOTYARD_STORE")
    if override:
        return Path(override).expanduser().resolve()
    home = Path.home().resolve()
    new = home / ".botpack" / "store" / "v1"
    old = home / ".botyard" / "store" / "v1"
    return new if new.exists() or not old.exists() else old


def pkgs_dir() -> Path:
    """Project-local materialized package roots (.botpack/pkgs)."""

    return botyard_dir() / "pkgs"
