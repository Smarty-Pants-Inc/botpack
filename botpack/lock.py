"""Botpack lockfile I/O.

This module implements a minimal, deterministic read/write layer for the
`botpack.lock` JSON lockfile described in botyard-spec.md.

Requirements:
- Stable JSON formatting (sorted keys, stable indentation)
- No timestamps
- stdlib-only implementation
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping


LOCKFILE_VERSION = 1
SPEC_VERSION = "0.1"


class LockfileError(ValueError):
    """Raised when a lockfile cannot be parsed or does not match the expected schema."""


def package_key(name: str, version: str) -> str:
    """Compute a stable package key string like "@scope/name@1.2.3".

    Args:
        name: Package name (scoped or unscoped).
        version: Resolved version string.

    Returns:
        Combined key string.
    """
    if not isinstance(name, str) or not name.strip():
        raise TypeError("package_key: name must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise TypeError("package_key: version must be a non-empty string")
    return f"{name}@{version}"


def _canonical_json(obj: Any) -> str:
    # Canonical formatting: sorted keys + stable indentation.
    # Use ensure_ascii=False to keep lockfile human-readable and stable.
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _expect_mapping(value: Any, *, ctx: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LockfileError(f"Invalid lockfile: {ctx} must be an object")
    return value


def _expect_str(value: Any, *, ctx: str) -> str:
    if not isinstance(value, str):
        raise LockfileError(f"Invalid lockfile: {ctx} must be a string")
    return value


def _expect_int(value: Any, *, ctx: str) -> int:
    if not isinstance(value, int):
        raise LockfileError(f"Invalid lockfile: {ctx} must be an integer")
    return value


def _expect_str_dict(value: Any, *, ctx: str) -> dict[str, str]:
    m = _expect_mapping(value, ctx=ctx)
    out: dict[str, str] = {}
    for k, v in m.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise LockfileError(f"Invalid lockfile: {ctx} must be a map of strings to strings")
        out[k] = v
    return out


def _unknown_keys_msg(*, ctx: str, unknown: list[str]) -> str:
    # Deterministic ordering.
    u = sorted(unknown)
    return f"Invalid lockfile: unknown {ctx} keys: {u}"


@dataclass(frozen=True)
class Package:
    """A resolved package entry in the lockfile."""

    source: dict[str, Any]
    resolved: dict[str, Any] = field(default_factory=dict)
    integrity: str | None = None
    dependencies: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "resolved": self.resolved,
            "integrity": self.integrity,
            "dependencies": dict(self.dependencies),
            "capabilities": dict(self.capabilities),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Package":
        allowed = {"source", "resolved", "integrity", "dependencies", "capabilities"}
        unknown = [k for k in data.keys() if k not in allowed]
        if unknown:
            raise LockfileError(_unknown_keys_msg(ctx="package", unknown=unknown))

        source_raw = data.get("source")
        if source_raw is None:
            raise LockfileError("Invalid lockfile: package.source is required")
        source = dict(_expect_mapping(source_raw, ctx="package.source"))
        if "type" not in source or not isinstance(source.get("type"), str):
            raise LockfileError("Invalid lockfile: package.source.type is required and must be a string")

        resolved_raw = data.get("resolved")
        resolved: dict[str, Any] = {}
        if resolved_raw is not None:
            resolved = dict(_expect_mapping(resolved_raw, ctx="package.resolved"))

        integrity_raw = data.get("integrity")
        integrity: str | None
        if integrity_raw is None:
            integrity = None
        else:
            integrity = _expect_str(integrity_raw, ctx="package.integrity")

        deps = _expect_str_dict(data.get("dependencies", {}), ctx="package.dependencies")

        caps_raw = data.get("capabilities", {})
        caps_map = _expect_mapping(caps_raw, ctx="package.capabilities")
        caps: dict[str, bool] = {}
        for k, v in caps_map.items():
            if not isinstance(k, str) or not isinstance(v, bool):
                raise LockfileError("Invalid lockfile: package.capabilities must be a map of strings to booleans")
            caps[k] = v

        return cls(
            source=source,
            resolved=resolved,
            integrity=integrity,
            dependencies=deps,
            capabilities=caps,
        )


@dataclass(frozen=True)
class Lockfile:
    """Top-level lockfile model."""

    lockfileVersion: int
    botpackVersion: str
    specVersion: str
    dependencies: dict[str, str] = field(default_factory=dict)
    packages: dict[str, Package] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lockfileVersion": self.lockfileVersion,
            "botpackVersion": self.botpackVersion,
            "specVersion": self.specVersion,
            "dependencies": dict(self.dependencies),
            "packages": {k: v.to_dict() for k, v in self.packages.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Lockfile":
        required = {"lockfileVersion", "specVersion", "dependencies", "packages"}
        version_key: str | None = None
        if "botpackVersion" in data:
            version_key = "botpackVersion"
        elif "botyardVersion" in data:  # legacy
            version_key = "botyardVersion"

        missing = sorted([k for k in required if k not in data])
        if version_key is None:
            missing.append("botpackVersion")
        if missing:
            raise LockfileError(f"Invalid lockfile: missing required keys: {sorted(missing)}")

        allowed = set(required) | {"botpackVersion", "botyardVersion"}
        unknown = [k for k in data.keys() if k not in allowed]
        if unknown:
            raise LockfileError(_unknown_keys_msg(ctx="top-level", unknown=unknown))

        lf_ver = _expect_int(data.get("lockfileVersion"), ctx="lockfileVersion")
        if lf_ver != LOCKFILE_VERSION:
            raise LockfileError(
                f"Unsupported lockfileVersion: {lf_ver} (expected {LOCKFILE_VERSION})"
            )

        if "botpackVersion" in data and "botyardVersion" in data:
            bp = _expect_str(data.get("botpackVersion"), ctx="botpackVersion")
            by = _expect_str(data.get("botyardVersion"), ctx="botyardVersion")
            if bp != by:
                raise LockfileError("Invalid lockfile: botpackVersion and botyardVersion disagree")

        assert version_key is not None
        bp_ver = _expect_str(data.get(version_key), ctx=version_key)
        spec_ver = _expect_str(data.get("specVersion"), ctx="specVersion")
        if spec_ver != SPEC_VERSION:
            raise LockfileError(f"Unsupported specVersion: {spec_ver} (expected {SPEC_VERSION})")

        deps = _expect_str_dict(data.get("dependencies"), ctx="dependencies")

        pkgs_raw = _expect_mapping(data.get("packages"), ctx="packages")
        pkgs: dict[str, Package] = {}
        for k, v in pkgs_raw.items():
            if not isinstance(k, str):
                raise LockfileError("Invalid lockfile: packages keys must be strings")
            pkg_dict = _expect_mapping(v, ctx=f"packages[{k}]")
            pkgs[k] = Package.from_dict(pkg_dict)

        return cls(
            lockfileVersion=lf_ver,
            botpackVersion=bp_ver,
            specVersion=spec_ver,
            dependencies=deps,
            packages=pkgs,
        )


def load_lock(path: str | Path) -> Lockfile:
    """Load and validate a botpack.lock file.

    Raises LockfileError for parse/schema errors.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise LockfileError("Invalid lockfile: unable to read") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LockfileError("Invalid lockfile: invalid JSON") from e

    m = _expect_mapping(data, ctx="top-level")
    return Lockfile.from_dict(m)


def save_lock(path: str | Path, lock: Lockfile) -> None:
    """Write a botpack.lock file with canonical JSON formatting."""
    p = Path(path)
    text = _canonical_json(lock.to_dict())

    # Atomic-ish write: write to sibling temp file then replace.
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
