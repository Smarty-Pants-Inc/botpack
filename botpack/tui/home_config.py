from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .config_snippets import snippet_for


_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_id(s: str) -> str:
    s2 = _ID_SAFE_RE.sub("-", s.strip())
    s2 = s2.strip("-")
    return s2 or "server"


def _home_id_for_fqid(fqid: str) -> str:
    # Prefer a stable, human-readable id. TOML bare keys allow letters, digits, underscores, and dashes.
    return _safe_id(fqid.replace("/", "-"))


def _toml_quote(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _toml_array(xs: list[str]) -> str:
    return "[" + ", ".join(_toml_quote(x) for x in xs) + "]"


def _toml_inline_env(env: dict[str, str]) -> str:
    parts: list[str] = []
    for k in sorted(env.keys()):
        parts.append(f"{_toml_quote(k)} = {_toml_quote(env[k])}")
    return "{ " + ", ".join(parts) + " }"


def _render_toml_mcp_servers(servers: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for s in servers:
        sid = str(s["id"])
        transport = str(s["transport"])
        lines.append(f"[mcp_servers.{sid}]")
        if transport == "stdio":
            lines.append(f"command = {_toml_quote(str(s['command']))}")
            lines.append(f"args = {_toml_array(list(s.get('args') or []))}")
        else:
            lines.append(f"url = {_toml_quote(str(s['url']))}")
        env = s.get("env")
        if isinstance(env, dict) and env:
            lines.append(f"env = {_toml_inline_env({str(k): str(v) for k, v in env.items()})}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _sha256_json(obj: object) -> str:
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def _builtin_magic_server() -> dict[str, object]:
    import sys

    return {
        "id": "mcp-magic-number",
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "botpack.mcp_magic_number_server"],
    }


def _try_collect_project_servers() -> tuple[list[dict[str, object]], list[str]]:
    """Best-effort collect project-derived servers (workspace + packages).

    Returns (servers, blocked_reasons). If no botpack project is present, returns empty.
    """

    from ..config import botyard_manifest_path, parse_botyard_toml_file
    from ..install import default_lock_path
    from ..mcp import build_mcp_servers
    from ..paths import store_dir, work_root
    from ..trust import WORKSPACE_TRUST_KEY, check_mcp_server_trust
    from ..lock import load_lock

    manifest = botyard_manifest_path()
    if not manifest.exists():
        return ([], [])

    try:
        cfg = parse_botyard_toml_file(manifest)
    except Exception:
        return ([], [])

    root = work_root()
    ws = Path(cfg.workspace.dir)
    if not ws.is_absolute():
        ws = (root / ws).resolve()

    servers: list[dict[str, object]] = []
    blocked: list[str] = []

    ws_prefix = cfg.workspace.name.replace("/", "-").replace("@", "") if cfg.workspace.name else "workspace"

    ws_servers_toml = ws / "mcp" / "servers.toml"
    if ws_servers_toml.exists():
        for s in build_mcp_servers(namespace=ws_prefix, servers_toml_path=ws_servers_toml):
            decision = check_mcp_server_trust(
                pkg_key=WORKSPACE_TRUST_KEY,
                integrity=None,
                fqid=s.fqid,
                needs_exec=s.transport == "stdio",
                needs_mcp=s.transport != "stdio",
            )
            if not decision.ok:
                blocked.append(decision.reason or f"{WORKSPACE_TRUST_KEY}: not trusted for {s.fqid}")
                continue
            servers.append(
                {
                    "id": _home_id_for_fqid(s.fqid),
                    "transport": s.transport,
                    "command": s.command,
                    "args": s.args,
                    "url": s.url,
                    "env": s.env,
                }
            )

    lock_path = default_lock_path()
    if lock_path.exists():
        try:
            lock = load_lock(lock_path)
        except Exception:
            lock = None
        if lock is not None:
            for pkg_key, pkg in sorted(lock.packages.items()):
                if not pkg.integrity:
                    continue
                pkg_name, _ver = pkg_key.rsplit("@", 1)
                pkg_root = store_dir() / pkg.integrity
                servers_toml = pkg_root / "mcp" / "servers.toml"
                if not servers_toml.exists():
                    continue
                for s in build_mcp_servers(namespace=pkg_name, servers_toml_path=servers_toml):
                    decision = check_mcp_server_trust(
                        pkg_key=pkg_key,
                        integrity=pkg.integrity,
                        fqid=s.fqid,
                        needs_exec=s.transport == "stdio",
                        needs_mcp=s.transport != "stdio",
                    )
                    if not decision.ok:
                        blocked.append(decision.reason or f"{pkg_key}: not trusted for {s.fqid}")
                        continue
                    servers.append(
                        {
                            "id": _home_id_for_fqid(s.fqid),
                            "transport": s.transport,
                            "command": s.command,
                            "args": s.args,
                            "url": s.url,
                            "env": s.env,
                        }
                    )

    # Deterministic output + id collision defense.
    servers.sort(key=lambda x: str(x.get("id")))
    seen: set[str] = set()
    for s in servers:
        sid = str(s["id"])
        if sid in seen:
            # Disambiguate deterministically.
            s["id"] = sid + "--" + _sha256_json(s)[0:8]
        seen.add(str(s["id"]))

    return (servers, blocked)


HomeTui = Literal["codex", "coder", "amp"]


BEGIN_MARKER = "# BEGIN BOTPACK MANAGED (do not edit by hand)"
END_MARKER = "# END BOTPACK MANAGED"


def _ts_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _state_dir() -> Path:
    # Allow tests / power-users to override.
    override = os.environ.get("BOTPACK_HOME_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".botpack" / "state").resolve()


def _state_path() -> Path:
    return _state_dir() / "home-config.json"


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {"version": 1, "paths": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "paths": {}}
        if data.get("version") != 1:
            return {"version": 1, "paths": {}}
        if not isinstance(data.get("paths"), dict):
            data["paths"] = {}
        return data
    except Exception:
        return {"version": 1, "paths": {}}


def _write_state(state: dict, *, dry_run: bool) -> None:
    if dry_run:
        return
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def default_home_config_path(tui: HomeTui) -> Path:
    home = Path.home()
    if tui == "codex":
        return home / ".codex" / "config.toml"
    if tui == "coder":
        return home / ".code" / "config.toml"
    if tui == "amp":
        return home / ".config" / "amp" / "settings.json"
    raise ValueError(f"unsupported tui: {tui}")


def _backup_path(path: Path) -> Path:
    # Avoid stomping suffix logic; always append.
    return path.with_name(path.name + ".botpack.bak")


def _maybe_backup(path: Path, *, backup: bool, dry_run: bool) -> Path | None:
    if not backup:
        return None
    if not path.exists():
        return None
    bp = _backup_path(path)
    if dry_run:
        return bp
    bp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, bp)
    return bp


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    changed: bool
    status: Literal["ok", "conflict", "error"]
    path: Path
    message: str = ""
    backup_path: Path | None = None
    dry_run: bool = False


def _extract_managed_block(text: str) -> tuple[str | None, str | None, str | None]:
    """Return (prefix, inner, suffix) if markers exist, else (None, None, None)."""

    lines = text.splitlines(keepends=True)
    b = None
    e = None
    for i, ln in enumerate(lines):
        if ln.rstrip("\n") == BEGIN_MARKER:
            b = i
            continue
        if ln.rstrip("\n") == END_MARKER and b is not None:
            e = i
            break
    if b is None or e is None or e <= b:
        return (None, None, None)

    prefix = "".join(lines[:b])
    inner = "".join(lines[b + 1 : e])
    suffix = "".join(lines[e + 1 :])
    return (prefix, inner, suffix)


def _render_managed_block(inner: str) -> str:
    body = inner.rstrip() + "\n" if inner.strip() else ""
    return BEGIN_MARKER + "\n" + body + END_MARKER + "\n"


def _toml_has_section(text: str, section: str) -> bool:
    hdr = f"[{section}]"
    return any(ln.strip() == hdr for ln in text.splitlines())


def _remove_toml_section(text: str, section: str) -> str:
    """Remove a TOML section like [mcp_servers.mcp-magic-number] until next [..] header."""

    lines = text.splitlines(keepends=True)
    hdr = f"[{section}]"
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == hdr:
            # Skip until next header at column 0 (best-effort).
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.startswith("[") and nxt.rstrip("\n").endswith("]"):
                    break
                i += 1
            continue
        out.append(ln)
        i += 1
    return "".join(out)


def apply_mcp_magic_number_home_config(
    *,
    tui: HomeTui,
    path: Path | None = None,
    dry_run: bool = False,
    backup: bool = False,
    force: bool = False,
) -> ApplyResult:
    """Apply Botpack-managed MCP config for a single TUI home config file.

    This is intentionally conservative:
    - For TOML (codex/coder): we only touch a managed BEGIN/END block.
    - For JSON (amp): we only touch the amp.mcpServers entries that Botpack manages.

    Drift detection:
    - If the previously-written managed content hash differs from what's currently on disk,
      we treat it as user edits and refuse unless --force.
    """

    cfg_path = (path or default_home_config_path(tui)).expanduser().resolve()

    # Desired servers: always include the bundled magic-number server, plus best-effort project-derived servers.
    desired_servers = [_builtin_magic_server()]
    project_servers, blocked = _try_collect_project_servers()
    desired_servers.extend(project_servers)

    if tui in {"codex", "coder"}:
        # Avoid duplication: if a server already exists outside the managed block,
        # don't add a second definition (TOML would reject re-defining a table).
        servers_to_manage: list[dict[str, object]] = []
        skipped_existing: list[str] = []

        prev_state = _load_state()
        paths_state = prev_state.get("paths") or {}
        entry = paths_state.get(str(cfg_path))
        prev_sha = entry.get("managed_sha256") if isinstance(entry, dict) else None

        current_text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
        prefix, inner, suffix = _extract_managed_block(current_text)

        outside_text = (prefix or "") + (suffix or "") if inner is not None else current_text
        prefix2 = prefix or ""
        suffix2 = suffix or ""
        current_text2 = current_text

        for s in desired_servers:
            section = f"mcp_servers.{s['id']}"
            if _toml_has_section(outside_text, section):
                if force:
                    if inner is not None:
                        prefix2 = _remove_toml_section(prefix2, section)
                        suffix2 = _remove_toml_section(suffix2, section)
                        outside_text = prefix2 + suffix2
                    else:
                        current_text2 = _remove_toml_section(current_text2, section)
                        outside_text = current_text2
                    servers_to_manage.append(s)
                else:
                    skipped_existing.append(str(s["id"]))
                continue
            servers_to_manage.append(s)

        desired_inner = _render_toml_mcp_servers(servers_to_manage)
        desired_block = _render_managed_block(desired_inner)
        desired_sha = _sha256_text(desired_inner)
        if inner is not None:
            current_sha = _sha256_text(inner)
            if isinstance(prev_sha, str) and prev_sha and current_sha != prev_sha and not force:
                return ApplyResult(
                    ok=False,
                    changed=False,
                    status="conflict",
                    path=cfg_path,
                    message="managed block was modified since last botpack write",
                    dry_run=dry_run,
                )
            if (not isinstance(prev_sha, str) or not prev_sha) and current_sha != desired_sha and not force:
                return ApplyResult(
                    ok=False,
                    changed=False,
                    status="conflict",
                    path=cfg_path,
                    message="existing managed block differs from botpack desired content",
                    dry_run=dry_run,
                )

            changed = inner != desired_inner or prefix2 != (prefix or "") or suffix2 != (suffix or "")
            new_text = prefix2 + desired_block + suffix2
        else:
            current_text = current_text2

            sep = "\n" if current_text and not current_text.endswith("\n") else ""
            prefix = current_text + sep
            if prefix and not prefix.endswith("\n\n"):
                prefix += "\n"
            new_text = prefix + desired_block
            changed = True

        bp = _maybe_backup(cfg_path, backup=backup, dry_run=dry_run) if changed else None
        if changed and not dry_run:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cfg_path.with_name(cfg_path.name + ".tmp")
            tmp.write_text(new_text, encoding="utf-8")
            tmp.replace(cfg_path)

        # Update state even if no-op; it stabilizes drift detection.
        paths_state[str(cfg_path)] = {
            "tui": tui,
            "kind": "toml-managed-block",
            "managed_sha256": desired_sha,
            "updated_at": _ts_utc(),
        }
        prev_state["paths"] = paths_state
        _write_state(prev_state, dry_run=dry_run)

        msg_parts: list[str] = []
        if blocked:
            msg_parts.append(f"skipped {len(blocked)} untrusted project MCP server(s)")
        if skipped_existing:
            msg_parts.append(f"skipped {len(skipped_existing)} already-configured server(s)")
        msg = "; ".join(msg_parts)
        return ApplyResult(ok=True, changed=changed, status="ok", path=cfg_path, message=msg, backup_path=bp, dry_run=dry_run)

    # amp (JSON)
    _fmt, _snippet = snippet_for("amp")
    assert _fmt == "json"
    desired_map: dict[str, dict[str, object]] = {}
    for s in desired_servers:
        sid = str(s["id"])
        entry: dict[str, object] = {"transport": s["transport"]}
        if s["transport"] == "stdio":
            entry["command"] = s["command"]
            entry["args"] = list(s.get("args") or [])
        else:
            entry["url"] = s["url"]
        env = s.get("env")
        if isinstance(env, dict) and env:
            entry["env"] = {str(k): str(v) for k, v in env.items()}
        desired_map[sid] = entry

    prev_state = _load_state()
    paths_state = prev_state.get("paths") or {}
    entry_state = paths_state.get(str(cfg_path)) if isinstance(paths_state, dict) else None
    prev_servers = entry_state.get("servers") if isinstance(entry_state, dict) else {}
    if not isinstance(prev_servers, dict):
        prev_servers = {}

    try:
        current_obj: dict[str, Any] = {}
        if cfg_path.exists():
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current_obj = loaded
            else:
                return ApplyResult(
                    ok=False,
                    changed=False,
                    status="error",
                    path=cfg_path,
                    message="settings.json: top-level must be an object",
                    dry_run=dry_run,
                )

        amp = current_obj.get("amp")
        if amp is None:
            amp = {}
            current_obj["amp"] = amp
        if not isinstance(amp, dict):
            return ApplyResult(
                ok=False,
                changed=False,
                status="error",
                path=cfg_path,
                message="settings.json: amp must be an object",
                dry_run=dry_run,
            )

        mcp_servers = amp.get("mcpServers")
        if mcp_servers is None:
            mcp_servers = {}
            amp["mcpServers"] = mcp_servers
        if not isinstance(mcp_servers, dict):
            return ApplyResult(
                ok=False,
                changed=False,
                status="error",
                path=cfg_path,
                message="settings.json: amp.mcpServers must be an object",
                dry_run=dry_run,
            )

        original = json.loads(json.dumps(current_obj))  # cheap deep copy
        skipped_existing: list[str] = []

        # Apply/update managed servers.
        for sid, desired_entry in desired_map.items():
            cur = mcp_servers.get(sid)
            desired_sha = _sha256_json(desired_entry)
            cur_sha = _sha256_json(cur) if cur is not None else None
            prev_sha = prev_servers.get(sid)

            # Avoid clobbering user-managed entries: if the key exists and we
            # haven't previously managed it, skip unless --force.
            if (
                cur is not None
                and (not isinstance(prev_sha, str) or not prev_sha)
                and cur_sha != desired_sha
                and not force
            ):
                skipped_existing.append(sid)
                continue

            if isinstance(prev_sha, str) and prev_sha and cur is not None and cur_sha != prev_sha and not force:
                return ApplyResult(
                    ok=False,
                    changed=False,
                    status="conflict",
                    path=cfg_path,
                    message=f"managed server {sid!r} was modified since last botpack write",
                    dry_run=dry_run,
                )
            if (not isinstance(prev_sha, str) or not prev_sha) and cur is not None and cur_sha != desired_sha and not force:
                return ApplyResult(
                    ok=False,
                    changed=False,
                    status="conflict",
                    path=cfg_path,
                    message=f"existing amp.mcpServers[{sid!r}] differs from botpack desired content",
                    dry_run=dry_run,
                )

            mcp_servers[sid] = desired_entry
            prev_servers[sid] = desired_sha

        # Remove servers we previously managed but no longer desire.
        for sid in sorted(list(prev_servers.keys())):
            if sid in desired_map:
                continue
            cur = mcp_servers.get(sid)
            if cur is None:
                prev_servers.pop(sid, None)
                continue
            cur_sha = _sha256_json(cur)
            prev_sha = prev_servers.get(sid)
            if isinstance(prev_sha, str) and prev_sha and cur_sha != prev_sha and not force:
                return ApplyResult(
                    ok=False,
                    changed=False,
                    status="conflict",
                    path=cfg_path,
                    message=f"managed server {sid!r} was modified since last botpack write",
                    dry_run=dry_run,
                )
            mcp_servers.pop(sid, None)
            prev_servers.pop(sid, None)

        changed = _canonical_json(original) != _canonical_json(current_obj)
        bp = _maybe_backup(cfg_path, backup=backup, dry_run=dry_run) if changed else None
        if changed and not dry_run:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cfg_path.with_name(cfg_path.name + ".tmp")
            tmp.write_text(json.dumps(current_obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(cfg_path)

        paths_state[str(cfg_path)] = {
            "tui": tui,
            "kind": "json-managed-mcpServers",
            "servers": prev_servers,
            "updated_at": _ts_utc(),
        }
        prev_state["paths"] = paths_state
        _write_state(prev_state, dry_run=dry_run)

        msg = ""
        msg_parts: list[str] = []
        if blocked:
            msg_parts.append(f"skipped {len(blocked)} untrusted project MCP server(s)")
        if skipped_existing:
            msg_parts.append(f"skipped {len(skipped_existing)} already-configured server(s)")
        msg = "; ".join(msg_parts)
        return ApplyResult(ok=True, changed=changed, status="ok", path=cfg_path, message=msg, backup_path=bp, dry_run=dry_run)

    except Exception as e:
        return ApplyResult(
            ok=False,
            changed=False,
            status="error",
            path=cfg_path,
            message=str(e),
            dry_run=dry_run,
        )

    raise ValueError(f"unsupported tui: {tui}")
