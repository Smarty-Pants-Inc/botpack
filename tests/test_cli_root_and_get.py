from __future__ import annotations

import os
from pathlib import Path

from botpack.cli import main


def test_cli_sets_botpack_root_by_searching_parents_for_manifest(tmp_path: Path, monkeypatch) -> None:
    proj = tmp_path / "proj"
    (proj / "nested" / "dir").mkdir(parents=True)
    (proj / "botpack.toml").write_text("version = 1\n", encoding="utf-8")

    monkeypatch.chdir(proj / "nested" / "dir")
    monkeypatch.delenv("BOTPACK_ROOT", raising=False)
    monkeypatch.delenv("BOTYARD_ROOT", raising=False)
    monkeypatch.delenv("SMARTY_ROOT", raising=False)

    assert main(["list"]) == 0
    assert os.environ.get("BOTPACK_ROOT") == str(proj.resolve())


def test_cli_root_flag_overrides_auto_detection(tmp_path: Path, monkeypatch) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    (a / "sub").mkdir(parents=True)
    b.mkdir()
    (a / "botpack.toml").write_text("version = 1\n", encoding="utf-8")
    (b / "botpack.toml").write_text("version = 1\n", encoding="utf-8")

    monkeypatch.chdir(a / "sub")
    monkeypatch.delenv("BOTPACK_ROOT", raising=False)
    monkeypatch.delenv("BOTYARD_ROOT", raising=False)
    monkeypatch.delenv("SMARTY_ROOT", raising=False)

    assert main(["--root", str(b), "list"]) == 0
    assert os.environ.get("BOTPACK_ROOT") == str(b.resolve())


def test_get_adds_installs_and_syncs_from_subdir_using_auto_root(tmp_path: Path, monkeypatch) -> None:
    # Project root with manifest
    proj = tmp_path / "proj"
    (proj / "nested").mkdir(parents=True)
    (proj / "botpack.toml").write_text("version = 1\n", encoding="utf-8")

    # Dependency package (local path)
    pkg = tmp_path / "pkg"
    (pkg / "skills" / "hello").mkdir(parents=True)
    (pkg / "skills" / "hello" / "SKILL.md").write_text(
        """---
id: hello
name: hello
description: from pkg
---
""",
        encoding="utf-8",
    )
    (pkg / "agentpkg.toml").write_text(
        """agentpkg = "0.1"
name = "@acme/quality"
version = "1.0.0"

[capabilities]
exec = false
network = false
mcp = false
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))
    monkeypatch.chdir(proj / "nested")
    monkeypatch.delenv("BOTPACK_ROOT", raising=False)
    monkeypatch.delenv("BOTYARD_ROOT", raising=False)
    monkeypatch.delenv("SMARTY_ROOT", raising=False)

    assert main(["get", "@acme/quality", "--path", str(pkg)]) == 0

    # Wrote manifest + lockfile at project root.
    assert (proj / "botpack.lock").exists()
    assert "\"@acme/quality\"" in (proj / "botpack.toml").read_text(encoding="utf-8")

    # Synced to default target (claude)
    out_skill = proj / ".claude" / "skills" / "acme-quality.hello" / "SKILL.md"
    assert out_skill.exists()


def test_cli_global_uses_default_profile_root(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BOTPACK_ROOT", raising=False)
    monkeypatch.delenv("BOTYARD_ROOT", raising=False)
    monkeypatch.delenv("SMARTY_ROOT", raising=False)

    root = home / ".botpack" / "profiles" / "default"
    root.mkdir(parents=True)
    (root / "botpack.toml").write_text("version = 1\n", encoding="utf-8")

    assert main(["--global", "list"]) == 0
    assert os.environ.get("BOTPACK_ROOT") == str(root.resolve())


def test_cli_profile_uses_named_profile_root(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BOTPACK_ROOT", raising=False)
    monkeypatch.delenv("BOTYARD_ROOT", raising=False)
    monkeypatch.delenv("SMARTY_ROOT", raising=False)

    root = home / ".botpack" / "profiles" / "work"
    root.mkdir(parents=True)
    (root / "botpack.toml").write_text("version = 1\n", encoding="utf-8")

    assert main(["--profile", "work", "list"]) == 0
    assert os.environ.get("BOTPACK_ROOT") == str(root.resolve())
