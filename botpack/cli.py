from __future__ import annotations

import argparse
from pathlib import Path

from .catalog import generate_and_write_catalog
from .errors import BotyardConfigError
from .fetch import FetchError
from .lock import LockfileError
from .sync import sync


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="botpack")
    sub = p.add_subparsers(dest="cmd", required=True)

    mig = sub.add_parser("migrate", help="Migrate legacy workspace layouts")
    mig_sub = mig.add_subparsers(dest="migrate_cmd", required=True)
    mig_smarty = mig_sub.add_parser("from-smarty", help="Copy .smarty into .botpack/workspace")
    mig_smarty.add_argument("--root", type=Path, default=None)
    mig_smarty.add_argument("--force", action="store_true")

    add = sub.add_parser("add", help="Add a dependency to botpack.toml")
    add.add_argument("name")
    add.add_argument("--manifest", type=Path, default=None)
    src = add.add_mutually_exclusive_group(required=True)
    src.add_argument("--path", dest="dep_path")
    src.add_argument("--git", dest="git_url")
    add.add_argument("--rev", default=None)

    rem = sub.add_parser("remove", help="Remove a dependency from botpack.toml")
    rem.add_argument("name")
    rem.add_argument("--manifest", type=Path, default=None)

    cat = sub.add_parser("catalog", help="Generate .botpack/catalog.json")
    cat.add_argument("--manifest", type=Path, default=None)

    s = sub.add_parser("sync", help="Materialize workspace assets into a target runtime")
    s.add_argument("--target", default="claude")
    s.add_argument("--manifest", type=Path, default=None)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--clean", action="store_true")
    s.add_argument("--force", action="store_true")

    d = sub.add_parser("doctor", help="Basic environment checks")
    d.add_argument("--manifest", type=Path, default=None)

    ins = sub.add_parser("install", help="Resolve + fetch dependencies and write botpack.lock")
    ins.add_argument("--manifest", type=Path, default=None)
    ins.add_argument("--lockfile", type=Path, default=None)
    ins.add_argument("--offline", action="store_true")

    upd = sub.add_parser("update", help="Alias for install (refresh botpack.lock)")
    upd.add_argument("--manifest", type=Path, default=None)
    upd.add_argument("--lockfile", type=Path, default=None)
    upd.add_argument("--offline", action="store_true")

    pre = sub.add_parser("prefetch", help="Fetch deps into cache/store and write/update lockfile")
    pre.add_argument("--manifest", type=Path, default=None)
    pre.add_argument("--lockfile", type=Path, default=None)
    pre.add_argument("--offline", action="store_true")

    audit = sub.add_parser("audit", help="List lockfile packages requiring trust that are not trusted")
    audit.add_argument("--lockfile", type=Path, default=None)

    trust = sub.add_parser("trust", help="Manage trust decisions")
    trust_sub = trust.add_subparsers(dest="trust_cmd", required=True)
    allow = trust_sub.add_parser("allow", help="Allow capabilities for a package")
    allow.add_argument("pkg")
    allow.add_argument("--exec", dest="allow_exec", action="store_true")
    allow.add_argument("--mcp", dest="allow_mcp", action="store_true")
    allow.add_argument("--integrity", default=None)
    revoke = trust_sub.add_parser("revoke", help="Revoke trust for a package")
    revoke.add_argument("pkg")

    ls = sub.add_parser("list", help="List workspace assets and installed packages")
    ls.add_argument("--manifest", type=Path, default=None)
    ls.add_argument("--lockfile", type=Path, default=None)

    info = sub.add_parser("info", help="Show workspace + lockfile summary")
    info.add_argument("--manifest", type=Path, default=None)
    info.add_argument("--lockfile", type=Path, default=None)

    tree = sub.add_parser("tree", help="Show dependency + install tree")
    tree.add_argument("--manifest", type=Path, default=None)
    tree.add_argument("--lockfile", type=Path, default=None)

    why = sub.add_parser("why", help="Explain why a package is present")
    why.add_argument("pkg")
    why.add_argument("--manifest", type=Path, default=None)
    why.add_argument("--lockfile", type=Path, default=None)

    v = sub.add_parser("verify", help="Verify lockfile entries against the content-addressed store")
    v.add_argument("--lockfile", type=Path, required=True)

    pr = sub.add_parser("prune", help="Delete unreferenced store entries")
    pr.add_argument("--lockfile", type=Path, required=True)
    pr.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        return _run(args)
    except BotyardConfigError as e:
        print(f"error: {e}")
        return 2
    except LockfileError as e:
        print(f"error: {e}")
        return 2
    except PermissionError as e:
        print(f"error: {e}")
        return 6
    except FetchError as e:
        print(f"error: {e}")
        return 4
    except Exception as e:  # pragma: no cover
        print(f"error: {e}")
        return 1


def _run(args: argparse.Namespace) -> int:

    if args.cmd == "migrate":
        if args.migrate_cmd == "from-smarty":
            from .migrate import migrate_from_smarty
            from .paths import work_root

            root = (args.root or work_root()).resolve()
            try:
                migrate_from_smarty(root=root, force=bool(args.force))
            except FileNotFoundError as e:
                print(f"error: legacy workspace not found: {e}")
                return 1
            return 0

        raise AssertionError(f"unhandled migrate cmd: {args.migrate_cmd}")

    if args.cmd == "add":
        from .config import botyard_manifest_path
        from .manifest_edit import add_git_dependency, add_path_dependency

        manifest = args.manifest or botyard_manifest_path()
        if args.dep_path:
            add_path_dependency(manifest, name=str(args.name), dep_path=str(args.dep_path))
        elif args.git_url:
            add_git_dependency(manifest, name=str(args.name), url=str(args.git_url), rev=args.rev)
        else:  # pragma: no cover (argparse enforces)
            raise ValueError("add requires --path or --git")
        return 0

    if args.cmd == "remove":
        from .config import botyard_manifest_path
        from .manifest_edit import remove_dependency

        manifest = args.manifest or botyard_manifest_path()
        remove_dependency(manifest, name=str(args.name))
        return 0

    if args.cmd == "catalog":
        generate_and_write_catalog(manifest_path=args.manifest)
        return 0

    if args.cmd == "sync":
        res = sync(
            target=str(args.target),
            manifest_path=args.manifest,
            dry_run=bool(args.dry_run),
            clean=bool(args.clean),
            force=bool(args.force),
        )
        # For now, treat conflicts as a non-zero exit.
        return 2 if res.conflicts else 0

    if args.cmd == "doctor":
        from .doctor import run_doctor

        res = run_doctor(manifest_path=args.manifest)
        for w in res.warnings:
            print(f"warning: {w}")
        return 0 if res.ok else 1

    if args.cmd == "install":
        from .install import install

        install(manifest_path=args.manifest, lock_path=args.lockfile, offline=bool(args.offline))
        return 0

    if args.cmd == "update":
        from .install import install

        install(manifest_path=args.manifest, lock_path=args.lockfile, offline=bool(args.offline))
        return 0

    if args.cmd == "prefetch":
        from .prefetch import prefetch

        prefetch(manifest_path=args.manifest, lock_path=args.lockfile, offline=bool(args.offline))
        return 0

    if args.cmd == "audit":
        from .install import default_lock_path
        from .lock import load_lock
        from .trust import check_package_trust

        lock_path = args.lockfile or default_lock_path()
        lf = load_lock(lock_path)

        problems: list[str] = []
        for pkg_key in sorted(lf.packages.keys()):
            pkg = lf.packages[pkg_key]
            needs_exec = bool(pkg.capabilities.get("exec"))
            needs_mcp = bool(pkg.capabilities.get("mcp"))
            if not (needs_exec or needs_mcp):
                continue
            decision = check_package_trust(
                pkg_key=pkg_key,
                integrity=pkg.integrity,
                needs_exec=needs_exec,
                needs_mcp=needs_mcp,
            )
            if not decision.ok:
                problems.append(decision.reason or f"{pkg_key}: not trusted")

        for r in problems:
            print(r)

        return 0 if not problems else 6

    if args.cmd == "trust":
        from .config import trust_path
        from .trust_edit import trust_allow, trust_revoke

        p = trust_path()
        if args.trust_cmd == "allow":
            if not (bool(args.allow_exec) or bool(args.allow_mcp) or args.integrity):
                raise ValueError("trust allow: must specify at least one of --exec, --mcp, --integrity")
            trust_allow(
                p,
                pkg_key=str(args.pkg),
                allow_exec=True if args.allow_exec else None,
                allow_mcp=True if args.allow_mcp else None,
                integrity=args.integrity,
            )
            return 0
        if args.trust_cmd == "revoke":
            trust_revoke(p, pkg_key=str(args.pkg))
            return 0
        raise AssertionError(f"unhandled trust cmd: {args.trust_cmd}")

    if args.cmd == "list":
        from .introspect import build_list_output

        print(build_list_output(manifest_path=args.manifest, lock_path=args.lockfile), end="")
        return 0

    if args.cmd == "info":
        from .introspect import build_info_output

        print(build_info_output(manifest_path=args.manifest, lock_path=args.lockfile), end="")
        return 0

    if args.cmd == "tree":
        from .introspect import build_tree_output

        print(build_tree_output(manifest_path=args.manifest, lock_path=args.lockfile), end="")
        return 0

    if args.cmd == "why":
        from .introspect import build_why_output

        print(
            build_why_output(pkg=str(args.pkg), manifest_path=args.manifest, lock_path=args.lockfile),
            end="",
        )
        return 0

    if args.cmd == "verify":
        from .verify import verify_lockfile

        res = verify_lockfile(lock_path=args.lockfile)
        for e in res.errors:
            print(f"error: {e}")
        return 0 if res.ok else 1

    if args.cmd == "prune":
        from .prune import prune_store

        res = prune_store(lock_path=args.lockfile, dry_run=bool(args.dry_run))
        for r in res.removed:
            print(r)
        return 0

    raise AssertionError(f"unhandled cmd: {args.cmd}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
