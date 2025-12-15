from __future__ import annotations

from pathlib import Path

from botpack.install import install
from botpack.lock import load_lock


def test_install_path_dependency_writes_lockfile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    dep = tmp_path / "dep_pkg"
    dep.mkdir()
    (dep / "agentpkg.toml").write_text(
        """agentpkg = "0.1"
name = "@acme/quality"
version = "1.2.3"
""",
        encoding="utf-8",
    )
    (dep / "skills").mkdir()

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[dependencies]
"@acme/quality" = { path = "dep_pkg" }
""",
        encoding="utf-8",
    )

    out = install(manifest_path=tmp_path / "botpack.toml", lock_path=tmp_path / "botpack.lock")
    lf = load_lock(out)
    assert lf.dependencies["@acme/quality"] == "*"
    assert "@acme/quality@1.2.3" in lf.packages
