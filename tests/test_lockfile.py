"""Tests for Botpack lockfile I/O (by-12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from botpack.lock import (
    Lockfile,
    LockfileError,
    Package,
    load_lock,
    package_key,
    save_lock,
)


def _sample_lock() -> Lockfile:
    pkg_name = "@acme/quality-skills"
    pkg_ver = "2.1.0"
    key = package_key(pkg_name, pkg_ver)
    return Lockfile(
        lockfileVersion=1,
        botpackVersion="0.1.0",
        specVersion="0.1",
        dependencies={pkg_name: "^2.1.0"},
        packages={
            key: Package(
                source={
                    "type": "git",
                    "url": "https://github.com/acme/quality-skills.git",
                },
                resolved={
                    "commit": "0123456789abcdef",
                    "ref": "refs/tags/v2.1.0",
                },
                integrity="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                dependencies={"@acme/base": "1.2.0"},
                capabilities={"exec": False, "mcp": False, "network": False},
            )
        },
    )


class TestBotpackLockfile:
    def test_roundtrip_write_then_read_preserves_structure(self, tmp_path: Path):
        lock = _sample_lock()
        p = tmp_path / "botpack.lock"
        save_lock(p, lock)
        loaded = load_lock(p)
        assert loaded == lock

    def test_json_output_is_stable_exact_fixture(self, tmp_path: Path):
        lock = _sample_lock()
        p = tmp_path / "botpack.lock"
        save_lock(p, lock)

        # Exact string compare to enforce canonical JSON formatting.
        expected = (
            "{\n"
            "  \"botpackVersion\": \"0.1.0\",\n"
            "  \"dependencies\": {\n"
            "    \"@acme/quality-skills\": \"^2.1.0\"\n"
            "  },\n"
            "  \"lockfileVersion\": 1,\n"
            "  \"packages\": {\n"
            "    \"@acme/quality-skills@2.1.0\": {\n"
            "      \"capabilities\": {\n"
            "        \"exec\": false,\n"
            "        \"mcp\": false,\n"
            "        \"network\": false\n"
            "      },\n"
            "      \"dependencies\": {\n"
            "        \"@acme/base\": \"1.2.0\"\n"
            "      },\n"
            "      \"integrity\": \"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\n"
            "      \"resolved\": {\n"
            "        \"commit\": \"0123456789abcdef\",\n"
            "        \"ref\": \"refs/tags/v2.1.0\"\n"
            "      },\n"
            "      \"source\": {\n"
            "        \"type\": \"git\",\n"
            "        \"url\": \"https://github.com/acme/quality-skills.git\"\n"
            "      }\n"
            "    }\n"
            "  },\n"
            "  \"specVersion\": \"0.1\"\n"
            "}\n"
        )
        assert p.read_text(encoding="utf-8") == expected

    def test_unknown_or_invalid_schema_raises_deterministic_exception(self, tmp_path: Path):
        p = tmp_path / "botpack.lock"

        # Unsupported lockfileVersion
        p.write_text(
            json.dumps(
                {
                    "lockfileVersion": 2,
                    "botpackVersion": "0.1.0",
                    "specVersion": "0.1",
                    "dependencies": {},
                    "packages": {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with pytest.raises(LockfileError) as excinfo:
            load_lock(p)
        assert str(excinfo.value) == "Unsupported lockfileVersion: 2 (expected 1)"
