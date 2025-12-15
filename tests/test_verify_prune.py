from __future__ import annotations

from pathlib import Path

from botpack.lock import Lockfile, Package, save_lock
from botpack.prune import prune_store
from botpack.store import store_put_tree
from botpack.verify import verify_lockfile


def test_verify_and_prune(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    a = tmp_path / "a"
    a.mkdir()
    (a / "x.txt").write_text("x", encoding="utf-8")
    ta = store_put_tree(a)

    b = tmp_path / "b"
    b.mkdir()
    (b / "y.txt").write_text("y", encoding="utf-8")
    tb = store_put_tree(b)

    lock_path = tmp_path / "botpack.lock"
    save_lock(
        lock_path,
        Lockfile(
            lockfileVersion=1,
            botpackVersion="0.1.0",
            specVersion="0.1",
            dependencies={},
            packages={
                "@acme/a@1.0.0": Package(source={"type": "path"}, integrity=ta.digest),
            },
        ),
    )

    assert verify_lockfile(lock_path=lock_path).ok is True

    res = prune_store(lock_path=lock_path)
    assert tb.digest in res.removed
