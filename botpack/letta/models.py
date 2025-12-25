"""Data structures for Letta managed resources and observed runtime state.

This module defines the core models for Letta integration:
- Managed resources: What Botpack intends to deploy (derived from Git)
- Observed state: What currently exists in the Letta runtime

Key resource types (per SPEC.md section 17.1):
- Memory blocks (shared repo/org/company docs)
- Templates / agent definitions
- Tools (optional v1)
- MCP servers
- Letta filesystem folders/sources

Never managed (excluded):
- Message history
- Runs/steps
- Telemetry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


# ---------------------------------------------------------------------------
# Asset addressing (per SPEC.md section 2.1.2)
# Format: letta:<type>:<id>
# Examples: letta:block:project, letta:block:conventions, letta:template:dev
# ---------------------------------------------------------------------------


class LettaResourceType(str, Enum):
    """Types of Letta resources that Botpack can manage."""

    BLOCK = "block"
    TEMPLATE = "template"
    TOOL = "tool"
    MCP = "mcp"
    FOLDER = "folder"
    AGENT = "agent"


@dataclass(frozen=True)
class LettaAssetAddress:
    """Stable identifier for a Letta resource.

    Asset addresses are the primary UX primitive for diagnostics, conflicts,
    and selection mechanisms. Paths are secondary (for debugging).

    Format: letta:<type>:<id>

    Examples:
        letta:block:project
        letta:block:conventions
        letta:template:dev-agent
        letta:mcp:github
    """

    resource_type: LettaResourceType
    id: str

    def __str__(self) -> str:
        return f"letta:{self.resource_type.value}:{self.id}"

    @classmethod
    def parse(cls, address: str) -> "LettaAssetAddress":
        """Parse an asset address string.

        Args:
            address: String in format "letta:<type>:<id>"

        Returns:
            LettaAssetAddress instance

        Raises:
            ValueError: If address format is invalid
        """
        parts = address.split(":", 2)
        if len(parts) != 3 or parts[0] != "letta":
            raise ValueError(f"Invalid Letta asset address: {address!r}")
        try:
            resource_type = LettaResourceType(parts[1])
        except ValueError:
            raise ValueError(f"Unknown Letta resource type: {parts[1]!r}")
        return cls(resource_type=resource_type, id=parts[2])


# ---------------------------------------------------------------------------
# Block label to path mapping (per SPEC.md section 17.3)
# Convention: botpack/letta/blocks/<scope>/<label>.md
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LettaBlockPathMapping:
    """Maps block labels to canonical file paths.

    Per SPEC.md section 17.3 conventions:
    - block label `project` => `botpack/letta/blocks/repo/project.md`
    - block label `conventions` => `botpack/letta/blocks/repo/conventions.md`
    - block label `org_agent_playbook` => `botpack/letta/blocks/org/org_agent_playbook.md`
    - block label `scope_<name>_project` => `botpack/letta/blocks/scopes/<name>/project.md`
    """

    label: str
    scope: str  # "repo", "org", "scopes/<name>"
    relative_path: str  # e.g., "blocks/repo/project.md"

    @classmethod
    def from_label(cls, label: str) -> "LettaBlockPathMapping":
        """Derive path mapping from a block label.

        Args:
            label: The Letta block label (e.g., "project", "scope_myproj_project")

        Returns:
            LettaBlockPathMapping with scope and path derived from label
        """
        # Handle scope-prefixed labels: scope_<name>_<suffix>
        if label.startswith("scope_"):
            parts = label.split("_", 2)
            if len(parts) >= 3:
                scope_name = parts[1]
                suffix = parts[2]
                return cls(
                    label=label,
                    scope=f"scopes/{scope_name}",
                    relative_path=f"blocks/scopes/{scope_name}/{suffix}.md",
                )

        # Handle org-prefixed labels: org_<suffix>
        if label.startswith("org_"):
            suffix = label[4:]  # Remove "org_" prefix
            return cls(
                label=label,
                scope="org",
                relative_path=f"blocks/org/{suffix}.md",
            )

        # Default: repo-level blocks
        return cls(
            label=label,
            scope="repo",
            relative_path=f"blocks/repo/{label}.md",
        )


# ---------------------------------------------------------------------------
# Core managed resource types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LettaBlock:
    """A Letta memory block managed by Botpack.

    Memory blocks are shared repo/org/company docs that are version-controlled
    and deployed to Letta via PR-only governance.

    Attributes:
        label: The block's unique label (e.g., "project", "conventions")
        description: Human-readable description of the block's purpose
        value: The block content (markdown text)
        source_path: Path to the source file in Git (e.g., botpack/letta/blocks/repo/project.md)
        letta_id: The Letta server's ID for this block (populated when observed)
    """

    label: str
    description: str
    value: str
    source_path: Path | None = None
    letta_id: str | None = None

    @property
    def address(self) -> LettaAssetAddress:
        return LettaAssetAddress(LettaResourceType.BLOCK, self.label)


@dataclass(frozen=True)
class LettaTemplate:
    """A Letta agent template managed by Botpack.

    Templates define agent configurations that can be instantiated.

    Attributes:
        id: Template identifier
        name: Display name
        description: Template description
        system_prompt: The system prompt for agents created from this template
        model: The LLM model to use
        tools: List of tool IDs to attach
        memory_blocks: List of block labels to include
        source_path: Path to source file
        letta_id: Letta server ID (when observed)
    """

    id: str
    name: str
    description: str
    system_prompt: str
    model: str | None = None
    tools: list[str] = field(default_factory=list)
    memory_blocks: list[str] = field(default_factory=list)
    source_path: Path | None = None
    letta_id: str | None = None

    @property
    def address(self) -> LettaAssetAddress:
        return LettaAssetAddress(LettaResourceType.TEMPLATE, self.id)


@dataclass(frozen=True)
class LettaTool:
    """A Letta tool managed by Botpack.

    Tools are callable functions that agents can use.

    Attributes:
        id: Tool identifier
        name: Display name
        description: Tool description
        source_code: Python source code for the tool
        source_path: Path to source file
        letta_id: Letta server ID (when observed)
    """

    id: str
    name: str
    description: str
    source_code: str
    source_path: Path | None = None
    letta_id: str | None = None

    @property
    def address(self) -> LettaAssetAddress:
        return LettaAssetAddress(LettaResourceType.TOOL, self.id)


@dataclass(frozen=True)
class LettaMcpServer:
    """A Letta MCP server configuration managed by Botpack.

    MCP servers extend agent capabilities through the Model Context Protocol.

    Attributes:
        id: Server identifier (namespace/name format)
        name: Display name
        transport: "stdio" or "sse"
        command: Command to run (for stdio)
        args: Command arguments (for stdio)
        url: Server URL (for sse)
        env: Environment variables
        source_path: Path to source config
        letta_id: Letta server ID (when observed)
    """

    id: str
    name: str
    transport: str  # "stdio" | "sse"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    source_path: Path | None = None
    letta_id: str | None = None

    @property
    def address(self) -> LettaAssetAddress:
        return LettaAssetAddress(LettaResourceType.MCP, self.id)


@dataclass(frozen=True)
class LettaFolder:
    """A Letta filesystem folder/source managed by Botpack.

    Folders define file system sources that agents can access.

    Attributes:
        id: Folder identifier
        name: Display name
        path: File system path
        description: Folder description
        source_path: Path to source config
        letta_id: Letta server ID (when observed)
    """

    id: str
    name: str
    path: str
    description: str | None = None
    source_path: Path | None = None
    letta_id: str | None = None

    @property
    def address(self) -> LettaAssetAddress:
        return LettaAssetAddress(LettaResourceType.FOLDER, self.id)


@dataclass(frozen=True)
class LettaAgentConfig:
    """A Letta agent configuration managed by Botpack.

    Agent configs define persistent agent instances that can be deployed.

    Attributes:
        id: Agent identifier
        name: Display name
        template_id: Template to instantiate from (if any)
        description: Agent description
        source_path: Path to source config
        letta_id: Letta server agent ID (when observed)
    """

    id: str
    name: str
    template_id: str | None = None
    description: str | None = None
    source_path: Path | None = None
    letta_id: str | None = None

    @property
    def address(self) -> LettaAssetAddress:
        return LettaAssetAddress(LettaResourceType.AGENT, self.id)


# ---------------------------------------------------------------------------
# State containers: Managed (Git) vs Observed (Letta runtime)
# ---------------------------------------------------------------------------


@dataclass
class LettaManagedState:
    """Desired state for Letta resources, derived from Git.

    This represents what Botpack intends to deploy to Letta, based on
    the contents of `botpack/letta/` in the repository.

    All resources here are version-controlled and subject to PR-only governance.
    """

    blocks: dict[str, LettaBlock] = field(default_factory=dict)
    templates: dict[str, LettaTemplate] = field(default_factory=dict)
    tools: dict[str, LettaTool] = field(default_factory=dict)
    mcp_servers: dict[str, LettaMcpServer] = field(default_factory=dict)
    folders: dict[str, LettaFolder] = field(default_factory=dict)
    agents: dict[str, LettaAgentConfig] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not any([
            self.blocks,
            self.templates,
            self.tools,
            self.mcp_servers,
            self.folders,
            self.agents,
        ])


@dataclass
class LettaObservedState:
    """Current state of Letta resources observed at runtime.

    This represents what actually exists in the Letta server, obtained
    by querying the Letta API.

    Comparing managed state to observed state reveals drift.
    """

    blocks: dict[str, LettaBlock] = field(default_factory=dict)
    templates: dict[str, LettaTemplate] = field(default_factory=dict)
    tools: dict[str, LettaTool] = field(default_factory=dict)
    mcp_servers: dict[str, LettaMcpServer] = field(default_factory=dict)
    folders: dict[str, LettaFolder] = field(default_factory=dict)
    agents: dict[str, LettaAgentConfig] = field(default_factory=dict)

    # Metadata about observation
    observed_at: datetime | None = None
    agent_id: str | None = None  # The Letta agent instance these were observed from

    @property
    def is_empty(self) -> bool:
        return not any([
            self.blocks,
            self.templates,
            self.tools,
            self.mcp_servers,
            self.folders,
            self.agents,
        ])


# ---------------------------------------------------------------------------
# Diff types for drift detection
# ---------------------------------------------------------------------------


class LettaDriftDirection(str, Enum):
    """Direction of drift between managed and observed state."""

    # Resource exists in Git but not in Letta (need to push)
    ADDED_IN_GIT = "added_in_git"

    # Resource exists in Letta but not in Git (need to pull or delete)
    ADDED_IN_LETTA = "added_in_letta"

    # Resource differs: Git is newer (need to push)
    MODIFIED_IN_GIT = "modified_in_git"

    # Resource differs: Letta is newer (need to pull)
    MODIFIED_IN_LETTA = "modified_in_letta"

    # Resource differs but unclear which is newer (conflict)
    CONFLICT = "conflict"


@dataclass(frozen=True)
class LettaDiffItem:
    """A single difference between managed and observed state.

    Used by `letta diff` and `letta status` to report drift.

    Attributes:
        address: The asset address (e.g., letta:block:project)
        direction: Type/direction of the drift
        managed_value: Value from Git (if present)
        observed_value: Value from Letta (if present)
        message: Human-readable description of the difference
    """

    address: LettaAssetAddress
    direction: LettaDriftDirection
    managed_value: str | None = None
    observed_value: str | None = None
    message: str | None = None

    def __str__(self) -> str:
        prefix = {
            LettaDriftDirection.ADDED_IN_GIT: "+",
            LettaDriftDirection.ADDED_IN_LETTA: "?",
            LettaDriftDirection.MODIFIED_IN_GIT: "M",
            LettaDriftDirection.MODIFIED_IN_LETTA: "~",
            LettaDriftDirection.CONFLICT: "!",
        }.get(self.direction, " ")
        return f"{prefix} {self.address}"


@dataclass
class LettaDiffResult:
    """Result of comparing managed state to observed state.

    This is the output of `letta diff` and is used to determine
    what actions `push` or `pull` would take.
    """

    items: list[LettaDiffItem] = field(default_factory=list)
    managed_state: LettaManagedState | None = None
    observed_state: LettaObservedState | None = None

    @property
    def has_drift(self) -> bool:
        """Returns True if any differences were found."""
        return len(self.items) > 0

    @property
    def has_letta_changes(self) -> bool:
        """Returns True if Letta has changes not in Git (drift requiring pull)."""
        return any(
            item.direction in (LettaDriftDirection.ADDED_IN_LETTA, LettaDriftDirection.MODIFIED_IN_LETTA)
            for item in self.items
        )

    @property
    def has_git_changes(self) -> bool:
        """Returns True if Git has changes not in Letta (changes requiring push)."""
        return any(
            item.direction in (LettaDriftDirection.ADDED_IN_GIT, LettaDriftDirection.MODIFIED_IN_GIT)
            for item in self.items
        )

    @property
    def has_conflicts(self) -> bool:
        """Returns True if there are conflicting changes."""
        return any(item.direction == LettaDriftDirection.CONFLICT for item in self.items)

    @property
    def items_by_direction(self) -> dict[LettaDriftDirection, list[LettaDiffItem]]:
        """Group diff items by drift direction."""
        result: dict[LettaDriftDirection, list[LettaDiffItem]] = {}
        for item in self.items:
            if item.direction not in result:
                result[item.direction] = []
            result[item.direction].append(item)
        return result
