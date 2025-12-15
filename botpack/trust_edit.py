from __future__ import annotations

"""Deterministic editing + rewriting of .botpack/trust.toml."""

from pathlib import Path
from typing import Any

from .errors import ConfigParseError, ConfigValidationError
from .toml_write import toml_basic_string, toml_value


try:  # Python 3.11+
    import tomllib as _tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _tomllib  # type: ignore


def load_trust_raw(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": 1}
    except OSError as e:
        raise ConfigValidationError(path=path, message=f"unable to read file: {e}") from e

    try:
        data = _tomllib.loads(text)
    except Exception as e:
        msg = getattr(e, "msg", str(e))
        lineno = getattr(e, "lineno", None)
        colno = getattr(e, "colno", None)
        raise ConfigParseError(path=path, message=str(msg), lineno=lineno, colno=colno) from e

    if not isinstance(data, dict):
        raise ConfigValidationError(path=path, message="top-level TOML must be a table")
    return dict(data)


def trust_allow(
    path: Path,
    *,
    pkg_key: str,
    allow_exec: bool | None = None,
    allow_mcp: bool | None = None,
    integrity: str | None = None,
) -> None:
    data = load_trust_raw(path)
    if "version" not in data:
        data["version"] = 1

    entry_raw = data.get(pkg_key)
    if entry_raw is None:
        entry: dict[str, Any] = {}
    elif isinstance(entry_raw, dict):
        entry = dict(entry_raw)
    else:
        raise ConfigValidationError(path=path, message=f"{pkg_key}: expected table")

    if allow_exec is not None:
        entry["allowExec"] = bool(allow_exec)
    if allow_mcp is not None:
        entry["allowMcp"] = bool(allow_mcp)

    if integrity is not None:
        digest_raw = entry.get("digest")
        digest: dict[str, Any]
        if digest_raw is None:
            digest = {}
        elif isinstance(digest_raw, dict):
            digest = dict(digest_raw)
        else:
            raise ConfigValidationError(path=path, message=f"{pkg_key}.digest: expected table")
        digest["integrity"] = integrity
        entry["digest"] = digest

    data[pkg_key] = entry
    save_trust(path, data)


def trust_revoke(path: Path, *, pkg_key: str) -> bool:
    data = load_trust_raw(path)
    existed = pkg_key in data
    data.pop(pkg_key, None)
    if "version" not in data:
        data["version"] = 1
    save_trust(path, data)
    return existed


def save_trust(path: Path, data: dict[str, Any]) -> None:
    if "version" not in data:
        raise ConfigValidationError(path=path, message="version: required")
    if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool):
        raise ConfigValidationError(path=path, message="version: expected integer")

    lines: list[str] = []
    lines.append(f"version = {toml_value(int(data['version']))}")

    # Collect package entries, ignore non-string keys (invalid).
    pkg_keys = [k for k in data.keys() if k != "version"]
    for k in pkg_keys:
        if not isinstance(k, str):
            raise ConfigValidationError(path=path, message="trust entries: keys must be strings")

    for pkg_key in sorted(pkg_keys):
        raw = data.get(pkg_key)
        if not isinstance(raw, dict):
            raise ConfigValidationError(path=path, message=f"{pkg_key}: expected table")
        entry = dict(raw)

        # Top-level entry table.
        lines.append("")
        lines.append(f"[{toml_basic_string(pkg_key)}]")
        # Keep stable key order; omit absent.
        if "allowExec" in entry:
            lines.append(f"allowExec = {toml_value(bool(entry['allowExec']))}")
        if "allowMcp" in entry:
            lines.append(f"allowMcp = {toml_value(bool(entry['allowMcp']))}")

        # Digest subtable (if present).
        digest = entry.get("digest")
        if digest is not None:
            if not isinstance(digest, dict):
                raise ConfigValidationError(path=path, message=f"{pkg_key}.digest: expected table")
            if "integrity" not in digest:
                raise ConfigValidationError(path=path, message=f"{pkg_key}.digest.integrity: required")
            lines.append("")
            lines.append(f"[{toml_basic_string(pkg_key)}.digest]")
            lines.append(f"integrity = {toml_value(digest['integrity'])}")

        # MCP per-server overrides (if present).
        mcp = entry.get("mcp")
        if mcp is not None:
            if not isinstance(mcp, dict):
                raise ConfigValidationError(path=path, message=f"{pkg_key}.mcp: expected table")
            for server_id in sorted(mcp.keys()):
                if not isinstance(server_id, str):
                    raise ConfigValidationError(path=path, message=f"{pkg_key}.mcp: server id keys must be strings")
                srv = mcp.get(server_id)
                if not isinstance(srv, dict):
                    raise ConfigValidationError(path=path, message=f"{pkg_key}.mcp.{server_id}: expected table")
                lines.append("")
                lines.append(f"[{toml_basic_string(pkg_key)}.mcp.{toml_basic_string(server_id)}]")
                if "allowExec" in srv:
                    lines.append(f"allowExec = {toml_value(bool(srv['allowExec']))}")
                if "allowMcp" in srv:
                    lines.append(f"allowMcp = {toml_value(bool(srv['allowMcp']))}")

    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
