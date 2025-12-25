from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkspaceConfig:
    """Config for the [assets] section (legacy: [workspace]).

    v0.3 changed the default assets directory from `.botpack/workspace` to `botpack/`.
    The internal type name is kept as WorkspaceConfig for now to avoid a large rename;
    the TOML key is `[assets]` (with `[workspace]` as a backward-compat alias).
    """

    dir: str = "botpack"
    name: str | None = None
    private: bool = True


# Type alias for clarity - the manifest section is now called [assets]
AssetsConfig = WorkspaceConfig


@dataclass(frozen=True)
class SemverDependency:
    spec: str


@dataclass(frozen=True)
class GitDependency:
    git: str
    rev: str | None = None


@dataclass(frozen=True)
class PathDependency:
    path: str


@dataclass(frozen=True)
class UrlDependency:
    url: str
    integrity: str | None = None


Dependency = SemverDependency | GitDependency | PathDependency | UrlDependency


@dataclass(frozen=True)
class SyncConfig:
    on_add: bool = True
    on_install: bool = True
    catalog: bool = True
    link_mode: str = "auto"  # auto|symlink|hardlink|copy


@dataclass(frozen=True)
class TargetConfig:
    root: str | None = None
    skills_dir: str | None = None
    commands_dir: str | None = None
    agents_dir: str | None = None
    mcp_out: str | None = None
    policy_mode: str | None = None
    skills_fallback_root: str | None = None
    skills_fallback_dir: str | None = None


@dataclass(frozen=True)
class AliasesConfig:
    skills: dict[str, str] = field(default_factory=dict)
    commands: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EntryConfig:
    """Default launch selection.

    This matches SPEC.md's `[entry]` table.
    """

    agent: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class BotyardConfig:
    version: int
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    dependencies: dict[str, Dependency] = field(default_factory=dict)
    sync: SyncConfig = field(default_factory=SyncConfig)
    targets: dict[str, TargetConfig] = field(default_factory=dict)
    aliases: AliasesConfig = field(default_factory=AliasesConfig)
    entry: EntryConfig = field(default_factory=EntryConfig)
    overrides: dict[str, Any] = field(default_factory=dict)


# -------------------------
# agentpkg.toml


@dataclass(frozen=True)
class PackageCapabilities:
    exec: bool = False
    network: bool = False
    mcp: bool = False


@dataclass(frozen=True)
class PackageCompat:
    requires: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PackageExports:
    skills: list[str] | None = None
    commands: list[str] | None = None
    agents: list[str] | None = None


@dataclass(frozen=True)
class AgentPackageConfig:
    agentpkg: str
    name: str
    version: str
    description: str | None = None
    license: str | None = None
    repository: str | None = None
    compat: PackageCompat = field(default_factory=PackageCompat)
    exports: PackageExports = field(default_factory=PackageExports)
    capabilities: PackageCapabilities = field(default_factory=PackageCapabilities)


# -------------------------
# trust.toml


@dataclass(frozen=True)
class McpTrust:
    allow_exec: bool = False
    allow_mcp: bool = False


@dataclass(frozen=True)
class TrustDigest:
    integrity: str


@dataclass(frozen=True)
class TrustEntry:
    allow_exec: bool = False
    allow_mcp: bool = False
    digest: TrustDigest | None = None
    mcp: dict[str, McpTrust] = field(default_factory=dict)


@dataclass(frozen=True)
class TrustConfig:
    version: int
    packages: dict[str, TrustEntry] = field(default_factory=dict)
