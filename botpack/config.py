from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from . import paths
from .errors import ConfigParseError, ConfigValidationError
from .models import (
    AgentPackageConfig,
    AliasesConfig,
    BotyardConfig,
    GitDependency,
    McpTrust,
    PackageCapabilities,
    PackageCompat,
    PackageExports,
    PathDependency,
    SemverDependency,
    SyncConfig,
    TargetConfig,
    TrustConfig,
    TrustDigest,
    TrustEntry,
    UrlDependency,
    WorkspaceConfig,
    EntryConfig,
)


try:  # Python 3.11+
    import tomllib as _tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover (dev envs < 3.11)
    import tomli as _tomllib  # type: ignore


_BOTYARD_LINK_MODES = {"auto", "symlink", "hardlink", "copy"}


def botyard_manifest_path() -> Path:
    """Default repo-level project manifest path.

    New default is `botpack.toml`, with a fallback to legacy `botyard.toml`.
    """

    root = paths.work_root()
    new = root / "botpack.toml"
    old = root / "botyard.toml"
    return new if new.exists() or not old.exists() else old


def trust_path() -> Path:
    """Default repo-local trust file path (.botpack/trust.toml)."""

    return paths.botyard_dir() / "trust.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ConfigValidationError(path=path, message="file not found") from e
    except OSError as e:
        raise ConfigValidationError(path=path, message=f"unable to read file: {e}") from e

    try:
        data = _tomllib.loads(text)
    except Exception as e:
        # tomllib/tomli both raise TOMLDecodeError with msg/lineno/colno.
        msg = getattr(e, "msg", str(e))
        lineno = getattr(e, "lineno", None)
        colno = getattr(e, "colno", None)
        raise ConfigParseError(path=path, message=str(msg), lineno=lineno, colno=colno) from e

    if not isinstance(data, dict):
        raise ConfigValidationError(path=path, message="top-level TOML must be a table")
    return data


def _unknown_keys_message(unknown: set[str]) -> str:
    keys = ", ".join(sorted(unknown))
    return f"unknown keys: {keys}"


def _require_table(path: Path, value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(path=path, message=f"{where}: expected table")
    return value


def _optional_table(path: Path, value: Any, where: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _require_table(path, value, where)


def _require_str(path: Path, value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigValidationError(path=path, message=f"{where}: expected string")
    return value


def _optional_str(path: Path, value: Any, where: str) -> str | None:
    if value is None:
        return None
    return _require_str(path, value, where)


def _require_bool(path: Path, value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(path=path, message=f"{where}: expected bool")
    return value


def _optional_bool(path: Path, value: Any, where: str) -> bool | None:
    if value is None:
        return None
    return _require_bool(path, value, where)


def _require_int(path: Path, value: Any, where: str) -> int:
    if not isinstance(value, int):
        raise ConfigValidationError(path=path, message=f"{where}: expected integer")
    return value


def _require_str_list(path: Path, value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigValidationError(path=path, message=f"{where}: expected list of strings")
    return value


def parse_botyard_toml_file(path: Path | None = None) -> BotyardConfig:
    """Load + validate the workspace manifest (botpack.toml / botyard.toml) into a typed config model."""

    p = path or botyard_manifest_path()
    data = _load_toml(p)
    return _parse_botyard(p, data)


def _parse_botyard(path: Path, data: dict[str, Any]) -> BotyardConfig:
    # Accept both "assets" (v0.3+) and "workspace" (legacy) for reading.
    allowed_top = {
        "version",
        "assets",
        "workspace",  # legacy alias
        "dependencies",
        "sync",
        "targets",
        "aliases",
        "entry",
        "overrides",
    }
    unknown_top = set(data.keys()) - allowed_top
    if unknown_top:
        raise ConfigValidationError(path=path, message=_unknown_keys_message(unknown_top))

    version = _require_int(path, data.get("version"), "version")
    if version != 1:
        raise ConfigValidationError(path=path, message=f"version: expected 1, got {version}")

    # Accept both [assets] and [workspace], prefer [assets] if both present (error).
    assets_raw = data.get("assets")
    ws_raw = data.get("workspace")
    if assets_raw is not None and ws_raw is not None:
        raise ConfigValidationError(path=path, message="cannot have both [assets] and [workspace]; use [assets]")

    workspace = WorkspaceConfig()
    # Prefer assets_raw, fall back to ws_raw for backward compat
    combined_tbl = _optional_table(path, assets_raw if assets_raw is not None else ws_raw, "assets")
    if combined_tbl is not None:
        allowed_assets = {"dir", "name", "private"}
        unknown_assets = set(combined_tbl.keys()) - allowed_assets
        if unknown_assets:
            raise ConfigValidationError(path=path, message=f"assets: {_unknown_keys_message(unknown_assets)}")
        if "dir" in combined_tbl:
            workspace = replace(workspace, dir=_require_str(path, combined_tbl.get("dir"), "assets.dir"))
        if "name" in combined_tbl:
            workspace = replace(workspace, name=_optional_str(path, combined_tbl.get("name"), "assets.name"))
        if "private" in combined_tbl:
            workspace = replace(workspace, private=_require_bool(path, combined_tbl.get("private"), "assets.private"))

    # Optional: entry defaults used by `botpack launch`
    entry = EntryConfig()
    entry_tbl = _optional_table(path, data.get("entry"), "entry")
    if entry_tbl is not None:
        allowed_entry = {"agent", "target"}
        unknown_entry = set(entry_tbl.keys()) - allowed_entry
        if unknown_entry:
            raise ConfigValidationError(path=path, message=f"entry: {_unknown_keys_message(unknown_entry)}")
        if "agent" in entry_tbl:
            entry = replace(entry, agent=_optional_str(path, entry_tbl.get("agent"), "entry.agent"))
        if "target" in entry_tbl:
            entry = replace(entry, target=_optional_str(path, entry_tbl.get("target"), "entry.target"))

    # Optional: explicit override rules (schema is intentionally loose in v0.3).
    overrides_tbl = _optional_table(path, data.get("overrides"), "overrides")
    overrides: dict[str, Any] = overrides_tbl or {}

    deps_tbl = data.get("dependencies")
    dependencies: dict[str, Any] = {}
    if deps_tbl is not None:
        deps_dict = _require_table(path, deps_tbl, "dependencies")
        for pkg_name, spec in deps_dict.items():
            if not isinstance(pkg_name, str):
                raise ConfigValidationError(path=path, message="dependencies: package name keys must be strings")
            dependencies[pkg_name] = _parse_dependency(path, pkg_name, spec)

    sync = SyncConfig()
    sync_tbl = _optional_table(path, data.get("sync"), "sync")
    if sync_tbl is not None:
        allowed_sync = {"onAdd", "onInstall", "catalog", "linkMode"}
        unknown_sync = set(sync_tbl.keys()) - allowed_sync
        if unknown_sync:
            raise ConfigValidationError(path=path, message=f"sync: {_unknown_keys_message(unknown_sync)}")
        if "onAdd" in sync_tbl:
            sync = replace(sync, on_add=_require_bool(path, sync_tbl.get("onAdd"), "sync.onAdd"))
        if "onInstall" in sync_tbl:
            sync = replace(sync, on_install=_require_bool(path, sync_tbl.get("onInstall"), "sync.onInstall"))
        if "catalog" in sync_tbl:
            sync = replace(sync, catalog=_require_bool(path, sync_tbl.get("catalog"), "sync.catalog"))
        if "linkMode" in sync_tbl:
            link_mode = _require_str(path, sync_tbl.get("linkMode"), "sync.linkMode")
            if link_mode not in _BOTYARD_LINK_MODES:
                raise ConfigValidationError(
                    path=path,
                    message=f"sync.linkMode: expected one of {sorted(_BOTYARD_LINK_MODES)}, got {link_mode!r}",
                )
            sync = replace(sync, link_mode=link_mode)

    targets: dict[str, TargetConfig] = {}
    targets_tbl = _optional_table(path, data.get("targets"), "targets")
    if targets_tbl is not None:
        for target_name, target_raw in targets_tbl.items():
            if not isinstance(target_name, str):
                raise ConfigValidationError(path=path, message="targets: target name keys must be strings")
            target_tbl = _require_table(path, target_raw, f"targets.{target_name}")
            targets[target_name] = _parse_target(path, target_name, target_tbl)

    aliases = AliasesConfig()
    aliases_tbl = _optional_table(path, data.get("aliases"), "aliases")
    if aliases_tbl is not None:
        allowed_aliases = {"skills", "commands"}
        unknown_aliases = set(aliases_tbl.keys()) - allowed_aliases
        if unknown_aliases:
            raise ConfigValidationError(path=path, message=f"aliases: {_unknown_keys_message(unknown_aliases)}")
        skills_tbl = _optional_table(path, aliases_tbl.get("skills"), "aliases.skills")
        commands_tbl = _optional_table(path, aliases_tbl.get("commands"), "aliases.commands")
        if skills_tbl is not None:
            aliases = replace(aliases, skills=_parse_alias_map(path, skills_tbl, "aliases.skills"))
        if commands_tbl is not None:
            aliases = replace(aliases, commands=_parse_alias_map(path, commands_tbl, "aliases.commands"))

    return BotyardConfig(
        version=version,
        workspace=workspace,
        dependencies=dependencies,
        sync=sync,
        targets=targets,
        aliases=aliases,
        entry=entry,
        overrides=overrides,
    )


def _parse_alias_map(path: Path, tbl: dict[str, Any], where: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in tbl.items():
        if not isinstance(k, str):
            raise ConfigValidationError(path=path, message=f"{where}: keys must be strings")
        out[k] = _require_str(path, v, f"{where}.{k}")
    return out


def _parse_dependency(path: Path, pkg_name: str, spec: Any):
    if isinstance(spec, str):
        return SemverDependency(spec=spec)
    if not isinstance(spec, dict):
        raise ConfigValidationError(path=path, message=f"dependencies.{pkg_name}: expected string or table")

    keys = set(spec.keys())
    # Supported: {git=..., rev=?} | {path=...} | {url=..., integrity=?}
    if "git" in keys:
        allowed = {"git", "rev"}
        unknown = keys - allowed
        if unknown:
            raise ConfigValidationError(
                path=path, message=f"dependencies.{pkg_name}: {_unknown_keys_message(unknown)}"
            )
        git = _require_str(path, spec.get("git"), f"dependencies.{pkg_name}.git")
        rev = _optional_str(path, spec.get("rev"), f"dependencies.{pkg_name}.rev")
        return GitDependency(git=git, rev=rev)

    if "path" in keys:
        allowed = {"path"}
        unknown = keys - allowed
        if unknown:
            raise ConfigValidationError(
                path=path, message=f"dependencies.{pkg_name}: {_unknown_keys_message(unknown)}"
            )
        p = _require_str(path, spec.get("path"), f"dependencies.{pkg_name}.path")
        return PathDependency(path=p)

    if "url" in keys:
        allowed = {"url", "integrity"}
        unknown = keys - allowed
        if unknown:
            raise ConfigValidationError(
                path=path, message=f"dependencies.{pkg_name}: {_unknown_keys_message(unknown)}"
            )
        url = _require_str(path, spec.get("url"), f"dependencies.{pkg_name}.url")
        integrity = _optional_str(path, spec.get("integrity"), f"dependencies.{pkg_name}.integrity")
        return UrlDependency(url=url, integrity=integrity)

    raise ConfigValidationError(
        path=path,
        message=(
            f"dependencies.{pkg_name}: unsupported spec; expected string or one of {{git=...}}, {{path=...}}, {{url=...}}"
        ),
    )


def _parse_target(path: Path, target_name: str, tbl: dict[str, Any]) -> TargetConfig:
    allowed = {
        "root",
        "skillsDir",
        "commandsDir",
        "agentsDir",
        "mcpOut",
        "policyMode",
        "skillsFallbackRoot",
        "skillsFallbackDir",
    }
    unknown = set(tbl.keys()) - allowed
    if unknown:
        raise ConfigValidationError(path=path, message=f"targets.{target_name}: {_unknown_keys_message(unknown)}")

    return TargetConfig(
        root=_optional_str(path, tbl.get("root"), f"targets.{target_name}.root"),
        skills_dir=_optional_str(path, tbl.get("skillsDir"), f"targets.{target_name}.skillsDir"),
        commands_dir=_optional_str(path, tbl.get("commandsDir"), f"targets.{target_name}.commandsDir"),
        agents_dir=_optional_str(path, tbl.get("agentsDir"), f"targets.{target_name}.agentsDir"),
        mcp_out=_optional_str(path, tbl.get("mcpOut"), f"targets.{target_name}.mcpOut"),
        policy_mode=_optional_str(path, tbl.get("policyMode"), f"targets.{target_name}.policyMode"),
        skills_fallback_root=_optional_str(
            path, tbl.get("skillsFallbackRoot"), f"targets.{target_name}.skillsFallbackRoot"
        ),
        skills_fallback_dir=_optional_str(
            path, tbl.get("skillsFallbackDir"), f"targets.{target_name}.skillsFallbackDir"
        ),
    )


def parse_agentpkg_toml(path: Path) -> AgentPackageConfig:
    """Load + validate an agent package manifest (agentpkg.toml)."""

    p = path
    if p.is_dir():
        p = p / "agentpkg.toml"
    data = _load_toml(p)
    return _parse_agentpkg(p, data)


def _parse_agentpkg(path: Path, data: dict[str, Any]) -> AgentPackageConfig:
    allowed_top = {
        "agentpkg",
        "name",
        "version",
        "description",
        "license",
        "repository",
        "compat",
        "exports",
        "capabilities",
    }
    unknown_top = set(data.keys()) - allowed_top
    if unknown_top:
        raise ConfigValidationError(path=path, message=_unknown_keys_message(unknown_top))

    agentpkg = _require_str(path, data.get("agentpkg"), "agentpkg")
    name = _require_str(path, data.get("name"), "name")
    version = _require_str(path, data.get("version"), "version")

    desc = _optional_str(path, data.get("description"), "description")
    lic = _optional_str(path, data.get("license"), "license")
    repo = _optional_str(path, data.get("repository"), "repository")

    compat = PackageCompat()
    compat_tbl = _optional_table(path, data.get("compat"), "compat")
    if compat_tbl is not None:
        allowed_compat = {"requires"}
        unknown_compat = set(compat_tbl.keys()) - allowed_compat
        if unknown_compat:
            raise ConfigValidationError(path=path, message=f"compat: {_unknown_keys_message(unknown_compat)}")
        if "requires" in compat_tbl:
            compat = PackageCompat(requires=_require_str_list(path, compat_tbl.get("requires"), "compat.requires"))

    exports = PackageExports()
    exports_tbl = _optional_table(path, data.get("exports"), "exports")
    if exports_tbl is not None:
        allowed_exports = {"skills", "commands", "agents"}
        unknown_exports = set(exports_tbl.keys()) - allowed_exports
        if unknown_exports:
            raise ConfigValidationError(path=path, message=f"exports: {_unknown_keys_message(unknown_exports)}")
        if "skills" in exports_tbl:
            exports = replace(exports, skills=_require_str_list(path, exports_tbl.get("skills"), "exports.skills"))
        if "commands" in exports_tbl:
            exports = replace(
                exports, commands=_require_str_list(path, exports_tbl.get("commands"), "exports.commands")
            )
        if "agents" in exports_tbl:
            exports = replace(exports, agents=_require_str_list(path, exports_tbl.get("agents"), "exports.agents"))

    capabilities = PackageCapabilities()
    cap_tbl = _optional_table(path, data.get("capabilities"), "capabilities")
    if cap_tbl is not None:
        allowed_cap = {"exec", "network", "mcp"}
        unknown_cap = set(cap_tbl.keys()) - allowed_cap
        if unknown_cap:
            raise ConfigValidationError(path=path, message=f"capabilities: {_unknown_keys_message(unknown_cap)}")
        if "exec" in cap_tbl:
            capabilities = replace(capabilities, exec=_require_bool(path, cap_tbl.get("exec"), "capabilities.exec"))
        if "network" in cap_tbl:
            capabilities = replace(
                capabilities, network=_require_bool(path, cap_tbl.get("network"), "capabilities.network")
            )
        if "mcp" in cap_tbl:
            capabilities = replace(capabilities, mcp=_require_bool(path, cap_tbl.get("mcp"), "capabilities.mcp"))

    return AgentPackageConfig(
        agentpkg=agentpkg,
        name=name,
        version=version,
        description=desc,
        license=lic,
        repository=repo,
        compat=compat,
        exports=exports,
        capabilities=capabilities,
    )


def parse_trust_toml_file(path: Path | None = None) -> TrustConfig:
    """Load + validate trust.toml."""

    p = path or trust_path()
    try:
        data = _load_toml(p)
    except ConfigValidationError as e:
        if e.message == "file not found":
            return TrustConfig(version=1, packages={})
        raise
    return _parse_trust(p, data)


def _parse_trust(path: Path, data: dict[str, Any]) -> TrustConfig:
    if "version" not in data:
        raise ConfigValidationError(path=path, message="version: required")
    version = _require_int(path, data.get("version"), "version")
    if version != 1:
        raise ConfigValidationError(path=path, message=f"version: expected 1, got {version}")

    packages: dict[str, TrustEntry] = {}
    for key, raw in data.items():
        if key == "version":
            continue
        if not isinstance(key, str):
            raise ConfigValidationError(path=path, message="trust entries: keys must be strings")
        entry_tbl = _require_table(path, raw, f"{key}")
        packages[key] = _parse_trust_entry(path, key, entry_tbl)

    return TrustConfig(version=version, packages=packages)


def _parse_trust_entry(path: Path, pkg_ref: str, tbl: dict[str, Any]) -> TrustEntry:
    allowed = {"allowExec", "allowMcp", "digest", "mcp"}
    unknown = set(tbl.keys()) - allowed
    if unknown:
        raise ConfigValidationError(path=path, message=f"{pkg_ref}: {_unknown_keys_message(unknown)}")

    allow_exec = False
    allow_mcp = False
    if "allowExec" in tbl:
        allow_exec = _require_bool(path, tbl.get("allowExec"), f"{pkg_ref}.allowExec")
    if "allowMcp" in tbl:
        allow_mcp = _require_bool(path, tbl.get("allowMcp"), f"{pkg_ref}.allowMcp")

    digest_obj: TrustDigest | None = None
    if "digest" in tbl:
        digest_tbl = _require_table(path, tbl.get("digest"), f"{pkg_ref}.digest")
        allowed_digest = {"integrity"}
        unknown_digest = set(digest_tbl.keys()) - allowed_digest
        if unknown_digest:
            raise ConfigValidationError(path=path, message=f"{pkg_ref}.digest: {_unknown_keys_message(unknown_digest)}")
        integrity = _require_str(path, digest_tbl.get("integrity"), f"{pkg_ref}.digest.integrity")
        digest_obj = TrustDigest(integrity=integrity)

    mcp_entries: dict[str, McpTrust] = {}
    if "mcp" in tbl:
        mcp_tbl = _require_table(path, tbl.get("mcp"), f"{pkg_ref}.mcp")
        for server_id, server_raw in mcp_tbl.items():
            if not isinstance(server_id, str):
                raise ConfigValidationError(path=path, message=f"{pkg_ref}.mcp: server id keys must be strings")
            server_tbl = _require_table(path, server_raw, f"{pkg_ref}.mcp.{server_id}")
            allowed_server = {"allowExec", "allowMcp"}
            unknown_server = set(server_tbl.keys()) - allowed_server
            if unknown_server:
                raise ConfigValidationError(
                    path=path,
                    message=f"{pkg_ref}.mcp.{server_id}: {_unknown_keys_message(unknown_server)}",
                )
            se = False
            sm = False
            if "allowExec" in server_tbl:
                se = _require_bool(path, server_tbl.get("allowExec"), f"{pkg_ref}.mcp.{server_id}.allowExec")
            if "allowMcp" in server_tbl:
                sm = _require_bool(path, server_tbl.get("allowMcp"), f"{pkg_ref}.mcp.{server_id}.allowMcp")
            mcp_entries[server_id] = McpTrust(allow_exec=se, allow_mcp=sm)

    return TrustEntry(allow_exec=allow_exec, allow_mcp=allow_mcp, digest=digest_obj, mcp=mcp_entries)
