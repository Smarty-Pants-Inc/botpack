from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

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


def store_materialize(tree: StoredTree, dest: Path, *, mode: str = "copy") -> None:
    if mode not in {"copy", "symlink"}:
        raise ValueError(f"unsupported mode: {mode}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copytree(tree.path, dest, symlinks=True)
    else:
        dest.symlink_to(tree.path, target_is_directory=True)
