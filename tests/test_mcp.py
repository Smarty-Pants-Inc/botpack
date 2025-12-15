from __future__ import annotations

import json
from pathlib import Path

from botpack.sync import sync
from botpack.lock import Lockfile, Package, save_lock
from botpack.store import store_put_tree


def test_sync_generates_claude_mcp_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    # Trust-gate MCP activation: workspace servers are only materialized once
    # explicitly trusted.
    trust = tmp_path / ".botpack" / "trust.toml"
    trust.parent.mkdir(parents=True)
    trust.write_text(
        """version = 1

["__workspace__"]
allowExec = true
allowMcp = true
""",
        encoding="utf-8",
    )

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"
""",
        encoding="utf-8",
    )

    ws = tmp_path / ".botpack" / "workspace"
    mcp_dir = ws / "mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "servers.toml").write_text(
        """version = 1

[[server]]
id = "postgres"
name = "Postgres"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
""",
        encoding="utf-8",
    )

    res = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res.conflicts == []

    mcp_out = tmp_path / ".claude" / "mcp.json"
    payload = json.loads(mcp_out.read_text(encoding="utf-8"))
    assert payload["servers"][0]["name"] == "workspace/postgres"
    assert payload["servers"][0]["transport"] == "stdio"


def test_sync_mcp_json_output_is_stable_exact_fixture(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    # Enable workspace MCP materialization for this test.
    trust = tmp_path / ".botpack" / "trust.toml"
    trust.parent.mkdir(parents=True)
    trust.write_text(
        """version = 1

["__workspace__"]
allowExec = true
allowMcp = true
""",
        encoding="utf-8",
    )

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"
""",
        encoding="utf-8",
    )

    ws = tmp_path / ".botpack" / "workspace"
    mcp_dir = ws / "mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "servers.toml").write_text(
        """version = 1

[[server]]
id = "zeta"
name = "Zeta"
command = "npx"
args = ["-y", "zeta"]

[[server]]
id = "alpha"
name = "Alpha"
url = "http://example.test"
env = { FOO = "bar", BAZ = "qux" }
""",
        encoding="utf-8",
    )

    res = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res.conflicts == []

    mcp_out = tmp_path / ".claude" / "mcp.json"
    expected = (
        "{\n"
        '  "$schema": "https://smartykit.dev/schemas/mcp.json",\n'
        '  "servers": [\n'
        "    {\n"
        '      "env": {\n'
        '        "BAZ": "qux",\n'
        '        "FOO": "bar"\n'
        "      },\n"
        '      "name": "workspace/alpha",\n'
        '      "notes": "Alpha",\n'
        '      "transport": "http",\n'
        '      "url": "http://example.test"\n'
        "    },\n"
        "    {\n"
        '      "args": [\n'
        '        "-y",\n'
        '        "zeta"\n'
        "      ],\n"
        '      "command": "npx",\n'
        '      "name": "workspace/zeta",\n'
        '      "notes": "Zeta",\n'
        '      "transport": "stdio"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )
    assert mcp_out.read_text(encoding="utf-8") == expected


def test_sync_merges_package_mcp_servers_only_when_trusted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_STORE", str(tmp_path / "store"))

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"
""",
        encoding="utf-8",
    )

    # Package provides an MCP server.
    pkg_src = tmp_path / "pkg_src"
    (pkg_src / "mcp").mkdir(parents=True)
    (pkg_src / "mcp" / "servers.toml").write_text(
        """version = 1

[[server]]
id = "postgres"
name = "Postgres"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
""",
        encoding="utf-8",
    )
    (pkg_src / "agentpkg.toml").write_text(
        """agentpkg = "0.1"
name = "@acme/mcp-pack"
version = "0.3.0"
""",
        encoding="utf-8",
    )
    stored = store_put_tree(pkg_src)

    lock = Lockfile(
        lockfileVersion=1,
        botpackVersion="0.1.0",
        specVersion="0.1",
        dependencies={"@acme/mcp-pack": "*"},
        packages={
            "@acme/mcp-pack@0.3.0": Package(
                source={"type": "path", "path": "pkg_src"},
                resolved={},
                integrity=stored.digest,
                dependencies={},
                capabilities={},
            )
        },
    )
    save_lock(tmp_path / "botpack.lock", lock)

    # Without trust, the package server is omitted (reported as blocked, not a sync conflict).
    res1 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res1.conflicts == []
    assert res1.blocked
    payload1 = json.loads((tmp_path / ".claude" / "mcp.json").read_text(encoding="utf-8"))
    assert all(s["name"] != "@acme/mcp-pack/postgres" for s in payload1["servers"])

    # Add digest-scoped trust with a per-server override.
    trust = tmp_path / ".botpack" / "trust.toml"
    trust.parent.mkdir(parents=True, exist_ok=True)
    trust.write_text(
        (
            "version = 1\n\n"
            "[\"@acme/mcp-pack@0.3.0\"]\n"
            "allowExec = false\n"
            "allowMcp = false\n\n"
            "[\"@acme/mcp-pack@0.3.0\".digest]\n"
            f"integrity = \"{stored.digest}\"\n\n"
            "[\"@acme/mcp-pack@0.3.0\".mcp.\"@acme/mcp-pack/postgres\"]\n"
            "allowExec = true\n"
            "allowMcp = false\n"
        ),
        encoding="utf-8",
    )

    res2 = sync(target="claude", manifest_path=tmp_path / "botpack.toml")
    assert res2.conflicts == []
    assert res2.blocked == []
    payload2 = json.loads((tmp_path / ".claude" / "mcp.json").read_text(encoding="utf-8"))
    assert any(s["name"] == "@acme/mcp-pack/postgres" for s in payload2["servers"])
