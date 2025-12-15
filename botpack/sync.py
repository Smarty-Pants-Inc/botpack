from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .assets import AssetIndex, scan_assets
from .config import BotyardConfig, parse_botyard_toml_file
from .lock import load_lock
from .paths import botyard_dir, store_dir, work_root
from .trust import WORKSPACE_TRUST_KEY, check_mcp_server_trust


@dataclass(frozen=True)
class SyncResult:
    target: str
    created: list[str]
    updated: list[str]
    removed: list[str]
    conflicts: list[str]
    blocked: list[str]


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


def _workspace_prefix(cfg: BotyardConfig) -> str:
    if cfg.workspace.name:
        return cfg.workspace.name.replace("/", "-").replace("@", "")
    return "workspace"


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
    workspace_dir: Path,
    root_dir: Path,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    skills_out = root_dir / "skills"
    commands_out = root_dir / "commands"
    agents_out = root_dir / "agents"
    mcp_out = root_dir / "mcp.json"

    ws_idx = scan_assets(workspace_dir)
    ws_prefix = _workspace_prefix(cfg)

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
    prev = _load_state(state_path).get("paths", {})
    next_state: dict[str, dict] = {}

    created: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    conflicts: list[str] = []
    blocked: list[str] = []

    def sync_skill(*, prefix: str, src_skill_md: Path, sid: str) -> None:
        out_name = f"{prefix}.{sid}"
        out_dir = skills_out / out_name
        out_skill_md = out_dir / "SKILL.md"
        p_str = str(out_skill_md)
        prev_entry = prev.get(p_str)

        desired_hash = _sha256_file(src_skill_md)

        _ensure_dir(out_dir, dry_run=dry_run)
        if out_skill_md.exists() and _files_differ(src_skill_md, out_skill_md):
            if not force and _is_drifted(dst=out_skill_md, prev_entry=prev_entry):
                conflicts.append(p_str)
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
                return
            _safe_copy(src_skill_md, out_skill_md, dry_run=dry_run)
            updated.append(p_str)
        elif not out_skill_md.exists():
            _safe_copy(src_skill_md, out_skill_md, dry_run=dry_run)
            created.append(p_str)

        next_state[p_str] = {"src": str(src_skill_md), "sha256": desired_hash}

    # Skills: workspace
    for s in ws_idx.skills:
        sync_skill(prefix=ws_prefix, src_skill_md=Path(s.path), sid=s.id)

    # Skills: packages
    for _pkg_key, _pkg_name, pkg_prefix, _integrity, _pkg_root, pkg_idx in pkg_indices:
        for s in pkg_idx.skills:
            sync_skill(prefix=pkg_prefix, src_skill_md=Path(s.path), sid=s.id)

    def sync_command(*, prefix: str, src: Path, cid: str) -> None:
        out_name = f"{prefix}.{cid}.md"
        dst = commands_out / out_name
        p_str = str(dst)
        prev_entry = prev.get(p_str)

        desired_hash = _sha256_file(src)

        _ensure_dir(commands_out, dry_run=dry_run)
        if dst.exists() and _files_differ(src, dst):
            if not force and _is_drifted(dst=dst, prev_entry=prev_entry):
                conflicts.append(p_str)
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
                return
            _safe_copy(src, dst, dry_run=dry_run)
            updated.append(p_str)
        elif not dst.exists():
            _safe_copy(src, dst, dry_run=dry_run)
            created.append(p_str)

        next_state[p_str] = {"src": str(src), "sha256": desired_hash}

    # Commands: workspace
    for c in ws_idx.commands:
        sync_command(prefix=ws_prefix, src=Path(c.path), cid=c.id)

    # Commands: packages
    for _pkg_key, _pkg_name, pkg_prefix, _integrity, _pkg_root, pkg_idx in pkg_indices:
        for c in pkg_idx.commands:
            sync_command(prefix=pkg_prefix, src=Path(c.path), cid=c.id)

    def sync_agent(*, prefix: str, src: Path, aid: str) -> None:
        out_name = f"{prefix}.{aid}.md"
        dst = agents_out / out_name
        p_str = str(dst)
        prev_entry = prev.get(p_str)

        desired_hash = _sha256_file(src)

        _ensure_dir(agents_out, dry_run=dry_run)
        if dst.exists() and _files_differ(src, dst):
            if not force and _is_drifted(dst=dst, prev_entry=prev_entry):
                conflicts.append(p_str)
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
                return
            _safe_copy(src, dst, dry_run=dry_run)
            updated.append(p_str)
        elif not dst.exists():
            _safe_copy(src, dst, dry_run=dry_run)
            created.append(p_str)

        next_state[p_str] = {"src": str(src), "sha256": desired_hash}

    # Agents: workspace
    for a in ws_idx.agents:
        sync_agent(prefix=ws_prefix, src=Path(a.path), aid=a.id)

    # Agents: packages
    for _pkg_key, _pkg_name, pkg_prefix, _integrity, _pkg_root, pkg_idx in pkg_indices:
        for a in pkg_idx.agents:
            sync_agent(prefix=pkg_prefix, src=Path(a.path), aid=a.id)

    # MCP (merge workspace + packages)
    mcp_inputs: list[Path] = []
    ws_servers_toml = workspace_dir / "mcp" / "servers.toml"
    if ws_servers_toml.exists():
        mcp_inputs.append(ws_servers_toml)

    for _pkg_key, _pkg_name, _pkg_prefix, _integrity, pkg_root, _pkg_idx in pkg_indices:
        p = Path(pkg_root) / "mcp" / "servers.toml"
        if p.exists():
            mcp_inputs.append(p)

    if mcp_inputs:
        from .mcp import build_mcp_servers, build_target_mcp_json

        servers = []

        # Workspace servers are trust-gated (they can spawn processes / reach network).
        if ws_servers_toml.exists():
            ws_servers = build_mcp_servers(namespace=ws_prefix, servers_toml_path=ws_servers_toml)
            for s in ws_servers:
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
                if isinstance(prev_entry, dict):
                    next_state[p_str] = prev_entry
            else:
                _safe_write_text(mcp_out, payload, dry_run=dry_run)
                updated.append(p_str)
                next_state[p_str] = {"srcs": [str(p) for p in sorted(mcp_inputs)], "sha256": desired_hash}
        elif not mcp_out.exists():
            _safe_write_text(mcp_out, payload, dry_run=dry_run)
            created.append(p_str)
            next_state[p_str] = {"srcs": [str(p) for p in sorted(mcp_inputs)], "sha256": desired_hash}
        else:
            # Up-to-date; keep it in state.
            next_state[p_str] = {"srcs": [str(p) for p in sorted(mcp_inputs)], "sha256": desired_hash}

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

    _write_state(
        state_path,
        {
            "version": 1,
            "target": target,
            "paths": next_state,
        },
        dry_run=dry_run,
    )

    return SyncResult(
        target=target,
        created=created,
        updated=updated,
        removed=removed,
        conflicts=conflicts,
        blocked=blocked,
    )


def sync_claude(
    *,
    cfg: BotyardConfig,
    workspace_dir: Path,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    root = work_root() / ".claude"
    return _sync_target(
        target="claude",
        cfg=cfg,
        workspace_dir=workspace_dir,
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
    root = work_root() / ".agents"
    return _sync_target(
        target="amp",
        cfg=cfg,
        workspace_dir=workspace_dir,
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
    root = work_root() / ".factory"
    return _sync_target(
        target="droid",
        cfg=cfg,
        workspace_dir=workspace_dir,
        root_dir=root,
        dry_run=dry_run,
        clean=clean,
        force=force,
    )


def sync(
    *,
    target: str,
    manifest_path: Path | None = None,
    dry_run: bool = False,
    clean: bool = False,
    force: bool = False,
) -> SyncResult:
    cfg = parse_botyard_toml_file(manifest_path)
    ws = Path(cfg.workspace.dir)
    root = Path.cwd() if manifest_path is None else manifest_path.parent
    if not ws.is_absolute():
        ws = (root / ws).resolve()

    if target == "claude":
        return sync_claude(cfg=cfg, workspace_dir=ws, dry_run=dry_run, clean=clean, force=force)
    if target == "amp":
        return sync_amp(cfg=cfg, workspace_dir=ws, dry_run=dry_run, clean=clean, force=force)
    if target == "droid":
        return sync_droid(cfg=cfg, workspace_dir=ws, dry_run=dry_run, clean=clean, force=force)
    raise ValueError(f"unsupported target: {target}")
