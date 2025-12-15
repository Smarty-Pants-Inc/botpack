from __future__ import annotations

import os
from pathlib import Path

from botpack.cli import main


def test_by_migrate_from_smarty_copies_expected_layout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    # Legacy .smarty workspace
    src_skill = tmp_path / ".smarty" / "skills" / "hello"
    src_skill.mkdir(parents=True)
    (src_skill / "SKILL.md").write_text("hello-skill", encoding="utf-8")
    (src_skill / "scripts").mkdir()
    (src_skill / "scripts" / "hello.py").write_text("print('hi')\n", encoding="utf-8")

    (tmp_path / ".smarty" / "commands").mkdir(parents=True)
    (tmp_path / ".smarty" / "commands" / "hi.md").write_text("hi", encoding="utf-8")

    (tmp_path / ".smarty" / "agents").mkdir(parents=True)
    (tmp_path / ".smarty" / "agents" / "dev.md").write_text("dev", encoding="utf-8")

    (tmp_path / ".smarty" / "config").mkdir(parents=True)
    (tmp_path / ".smarty" / "config" / "mcp.json").write_text('{"servers": []}\n', encoding="utf-8")

    assert main(["migrate", "from-smarty"]) == 0

    dst_root = tmp_path / ".botpack" / "workspace"
    assert (dst_root / "skills" / "hello" / "SKILL.md").read_text(encoding="utf-8") == "hello-skill"
    assert (dst_root / "skills" / "hello" / "scripts" / "hello.py").exists()
    assert (dst_root / "commands" / "hi.md").read_text(encoding="utf-8") == "hi"
    assert (dst_root / "agents" / "dev.md").read_text(encoding="utf-8") == "dev"
    assert (dst_root / "config" / "mcp.json").read_text(encoding="utf-8") == '{"servers": []}\n'


def test_migrate_is_idempotent_and_respects_newer_destination_unless_force(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    (tmp_path / ".smarty" / "commands").mkdir(parents=True)
    src = tmp_path / ".smarty" / "commands" / "hi.md"
    src.write_text("src", encoding="utf-8")

    # First migration copies
    assert main(["migrate", "from-smarty"]) == 0
    dst = tmp_path / ".botpack" / "workspace" / "commands" / "hi.md"
    assert dst.read_text(encoding="utf-8") == "src"

    # Idempotent: identical file is not rewritten.
    os.utime(dst, (1, 1))
    assert main(["migrate", "from-smarty"]) == 0
    assert int(dst.stat().st_mtime) == 1

    # Newer destination should not be overwritten unless forced.
    dst.write_text("dst-newer", encoding="utf-8")
    newer = src.stat().st_mtime + 10
    os.utime(dst, (newer, newer))
    assert main(["migrate", "from-smarty"]) == 0
    assert dst.read_text(encoding="utf-8") == "dst-newer"

    assert main(["migrate", "from-smarty", "--force"]) == 0
    assert dst.read_text(encoding="utf-8") == "src"
