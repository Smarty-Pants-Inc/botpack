from __future__ import annotations

from pathlib import Path

from .config import parse_agentpkg_toml, parse_botyard_toml_file
from .fetch import fetch_git, fetch_path
from .lock import Lockfile, Package, package_key, save_lock
from .models import GitDependency, PathDependency, SemverDependency, UrlDependency
from .paths import botyard_dir, work_root
from .store import store_put_tree
from .trust import check_package_trust


def default_lock_path() -> Path:
    root = work_root()
    new = root / "botpack.lock"
    old = root / "botyard.lock"
    return new if new.exists() or not old.exists() else old


def install(
    *,
    manifest_path: Path | None = None,
    lock_path: Path | None = None,
    offline: bool = False,
) -> Path:
    cfg = parse_botyard_toml_file(manifest_path)
    root = Path.cwd() if manifest_path is None else manifest_path.parent

    cache_dir = botyard_dir() / "cache" / "git"

    packages: dict[str, Package] = {}
    direct_deps: dict[str, str] = {}

    for dep_name, dep in cfg.dependencies.items():
        direct_deps[dep_name] = dep.spec if isinstance(dep, SemverDependency) else "*"

        if isinstance(dep, PathDependency):
            fetched = fetch_path(dep, base_dir=root)
            stored = store_put_tree(fetched.path)
            pkg_manifest = fetched.path / "agentpkg.toml"
            pkg_cfg = parse_agentpkg_toml(pkg_manifest)
            key = package_key(pkg_cfg.name, pkg_cfg.version)

            decision = check_package_trust(
                pkg_key=key,
                integrity=stored.digest,
                needs_exec=bool(pkg_cfg.capabilities.exec),
                needs_mcp=bool(pkg_cfg.capabilities.mcp),
            )
            if not decision.ok:
                raise PermissionError(decision.reason or f"{key}: not trusted")

            packages[key] = Package(
                source={"type": "path", "path": str(dep.path)},
                resolved=fetched.resolved,
                integrity=stored.digest,
                dependencies={},
                capabilities={
                    "exec": bool(pkg_cfg.capabilities.exec),
                    "network": bool(pkg_cfg.capabilities.network),
                    "mcp": bool(pkg_cfg.capabilities.mcp),
                },
            )
            continue

        if isinstance(dep, GitDependency):
            fetched = fetch_git(dep, cache_dir=cache_dir, offline=offline)
            stored = store_put_tree(fetched.path)
            pkg_manifest = fetched.path / "agentpkg.toml"
            pkg_cfg = parse_agentpkg_toml(pkg_manifest)
            key = package_key(pkg_cfg.name, pkg_cfg.version)

            decision = check_package_trust(
                pkg_key=key,
                integrity=stored.digest,
                needs_exec=bool(pkg_cfg.capabilities.exec),
                needs_mcp=bool(pkg_cfg.capabilities.mcp),
            )
            if not decision.ok:
                raise PermissionError(decision.reason or f"{key}: not trusted")

            packages[key] = Package(
                source={"type": "git", "url": dep.git, "rev": dep.rev},
                resolved=fetched.resolved,
                integrity=stored.digest,
                dependencies={},
                capabilities={
                    "exec": bool(pkg_cfg.capabilities.exec),
                    "network": bool(pkg_cfg.capabilities.network),
                    "mcp": bool(pkg_cfg.capabilities.mcp),
                },
            )
            continue

        if isinstance(dep, (SemverDependency, UrlDependency)):
            raise NotImplementedError("registry/url dependencies not implemented in v0.1")

        raise AssertionError(f"unknown dependency type: {dep!r}")

    lf = Lockfile(
        lockfileVersion=1,
        botpackVersion="0.1.0",
        specVersion="0.1",
        dependencies=direct_deps,
        packages=packages,
    )

    out = lock_path or default_lock_path()
    save_lock(out, lf)
    return out
