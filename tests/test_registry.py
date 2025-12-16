from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from botpack.install import install
from botpack.lock import load_lock
from botpack.registry import resolve_semver_dependency


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
    )
    return env


def _commit_agentpkg(repo: Path, *, name: str, version: str, env: dict[str, str], msg: str) -> str:
    (repo / "agentpkg.toml").write_text(
        f"""agentpkg = \"0.1\"\nname = \"{name}\"\nversion = \"{version}\"\n\n[capabilities]\nexec = false\nnetwork = false\nmcp = false\n""",
        encoding="utf-8",
    )
    (repo / "skills").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "agentpkg.toml"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True, env=env)
    cp = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    return cp.stdout.strip()


def test_resolve_semver_dependency_picks_highest_satisfying(tmp_path: Path, monkeypatch) -> None:
    pkg = "@acme/quality"

    # Minimal registry index served via file://
    registry_root = tmp_path / "registry"
    versions_path = registry_root / "@acme" / "quality"
    versions_path.mkdir(parents=True)
    (versions_path / "versions.json").write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.0": {"git": "https://example.invalid/repo.git", "commit": "a" * 40},
                    "1.2.0": {"git": "https://example.invalid/repo.git", "commit": "b" * 40},
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("BOTPACK_REGISTRY_URL", registry_root.as_uri())

    rr = resolve_semver_dependency(name=pkg, spec="^1")
    assert rr.version == "1.2.0"
    assert rr.commit == "b" * 40


def test_install_semver_dependency_resolves_via_registry_and_locks_commit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    pkg = "@acme/quality"

    # Create a local git repo with two versions.
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _git_env()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    sha_1_0_0 = _commit_agentpkg(repo, name=pkg, version="1.0.0", env=env, msg="v1.0.0")
    sha_1_2_0 = _commit_agentpkg(repo, name=pkg, version="1.2.0", env=env, msg="v1.2.0")

    # Minimal registry index served via file://
    registry_root = tmp_path / "registry"
    versions_dir = registry_root / "@acme" / "quality"
    versions_dir.mkdir(parents=True)
    (versions_dir / "versions.json").write_text(
        json.dumps(
            {
                "versions": {
                    "1.0.0": {"git": str(repo), "commit": sha_1_0_0},
                    "1.2.0": {"git": str(repo), "commit": sha_1_2_0},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BOTPACK_REGISTRY_URL", registry_root.as_uri())

    # Manifest uses caret-major shorthand.
    (tmp_path / "botpack.toml").write_text(
        """version = 1

[dependencies]
"@acme/quality" = "^1"
""",
        encoding="utf-8",
    )

    out = install(manifest_path=tmp_path / "botpack.toml", lock_path=tmp_path / "botpack.lock")
    lf = load_lock(out)

    assert lf.dependencies[pkg] == "^1"
    pkg_key = f"{pkg}@1.2.0"
    assert pkg_key in lf.packages

    locked = lf.packages[pkg_key]
    assert locked.source["type"] == "git"
    assert locked.source["url"] == str(repo)
    assert locked.source["rev"] == sha_1_2_0
    assert locked.resolved["commit"] == sha_1_2_0
