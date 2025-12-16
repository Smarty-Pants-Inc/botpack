from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

from .models import GitDependency
from .resolver import pick_highest_satisfying


DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/Smarty-Pants-Inc/botpack-registry/main"


@dataclass(frozen=True)
class RegistryResolution:
    name: str
    spec: str
    version: str
    git: str
    commit: str

    def as_git_dependency(self) -> GitDependency:
        # Pin to an immutable commit for deterministic installs.
        return GitDependency(git=self.git, rev=self.commit)


def registry_base_url() -> str:
    return os.environ.get("BOTPACK_REGISTRY_URL", DEFAULT_REGISTRY_URL).rstrip("/")


def _join_url(base: str, *parts: str) -> str:
    b = base.rstrip("/")
    segs: list[str] = []
    for p in parts:
        for seg in str(p).split("/"):
            if not seg or seg == ".":
                continue
            # Keep @ unescaped so scoped packages stay readable on disk/URLs.
            segs.append(quote(seg, safe="@-._~"))
    if not segs:
        return b
    return b + "/" + "/".join(segs)


def versions_index_url(pkg_name: str, *, base_url: str | None = None) -> str:
    base = (base_url or registry_base_url()).rstrip("/")
    return _join_url(base, pkg_name, "versions.json")


def _fetch_json(url: str, *, timeout_s: float = 10.0) -> Any:
    with urlopen(url, timeout=timeout_s) as resp:  # nosec - registry URL is user-configured
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def _expect_str(v: Any, *, ctx: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"registry: {ctx} must be a non-empty string")
    return v


def resolve_semver_dependency(
    *,
    name: str,
    spec: str,
    base_url: str | None = None,
) -> RegistryResolution:
    """Resolve a Semver dependency `name@spec` via a static registry index.

    Fetches `<base>/<name>/versions.json` and selects the highest version that
    satisfies `spec`, then returns a git dependency pinned to an immutable commit.

    Expected `versions.json` shape (minimal):

    ```json
    {
      "versions": {
        "1.2.3": {"git": "https://...", "commit": "<sha>"}
      }
    }
    ```
    """

    url = versions_index_url(name, base_url=base_url)
    data = _fetch_json(url)
    if not isinstance(data, dict):
        raise ValueError(f"registry: invalid index JSON at {url} (expected object)")

    versions_raw = data.get("versions")
    if not isinstance(versions_raw, dict):
        raise ValueError(f"registry: invalid index JSON at {url} (expected versions object)")

    available = [str(v) for v in versions_raw.keys()]
    chosen = pick_highest_satisfying(available, spec)
    if chosen is None:
        raise ValueError(f"registry: no version for {name!r} satisfies {spec!r}")

    entry = versions_raw.get(chosen)
    if not isinstance(entry, dict):
        raise ValueError(f"registry: invalid entry for {name}@{chosen} (expected object)")

    git = _expect_str(entry.get("git"), ctx=f"versions[{chosen}].git")
    commit = entry.get("commit") or entry.get("rev")
    commit = _expect_str(commit, ctx=f"versions[{chosen}].commit")

    return RegistryResolution(name=name, spec=spec, version=chosen, git=git, commit=commit)
