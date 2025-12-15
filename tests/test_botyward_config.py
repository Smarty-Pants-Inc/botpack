from __future__ import annotations

import re
from pathlib import Path

import pytest

from botpack.config import parse_agentpkg_toml, parse_botyard_toml_file, parse_trust_toml_file
from botpack.errors import ConfigParseError


def test_botyard_toml_minimal_parses(tmp_path: Path) -> None:
    p = tmp_path / "botpack.toml"
    p.write_text("version = 1\n", encoding="utf-8")

    cfg = parse_botyard_toml_file(p)

    assert cfg.version == 1
    assert cfg.workspace.dir == ".botpack/workspace"
    assert cfg.dependencies == {}


def test_botyard_toml_invalid_toml_surfaces_deterministic_error(tmp_path: Path) -> None:
    p = tmp_path / "botpack.toml"
    p.write_text("version =\n", encoding="utf-8")

    with pytest.raises(ConfigParseError) as exc:
        parse_botyard_toml_file(p)

    msg = str(exc.value)
    assert "Invalid TOML in" in msg
    assert str(p) in msg
    assert re.search(r"\(line \d+, column \d+\)$", msg)


def test_trust_toml_minimal_parses(tmp_path: Path) -> None:
    p = tmp_path / "trust.toml"
    p.write_text("version = 1\n", encoding="utf-8")

    cfg = parse_trust_toml_file(p)
    assert cfg.version == 1
    assert cfg.packages == {}


def test_trust_toml_parses_package_entry_with_digest_and_mcp_overrides(tmp_path: Path) -> None:
    p = tmp_path / "trust.toml"
    p.write_text(
        """
version = 1

["@acme/mcp-pack@0.3.0"]
allowExec = true
allowMcp = false

["@acme/mcp-pack@0.3.0".digest]
integrity = "blake3:abc"

["@acme/mcp-pack@0.3.0".mcp."@acme/mcp-pack/postgres"]
allowExec = true
allowMcp = true
""".lstrip(),
        encoding="utf-8",
    )

    cfg = parse_trust_toml_file(p)
    entry = cfg.packages["@acme/mcp-pack@0.3.0"]
    assert entry.allow_exec is True
    assert entry.allow_mcp is False
    assert entry.digest is not None
    assert entry.digest.integrity == "blake3:abc"
    assert entry.mcp["@acme/mcp-pack/postgres"].allow_exec is True
    assert entry.mcp["@acme/mcp-pack/postgres"].allow_mcp is True


def test_agentpkg_toml_minimal_parses(tmp_path: Path) -> None:
    p = tmp_path / "agentpkg.toml"
    p.write_text(
        """
agentpkg = "0.1"
name = "@acme/quality-skills"
version = "2.1.0"

[capabilities]
exec = false
network = false
mcp = false
""".lstrip(),
        encoding="utf-8",
    )

    cfg = parse_agentpkg_toml(p)
    assert cfg.agentpkg == "0.1"
    assert cfg.name == "@acme/quality-skills"
    assert cfg.version == "2.1.0"
    assert cfg.capabilities.exec is False
    assert cfg.capabilities.network is False
    assert cfg.capabilities.mcp is False
