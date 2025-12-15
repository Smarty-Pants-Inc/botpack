from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MigrateResult:
    created: list[str]
    updated: list[str]
    skipped_newer: list[str]
    skipped_same: list[str]


def _is_ignorable_path(p: Path) -> bool:
    parts = p.parts
    return "__pycache__" in parts or ".pytest_cache" in parts


def _files_equal(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return a.read_bytes() == b.read_bytes()
    except FileNotFoundError:
        return False


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_bytes(src.read_bytes())
    tmp.replace(dst)


def _copy_tree(
    *,
    src_root: Path,
    dst_root: Path,
    force: bool,
    created: list[str],
    updated: list[str],
    skipped_newer: list[str],
    skipped_same: list[str],
) -> None:
    if not src_root.exists():
        return

    for src in sorted(src_root.rglob("*")):
        if src.is_dir():
            continue
        if _is_ignorable_path(src):
            continue

        rel = src.relative_to(src_root)
        dst = dst_root / rel

        if dst.exists():
            if _files_equal(src, dst):
                skipped_same.append(str(dst))
                continue

            if not force:
                try:
                    if dst.stat().st_mtime > src.stat().st_mtime:
                        skipped_newer.append(str(dst))
                        continue
                except OSError:
                    # If we can't stat, be conservative and skip unless forced.
                    skipped_newer.append(str(dst))
                    continue

            _atomic_copy(src, dst)
            updated.append(str(dst))
            continue

        _atomic_copy(src, dst)
        created.append(str(dst))


def migrate_from_smarty(*, root: Path, force: bool = False) -> MigrateResult:
    """Copy/mirror legacy `.smarty/` assets into `.botpack/workspace/`.

    Mapping rules:
      - .smarty/skills/**   -> .botpack/workspace/skills/**
      - .smarty/commands/** -> .botpack/workspace/commands/**
      - .smarty/agents/**   -> .botpack/workspace/agents/**
      - .smarty/config/mcp.json (if present) -> .botpack/workspace/config/mcp.json

    Idempotent: identical files are not rewritten.
    Safety: destination files newer than source are not overwritten unless `force=True`.
    """

    smarty = root / ".smarty"
    if not smarty.exists():
        raise FileNotFoundError(str(smarty))

    ws = root / ".botpack" / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    updated: list[str] = []
    skipped_newer: list[str] = []
    skipped_same: list[str] = []

    _copy_tree(
        src_root=smarty / "skills",
        dst_root=ws / "skills",
        force=force,
        created=created,
        updated=updated,
        skipped_newer=skipped_newer,
        skipped_same=skipped_same,
    )
    _copy_tree(
        src_root=smarty / "commands",
        dst_root=ws / "commands",
        force=force,
        created=created,
        updated=updated,
        skipped_newer=skipped_newer,
        skipped_same=skipped_same,
    )
    _copy_tree(
        src_root=smarty / "agents",
        dst_root=ws / "agents",
        force=force,
        created=created,
        updated=updated,
        skipped_newer=skipped_newer,
        skipped_same=skipped_same,
    )

    mcp_src = smarty / "config" / "mcp.json"
    if mcp_src.exists() and mcp_src.is_file() and not _is_ignorable_path(mcp_src):
        mcp_dst = ws / "config" / "mcp.json"
        if mcp_dst.exists():
            if _files_equal(mcp_src, mcp_dst):
                skipped_same.append(str(mcp_dst))
            elif not force and mcp_dst.stat().st_mtime > mcp_src.stat().st_mtime:
                skipped_newer.append(str(mcp_dst))
            else:
                _atomic_copy(mcp_src, mcp_dst)
                updated.append(str(mcp_dst))
        else:
            _atomic_copy(mcp_src, mcp_dst)
            created.append(str(mcp_dst))

    # Ensure deterministic ordering in reports.
    created.sort()
    updated.sort()
    skipped_newer.sort()
    skipped_same.sort()

    return MigrateResult(
        created=created,
        updated=updated,
        skipped_newer=skipped_newer,
        skipped_same=skipped_same,
    )
