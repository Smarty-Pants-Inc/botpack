from __future__ import annotations

from pathlib import Path

import pytest

from botpack.tui.home_config import BEGIN_MARKER, END_MARKER, apply_mcp_magic_number_home_config


def test_cli_tui_config_apply_codex_uses_toml_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_HOME_STATE_DIR", str(tmp_path / "state"))

    from botpack.cli import main

    cfg = tmp_path / "config.toml"
    rc = main(["tui", "config", "apply", "codex", "--path", str(cfg)])
    assert rc == 0
    text = cfg.read_text(encoding="utf-8")
    assert BEGIN_MARKER in text
    assert "[mcp_servers.mcp-magic-number]" in text


def test_apply_codex_toml_inserts_managed_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_HOME_STATE_DIR", str(tmp_path / "state"))

    cfg = tmp_path / "config.toml"
    res1 = apply_mcp_magic_number_home_config(tui="codex", path=cfg)
    assert res1.ok is True
    assert res1.changed is True
    text = cfg.read_text(encoding="utf-8")
    assert BEGIN_MARKER in text
    assert END_MARKER in text
    assert "[mcp_servers.mcp-magic-number]" in text

    res2 = apply_mcp_magic_number_home_config(tui="codex", path=cfg)
    assert res2.ok is True
    assert res2.changed is False


def test_apply_codex_toml_conflict_on_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_HOME_STATE_DIR", str(tmp_path / "state"))

    cfg = tmp_path / "config.toml"
    _ = apply_mcp_magic_number_home_config(tui="codex", path=cfg)

    # Simulate user edit inside the managed block.
    text = cfg.read_text(encoding="utf-8")
    cfg.write_text(text.replace("mcp-magic-number", "mcp-magic-number-user"), encoding="utf-8")

    res = apply_mcp_magic_number_home_config(tui="codex", path=cfg)
    assert res.ok is False
    assert res.status == "conflict"

    res_force = apply_mcp_magic_number_home_config(tui="codex", path=cfg, force=True)
    assert res_force.ok is True


def test_apply_amp_json_sets_subtree_and_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_HOME_STATE_DIR", str(tmp_path / "state"))

    cfg = tmp_path / "settings.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('{"amp": {"foo": 1}}\n', encoding="utf-8")

    res = apply_mcp_magic_number_home_config(tui="amp", path=cfg, backup=True)
    assert res.ok is True
    assert res.changed is True
    assert res.backup_path is not None
    assert res.backup_path.exists()

    out = cfg.read_text(encoding="utf-8")
    assert '"mcpServers"' in out
    assert '"mcp-magic-number"' in out


def test_apply_amp_json_conflict_on_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_HOME_STATE_DIR", str(tmp_path / "state"))

    cfg = tmp_path / "settings.json"
    res1 = apply_mcp_magic_number_home_config(tui="amp", path=cfg)
    assert res1.ok is True

    # User changes the managed subtree value.
    import json

    obj = json.loads(cfg.read_text(encoding="utf-8"))
    obj["amp"]["mcpServers"]["mcp-magic-number"]["transport"] = "http"
    cfg.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    res = apply_mcp_magic_number_home_config(tui="amp", path=cfg)
    assert res.ok is False
    assert res.status == "conflict"


def test_apply_codex_includes_trusted_workspace_mcp_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_HOME_STATE_DIR", str(tmp_path / "state"))

    # Minimal botpack.toml
    (tmp_path / "botpack.toml").write_text(
        """
version = 1

[workspace]
dir = ".botpack/workspace"
private = true
""".lstrip(),
        encoding="utf-8",
    )

    # Trust workspace MCP servers.
    trust = tmp_path / ".botpack" / "trust.toml"
    trust.parent.mkdir(parents=True, exist_ok=True)
    trust.write_text(
        """
version = 1

[__workspace__]
allowExec = true
allowMcp = true
""".lstrip(),
        encoding="utf-8",
    )

    servers_toml = tmp_path / ".botpack" / "workspace" / "mcp" / "servers.toml"
    servers_toml.parent.mkdir(parents=True, exist_ok=True)
    servers_toml.write_text(
        """
version = 1

[[server]]
id = "ws-echo"
name = "Workspace echo"
command = "echo"
args = ["hello"]
""".lstrip(),
        encoding="utf-8",
    )

    cfg = tmp_path / "config.toml"
    res = apply_mcp_magic_number_home_config(tui="codex", path=cfg)
    assert res.ok is True

    text = cfg.read_text(encoding="utf-8")
    assert "[mcp_servers.mcp-magic-number]" in text
    assert "[mcp_servers.workspace-ws-echo]" in text


def test_apply_codex_skips_already_configured_server_outside_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_HOME_STATE_DIR", str(tmp_path / "state"))

    (tmp_path / "botpack.toml").write_text(
        """
version = 1

[workspace]
dir = ".botpack/workspace"
private = true
""".lstrip(),
        encoding="utf-8",
    )

    trust = tmp_path / ".botpack" / "trust.toml"
    trust.parent.mkdir(parents=True, exist_ok=True)
    trust.write_text(
        """
version = 1

[__workspace__]
allowExec = true
allowMcp = true
""".lstrip(),
        encoding="utf-8",
    )

    servers_toml = tmp_path / ".botpack" / "workspace" / "mcp" / "servers.toml"
    servers_toml.parent.mkdir(parents=True, exist_ok=True)
    servers_toml.write_text(
        """
version = 1

[[server]]
id = "ws-echo"
name = "Workspace echo"
command = "echo"
args = ["hello"]
""".lstrip(),
        encoding="utf-8",
    )

    cfg = tmp_path / "config.toml"
    # User already has the workspace server configured.
    cfg.write_text(
        """
[mcp_servers.workspace-ws-echo]
command = "echo"
args = ["hello"]
""".lstrip(),
        encoding="utf-8",
    )

    res = apply_mcp_magic_number_home_config(tui="codex", path=cfg)
    assert res.ok is True
    text = cfg.read_text(encoding="utf-8")
    assert text.count("[mcp_servers.workspace-ws-echo]") == 1
    assert "[mcp_servers.mcp-magic-number]" in text


def test_apply_amp_skips_already_configured_server_if_user_owned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
    monkeypatch.setenv("BOTPACK_HOME_STATE_DIR", str(tmp_path / "state"))

    (tmp_path / "botpack.toml").write_text(
        """
version = 1

[workspace]
dir = ".botpack/workspace"
private = true
""".lstrip(),
        encoding="utf-8",
    )

    trust = tmp_path / ".botpack" / "trust.toml"
    trust.parent.mkdir(parents=True, exist_ok=True)
    trust.write_text(
        """
version = 1

[__workspace__]
allowExec = true
allowMcp = true
""".lstrip(),
        encoding="utf-8",
    )

    servers_toml = tmp_path / ".botpack" / "workspace" / "mcp" / "servers.toml"
    servers_toml.parent.mkdir(parents=True, exist_ok=True)
    servers_toml.write_text(
        """
version = 1

[[server]]
id = "ws-echo"
name = "Workspace echo"
command = "echo"
args = ["hello"]
""".lstrip(),
        encoding="utf-8",
    )

    cfg = tmp_path / "settings.json"
    cfg.write_text(
        '{"amp": {"mcpServers": {"workspace-ws-echo": {"transport": "stdio", "command": "echo", "args": ["DIFFERENT"]}}}}\n',
        encoding="utf-8",
    )

    res = apply_mcp_magic_number_home_config(tui="amp", path=cfg)
    assert res.ok is True
    out = cfg.read_text(encoding="utf-8")
    assert '"workspace-ws-echo"' in out
    assert '"DIFFERENT"' in out
    assert '"mcp-magic-number"' in out
