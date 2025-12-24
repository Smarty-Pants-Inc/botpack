from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    tools_count: int
    resources_count: int
    server: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "ok": bool(self.ok),
            "tools_count": int(self.tools_count),
            "resources_count": int(self.resources_count),
        }


def _rpc_send(proc: subprocess.Popen, msg: dict) -> None:
    body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    headers = f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode("ascii")
    assert proc.stdin is not None
    proc.stdin.buffer.write(headers)
    proc.stdin.buffer.write(body)
    proc.stdin.buffer.flush()


def _rpc_recv(proc: subprocess.Popen) -> dict:
    assert proc.stdout is not None
    content_length = None
    while True:
        line = proc.stdout.buffer.readline()
        if not line:
            raise RuntimeError("server closed pipe without response")
        if line in (b"\r\n", b"\n"):
            break
        low = line.decode("ascii", errors="ignore").strip()
        if low.lower().startswith("content-length:"):
            try:
                content_length = int(low.split(":", 1)[1].strip())
            except Exception:
                pass
    if content_length is None or content_length < 0:
        raise RuntimeError("missing Content-Length")
    body = proc.stdout.buffer.read(content_length)
    if not body:
        raise RuntimeError("empty body")
    return json.loads(body)


def default_stdio_server_cmd(*, repo_root: Path | None = None) -> tuple[str, list[str], str]:
    # Prefer sys.executable so this works under uv/venv.
    cmd = sys.executable
    args = ["-m", "botpack.mcp_magic_number_server"]
    return (cmd, args, "mcp-magic-number")


def run_stdio_smoke(
    *,
    cmd: str,
    args: list[str],
    server_name: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> SmokeResult:
    proc = subprocess.Popen(
        [cmd, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
    )
    try:
        _rpc_send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _ = _rpc_recv(proc)

        _rpc_send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_resp = _rpc_recv(proc)
        tools = (tools_resp.get("result") or {}).get("tools") or []

        _rpc_send(proc, {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}})
        res_resp = _rpc_recv(proc)
        resources = (res_resp.get("result") or {}).get("resources") or []

        ok = len(tools) >= 1
        return SmokeResult(ok=bool(ok), tools_count=len(tools), resources_count=len(resources), server=server_name)
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def run_smoke(
    *,
    cmd: str | None = None,
    args: list[str] | None = None,
    server_name: str | None = None,
    cwd: Path | None = None,
) -> SmokeResult:
    if cmd is None or args is None or server_name is None:
        dcmd, dargs, dname = default_stdio_server_cmd(repo_root=cwd)
        cmd = cmd or dcmd
        args = args or dargs
        server_name = server_name or dname

    env = dict(os.environ)
    # Make the module importable even when invoked from a temp cwd.
    if "PYTHONPATH" not in env:
        # If running from source, add the repo root on best-effort basis.
        # (<repo>/botpack is import root)
        try:
            pkg_root = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = pkg_root
        except Exception:
            pass

    return run_stdio_smoke(cmd=str(cmd), args=list(args), server_name=str(server_name), cwd=cwd, env=env)
