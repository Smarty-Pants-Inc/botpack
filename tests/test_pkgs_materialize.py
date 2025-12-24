from __future__ import annotations

import os
from pathlib import Path

import pytest

from botpack.lock import Lockfile, Package
from botpack.pkgs import materialize_pkgs
from botpack.store import store_put_tree


def _mk_lock(*, pkg_key: str, integrity: str) -> Lockfile:
    return Lockfile(
        lockfileVersion=1,
        botpackVersion="0.0",
        specVersion="0.1",
        dependencies={},
        packages={
            pkg_key: Package(
                source={"type": "path", "path": "."},
                resolved={},
                integrity=integrity,
                dependencies={},
                capabilities={},
            )
        },
    )


def test_pkgs_materialize_copy_and_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store" / "v1"))

    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "hello.txt").write_text("hi", encoding="utf-8")
    stored = store_put_tree(src)

    pkg_key = "@acme/thing@1.0.0"
    lock = _mk_lock(pkg_key=pkg_key, integrity=stored.digest)
    r1 = materialize_pkgs(lock=lock, mode="copy")
    assert r1.conflicts == []

    dest = tmp_path / ".botpack" / "pkgs" / "@acme" / "thing@1.0.0"
    assert dest.exists()
    assert (dest / "hello.txt").read_text(encoding="utf-8") == "hi"

    # Idempotent.
    r2 = materialize_pkgs(lock=lock, mode="copy")
    assert r2.conflicts == []

    # Clean removes when no longer desired.
    empty = Lockfile(lockfileVersion=1, botpackVersion="0.0", specVersion="0.1", dependencies={}, packages={})
    r3 = materialize_pkgs(lock=empty, mode="copy", clean=True)
    assert dest.exists() is False
    assert r3.conflicts == []


def test_pkgs_materialize_hardlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store" / "v1"))

    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "file.txt").write_text("x", encoding="utf-8")
    stored = store_put_tree(src)

    pkg_key = "pkg@1.0.0"
    lock = _mk_lock(pkg_key=pkg_key, integrity=stored.digest)
    r = materialize_pkgs(lock=lock, mode="hardlink")
    assert r.conflicts == []

    store_file = (tmp_path / "store" / "v1" / stored.digest / "file.txt").resolve()
    dest_file = (tmp_path / ".botpack" / "pkgs" / "pkg@1.0.0" / "file.txt").resolve()
    assert dest_file.exists()

    st_store = os.stat(store_file)
    st_dest = os.stat(dest_file)
    assert st_store.st_ino == st_dest.st_ino
    assert st_dest.st_nlink >= 2


def test_pkgs_conflict_if_preexisting_unowned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store" / "v1"))

    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "x.txt").write_text("x", encoding="utf-8")
    stored = store_put_tree(src)

    dest = tmp_path / ".botpack" / "pkgs" / "pkg@1.0.0"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "user.txt").write_text("user", encoding="utf-8")

    lock = _mk_lock(pkg_key="pkg@1.0.0", integrity=stored.digest)
    r = materialize_pkgs(lock=lock, mode="copy")
    assert r.conflicts
