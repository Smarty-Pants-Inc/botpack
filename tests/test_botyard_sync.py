from __future__ import annotations

import json
from pathlib import Path

from botpack.sync import sync, load_conflicts, AssetAddress, ConflictRecord
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

    out_skill = tmp_path / ".claude" / "skills" / "assets.hello" / "SKILL.md"
    out_cmd = tmp_path / ".claude" / "commands" / "assets.hi.md"
    assert out_skill.exists()
    assert out_cmd.exists()

    # Also supports other targets with identical materialization model.
    assert sync(target="amp", manifest_path=tmp_path / "botpack.toml").conflicts == []
    assert (tmp_path / ".agents" / "skills" / "assets.hello" / "SKILL.md").exists()

    assert sync(target="droid", manifest_path=tmp_path / "botpack.toml").conflicts == []
    assert (tmp_path / ".factory" / "skills" / "assets.hello" / "SKILL.md").exists()

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

    out_cmd = tmp_path / ".claude" / "commands" / "assets.hi.md"
    assert out_cmd.exists()

    # User modifies the generated file.
    out_cmd.write_text("user edit", encoding="utf-8")

    res2 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert str(out_cmd) in res2.conflicts
    assert out_cmd.read_text(encoding="utf-8") == "user edit"

    res3 = sync(target="claude", manifest_path=tmp_path / "botpack.toml", force=True)
    assert res3.conflicts == []
    assert out_cmd.read_text(encoding="utf-8") == "hi"


def test_sync_state_format_v2_includes_source_type_and_asset_address(tmp_path: Path, monkeypatch) -> None:
    """Test that sync state v2 includes source_type and asset_address fields."""
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"
""",
        encoding="utf-8",
    )

    # Create assets directory (first-party) assets
    ws = tmp_path / ".botpack" / "workspace"
    skill_dir = ws / "skills" / "local_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: local_skill
name: local skill
description: test
---
""",
        encoding="utf-8",
    )

    # Create a package
    pkg_src = tmp_path / "pkg_src"
    (pkg_src / "skills" / "pkg_skill").mkdir(parents=True)
    (pkg_src / "skills" / "pkg_skill" / "SKILL.md").write_text(
        """---
id: pkg_skill
name: package skill
description: from package
---
""",
        encoding="utf-8",
    )
    (pkg_src / "agentpkg.toml").write_text(
        """agentpkg = "0.1"
name = "@test/pkg"
version = "1.0.0"
""",
        encoding="utf-8",
    )

    stored = store_put_tree(pkg_src)

    lock = Lockfile(
        lockfileVersion=1,
        botpackVersion="0.1.0",
        specVersion="0.1",
        dependencies={"@test/pkg": "*"},
        packages={
            "@test/pkg@1.0.0": Package(
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

    # Check state file format
    state_path = tmp_path / ".botpack" / "state" / "sync-claude.json"
    assert state_path.exists()

    state = json.loads(state_path.read_text(encoding="utf-8"))

    # Verify state format version 2
    assert state.get("version") == 2
    assert state.get("target") == "claude"
    assert "assets_dir" in state

    # Verify assets directory skill has correct source_type
    local_skill_path = str(tmp_path / ".claude" / "skills" / "assets.local_skill" / "SKILL.md")
    assert local_skill_path in state["paths"]
    local_entry = state["paths"][local_skill_path]
    assert local_entry.get("source_type") == "assets_dir"
    assert local_entry.get("source_name") is None
    assert local_entry.get("asset_address") == "skill:local_skill"
    assert "asset_mapping" in local_entry  # Placeholder field

    # Verify package skill has correct source_type
    pkg_skill_path = str(tmp_path / ".claude" / "skills" / "test-pkg.pkg_skill" / "SKILL.md")
    assert pkg_skill_path in state["paths"]
    pkg_entry = state["paths"][pkg_skill_path]
    assert pkg_entry.get("source_type") == "pkg"
    assert pkg_entry.get("source_name") == "@test/pkg"
    assert pkg_entry.get("asset_address") == "skill:pkg_skill"


def test_sync_conflict_records_written_for_doctor(tmp_path: Path, monkeypatch) -> None:
    """Test that conflict records are written for doctor/explain consumption."""
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
    (cmd_dir / "test.md").write_text("original", encoding="utf-8")

    # Initial sync
    res1 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res1.conflicts == []
    assert res1.conflict_records == []

    out_cmd = tmp_path / ".claude" / "commands" / "assets.test.md"
    assert out_cmd.exists()

    # User modifies the generated file to create drift
    out_cmd.write_text("user modified", encoding="utf-8")

    # Sync again - should detect conflict
    res2 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert len(res2.conflicts) == 1
    assert len(res2.conflict_records) == 1

    # Verify conflict record structure
    cr = res2.conflict_records[0]
    assert cr.path == str(out_cmd)
    assert cr.reason == "target file modified since last sync"
    assert cr.asset_address is not None
    assert cr.asset_address.asset_type == "command"
    assert cr.asset_address.asset_id == "test"
    assert cr.asset_address.source_type == "assets_dir"
    assert cr.last_known_good_sha256 is not None

    # Verify conflict records file was written
    conflicts_path = tmp_path / ".botpack" / "state" / "conflicts-claude.json"
    assert conflicts_path.exists()

    # Verify load_conflicts can read them back
    loaded = load_conflicts("claude")
    assert len(loaded) == 1
    assert loaded[0].path == str(out_cmd)
    assert loaded[0].asset_address is not None
    assert loaded[0].asset_address.address == "command:test"

    # Force sync should clear conflicts
    res3 = sync(target="claude", manifest_path=tmp_path / "botpack.toml", force=True)
    assert res3.conflicts == []
    assert res3.conflict_records == []

    # Conflicts file should be cleared
    assert not conflicts_path.exists() or load_conflicts("claude") == []


def test_asset_address_dataclass() -> None:
    """Test AssetAddress dataclass functionality."""
    addr = AssetAddress(
        asset_type="skill",
        asset_id="fetch_web",
        source_type="pkg",
        source_name="@acme/quality-skills",
    )

    assert addr.address == "skill:fetch_web"

    d = addr.to_dict()
    assert d["asset_type"] == "skill"
    assert d["asset_id"] == "fetch_web"
    assert d["source_type"] == "pkg"
    assert d["source_name"] == "@acme/quality-skills"
    assert d["address"] == "skill:fetch_web"


def test_conflict_record_dataclass() -> None:
    """Test ConflictRecord dataclass functionality."""
    addr = AssetAddress(
        asset_type="command",
        asset_id="pr-review",
        source_type="assets_dir",
        source_name=None,
    )

    cr = ConflictRecord(
        path="/path/to/file.md",
        asset_address=addr,
        reason="target file modified since last sync",
        last_known_good_sha256="abc123",
    )

    d = cr.to_dict()
    assert d["path"] == "/path/to/file.md"
    assert d["asset_address"]["address"] == "command:pr-review"
    assert d["reason"] == "target file modified since last sync"
    assert d["last_known_good_sha256"] == "abc123"


def test_sync_preserves_last_known_good_on_conflict(tmp_path: Path, monkeypatch) -> None:
    """Test that sync preserves last-known-good state when conflicts occur."""
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
    (cmd_dir / "test.md").write_text("v1", encoding="utf-8")

    # Initial sync
    res1 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res1.conflicts == []

    out_cmd = tmp_path / ".claude" / "commands" / "assets.test.md"

    # Get the original hash from state
    state_path = tmp_path / ".botpack" / "state" / "sync-claude.json"
    state1 = json.loads(state_path.read_text(encoding="utf-8"))
    original_sha = state1["paths"][str(out_cmd)]["sha256"]

    # User modifies the generated file
    out_cmd.write_text("user modified", encoding="utf-8")

    # Update source
    (cmd_dir / "test.md").write_text("v2", encoding="utf-8")

    # Sync again - should detect conflict and preserve last-known-good
    res2 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert len(res2.conflicts) == 1

    # Verify the state still has the original sha (last-known-good)
    state2 = json.loads(state_path.read_text(encoding="utf-8"))
    assert state2["paths"][str(out_cmd)]["sha256"] == original_sha

    # User's edit should be preserved
    assert out_cmd.read_text(encoding="utf-8") == "user modified"
