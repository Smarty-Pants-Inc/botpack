from __future__ import annotations

from pathlib import Path

from botpack.store import store_materialize, store_put_tree, tree_digest


def test_store_put_tree_is_content_addressed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")

    d1 = tree_digest(src)
    t1 = store_put_tree(src)
    assert t1.digest == d1
    assert t1.path.exists()

    # Re-put is idempotent
    t2 = store_put_tree(src)
    assert t2.digest == t1.digest
    assert t2.path == t1.path

    out = tmp_path / "out"
    store_materialize(t1, out, mode="copy")
    assert (out / "a.txt").read_text(encoding="utf-8") == "hello"
