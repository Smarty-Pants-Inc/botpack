#!/usr/bin/env python3
"""Minimal stdio JSON-RPC 2.0 server for MCP smoke testing.

This is intentionally tiny and read-only. It exists so Botpack (and TUIs Botpack
targets) can validate MCP wiring without depending on external MCP servers.

Supported methods:
  - initialize
  - notifications/initialized (no response)
  - tools/list
  - tools/call
  - resources/list

Protocol framing: MCP/LSP style Content-Length headers (RFC 7230-ish).
We also tolerate newline-delimited JSON from clients that skip headers.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional


LOG_FILE = os.environ.get("BOTPACK_MCP_MAGIC_SERVER_LOG", "")
_USE_NEWLINE = False


def _log(msg: str) -> None:
    if not LOG_FILE:
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _write_message(obj: dict) -> None:
    global _USE_NEWLINE
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if _USE_NEWLINE:
        sys.stdout.buffer.write(body + b"\n")
        sys.stdout.buffer.flush()
        return
    headers = f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(headers)
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def respond(req_id: Optional[int | str], result: Optional[dict] = None, error: Optional[dict] = None) -> None:
    msg: dict = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result or {}
    _write_message(msg)


def _read_message() -> Optional[dict]:
    content_length = None
    json_line: Optional[bytes] = None

    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            _log("<stdin EOF>")
            return None
        if line in (b"\r\n", b"\n"):
            break
        if line.lstrip().startswith(b"{"):
            json_line = line.rstrip(b"\r\n")
            break
        low = line.decode("ascii", errors="ignore").strip()
        if low.lower().startswith("content-length:"):
            try:
                content_length = int(low.split(":", 1)[1].strip())
            except Exception:
                pass

    global _USE_NEWLINE
    if json_line is not None:
        _USE_NEWLINE = True
        try:
            return json.loads(json_line)
        except Exception:
            _log("json parse error (nl)")
            return None

    _USE_NEWLINE = False
    if content_length is None or content_length < 0:
        _log("missing content-length")
        return None
    body = sys.stdin.buffer.read(content_length)
    if not body:
        _log("empty body")
        return None
    try:
        return json.loads(body)
    except Exception:
        _log("json parse error")
        return None


MAGIC_NUMBER = int(os.environ.get("BOTPACK_MCP_MAGIC_NUMBER", "424242"))


def _repo_root() -> Path:
    # Prefer an explicit hint if provided by the caller.
    hint = os.environ.get("BOTPACK_REPO_ROOT")
    if hint:
        try:
            return Path(hint).expanduser().resolve()
        except Exception:
            pass
    return Path.cwd().resolve()


def main() -> int:
    repo_root = _repo_root()

    while True:
        req = _read_message()
        if req is None:
            break

        mid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        is_notification = mid is None

        if method == "initialize":
            respond(
                mid,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "mcp-magic-number", "version": "1.0.0"},
                },
            )
            continue

        if method == "notifications/initialized":
            # Per JSON-RPC 2.0: notifications MUST NOT receive responses.
            continue

        if method == "tools/list":
            respond(
                mid,
                {
                    "tools": [
                        {
                            "name": "magic_number",
                            "description": "Return a fixed magic number for smoke testing.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "ping",
                            "description": "Responds with PONG (dry-run)",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "list_files",
                            "description": "List files at current repo root (read-only)",
                            "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
                        },
                    ]
                },
            )
            continue

        if method == "tools/call":
            name = (params.get("name") if isinstance(params, dict) else None) or ""
            if name == "magic_number":
                respond(mid, {"content": [{"type": "text", "text": str(MAGIC_NUMBER)}]})
                continue
            if name == "ping":
                respond(mid, {"content": [{"type": "text", "text": "PONG"}]})
                continue
            if name == "list_files":
                try:
                    limit = 50
                    if isinstance(params, dict):
                        argobj = params.get("arguments") or {}
                        if isinstance(argobj, dict) and "limit" in argobj:
                            limit = int(argobj.get("limit") or 50)
                    paths = [str(p.name) for p in list(repo_root.iterdir())[: max(0, limit)]]
                except Exception:
                    paths = []
                respond(mid, {"content": [{"type": "text", "text": "\n".join(paths)}]})
                continue

            respond(mid, error={"code": -32601, "message": f"Unknown tool: {name}"})
            continue

        if method == "resources/list":
            readme = repo_root / "README.md"
            resources = []
            if readme.exists():
                resources.append(
                    {
                        "uri": f"file://{readme}",
                        "name": "README",
                        "mimeType": "text/markdown",
                        "description": "Top-level README",
                    }
                )
            respond(mid, {"resources": resources})
            continue

        if not is_notification:
            respond(mid, error={"code": -32601, "message": f"Method not found: {method}"})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
