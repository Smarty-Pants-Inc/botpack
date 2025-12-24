from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FixtureSpec:
    pkg_name: str
    pkg_version: str
    pkg_key: str
    pkg_relpath: Path


DEFAULT_FIXTURE = FixtureSpec(
    pkg_name="@fixture/shared-pack",
    pkg_version="0.1.0",
    pkg_key="@fixture/shared-pack@0.1.0",
    pkg_relpath=Path("deps") / "shared-pack",
)


def write_fixture_project(
    *,
    root: Path,
    python_exe: str,
    spec: FixtureSpec = DEFAULT_FIXTURE,
) -> None:
    """Create a deterministic Botpack project fixture.

    The fixture is designed for automation:
    - Includes all asset types (skills/commands/agents)
    - Includes workspace + package MCP servers
    - Includes a path dependency to exercise lock/store/pkgs materialization
    """

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    # botpack.toml
    (root / "botpack.toml").write_text(
        (
            "version = 1\n\n"
            "[workspace]\n"
            "dir = \".botpack/workspace\"\n"
            "private = true\n\n"
            "[dependencies]\n"
            f"\"{spec.pkg_name}\" = {{ path = \"{spec.pkg_relpath.as_posix()}\" }}\n\n"
            "[sync]\n"
            "linkMode = \"auto\"\n"
        ),
        encoding="utf-8",
    )

    # trust.toml (trust workspace + package servers)
    trust = root / ".botpack" / "trust.toml"
    trust.parent.mkdir(parents=True, exist_ok=True)
    trust.write_text(
        (
            "version = 1\n\n"
            "[__workspace__]\n"
            "allowExec = true\n"
            "allowMcp = true\n\n"
            f"[\"{spec.pkg_key}\"]\n"
            "allowExec = true\n"
            "allowMcp = true\n"
        ),
        encoding="utf-8",
    )

    ws = root / ".botpack" / "workspace"

    # Workspace skill
    skill_dir = ws / "skills" / "fixture-skill"
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            "id: fixture-skill\n"
            "name: Fixture Skill\n"
            "description: Deterministic fixture skill for Botpack matrix\n"
            "---\n\n"
            "This is a fixture skill.\n"
        ),
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "hello.py").write_text(
        (
            "# /// script\n"
            "# requires-python = \">=3.10\"\n"
            "# dependencies = []\n"
            "# ///\n"
            "print('fixture-skill:hello')\n"
        ),
        encoding="utf-8",
    )

    # Workspace command
    (ws / "commands").mkdir(parents=True, exist_ok=True)
    (ws / "commands" / "hello.md").write_text(
        "# hello\n\nThis is a deterministic fixture command.\n",
        encoding="utf-8",
    )

    # Workspace agent
    (ws / "agents").mkdir(parents=True, exist_ok=True)
    (ws / "agents" / "echo.md").write_text(
        "# echo\n\nEcho agent fixture.\n",
        encoding="utf-8",
    )

    # Workspace MCP
    (ws / "mcp").mkdir(parents=True, exist_ok=True)
    (ws / "mcp" / "servers.toml").write_text(
        (
            "version = 1\n\n"
            "[[server]]\n"
            "id = \"magic-number\"\n"
            "name = \"Workspace magic-number (fixture)\"\n"
            f"command = \"{python_exe}\"\n"
            "args = [\"-m\", \"botpack.mcp_magic_number_server\"]\n"
        ),
        encoding="utf-8",
    )

    # Package dependency
    pkg_root = root / spec.pkg_relpath
    pkg_root.mkdir(parents=True, exist_ok=True)
    (pkg_root / "agentpkg.toml").write_text(
        (
            'agentpkg = "0.1"\n'
            f'name = "{spec.pkg_name}"\n'
            f'version = "{spec.pkg_version}"\n'
            "\n"
            "[capabilities]\n"
            "exec = true\n"
            "mcp = true\n"
        ),
        encoding="utf-8",
    )

    # Package assets
    (pkg_root / "skills" / "pkg-skill" / "scripts").mkdir(parents=True, exist_ok=True)
    (pkg_root / "skills" / "pkg-skill" / "SKILL.md").write_text(
        (
            "---\n"
            "id: pkg-skill\n"
            "name: Package Skill\n"
            "description: Fixture package skill\n"
            "---\n\n"
            "Package skill.\n"
        ),
        encoding="utf-8",
    )
    (pkg_root / "skills" / "pkg-skill" / "scripts" / "pkg_hello.py").write_text(
        "print('pkg-skill:hello')\n",
        encoding="utf-8",
    )

    (pkg_root / "commands").mkdir(parents=True, exist_ok=True)
    (pkg_root / "commands" / "pkg-hello.md").write_text(
        "# pkg-hello\n\nFixture package command.\n",
        encoding="utf-8",
    )

    (pkg_root / "agents").mkdir(parents=True, exist_ok=True)
    (pkg_root / "agents" / "pkg-agent.md").write_text(
        "# pkg-agent\n\nFixture package agent.\n",
        encoding="utf-8",
    )

    (pkg_root / "mcp").mkdir(parents=True, exist_ok=True)
    (pkg_root / "mcp" / "servers.toml").write_text(
        (
            "version = 1\n\n"
            "[[server]]\n"
            "id = \"pkg-magic-number\"\n"
            "name = \"Package magic-number (fixture)\"\n"
            f"command = \"{python_exe}\"\n"
            "args = [\"-m\", \"botpack.mcp_magic_number_server\"]\n"
        ),
        encoding="utf-8",
    )
