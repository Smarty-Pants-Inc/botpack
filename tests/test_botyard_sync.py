from __future__ import annotations

from pathlib import Path

from botpack.sync import sync
from botpack.lock import Lockfile, Package, save_lock
from botpack.store import store_put_tree


def test_sync_claude_creates_outputs_and_clean_removes_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"

[sync]
linkMode = "copy"
""",
        encoding="utf-8",
    )

    ws = tmp_path / ".botpack" / "workspace"
    skill_dir = ws / "skills" / "hello"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: hello
name: hello
description: test
---
""",
        encoding="utf-8",
    )
    cmd_dir = ws / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "hi.md").write_text("hi", encoding="utf-8")

    res = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res.conflicts == []

    out_skill = tmp_path / ".claude" / "skills" / "workspace.hello" / "SKILL.md"
    out_cmd = tmp_path / ".claude" / "commands" / "workspace.hi.md"
    assert out_skill.exists()
    assert out_cmd.exists()

    # Also supports other targets with identical materialization model.
    assert sync(target="amp", manifest_path=tmp_path / "botpack.toml").conflicts == []
    assert (tmp_path / ".agents" / "skills" / "workspace.hello" / "SKILL.md").exists()

    assert sync(target="droid", manifest_path=tmp_path / "botpack.toml").conflicts == []
    assert (tmp_path / ".factory" / "skills" / "workspace.hello" / "SKILL.md").exists()

    # Remove skill source then clean
    (skill_dir / "SKILL.md").unlink()
    res2 = sync(target="claude", manifest_path=tmp_path / "botpack.toml", clean=True)
    assert str(out_skill) in res2.removed


def test_sync_materializes_package_assets_from_lockfile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"
""",
        encoding="utf-8",
    )

    # Create a fake package tree and store it.
    pkg_src = tmp_path / "pkg_src"
    (pkg_src / "skills" / "hello").mkdir(parents=True)
    (pkg_src / "skills" / "hello" / "SKILL.md").write_text(
        """---
id: hello
name: hello
description: from package
---
""",
        encoding="utf-8",
    )
    (pkg_src / "commands").mkdir(parents=True)
    (pkg_src / "commands" / "hi.md").write_text("hi from package", encoding="utf-8")
    (pkg_src / "agents").mkdir(parents=True)
    (pkg_src / "agents" / "agent.md").write_text("agent", encoding="utf-8")
    (pkg_src / "agentpkg.toml").write_text(
        """agentpkg = "0.1"
name = "@acme/quality"
version = "1.0.0"
""",
        encoding="utf-8",
    )

    stored = store_put_tree(pkg_src)

    lock = Lockfile(
        lockfileVersion=1,
        botpackVersion="0.1.0",
        specVersion="0.1",
        dependencies={"@acme/quality": "*"},
        packages={
            "@acme/quality@1.0.0": Package(
                source={"type": "path", "path": "pkg_src"},
                resolved={},
                integrity=stored.digest,
                dependencies={},
                capabilities={},
            )
        },
    )
    save_lock(tmp_path / "botpack.lock", lock)

    res = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res.conflicts == []

    out_skill = tmp_path / ".claude" / "skills" / "acme-quality.hello" / "SKILL.md"
    out_cmd = tmp_path / ".claude" / "commands" / "acme-quality.hi.md"
    out_agent = tmp_path / ".claude" / "agents" / "acme-quality.agent.md"
    assert out_skill.exists()
    assert out_cmd.exists()
    assert out_agent.exists()

    # Atomic writes should not leave tmp files around.
    assert not list((tmp_path / ".claude").rglob("*.tmp"))


def test_sync_detects_user_drift_and_requires_force(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"
""",
        encoding="utf-8",
    )

    ws = tmp_path / ".botpack" / "workspace"
    cmd_dir = ws / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "hi.md").write_text("hi", encoding="utf-8")

    # Initial sync
    res1 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res1.conflicts == []

    out_cmd = tmp_path / ".claude" / "commands" / "workspace.hi.md"
    assert out_cmd.exists()

    # User modifies the generated file.
    out_cmd.write_text("user edit", encoding="utf-8")

    res2 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert str(out_cmd) in res2.conflicts
    assert out_cmd.read_text(encoding="utf-8") == "user edit"

    res3 = sync(target="claude", manifest_path=tmp_path / "botpack.toml", force=True)
    assert res3.conflicts == []
    assert out_cmd.read_text(encoding="utf-8") == "hi"
