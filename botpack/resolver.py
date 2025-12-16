from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Semver:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_semver(version: str) -> Semver:
    parts = version.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"invalid semver: {version!r}")
    try:
        return Semver(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as e:
        raise ValueError(f"invalid semver: {version!r}") from e


def _normalize_spec_version(v: str) -> str:
    """Normalize a semver *spec* version to MAJOR.MINOR.PATCH.

    Supports shorthand specs like "^1" or "^1.2" by treating omitted parts as 0.
    """

    parts = v.strip().split(".")
    if len(parts) == 1:
        return f"{parts[0]}.0.0"
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1]}.0"
    if len(parts) == 3:
        return v.strip()
    raise ValueError(f"invalid semver: {v!r}")


def _caret_upper(v: Semver) -> Semver:
    # Cargo/npm caret semantics (simplified): bump the left-most non-zero.
    if v.major != 0:
        return Semver(v.major + 1, 0, 0)
    if v.minor != 0:
        return Semver(0, v.minor + 1, 0)
    return Semver(0, 0, v.patch + 1)


def satisfies(version: Semver, spec: str) -> bool:
    s = spec.strip()
    if not s:
        raise ValueError("empty version spec")

    if s.startswith("^"):
        base = parse_semver(_normalize_spec_version(s[1:]))
        upper = _caret_upper(base)
        return base <= version < upper

    if s.startswith("="):
        return version == parse_semver(_normalize_spec_version(s[1:]))

    # Exact
    if s[0].isdigit():
        return version == parse_semver(_normalize_spec_version(s))

    raise ValueError(f"unsupported version spec: {spec!r}")


def pick_highest_satisfying(versions: list[str], spec: str) -> str | None:
    parsed = [(parse_semver(v), v) for v in versions]
    ok = [raw for sv, raw in parsed if satisfies(sv, spec)]
    if not ok:
        return None
    return max(ok, key=lambda v: parse_semver(v))
