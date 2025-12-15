from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


try:  # Python 3.11+
    import tomllib as _tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _tomllib  # type: ignore


@dataclass(frozen=True)
class McpServer:
    fqid: str
    name: str
    transport: str
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.fqid,
            "transport": self.transport,
        }
        if self.command is not None:
            out["command"] = self.command
        if self.args is not None:
            out["args"] = list(self.args)
        if self.url is not None:
            out["url"] = self.url
        if self.env is not None:
            out["env"] = dict(self.env)
        if self.name:
            out["notes"] = self.name
        return out


def parse_servers_toml(path: Path) -> list[dict[str, Any]]:
    data = _tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("servers.toml: top-level must be a table")

    version = data.get("version")
    if version != 1:
        raise ValueError(f"servers.toml: unsupported version {version!r}")

    servers = data.get("server")
    if servers is None:
        return []
    if not isinstance(servers, list):
        raise ValueError("servers.toml: [[server]] must be an array")
    out: list[dict[str, Any]] = []
    for s in servers:
        if not isinstance(s, dict):
            raise ValueError("servers.toml: each [[server]] must be a table")
        out.append(s)
    return out


def build_mcp_servers(*, namespace: str, servers_toml_path: Path) -> list[McpServer]:
    raw = parse_servers_toml(servers_toml_path)
    out: list[McpServer] = []

    for s in raw:
        sid = s.get("id")
        name = s.get("name") or ""
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError("server.id is required")
        fqid = f"{namespace}/{sid}"

        env_raw = (s.get("env") or {})
        env: dict[str, str] | None = None
        if env_raw:
            if not isinstance(env_raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env_raw.items()):
                raise ValueError(f"server.env for {fqid} must be a string map")
            env = {k: v for k, v in env_raw.items()}

        if "url" in s:
            url = s.get("url")
            if not isinstance(url, str):
                raise ValueError(f"server.url for {fqid} must be a string")
            out.append(McpServer(fqid=fqid, name=str(name), transport="http", url=url, env=env))
            continue

        cmd = s.get("command")
        args = s.get("args") or []
        if not isinstance(cmd, str):
            raise ValueError(f"server.command for {fqid} must be a string")
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"server.args for {fqid} must be a list of strings")
        out.append(McpServer(fqid=fqid, name=str(name), transport="stdio", command=cmd, args=list(args), env=env))

    # Deterministic ordering
    out.sort(key=lambda s: s.fqid)
    return out


def build_target_mcp_json(*, servers: list[McpServer]) -> dict[str, Any]:
    return {
        "$schema": "https://smartykit.dev/schemas/mcp.json",
        "servers": [s.to_dict() for s in servers],
    }
