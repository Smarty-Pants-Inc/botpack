"""Letta Code target materialization helpers.

This module handles materialization of the `.letta/` directory,
which is the target output for Letta Code integration.

Key responsibilities (per SPEC.md section 17.4):
- Write `.letta/settings.json` with managed configuration
- PRESERVE `.letta/settings.local.json` (local bindings/caches)
- Never overwrite user's local settings

The `.letta/` directory structure:
    .letta/
        settings.json           # Botpack-managed (Git-tracked)
        settings.local.json     # User-local (Git-ignored, NEVER overwritten)
        agents/                 # Agent-specific data (future)

This is analogous to other targets like `.claude/` but specific
to Letta Code runtime configuration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class LettaMaterializeResult:
    """Result of materializing Letta Code target files.

    Tracks what files were created/updated and any issues encountered.
    """

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)  # Files intentionally not touched
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0 and len(self.conflicts) == 0


# ---------------------------------------------------------------------------
# Settings file schemas
# ---------------------------------------------------------------------------


@dataclass
class LettaSettingsConfig:
    """Configuration to write to .letta/settings.json.

    This is the managed/shared configuration that Botpack controls.

    Attributes:
        api_url: Default Letta API URL (can be overridden in local settings)
        default_agent: Default agent name to use
        memory_blocks: List of memory block labels to auto-load
        mcp_servers: List of MCP server IDs to enable
        model: Default model to use
        custom: Any additional custom settings
    """

    api_url: str | None = None
    default_agent: str | None = None
    memory_blocks: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    model: str | None = None
    custom: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {}
        if self.api_url:
            result["api_url"] = self.api_url
        if self.default_agent:
            result["default_agent"] = self.default_agent
        if self.memory_blocks:
            result["memory_blocks"] = self.memory_blocks
        if self.mcp_servers:
            result["mcp_servers"] = self.mcp_servers
        if self.model:
            result["model"] = self.model
        if self.custom:
            result.update(self.custom)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LettaSettingsConfig":
        """Create from dictionary."""
        known_keys = {"api_url", "default_agent", "memory_blocks", "mcp_servers", "model"}
        custom = {k: v for k, v in data.items() if k not in known_keys}
        return cls(
            api_url=data.get("api_url"),
            default_agent=data.get("default_agent"),
            memory_blocks=data.get("memory_blocks", []),
            mcp_servers=data.get("mcp_servers", []),
            model=data.get("model"),
            custom=custom,
        )


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


def _sha256_bytes(b: bytes) -> str:
    """Compute SHA256 hash of bytes."""
    return hashlib.sha256(b).hexdigest()


def _safe_write_json(path: Path, data: dict[str, Any], *, dry_run: bool = False) -> bool:
    """Safely write JSON file with atomic replacement.

    Args:
        path: Target file path
        data: Data to serialize as JSON
        dry_run: If True, don't actually write

    Returns:
        True if file was written (or would be written in dry_run)
    """
    if dry_run:
        return True

    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write via temp file
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    return True


def _read_json_safe(path: Path) -> dict[str, Any] | None:
    """Read JSON file, returning None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Main materialization function
# ---------------------------------------------------------------------------


def materialize_letta_settings(
    *,
    root: Path | None = None,
    config: LettaSettingsConfig | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> LettaMaterializeResult:
    """Materialize Letta Code target configuration files.

    This writes `.letta/settings.json` with managed configuration while
    PRESERVING `.letta/settings.local.json` (user's local settings).

    Per SPEC.md section 17.4:
    - Botpack may write `.letta/settings.json`
    - Botpack MUST preserve `.letta/settings.local.json`

    Args:
        root: Project root directory (default: current working directory)
        config: Settings configuration to write (default: minimal config)
        dry_run: If True, report changes without writing
        force: If True, overwrite existing settings.json even if modified

    Returns:
        LettaMaterializeResult with status of materialized files

    Example:
        # Basic materialization
        result = materialize_letta_settings()

        # With custom config
        config = LettaSettingsConfig(
            default_agent="my-agent",
            memory_blocks=["project", "conventions"],
        )
        result = materialize_letta_settings(config=config)

        # Dry run to preview changes
        result = materialize_letta_settings(dry_run=True)
    """
    from ..paths import work_root

    if root is None:
        root = work_root()

    if config is None:
        config = LettaSettingsConfig()

    result = LettaMaterializeResult()
    letta_dir = root / ".letta"
    settings_path = letta_dir / "settings.json"
    local_settings_path = letta_dir / "settings.local.json"

    # CRITICAL: Always preserve settings.local.json
    if local_settings_path.exists():
        result.preserved.append(str(local_settings_path))

    # Prepare settings content
    settings_data = config.to_dict()

    # Add metadata
    settings_data["_botpack"] = {
        "managed": True,
        "version": 1,
    }

    # Check existing settings.json
    existing = _read_json_safe(settings_path)
    new_content = json.dumps(settings_data, indent=2, sort_keys=True) + "\n"

    if existing is not None:
        existing_content = json.dumps(existing, indent=2, sort_keys=True) + "\n"

        # Check if content differs
        if existing_content == new_content:
            # No changes needed
            return result

        # Check if file was modified outside Botpack
        botpack_meta = existing.get("_botpack", {})
        if not botpack_meta.get("managed") and not force:
            result.conflicts.append(
                f"{settings_path}: Modified outside Botpack. Use --force to overwrite."
            )
            return result

        # Update existing file
        if _safe_write_json(settings_path, settings_data, dry_run=dry_run):
            result.updated.append(str(settings_path))
    else:
        # Create new file
        if _safe_write_json(settings_path, settings_data, dry_run=dry_run):
            result.created.append(str(settings_path))

    return result


def load_letta_settings(root: Path | None = None) -> LettaSettingsConfig | None:
    """Load existing Letta settings from .letta/settings.json.

    Args:
        root: Project root directory (default: current working directory)

    Returns:
        LettaSettingsConfig if settings exist, None otherwise
    """
    from ..paths import work_root

    if root is None:
        root = work_root()

    settings_path = root / ".letta" / "settings.json"
    data = _read_json_safe(settings_path)

    if data is None:
        return None

    # Remove internal metadata before parsing
    data.pop("_botpack", None)

    return LettaSettingsConfig.from_dict(data)


def ensure_letta_directory(root: Path | None = None) -> Path:
    """Ensure .letta/ directory exists.

    Creates the directory if it doesn't exist.

    Args:
        root: Project root directory (default: current working directory)

    Returns:
        Path to .letta/ directory
    """
    from ..paths import work_root

    if root is None:
        root = work_root()

    letta_dir = root / ".letta"
    letta_dir.mkdir(parents=True, exist_ok=True)
    return letta_dir
