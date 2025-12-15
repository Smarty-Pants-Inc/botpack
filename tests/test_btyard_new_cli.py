from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from botpack.cli import main
from botpack.lock import Lockfile, Package, save_lock


def test_trust_allow_and_revoke_rewrite_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    trust_path = tmp_path / ".botpack" / "trust.toml"

    assert main([
        "trust",
        "allow",
        "@acme/exec@1.0.0",
        "--exec",
        "--mcp",
        "--integrity",
        "sha256:deadbeef",
    ]) == 0

    expected = (
        "version = 1\n"
        "\n"
        "[\"@acme/exec@1.0.0\"]\n"
        "allowExec = true\n"
        "allowMcp = true\n"
        "\n"
        "[\"@acme/exec@1.0.0\".digest]\n"
        "integrity = \"sha256:deadbeef\"\n"
    )
    assert trust_path.read_text(encoding="utf-8") == expected

    assert main(["trust", "revoke", "@acme/exec@1.0.0"]) == 0
    assert trust_path.read_text(encoding="utf-8") == "version = 1\n"


def test_audit_reports_untrusted_packages_and_passes_after_trust(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    lock_path = tmp_path / "botpack.lock"
    lf = Lockfile(
        lockfileVersion=1,
        botpackVersion="0.1.0",
        specVersion="0.1",
        dependencies={"@acme/exec": "*"},
        packages={
            "@acme/exec@1.0.0": Package(
                source={"type": "path", "path": "dep_pkg"},
                resolved={"type": "path", "path": "/abs/dep"},
                integrity="sha256:aaaaaaaa",
                dependencies={},
                capabilities={"exec": True, "mcp": False, "network": False},
            )
        },
    )
    save_lock(lock_path, lf)

    code = main(["audit", "--lockfile", str(lock_path)])
    out = capsys.readouterr().out
    assert code == 6
    assert out.strip() == "@acme/exec@1.0.0: requires trust for exec/mcp"

    # Trust it, then audit should pass.
    assert main(["trust", "allow", "@acme/exec@1.0.0", "--exec"]) == 0
    code2 = main(["audit", "--lockfile", str(lock_path)])
    out2 = capsys.readouterr().out
    assert code2 == 0
    assert out2.strip() == ""


def _init_git_repo(repo: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    (repo / "agentpkg.toml").write_text(
        """agentpkg = \"0.1\"\nname = \"@acme/gitpkg\"\nversion = \"0.1.0\"\n\n[capabilities]\nexec = false\nnetwork = false\nmcp = false\n""",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "agentpkg.toml"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, env=env)


def test_prefetch_offline_requires_cached_git(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    manifest = tmp_path / "botpack.toml"
    manifest.write_text(
        f"""version = 1\n\n[dependencies]\n\"@acme/gitpkg\" = {{ git = \"{repo}\" }}\n""",
        encoding="utf-8",
    )

    lock_path = tmp_path / "botpack.lock"

    # First offline run should fail because git cache is empty.
    assert main(["prefetch", "--manifest", str(manifest), "--lockfile", str(lock_path), "--offline"]) == 4

    # Online prefetch populates cache + lockfile.
    assert main(["prefetch", "--manifest", str(manifest), "--lockfile", str(lock_path)]) == 0
    assert lock_path.exists()

    # Now offline should succeed because cached checkout exists.
    assert main(["prefetch", "--manifest", str(manifest), "--lockfile", str(lock_path), "--offline"]) == 0


def test_list_outputs_workspace_and_packages_deterministically(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    ws = tmp_path / ".botpack" / "workspace"
    (ws / "skills" / "hello").mkdir(parents=True)
    (ws / "skills" / "hello" / "SKILL.md").write_text(
        """---\nid: hello\nname: hello\ndescription: test\n---\n""",
        encoding="utf-8",
    )
    (ws / "commands").mkdir(parents=True)
    (ws / "commands" / "hi.md").write_text("hi", encoding="utf-8")
    (ws / "agents").mkdir(parents=True)
    (ws / "agents" / "bot.md").write_text("bot", encoding="utf-8")

    manifest = tmp_path / "botpack.toml"
    manifest.write_text(
        """version = 1\n\n[workspace]\ndir = \".botpack/workspace\"\n""",
        encoding="utf-8",
    )

    lock_path = tmp_path / "botpack.lock"
    save_lock(
        lock_path,
        Lockfile(
            lockfileVersion=1,
            botpackVersion="0.1.0",
            specVersion="0.1",
            dependencies={},
            packages={
                "@acme/quality@1.2.3": Package(
                    source={"type": "path", "path": "dep_pkg"},
                    resolved={"type": "path", "path": "/abs/dep"},
                    integrity="sha256:bbbbbbbb",
                    dependencies={},
                    capabilities={"exec": False, "mcp": False, "network": False},
                )
            },
        ),
    )

    assert main(["list", "--manifest", str(manifest), "--lockfile", str(lock_path)]) == 0
    out = capsys.readouterr().out
    expected = (
        "Workspace\n"
        "  Skills (1)\n"
        "    - hello\n"
        "  Commands (1)\n"
        "    - hi\n"
        "  Agents (1)\n"
        "    - bot\n"
        "\n"
        "Installed packages (1)\n"
        "  - @acme/quality@1.2.3\n"
    )
    assert out == expected
