from __future__ import annotations

from pathlib import Path
from typing import Any


try:  # Python 3.11+
    import tomllib as _tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _tomllib  # type: ignore


_ALLOWED_TOP = {"version", "workspace", "dependencies", "sync", "targets", "aliases"}
_ALLOWED_WS = {"dir", "name", "private"}
_ALLOWED_SYNC = {"onAdd", "onInstall", "catalog", "linkMode"}
_ALLOWED_TARGET = {
    "root",
    "skillsDir",
    "commandsDir",
    "agentsDir",
    "mcpOut",
    "policyMode",
    "skillsFallbackRoot",
    "skillsFallbackDir",
}
_ALLOWED_ALIASES = {"skills", "commands"}


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _toml_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _is_bare_key(k: str) -> bool:
    # TOML bare keys are limited; keep it conservative.
    return k.replace("_", "a").replace("-", "a").isalnum()


def _fmt_key(k: str) -> str:
    return k if _is_bare_key(k) else _toml_quote(k)


def _fmt_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return _toml_quote(v)
    raise ValueError(f"unsupported TOML value type: {type(v).__name__}")


def _fmt_inline_table(tbl: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in sorted(tbl.keys()):
        parts.append(f"{_fmt_key(k)} = {_fmt_value(tbl[k])}")
    return "{ " + ", ".join(parts) + " }"


def _validate_manifest(raw: dict[str, Any]) -> None:
    unknown = set(raw.keys()) - _ALLOWED_TOP
    if unknown:
        raise ValueError(f"botpack.toml: unknown keys: {', '.join(sorted(unknown))}")
    if raw.get("version") != 1:
        raise ValueError(f"botpack.toml: version must be 1 (got {raw.get('version')!r})")

    ws = raw.get("workspace")
    if ws is not None:
        if not isinstance(ws, dict):
            raise ValueError("botpack.toml: workspace must be a table")
        unk_ws = set(ws.keys()) - _ALLOWED_WS
        if unk_ws:
            raise ValueError(f"botpack.toml: workspace: unknown keys: {', '.join(sorted(unk_ws))}")

    deps = raw.get("dependencies")
    if deps is not None:
        if not isinstance(deps, dict):
            raise ValueError("botpack.toml: dependencies must be a table")
        for k, v in deps.items():
            if not isinstance(k, str):
                raise ValueError("botpack.toml: dependencies keys must be strings")
            if not isinstance(v, (str, dict)):
                raise ValueError(f"botpack.toml: dependencies.{k}: unsupported value type")
            if isinstance(v, dict):
                for kk, vv in v.items():
                    if not isinstance(kk, str):
                        raise ValueError(f"botpack.toml: dependencies.{k}: table keys must be strings")
                    if not isinstance(vv, (str, int, bool)):
                        raise ValueError(f"botpack.toml: dependencies.{k}.{kk}: unsupported value type")

    sync = raw.get("sync")
    if sync is not None:
        if not isinstance(sync, dict):
            raise ValueError("botpack.toml: sync must be a table")
        unk_sync = set(sync.keys()) - _ALLOWED_SYNC
        if unk_sync:
            raise ValueError(f"botpack.toml: sync: unknown keys: {', '.join(sorted(unk_sync))}")

    targets = raw.get("targets")
    if targets is not None:
        if not isinstance(targets, dict):
            raise ValueError("botpack.toml: targets must be a table")
        for tname, t in targets.items():
            if not isinstance(tname, str) or not isinstance(t, dict):
                raise ValueError("botpack.toml: targets must be a map of tables")
            unk_t = set(t.keys()) - _ALLOWED_TARGET
            if unk_t:
                raise ValueError(
                    f"botpack.toml: targets.{tname}: unknown keys: {', '.join(sorted(unk_t))}"
                )

    aliases = raw.get("aliases")
    if aliases is not None:
        if not isinstance(aliases, dict):
            raise ValueError("botpack.toml: aliases must be a table")
        unk_a = set(aliases.keys()) - _ALLOWED_ALIASES
        if unk_a:
            raise ValueError(f"botpack.toml: aliases: unknown keys: {', '.join(sorted(unk_a))}")


def load_manifest(path: Path) -> dict[str, Any]:
    raw = _tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("botpack.toml: top-level must be a table")
    _validate_manifest(raw)
    return raw


def parse_add_spec(spec: str) -> tuple[str, str]:
    """Parse `name@versionSpec` where name may include `@` (scoped packages).

    Examples:
      - @acme/quality-skills@^2
      - foo@~1.2
    """

    s = spec.strip()
    at = s.rfind("@")
    if at <= 0 or at == len(s) - 1:
        raise ValueError(f"invalid add spec: {spec!r} (expected name@version)")
    name = s[:at].strip()
    ver = s[at + 1 :].strip()
    if not name or not ver:
        raise ValueError(f"invalid add spec: {spec!r} (expected name@version)")
    return name, ver


def render_manifest(raw: dict[str, Any]) -> str:
    _validate_manifest(raw)
    lines: list[str] = []

    lines.append(f"version = {int(raw['version'])}")

    ws = raw.get("workspace")
    if isinstance(ws, dict):
        lines.append("")
        lines.append("[workspace]")
        for k in ("dir", "name", "private"):
            if k in ws:
                lines.append(f"{k} = {_fmt_value(ws[k])}")

    deps = raw.get("dependencies")
    if isinstance(deps, dict) and deps:
        lines.append("")
        lines.append("[dependencies]")
        for name in sorted(deps.keys()):
            v = deps[name]
            if isinstance(v, str):
                lines.append(f"{_toml_quote(name)} = {_toml_quote(v)}")
            elif isinstance(v, dict):
                lines.append(f"{_toml_quote(name)} = {_fmt_inline_table(v)}")
            else:  # pragma: no cover
                raise ValueError(f"botpack.toml: dependencies.{name}: unsupported value")

    sync = raw.get("sync")
    if isinstance(sync, dict) and sync:
        lines.append("")
        lines.append("[sync]")
        for k in ("onAdd", "onInstall", "catalog", "linkMode"):
            if k in sync:
                lines.append(f"{k} = {_fmt_value(sync[k])}")

    targets = raw.get("targets")
    if isinstance(targets, dict) and targets:
        for tname in sorted(targets.keys()):
            t = targets[tname]
            if not isinstance(t, dict):
                continue
            lines.append("")
            lines.append(f"[targets.{_fmt_key(tname)}]")
            for k in (
                "root",
                "skillsDir",
                "commandsDir",
                "agentsDir",
                "mcpOut",
                "policyMode",
                "skillsFallbackRoot",
                "skillsFallbackDir",
            ):
                if k in t:
                    lines.append(f"{k} = {_fmt_value(t[k])}")

    aliases = raw.get("aliases")
    if isinstance(aliases, dict) and aliases:
        # aliases.skills and aliases.commands are nested tables
        for section in ("skills", "commands"):
            tbl = aliases.get(section)
            if not isinstance(tbl, dict) or not tbl:
                continue
            lines.append("")
            lines.append(f"[aliases.{section}]")
            for k in sorted(tbl.keys()):
                lines.append(f"{_toml_quote(str(k))} = {_toml_quote(str(tbl[k]))}")

    return "\n".join(lines) + "\n"


def update_manifest_dependencies(
    *,
    path: Path,
    add: dict[str, str] | None = None,
    remove: set[str] | None = None,
) -> None:
    raw = load_manifest(path)
    deps = raw.get("dependencies")
    if deps is None:
        deps = {}
        raw["dependencies"] = deps
    if not isinstance(deps, dict):
        raise ValueError("botpack.toml: dependencies must be a table")

    if add:
        for name, spec in add.items():
            deps[str(name)] = str(spec)
    if remove:
        for name in remove:
            deps.pop(str(name), None)

    # If dependencies becomes empty, omit it for minimal diffs.
    if not deps:
        raw.pop("dependencies", None)

    _atomic_write_text(path, render_manifest(raw))
