from __future__ import annotations

import os
import subprocess
from pathlib import Path

from botpack.cli import main


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
        """agentpkg = "0.1"
name = "@acme/gitpkg"
version = "0.1.0"

[capabilities]
exec = false
network = false
mcp = false
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "agentpkg.toml"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, env=env)


def test_install_offline_requires_cached_git(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    manifest = tmp_path / "botpack.toml"
    manifest.write_text(
        f"""version = 1

[dependencies]
"@acme/gitpkg" = {{ git = "{repo}" }}
""",
        encoding="utf-8",
    )
    lock_path = tmp_path / "botpack.lock"

    # Offline install should fail when cache is empty.
    assert main(["install", "--manifest", str(manifest), "--lockfile", str(lock_path), "--offline"]) == 4

    # Online install populates cache + lockfile.
    assert main(["install", "--manifest", str(manifest), "--lockfile", str(lock_path)]) == 0
    assert lock_path.exists()

    # Offline now succeeds.
    assert main(["install", "--manifest", str(manifest), "--lockfile", str(lock_path), "--offline"]) == 0
