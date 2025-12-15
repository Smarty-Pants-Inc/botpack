from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import GitDependency, PathDependency


class FetchError(RuntimeError):
    """Raised when a dependency cannot be fetched (e.g., offline cache miss)."""


@dataclass(frozen=True)
class FetchedTree:
    path: Path
    resolved: dict


def fetch_path(dep: PathDependency, *, base_dir: Path) -> FetchedTree:
    p = Path(dep.path)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    if not p.exists() or not p.is_dir():
        raise ValueError(f"path dependency not found: {p}")
    return FetchedTree(path=p, resolved={"type": "path", "path": str(p)})


def fetch_git(
    dep: GitDependency,
    *,
    cache_dir: Path,
    offline: bool = False,
) -> FetchedTree:
    if shutil.which("git") is None:
        raise RuntimeError("git not available")

    cache_dir.mkdir(parents=True, exist_ok=True)

    # Use a stable directory name based on the URL and rev.
    safe = dep.git.replace("://", "_").replace("/", "_").replace("@", "_")
    rev = dep.rev or "HEAD"
    checkout_dir = cache_dir / f"{safe}-{rev}"
    if checkout_dir.exists():
        # Always capture resolved commit to keep lockfile deterministic even when cached.
        cp = subprocess.run(
            ["git", "-C", str(checkout_dir), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        commit = cp.stdout.strip()
        return FetchedTree(path=checkout_dir, resolved={"type": "git", "url": dep.git, "rev": rev, "commit": commit})

    if offline:
        raise FetchError(f"offline: git dependency not cached: {dep.git}@{rev}")

    tmp = cache_dir / (checkout_dir.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)

    subprocess.run(["git", "clone", "--quiet", dep.git, str(tmp)], check=True)
    if dep.rev:
        subprocess.run(["git", "-C", str(tmp), "checkout", "--quiet", dep.rev], check=True)

    tmp.replace(checkout_dir)
    # Capture resolved commit.
    cp = subprocess.run(
        ["git", "-C", str(checkout_dir), "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    commit = cp.stdout.strip()
    return FetchedTree(path=checkout_dir, resolved={"type": "git", "url": dep.git, "rev": rev, "commit": commit})
