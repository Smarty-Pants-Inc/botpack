from __future__ import annotations

import os
import subprocess
from pathlib import Path

from botpack.fetch import fetch_git, fetch_path
from botpack.models import GitDependency, PathDependency


def test_fetch_path(tmp_path: Path) -> None:
    dep_dir = tmp_path / "dep"
    dep_dir.mkdir()
    (dep_dir / "x.txt").write_text("x", encoding="utf-8")

    ft = fetch_path(PathDependency(path="dep"), base_dir=tmp_path)
    assert ft.path == dep_dir


def test_fetch_git_local_repo(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

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
    (repo / "README.md").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, env=env)

    cache = tmp_path / "cache"
    ft = fetch_git(GitDependency(git=str(repo)), cache_dir=cache)
    assert (ft.path / "README.md").read_text(encoding="utf-8") == "hi"
    assert ft.resolved["type"] == "git"
    assert len(ft.resolved["commit"]) == 40
