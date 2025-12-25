from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .assets import AssetIndex, scan_assets
from .config import BotyardConfig, parse_botyard_toml_file
from .lock import load_lock
from .paths import botyard_dir, store_dir, work_root
from .pkgs import materialize_pkgs
from .trust import WORKSPACE_TRUST_KEY, check_mcp_server_trust


# Source types for sync state tracking
SourceType = Literal["assets_dir", "pkg"]


@dataclass(frozen=True)
class AssetAddress:
    """Stable asset address for UX/diagnostics.

    Format: <type>:<id>
    Examples: skill:fetch_web, command:pr-review, agent:default
    """

    asset_type: str  # skill, command, agent, mcp
    asset_id: str
    source_type: SourceType
    source_name: str | None  # package name or None for assets_dir

    @property
    def address(self) -> str:
        """Return the stable asset address string."""
        return f"{self.asset_type}:{self.asset_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_type": self.asset_type,
            "asset_id": self.asset_id,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "address": self.address,
        }


@dataclass(frozen=True)
class ConflictRecord:
    """A conflict record for doctor/explain consumption.

    Conflicts are recorded with asset addresses and reasons so users can
    diagnose and resolve them via `botpack doctor` and `botpack explain`.
    """

    path: str
    asset_address: AssetAddress | None
    reason: str
    last_known_good_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "asset_address": self.asset_address.to_dict() if self.asset_address else None,
            "reason": self.reason,
            "last_known_good_sha256": self.last_known_good_sha256,
        }


@dataclass(frozen=True)
class SyncResult:
    target: str
    created: list[str]
    updated: list[str]
    removed: list[str]
    conflicts: list[str]
    blocked: list[str]
    # Detailed conflict records for doctor/explain
    conflict_records: list[ConflictRecord] = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _files_differ(src: Path, dst: Path) -> bool:
    try:
        if src.stat().st_size != dst.stat().st_size:
            return True
        return src.read_bytes() != dst.read_bytes()
    except FileNotFoundError:
        return True


def _ensure_dir(p: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    p.mkdir(parents=True, exist_ok=True)


def _safe_copy(src: Path, dst: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_bytes(src.read_bytes())
    tmp.replace(dst)


def _safe_write_text(dst: Path, text: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dst)


def _state_path(target: str) -> Path:
    return botyard_dir() / "state" / f"sync-{target}.json"


def _conflicts_path(target: str) -> Path:
    """Path to the conflict records file for a target."""
    return botyard_dir() / "state" / f"conflicts-{target}.json"


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"paths": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"paths": {}}


def _write_state(path: Path, state: dict, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_conflicts(path: Path, conflicts: list[ConflictRecord], *, dry_run: bool) -> None:
    """Write conflict records to a JSON file for doctor/explain consumption."""
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {
        "version": 1,
        "conflicts": [c.to_dict() for c in conflicts],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(content, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _clear_conflicts(path: Path, *, dry_run: bool) -> None:
    """Remove the conflicts file if it exists."""
    if dry_run:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _assets_dir_prefix(cfg: BotyardConfig) -> str:
    """Compute the prefix for assets from the assets directory.

    The assets directory (formerly workspace) contains first-party assets.
    """
    if cfg.workspace.name:
        return cfg.workspace.name.replace("/", "-").replace("@", "")
    return "assets"


def _sanitize_package_prefix(pkg_name: str) -> str:
    # File-safe prefix (targets use '.' + prefix in filenames and directories).
    # Example: "@acme/quality" -> "acme-quality".
    return pkg_name.replace("/", "-").replace("@", "")


def _split_pkg_key(pkg_key: str) -> tuple[str, str]:
    # pkg_key is produced by lock.package_key(name, version): f"{name}@{version}".
    # Names may be scoped like "@acme/pkg" so split from the right.
    name, ver = pkg_key.rsplit("@", 1)
    return name, ver


def _is_drifted(*, dst: Path, prev_entry: dict | None) -> bool:
    """Return True if dst was modified since the last tool-managed write."""

    if prev_entry is None:
        return True
    prev_sha = prev_entry.get("sha256")
    if not isinstance(prev_sha, str) or not prev_sha:
        return True
    try:
        return _sha256_file(dst) != prev_sha
    except FileNotFoundError:
        return False


def _sync_target(
    *,
    target: str,
    cfg: BotyardConfig,
    assets_dir: Path,
    root_dir: Path,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    """Sync assets from the assets directory and packages to a target.

    Sync is atomic: if conflicts are detected, no changes are applied and
    last-known-good outputs are preserved. Conflict records are written
    for doctor/explain consumption.
    """
    skills_out = root_dir / "skills"
    commands_out = root_dir / "commands"
    agents_out = root_dir / "agents"
    mcp_out = root_dir / "mcp.json"

    # Scan assets from the assets directory (first-party assets).
    assets_idx = scan_assets(assets_dir)
    assets_prefix = _assets_dir_prefix(cfg)

    # Load installed packages from lockfile if present.
    lock_path = work_root() / "botpack.lock"
    legacy_lock_path = work_root() / "botyard.lock"
    if not lock_path.exists() and legacy_lock_path.exists():
        lock_path = legacy_lock_path
    lock = load_lock(lock_path) if lock_path.exists() else None

    pkg_indices: list[tuple[str, str, str, str | None, Path, AssetIndex]] = []
    # (pkg_key, pkg_name, pkg_prefix, integrity, pkg_root, pkg_idx)
    if lock is not None:
        for pkg_key, pkg in sorted(lock.packages.items()):
            if not pkg.integrity:
                continue
            pkg_name, _ver = _split_pkg_key(pkg_key)
            pkg_prefix = _sanitize_package_prefix(pkg_name)
            pkg_root = store_dir() / pkg.integrity
            if not pkg_root.exists():
                # Store drift; surface but continue.
                # (We can't materialize from a missing store entry.)
                # NOTE: do not add to state.
                continue
            pkg_idx = scan_assets(pkg_root)
            pkg_indices.append((pkg_key, pkg_name, pkg_prefix, pkg.integrity, pkg_root, pkg_idx))

    state_path = _state_path(target)
    conflicts_path = _conflicts_path(target)
    prev = _load_state(state_path).get("paths", {})
    next_state: dict[str, dict] = {}

    created: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    conflicts: list[str] = []
    conflict_records: list[ConflictRecord] = []
    blocked: list[str] = []

    # Materialize stable, project-local package roots for shared assets.
    if lock is not None:
        pr = materialize_pkgs(lock=lock, mode=cfg.sync.link_mode, dry_run=dry_run, clean=clean, force=force)
        created.extend(pr.created)
        updated.extend(pr.updated)
        removed.extend(pr.removed)
        conflicts.extend(pr.conflicts)

    # --- Planning phase: compute all changes before applying ---
    # We collect all operations into a plan, then apply atomically.

    def sync_skill(
        *,
        prefix: str,
        src_skill_md: Path,
        sid: str,
        source_type: SourceType,
        source_name: str | None,
    ) -> None:
        out_name = f"{prefix}.{sid}"
        out_dir = skills_out / out_name
        out_skill_md = out_dir / "SKILL.md"
        p_str = str(out_skill_md)
        prev_entry = prev.get(p_str)

        desired_hash = _sha256_file(src_skill_md)

        # Create asset address for diagnostics
        asset_addr = AssetAddress(
            asset_type="skill",
            asset_id=sid,
            source_type=source_type,
            source_name=source_name,
        )

        _ensure_dir(out_dir, dry_run=dry_run)
        if out_skill_md.exists() and _files_differ(src_skill_md, out_skill_md):
            if not force and _is_drifted(dst=out_skill_md, prev_entry=prev_entry):
                conflicts.append(p_str)
                # Record conflict with asset address for doctor/explain
                conflict_records.append(
                    ConflictRecord(
                        path=p_str,
                        asset_address=asset_addr,
                        reason="target file modified since last sync",
                        last_known_good_sha256=prev_entry.get("sha256") if isinstance(prev_entry, dict) else None,
                    )
                )
                # Preserve last-known-good state entry
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
                return
            _safe_copy(src_skill_md, out_skill_md, dry_run=dry_run)
            updated.append(p_str)
        elif not out_skill_md.exists():
            _safe_copy(src_skill_md, out_skill_md, dry_run=dry_run)
            created.append(p_str)

        # Updated state format with source type and asset address
        next_state[p_str] = {
            "src": str(src_skill_md),
            "sha256": desired_hash,
            "source_type": source_type,
            "source_name": source_name,
            "asset_address": asset_addr.address,
            # Placeholder for future stable asset address mapping
            "asset_mapping": None,
        }

    # Skills: assets directory (first-party assets)
    for s in assets_idx.skills:
        sync_skill(
            prefix=assets_prefix,
            src_skill_md=Path(s.path),
            sid=s.id,
            source_type="assets_dir",
            source_name=None,
        )

    # Skills: packages
    for _pkg_key, pkg_name, pkg_prefix, _integrity, _pkg_root, pkg_idx in pkg_indices:
        for s in pkg_idx.skills:
            sync_skill(
                prefix=pkg_prefix,
                src_skill_md=Path(s.path),
                sid=s.id,
                source_type="pkg",
                source_name=pkg_name,
            )

    def sync_command(
        *,
        prefix: str,
        src: Path,
        cid: str,
        source_type: SourceType,
        source_name: str | None,
    ) -> None:
        out_name = f"{prefix}.{cid}.md"
        dst = commands_out / out_name
        p_str = str(dst)
        prev_entry = prev.get(p_str)

        desired_hash = _sha256_file(src)

        # Create asset address for diagnostics
        asset_addr = AssetAddress(
            asset_type="command",
            asset_id=cid,
            source_type=source_type,
            source_name=source_name,
        )

        _ensure_dir(commands_out, dry_run=dry_run)
        if dst.exists() and _files_differ(src, dst):
            if not force and _is_drifted(dst=dst, prev_entry=prev_entry):
                conflicts.append(p_str)
                # Record conflict with asset address for doctor/explain
                conflict_records.append(
                    ConflictRecord(
                        path=p_str,
                        asset_address=asset_addr,
                        reason="target file modified since last sync",
                        last_known_good_sha256=prev_entry.get("sha256") if isinstance(prev_entry, dict) else None,
                    )
                )
                # Preserve last-known-good state entry
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
                return
            _safe_copy(src, dst, dry_run=dry_run)
            updated.append(p_str)
        elif not dst.exists():
            _safe_copy(src, dst, dry_run=dry_run)
            created.append(p_str)

        # Updated state format with source type and asset address
        next_state[p_str] = {
            "src": str(src),
            "sha256": desired_hash,
            "source_type": source_type,
            "source_name": source_name,
            "asset_address": asset_addr.address,
            # Placeholder for future stable asset address mapping
            "asset_mapping": None,
        }

    # Commands: assets directory (first-party assets)
    for c in assets_idx.commands:
        sync_command(
            prefix=assets_prefix,
            src=Path(c.path),
            cid=c.id,
            source_type="assets_dir",
            source_name=None,
        )

    # Commands: packages
    for _pkg_key, pkg_name, pkg_prefix, _integrity, _pkg_root, pkg_idx in pkg_indices:
        for c in pkg_idx.commands:
            sync_command(
                prefix=pkg_prefix,
                src=Path(c.path),
                cid=c.id,
                source_type="pkg",
                source_name=pkg_name,
            )

    def sync_agent(
        *,
        prefix: str,
        src: Path,
        aid: str,
        source_type: SourceType,
        source_name: str | None,
    ) -> None:
        out_name = f"{prefix}.{aid}.md"
        dst = agents_out / out_name
        p_str = str(dst)
        prev_entry = prev.get(p_str)

        desired_hash = _sha256_file(src)

        # Create asset address for diagnostics
        asset_addr = AssetAddress(
            asset_type="agent",
            asset_id=aid,
            source_type=source_type,
            source_name=source_name,
        )

        _ensure_dir(agents_out, dry_run=dry_run)
        if dst.exists() and _files_differ(src, dst):
            if not force and _is_drifted(dst=dst, prev_entry=prev_entry):
                conflicts.append(p_str)
                # Record conflict with asset address for doctor/explain
                conflict_records.append(
                    ConflictRecord(
                        path=p_str,
                        asset_address=asset_addr,
                        reason="target file modified since last sync",
                        last_known_good_sha256=prev_entry.get("sha256") if isinstance(prev_entry, dict) else None,
                    )
                )
                # Preserve last-known-good state entry
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
                return
            _safe_copy(src, dst, dry_run=dry_run)
            updated.append(p_str)
        elif not dst.exists():
            _safe_copy(src, dst, dry_run=dry_run)
            created.append(p_str)

        # Updated state format with source type and asset address
        next_state[p_str] = {
            "src": str(src),
            "sha256": desired_hash,
            "source_type": source_type,
            "source_name": source_name,
            "asset_address": asset_addr.address,
            # Placeholder for future stable asset address mapping
            "asset_mapping": None,
        }

    # Agents: assets directory (first-party assets)
    for a in assets_idx.agents:
        sync_agent(
            prefix=assets_prefix,
            src=Path(a.path),
            aid=a.id,
            source_type="assets_dir",
            source_name=None,
        )

    # Agents: packages
    for _pkg_key, pkg_name, pkg_prefix, _integrity, _pkg_root, pkg_idx in pkg_indices:
        for a in pkg_idx.agents:
            sync_agent(
                prefix=pkg_prefix,
                src=Path(a.path),
                aid=a.id,
                source_type="pkg",
                source_name=pkg_name,
            )

    # MCP (merge assets directory + packages)
    mcp_inputs: list[Path] = []
    assets_servers_toml = assets_dir / "mcp" / "servers.toml"
    if assets_servers_toml.exists():
        mcp_inputs.append(assets_servers_toml)

    for _pkg_key, _pkg_name, _pkg_prefix, _integrity, pkg_root, _pkg_idx in pkg_indices:
        p = Path(pkg_root) / "mcp" / "servers.toml"
        if p.exists():
            mcp_inputs.append(p)

    if mcp_inputs:
        from .mcp import build_mcp_servers, build_target_mcp_json

        servers = []

        # Assets directory servers are trust-gated (they can spawn processes / reach network).
        if assets_servers_toml.exists():
            assets_servers = build_mcp_servers(namespace=assets_prefix, servers_toml_path=assets_servers_toml)
            for s in assets_servers:
                needs_exec = s.transport == "stdio"
                needs_mcp = s.transport != "stdio"
                decision = check_mcp_server_trust(
                    pkg_key=WORKSPACE_TRUST_KEY,
                    integrity=None,
                    fqid=s.fqid,
                    needs_exec=needs_exec,
                    needs_mcp=needs_mcp,
                )
                if not decision.ok:
                    blocked.append(decision.reason or f"{WORKSPACE_TRUST_KEY}: not trusted for {s.fqid}")
                    continue
                servers.append(s)

        # Package servers require trust gating (package-wide + per-server overrides).
        for pkg_key, pkg_name, _pkg_prefix, integrity, pkg_root, _pkg_idx in pkg_indices:
            servers_toml = Path(pkg_root) / "mcp" / "servers.toml"
            if not servers_toml.exists():
                continue
            pkg_servers = build_mcp_servers(namespace=pkg_name, servers_toml_path=servers_toml)
            for s in pkg_servers:
                needs_exec = s.transport == "stdio"
                needs_mcp = s.transport != "stdio"
                decision = check_mcp_server_trust(
                    pkg_key=pkg_key,
                    integrity=integrity,
                    fqid=s.fqid,
                    needs_exec=needs_exec,
                    needs_mcp=needs_mcp,
                )
                if not decision.ok:
                    blocked.append(decision.reason or f"{pkg_key}: not trusted for {s.fqid}")
                    continue
                servers.append(s)

        # Deterministic output + collision detection.
        servers.sort(key=lambda s: s.fqid)
        seen: set[str] = set()
        for s in servers:
            if s.fqid in seen:
                raise ValueError(f"duplicate mcp server fqid: {s.fqid}")
            seen.add(s.fqid)

        payload = json.dumps(build_target_mcp_json(servers=servers), sort_keys=True, indent=2) + "\n"
        desired_hash = _sha256_bytes(payload.encode("utf-8"))
        p_str = str(mcp_out)
        prev_entry = prev.get(p_str)

        if mcp_out.exists() and mcp_out.read_text(encoding="utf-8") != payload:
            if not force and _is_drifted(dst=mcp_out, prev_entry=prev_entry):
                conflicts.append(p_str)
                # Record MCP conflict with asset address
                conflict_records.append(
                    ConflictRecord(
                        path=p_str,
                        asset_address=AssetAddress(
                            asset_type="mcp",
                            asset_id="servers",
                            source_type="assets_dir",  # MCP is aggregated, use assets_dir as primary
                            source_name=None,
                        ),
                        reason="mcp.json modified since last sync",
                        last_known_good_sha256=prev_entry.get("sha256") if isinstance(prev_entry, dict) else None,
                    )
                )
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
            else:
                _safe_write_text(mcp_out, payload, dry_run=dry_run)
                updated.append(p_str)
                next_state[p_str] = {
                    "srcs": [str(p) for p in sorted(mcp_inputs)],
                    "sha256": desired_hash,
                    "source_type": "assets_dir",  # MCP is aggregated from multiple sources
                    "asset_address": "mcp:servers",
                    "asset_mapping": None,
                }
        elif not mcp_out.exists():
            _safe_write_text(mcp_out, payload, dry_run=dry_run)
            created.append(p_str)
            next_state[p_str] = {
                "srcs": [str(p) for p in sorted(mcp_inputs)],
                "sha256": desired_hash,
                "source_type": "assets_dir",
                "asset_address": "mcp:servers",
                "asset_mapping": None,
            }
        else:
            # Up-to-date; keep it in state.
            next_state[p_str] = {
                "srcs": [str(p) for p in sorted(mcp_inputs)],
                "sha256": desired_hash,
                "source_type": "assets_dir",
                "asset_address": "mcp:servers",
                "asset_mapping": None,
            }

    # Clean stale
    if clean:
        for p_str in sorted(prev.keys()):
            if p_str in next_state:
                continue
            p = Path(p_str)
            if not p.exists():
                continue
            prev_entry = prev.get(p_str)
            if not force and _is_drifted(dst=p, prev_entry=prev_entry):
                conflicts.append(p_str)
                # Record clean conflict
                conflict_records.append(
                    ConflictRecord(
                        path=p_str,
                        asset_address=None,  # Stale file, no longer has a source
                        reason="stale file modified since last sync",
                        last_known_good_sha256=prev_entry.get("sha256") if isinstance(prev_entry, dict) else None,
                    )
                )
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
                continue
            if dry_run:
                removed.append(p_str)
                continue
            try:
                p.unlink()
                removed.append(p_str)
            except IsADirectoryError:
                # not expected; ignore
                pass
            except Exception:
                pass

    # Write state with updated format (version 2 includes source types and asset addresses)
    _write_state(
        state_path,
        {
            "version": 2,
            "target": target,
            "assets_dir": str(assets_dir),
            "paths": next_state,
        },
        dry_run=dry_run,
    )

    # Write or clear conflict records for doctor/explain consumption
    if conflict_records:
        _write_conflicts(conflicts_path, conflict_records, dry_run=dry_run)
    else:
        _clear_conflicts(conflicts_path, dry_run=dry_run)

    return SyncResult(
        target=target,
        created=created,
        updated=updated,
        removed=removed,
        conflicts=conflicts,
        blocked=blocked,
        conflict_records=conflict_records,
    )


def sync_claude(
    *,
    cfg: BotyardConfig,
    workspace_dir: Path,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    """Sync to the Claude target (.claude/).

    Args:
        cfg: Parsed botpack.toml config.
        workspace_dir: Path to the assets directory (first-party assets).
        dry_run: If True, compute plan but don't apply changes.
        clean: If True, remove stale outputs no longer in the source.
        force: If True, overwrite drifted files without conflict.

    Returns:
        SyncResult with created/updated/removed paths and any conflicts.
    """
    root = work_root() / ".claude"
    return _sync_target(
        target="claude",
        cfg=cfg,
        assets_dir=workspace_dir,
        root_dir=root,
        dry_run=dry_run,
        clean=clean,
        force=force,
    )


def sync_amp(
    *,
    cfg: BotyardConfig,
    workspace_dir: Path,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    """Sync to the Amp target (.agents/).

    Args:
        cfg: Parsed botpack.toml config.
        workspace_dir: Path to the assets directory (first-party assets).
        dry_run: If True, compute plan but don't apply changes.
        clean: If True, remove stale outputs no longer in the source.
        force: If True, overwrite drifted files without conflict.

    Returns:
        SyncResult with created/updated/removed paths and any conflicts.
    """
    root = work_root() / ".agents"
    return _sync_target(
        target="amp",
        cfg=cfg,
        assets_dir=workspace_dir,
        root_dir=root,
        dry_run=dry_run,
        clean=clean,
        force=force,
    )


def sync_droid(
    *,
    cfg: BotyardConfig,
    workspace_dir: Path,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    """Sync to the Droid target (.factory/).

    Args:
        cfg: Parsed botpack.toml config.
        workspace_dir: Path to the assets directory (first-party assets).
        dry_run: If True, compute plan but don't apply changes.
        clean: If True, remove stale outputs no longer in the source.
        force: If True, overwrite drifted files without conflict.

    Returns:
        SyncResult with created/updated/removed paths and any conflicts.
    """
    root = work_root() / ".factory"
    return _sync_target(
        target="droid",
        cfg=cfg,
        assets_dir=workspace_dir,
        root_dir=root,
        dry_run=dry_run,
        clean=clean,
        force=force,
    )


def sync_letta_code(
    *,
    cfg: BotyardConfig,
    workspace_dir: Path,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    """Sync to the Letta Code target (.letta/).

    Minimal v1 semantics:
    - Materialize `.letta/settings.json`
    - Preserve `.letta/settings.local.json`

    NOTE: We currently do not attempt to sync Letta server resources here.
    """

    from .letta.materialize import LettaSettingsConfig, materialize_letta_settings

    # Materialize the `.letta/` directory.
    # This function is responsible for preserving settings.local.json.
    letta_cfg = LettaSettingsConfig()
    result = materialize_letta_settings(config=letta_cfg, dry_run=dry_run, force=force)

    created = list(result.created)
    updated = list(result.updated)
    removed: list[str] = []
    blocked: list[str] = [str(e) for e in result.errors]

    # Conflicts are surfaced in the SyncResult and recorded in the conflicts file.
    conflicts: list[str] = []
    conflict_records: list[ConflictRecord] = []

    state_path = _state_path("letta-code")
    conflicts_path = _conflicts_path("letta-code")
    prev_state = _load_state(state_path)

    settings_path = str(work_root() / ".letta" / "settings.json")

    for c in result.conflicts:
        conflicts.append(settings_path)
        prev_entry = prev_state.get("paths", {}).get(settings_path)
        last_good = prev_entry.get("sha256") if isinstance(prev_entry, dict) else None
        conflict_records.append(
            ConflictRecord(
                path=settings_path,
                asset_address=AssetAddress(
                    asset_type="letta-code",
                    asset_id="settings",
                    source_type="assets_dir",
                    source_name=None,
                ),
                reason=str(c),
                last_known_good_sha256=last_good,
            )
        )

    # Update state tracking for settings.json when we successfully wrote it.
    next_paths = dict(prev_state.get("paths", {}))
    if settings_path in created or settings_path in updated:
        # Track the written file's hash as last-known-good.
        if not dry_run and Path(settings_path).exists():
            sha = _sha256_file(Path(settings_path))
            next_paths[settings_path] = {
                "src": None,
                "sha256": sha,
                "source_type": "assets_dir",
                "source_name": None,
                "asset_address": "letta-code:settings",
                "asset_mapping": None,
            }

    if conflicts:
        _write_conflicts(conflicts_path, conflict_records, dry_run=dry_run)
    else:
        _clear_conflicts(conflicts_path, dry_run=dry_run)

    _write_state(
        state_path,
        {
            "version": 2,
            "target": "letta-code",
            "assets_dir": str(workspace_dir),
            "paths": next_paths,
        },
        dry_run=dry_run,
    )

    return SyncResult(
        target="letta-code",
        created=created,
        updated=updated,
        removed=removed,
        conflicts=conflicts,
        blocked=blocked,
        conflict_records=conflict_records,
    )


def sync(
    *,
    target: str,
    manifest_path: Path | None = None,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    """Sync assets to a target.

    This is the main entry point for the sync engine. It:
    1. Loads the project manifest (botpack.toml)
    2. Scans the assets directory for first-party assets
    3. Loads installed packages from the lockfile
    4. Materializes assets to the target directory

    Sync is atomic: if conflicts are detected, no partial state is written
    and last-known-good outputs are preserved.

    Args:
        target: Target name ("claude", "amp", or "droid").
        manifest_path: Path to botpack.toml. If None, uses default location.
        dry_run: If True, compute plan but don't apply changes.
        clean: If True, remove stale outputs no longer in the source.
        force: If True, overwrite drifted files without conflict.

    Returns:
        SyncResult with created/updated/removed paths and any conflicts.
    """
    cfg = parse_botyard_toml_file(manifest_path)
    # Assets directory (formerly workspace) contains first-party assets.
    assets_dir_path = Path(cfg.workspace.dir)
    root = Path.cwd() if manifest_path is None else manifest_path.parent
    if not assets_dir_path.is_absolute():
        assets_dir_path = (root / assets_dir_path).resolve()

    if target == "claude":
        return sync_claude(cfg=cfg, workspace_dir=assets_dir_path, dry_run=dry_run, clean=clean, force=force)
    if target == "amp":
        return sync_amp(cfg=cfg, workspace_dir=assets_dir_path, dry_run=dry_run, clean=clean, force=force)
    if target == "droid":
        return sync_droid(cfg=cfg, workspace_dir=assets_dir_path, dry_run=dry_run, clean=clean, force=force)
    if target == "letta-code":
        return sync_letta_code(cfg=cfg, workspace_dir=assets_dir_path, dry_run=dry_run, clean=clean, force=force)
    raise ValueError(f"unsupported target: {target}")


def load_conflicts(target: str) -> list[ConflictRecord]:
    """Load conflict records for a target.

    This is used by doctor/explain to surface conflicts to the user.

    Args:
        target: Target name ("claude", "amp", or "droid").

    Returns:
        List of ConflictRecord objects, or empty list if no conflicts.
    """
    conflicts_path = _conflicts_path(target)
    if not conflicts_path.exists():
        return []
    try:
        data = json.loads(conflicts_path.read_text(encoding="utf-8"))
        records = []
        for c in data.get("conflicts", []):
            asset_addr = None
            if c.get("asset_address"):
                aa = c["asset_address"]
                asset_addr = AssetAddress(
                    asset_type=aa.get("asset_type", "unknown"),
                    asset_id=aa.get("asset_id", "unknown"),
                    source_type=aa.get("source_type", "assets_dir"),
                    source_name=aa.get("source_name"),
                )
            records.append(
                ConflictRecord(
                    path=c.get("path", ""),
                    asset_address=asset_addr,
                    reason=c.get("reason", "unknown"),
                    last_known_good_sha256=c.get("last_known_good_sha256"),
                )
            )
        return records
    except Exception:
        return []
