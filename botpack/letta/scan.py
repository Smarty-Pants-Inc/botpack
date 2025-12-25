"""Scan Letta assets from the botpack/letta/ directory.

This module scans the file system for Letta-managed resources and
constructs the LettaManagedState representing desired deployment state.

Directory structure (per SPEC.md section 17.3):
    botpack/letta/
        blocks/
            repo/           # Repo-level blocks
                project.md
                conventions.md
            org/            # Org-level blocks
                org_agent_playbook.md
            scopes/         # Scope-specific blocks
                <name>/
                    project.md
        templates/          # Agent templates
            dev.yaml
        tools/              # Custom tools
            fetch_data.py
        mcp/                # MCP server configs
            servers.toml
        agents/             # Agent configurations
            default.yaml
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (
    LettaBlock,
    LettaTemplate,
    LettaTool,
    LettaMcpServer,
    LettaFolder,
    LettaAgentConfig,
    LettaManagedState,
    LettaBlockPathMapping,
)


# ---------------------------------------------------------------------------
# Frontmatter parsing (YAML-style)
# ---------------------------------------------------------------------------

_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class ParsedDocument:
    """A parsed document with frontmatter and body."""

    frontmatter: dict[str, Any]
    body: str
    raw: str


def parse_frontmatter(content: str) -> ParsedDocument:
    """Parse YAML frontmatter from a markdown document.

    Args:
        content: Raw file content

    Returns:
        ParsedDocument with frontmatter dict and body text
    """
    match = _FRONTMATTER_PATTERN.match(content)
    if not match:
        return ParsedDocument(frontmatter={}, body=content.strip(), raw=content)

    frontmatter_text = match.group(1)
    body = content[match.end() :].strip()

    # Simple YAML-like parsing (key: value)
    # For production, consider using a proper YAML parser
    frontmatter: dict[str, Any] = {}
    for line in frontmatter_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Handle quoted strings
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            frontmatter[key] = value

    return ParsedDocument(frontmatter=frontmatter, body=body, raw=content)


# ---------------------------------------------------------------------------
# Block scanning
# ---------------------------------------------------------------------------


def _derive_block_label_from_path(rel_path: Path) -> str:
    """Derive a block label from its relative path.

    Examples:
        blocks/repo/project.md -> project
        blocks/org/agent_playbook.md -> org_agent_playbook
        blocks/scopes/myproj/project.md -> scope_myproj_project

    Args:
        rel_path: Path relative to letta/ directory

    Returns:
        Block label string
    """
    parts = rel_path.parts

    # Expected: blocks/<scope>/.../<name>.md
    if len(parts) < 3 or parts[0] != "blocks":
        # Fallback: use stem
        return rel_path.stem

    scope = parts[1]  # "repo", "org", or "scopes"
    name = rel_path.stem  # filename without .md

    if scope == "repo":
        return name
    elif scope == "org":
        return f"org_{name}"
    elif scope == "scopes" and len(parts) >= 4:
        scope_name = parts[2]
        return f"scope_{scope_name}_{name}"
    else:
        return name


def scan_blocks(letta_dir: Path) -> dict[str, LettaBlock]:
    """Scan for memory block definitions.

    Args:
        letta_dir: Path to botpack/letta/ directory

    Returns:
        Dict mapping block label to LettaBlock
    """
    blocks: dict[str, LettaBlock] = {}
    blocks_dir = letta_dir / "blocks"

    if not blocks_dir.exists():
        return blocks

    for md_path in blocks_dir.rglob("*.md"):
        if not md_path.is_file():
            continue

        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError:
            continue

        parsed = parse_frontmatter(content)
        rel_path = md_path.relative_to(letta_dir)

        # Derive label from path or frontmatter
        label = parsed.frontmatter.get("label") or _derive_block_label_from_path(rel_path)
        description = parsed.frontmatter.get("description", f"Memory block: {label}")

        blocks[label] = LettaBlock(
            label=label,
            description=description,
            value=parsed.body,
            source_path=md_path,
        )

    return blocks


# ---------------------------------------------------------------------------
# Template scanning
# ---------------------------------------------------------------------------


def scan_templates(letta_dir: Path) -> dict[str, LettaTemplate]:
    """Scan for agent template definitions.

    Templates can be defined as YAML or TOML files.

    Args:
        letta_dir: Path to botpack/letta/ directory

    Returns:
        Dict mapping template ID to LettaTemplate
    """
    templates: dict[str, LettaTemplate] = {}
    templates_dir = letta_dir / "templates"

    if not templates_dir.exists():
        return templates

    # Support .yaml, .yml, .toml
    for ext in ("*.yaml", "*.yml", "*.toml"):
        for path in templates_dir.glob(ext):
            if not path.is_file():
                continue

            template_id = path.stem
            try:
                content = path.read_text(encoding="utf-8")
                # TODO: Parse YAML/TOML content
                # For now, create a placeholder template
                templates[template_id] = LettaTemplate(
                    id=template_id,
                    name=template_id,
                    description=f"Agent template: {template_id}",
                    system_prompt="",  # Would be parsed from file
                    source_path=path,
                )
            except OSError:
                continue

    return templates


# ---------------------------------------------------------------------------
# Tool scanning
# ---------------------------------------------------------------------------


def scan_tools(letta_dir: Path) -> dict[str, LettaTool]:
    """Scan for tool definitions (Python files).

    Args:
        letta_dir: Path to botpack/letta/ directory

    Returns:
        Dict mapping tool ID to LettaTool
    """
    tools: dict[str, LettaTool] = {}
    tools_dir = letta_dir / "tools"

    if not tools_dir.exists():
        return tools

    for py_path in tools_dir.glob("*.py"):
        if not py_path.is_file() or py_path.name.startswith("_"):
            continue

        tool_id = py_path.stem
        try:
            content = py_path.read_text(encoding="utf-8")

            # Extract docstring as description
            description = f"Tool: {tool_id}"
            if content.startswith('"""'):
                end = content.find('"""', 3)
                if end > 3:
                    description = content[3:end].strip()

            tools[tool_id] = LettaTool(
                id=tool_id,
                name=tool_id,
                description=description,
                source_code=content,
                source_path=py_path,
            )
        except OSError:
            continue

    return tools


# ---------------------------------------------------------------------------
# Agent config scanning
# ---------------------------------------------------------------------------


def scan_agents(letta_dir: Path) -> dict[str, LettaAgentConfig]:
    """Scan for agent configuration definitions.

    Args:
        letta_dir: Path to botpack/letta/ directory

    Returns:
        Dict mapping agent ID to LettaAgentConfig
    """
    agents: dict[str, LettaAgentConfig] = {}
    agents_dir = letta_dir / "agents"

    if not agents_dir.exists():
        return agents

    for ext in ("*.yaml", "*.yml", "*.toml", "*.md"):
        for path in agents_dir.glob(ext):
            if not path.is_file():
                continue

            agent_id = path.stem
            try:
                content = path.read_text(encoding="utf-8")
                # TODO: Parse YAML/TOML/MD content for agent config
                agents[agent_id] = LettaAgentConfig(
                    id=agent_id,
                    name=agent_id,
                    description=f"Agent: {agent_id}",
                    source_path=path,
                )
            except OSError:
                continue

    return agents


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------


def scan_letta_assets(letta_dir: Path | None = None) -> LettaManagedState:
    """Scan the botpack/letta/ directory for all managed Letta assets.

    This is the main entry point for discovering what Botpack intends
    to deploy to Letta, based on Git-tracked files.

    Args:
        letta_dir: Path to letta assets directory (default: botpack/letta/)

    Returns:
        LettaManagedState containing all discovered assets
    """
    from ..paths import work_root

    if letta_dir is None:
        root = work_root()
        # Prefer the configured assets directory (v0.3), but fall back to the default
        # `botpack/letta` if config is missing.
        try:
            from ..config import botyard_manifest_path, parse_botyard_toml_file

            manifest = botyard_manifest_path()
            cfg = parse_botyard_toml_file(manifest)
            assets_dir = Path(cfg.workspace.dir)
            if not assets_dir.is_absolute():
                assets_dir = (root / assets_dir).resolve()
            letta_dir = assets_dir / "letta"
        except Exception:
            letta_dir = root / "botpack" / "letta"

    if not letta_dir.exists():
        return LettaManagedState()

    return LettaManagedState(
        blocks=scan_blocks(letta_dir),
        templates=scan_templates(letta_dir),
        tools=scan_tools(letta_dir),
        mcp_servers={},  # TODO: Integrate with existing MCP scanning
        folders={},  # TODO: Implement folder scanning
        agents=scan_agents(letta_dir),
    )
