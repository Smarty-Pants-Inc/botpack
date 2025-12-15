from __future__ import annotations

import pytest
from pathlib import Path

from botpack.install import install


def test_install_denies_untrusted_exec_packages(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    dep = tmp_path / "dep_pkg"
    dep.mkdir()
    (dep / "agentpkg.toml").write_text(
        """agentpkg = "0.1"
name = "@acme/exec"
version = "1.0.0"

[capabilities]
exec = true
""",
        encoding="utf-8",
    )

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[dependencies]
"@acme/exec" = { path = "dep_pkg" }
""",
        encoding="utf-8",
    )

    with pytest.raises(PermissionError):
        install(manifest_path=tmp_path / "botpack.toml", lock_path=tmp_path / "botpack.lock")

    trust = tmp_path / ".botpack" / "trust.toml"
    trust.parent.mkdir(parents=True)
    trust.write_text(
        """version = 1

["@acme/exec@1.0.0"]
allowExec = true
allowMcp = false
""",
        encoding="utf-8",
    )

    # Now it should succeed.
    install(manifest_path=tmp_path / "botpack.toml", lock_path=tmp_path / "botpack.lock")
