from __future__ import annotations

"""Deterministic editing + rewriting of the workspace manifest.

These helpers support the `botpack add` / `botpack remove` CLI commands.

We intentionally do not preserve comments or exact formatting; instead we
rewrite in a canonical minimal format with stable ordering.
"""

from pathlib import Path
from typing import Any

from .errors import ConfigParseError, ConfigValidationError
from .toml_write import toml_basic_string, toml_inline_table, toml_value


try:  # Python 3.11+
    import tomllib as _tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _tomllib  # type: ignore


# Note: "assets" is the v0.3+ key; "workspace" is accepted for backward compat (read only).
_TOP_ORDER = ["version", "assets", "dependencies", "sync", "targets", "aliases"]
_TOP_ALLOWED = {"version", "assets", "workspace", "dependencies", "sync", "targets", "aliases"}


def load_botyard_manifest_raw(path: Path) -> dict[str, Any]:
    """Load the manifest (botpack.toml / botyard.toml) as a dict.

    If the file does not exist, returns a minimal new manifest.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": 1, "dependencies": {}}
    except OSError as e:
        raise ConfigValidationError(path=path, message=f"unable to read file: {e}") from e

    try:
        data = _tomllib.loads(text)
    except Exception as e:
        msg = getattr(e, "msg", str(e))
        lineno = getattr(e, "lineno", None)
        colno = getattr(e, "colno", None)
        raise ConfigParseError(path=path, message=str(msg), lineno=lineno, colno=colno) from e

    if not isinstance(data, dict):
        raise ConfigValidationError(path=path, message="top-level TOML must be a table")
    return dict(data)


def _require_table(path: Path, value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(path=path, message=f"{where}: expected table")
    return value


def _canonicalize_and_validate(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Validate schema subset we know how to rewrite, and normalize shapes.

    Accepts both [assets] (v0.3+) and [workspace] (legacy) for reading,
    but canonicalizes to "assets" internally.
    """

    unknown = set(data.keys()) - _TOP_ALLOWED
    if unknown:
        keys = ", ".join(sorted(unknown))
        raise ConfigValidationError(path=path, message=f"unknown keys: {keys}")

    if "version" not in data:
        raise ConfigValidationError(path=path, message="version: required")
    if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool):
        raise ConfigValidationError(path=path, message="version: expected integer")

    out: dict[str, Any] = {"version": int(data["version"])}

    # Accept both [assets] (v0.3+) and [workspace] (legacy), canonicalize to "assets".
    assets_raw = data.get("assets")
    ws_raw = data.get("workspace")
    if assets_raw is not None and ws_raw is not None:
        raise ConfigValidationError(path=path, message="cannot have both [assets] and [workspace]; use [assets]")
    combined_assets = assets_raw if assets_raw is not None else ws_raw
    if combined_assets is not None:
        assets_tbl = _require_table(path, combined_assets, "assets")
        out["assets"] = dict(assets_tbl)

    deps_raw = data.get("dependencies")
    if deps_raw is None:
        deps: dict[str, Any] = {}
    else:
        deps = dict(_require_table(path, deps_raw, "dependencies"))
    # keys are package names, values are dependency specs.
    for k in deps.keys():
        if not isinstance(k, str):
            raise ConfigValidationError(path=path, message="dependencies: package name keys must be strings")
    out["dependencies"] = deps

    if "sync" in data:
        sync = _require_table(path, data.get("sync"), "sync")
        out["sync"] = dict(sync)

    if "targets" in data:
        targets = _require_table(path, data.get("targets"), "targets")
        out_targets: dict[str, Any] = {}
        for tname, tval in targets.items():
            if not isinstance(tname, str):
                raise ConfigValidationError(path=path, message="targets: target name keys must be strings")
            out_targets[tname] = dict(_require_table(path, tval, f"targets.{tname}"))
        out["targets"] = out_targets

    if "aliases" in data:
        aliases = _require_table(path, data.get("aliases"), "aliases")
        out["aliases"] = dict(aliases)

    return out


def add_path_dependency(path: Path, *, name: str, dep_path: str) -> None:
    data = _canonicalize_and_validate(path, load_botyard_manifest_raw(path))
    deps: dict[str, Any] = data.get("dependencies") or {}
    deps[name] = {"path": dep_path}
    data["dependencies"] = deps
    save_botyard_manifest(path, data)


def add_semver_dependency(path: Path, *, name: str, spec: str) -> None:
    """Add or update a semver/string dependency spec (e.g. "^1", "*", ">=2")."""

    data = _canonicalize_and_validate(path, load_botyard_manifest_raw(path))
    deps: dict[str, Any] = data.get("dependencies") or {}
    deps[name] = spec
    data["dependencies"] = deps
    save_botyard_manifest(path, data)


def add_git_dependency(path: Path, *, name: str, url: str, rev: str | None = None) -> None:
    data = _canonicalize_and_validate(path, load_botyard_manifest_raw(path))
    deps: dict[str, Any] = data.get("dependencies") or {}
    spec: dict[str, Any] = {"git": url}
    if rev:
        spec["rev"] = rev
    deps[name] = spec
    data["dependencies"] = deps
    save_botyard_manifest(path, data)


def remove_dependency(path: Path, *, name: str) -> bool:
    data = _canonicalize_and_validate(path, load_botyard_manifest_raw(path))
    deps: dict[str, Any] = data.get("dependencies") or {}
    existed = name in deps
    deps.pop(name, None)
    data["dependencies"] = deps
    save_botyard_manifest(path, data)
    return existed


def save_botyard_manifest(path: Path, data: dict[str, Any]) -> None:
    """Write the manifest in canonical minimal formatting."""

    d = _canonicalize_and_validate(path, data)

    lines: list[str] = []
    lines.append(f"version = {toml_value(d['version'])}")

    # Always emit [assets] (v0.3+), even if input used [workspace].
    assets = d.get("assets")
    if isinstance(assets, dict) and assets:
        lines.append("")
        lines.append("[assets]")
        # Keep schema-known keys in a fixed order; omit absent keys.
        for k in ("dir", "name", "private"):
            if k in assets:
                lines.append(f"{k} = {toml_value(assets[k])}")

    deps: dict[str, Any] = d.get("dependencies") or {}
    if deps:
        lines.append("")
        lines.append("[dependencies]")
        for pkg in sorted(deps.keys()):
            spec = deps[pkg]
            if isinstance(spec, str):
                lines.append(f"{toml_basic_string(pkg)} = {toml_basic_string(spec)}")
            elif isinstance(spec, dict):
                # Emit inline tables for deterministic one-line deps.
                if "path" in spec:
                    allowed = {"path"}
                    unknown = set(spec.keys()) - allowed
                    if unknown:
                        raise ConfigValidationError(
                            path=path,
                            message=f"dependencies.{pkg}: unknown keys: {', '.join(sorted(unknown))}",
                        )
                    lines.append(
                        f"{toml_basic_string(pkg)} = {toml_inline_table(spec, key_order=['path'])}"
                    )
                elif "git" in spec:
                    allowed = {"git", "rev"}
                    unknown = set(spec.keys()) - allowed
                    if unknown:
                        raise ConfigValidationError(
                            path=path,
                            message=f"dependencies.{pkg}: unknown keys: {', '.join(sorted(unknown))}",
                        )
                    lines.append(
                        f"{toml_basic_string(pkg)} = {toml_inline_table(spec, key_order=['git','rev'])}"
                    )
                elif "url" in spec:
                    allowed = {"url", "integrity"}
                    unknown = set(spec.keys()) - allowed
                    if unknown:
                        raise ConfigValidationError(
                            path=path,
                            message=f"dependencies.{pkg}: unknown keys: {', '.join(sorted(unknown))}",
                        )
                    lines.append(
                        f"{toml_basic_string(pkg)} = {toml_inline_table(spec, key_order=['url','integrity'])}"
                    )
                else:
                    raise ConfigValidationError(
                        path=path,
                        message=(
                            f"dependencies.{pkg}: unsupported spec; expected string or one of {{git=...}}, {{path=...}}, {{url=...}}"
                        ),
                    )
            else:
                raise ConfigValidationError(path=path, message=f"dependencies.{pkg}: expected string or table")

    sync = d.get("sync")
    if isinstance(sync, dict) and sync:
        lines.append("")
        lines.append("[sync]")
        for k in ("onAdd", "onInstall", "catalog", "linkMode"):
            if k in sync:
                lines.append(f"{k} = {toml_value(sync[k])}")

    targets = d.get("targets")
    if isinstance(targets, dict) and targets:
        # Each target becomes its own table.
        key_order = [
            "root",
            "skillsDir",
            "commandsDir",
            "agentsDir",
            "mcpOut",
            "policyMode",
            "skillsFallbackRoot",
            "skillsFallbackDir",
        ]
        for tname in sorted(targets.keys()):
            tcfg = targets[tname]
            if not isinstance(tcfg, dict):
                raise ConfigValidationError(path=path, message=f"targets.{tname}: expected table")
            lines.append("")
            lines.append(f"[targets.{tname}]")
            for k in key_order:
                if k in tcfg:
                    lines.append(f"{k} = {toml_value(tcfg[k])}")

    aliases = d.get("aliases")
    if isinstance(aliases, dict) and aliases:
        skills = aliases.get("skills")
        if isinstance(skills, dict) and skills:
            lines.append("")
            lines.append("[aliases.skills]")
            for k in sorted(skills.keys()):
                lines.append(f"{k} = {toml_value(skills[k])}")
        commands = aliases.get("commands")
        if isinstance(commands, dict) and commands:
            lines.append("")
            lines.append("[aliases.commands]")
            for k in sorted(commands.keys()):
                lines.append(f"{k} = {toml_value(commands[k])}")

    text = "\n".join(lines) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
