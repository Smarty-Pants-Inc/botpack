from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
import errno

from .paths import store_dir


@dataclass(frozen=True)
class StoredTree:
    digest: str
    path: Path


def tree_digest(root: Path) -> str:
    """Compute a deterministic digest for a directory tree.

    Digest is over (relative path, file bytes) for all regular files.
    """

    root = root.resolve()
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if p.is_symlink():
            # Hash link target path string (do not follow).
            rel = p.relative_to(root).as_posix().encode("utf-8")
            h.update(b"L")
            h.update(rel)
            h.update(b"\0")
            h.update(os.readlink(p).encode("utf-8"))
            h.update(b"\0")
            continue
        if not p.is_file():
            continue

        rel = p.relative_to(root).as_posix().encode("utf-8")
        h.update(b"F")
        h.update(rel)
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def store_put_tree(src: Path) -> StoredTree:
    src = src.resolve()
    if not src.is_dir():
        raise ValueError(f"store_put_tree: expected directory, got {src}")

    digest = tree_digest(src)
    dst = store_dir() / digest
    if dst.exists():
        return StoredTree(digest=digest, path=dst)

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp, symlinks=True)
    tmp.replace(dst)
    return StoredTree(digest=digest, path=dst)


def store_materialize(tree: StoredTree, dest: Path, *, mode: str = "copy") -> str:
    """Materialize a stored tree to `dest`.

    Modes:
    - copy: full copy
    - symlink: directory symlink
    - hardlink: hardlink files (best-effort; preserves symlinks)
    - auto: try symlink -> hardlink -> copy

    Returns the mode actually used.
    """

    if mode not in {"auto", "copy", "symlink", "hardlink"}:
        raise ValueError(f"unsupported mode: {mode}")

    attempts = [mode] if mode != "auto" else ["symlink", "hardlink", "copy"]
    last: Exception | None = None
    for m in attempts:
        try:
            _materialize_tree(src=tree.path, dest=dest, mode=m)
            return m
        except Exception as e:  # pragma: no cover (depends on fs/policy)
            last = e
            continue
    assert last is not None
    raise last


def _rm_any(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path)


def _hardlink_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        out = dst / rel
        if p.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        if p.is_symlink():
            out.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.readlink(p), out)
            continue
        if p.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            os.link(p, out)
            continue


def _materialize_tree(*, src: Path, dest: Path, mode: str) -> None:
    if mode not in {"copy", "symlink", "hardlink"}:
        raise ValueError(f"unsupported mode: {mode}")

    dest = dest.resolve() if dest.exists() else dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    _rm_any(tmp)

    if mode == "symlink":
        tmp.symlink_to(src, target_is_directory=True)
        _rm_any(dest)
        tmp.replace(dest)
        return

    if mode == "copy":
        shutil.copytree(src, tmp, symlinks=True)
        _rm_any(dest)
        tmp.replace(dest)
        return

    # hardlink
    try:
        _hardlink_tree(src, tmp)
    except OSError as e:
        # Surface the failure to allow auto fallback.
        if getattr(e, "errno", None) in {errno.EXDEV, errno.EPERM, errno.EACCES}:
            _rm_any(tmp)
        raise
    _rm_any(dest)
    tmp.replace(dest)
