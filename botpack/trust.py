from __future__ import annotations

from dataclasses import dataclass

from .config import parse_trust_toml_file


@dataclass(frozen=True)
class TrustDecision:
    ok: bool
    reason: str | None = None


# Pseudo-package key used for repo-local (workspace) trust decisions.
#
# The trust.toml schema accepts arbitrary string keys, so we can safely
# represent the local workspace with a reserved key rather than inventing a
# fake semver package version.
WORKSPACE_TRUST_KEY = "__workspace__"


def check_mcp_server_trust(
    *,
    pkg_key: str,
    integrity: str | None,
    fqid: str,
    needs_exec: bool,
    needs_mcp: bool,
) -> TrustDecision:
    """Evaluate trust for a single MCP server coming from a package.

    Trust is keyed by package (e.g. "@acme/mcp-pack@0.3.0") and may include
    optional per-server overrides under entry.mcp[<fqid>].
    """

    cfg = parse_trust_toml_file()
    entry = cfg.packages.get(pkg_key)

    if entry is None:
        if needs_exec or needs_mcp:
            return TrustDecision(ok=False, reason=f"{pkg_key}: requires trust for exec/mcp")
        return TrustDecision(ok=True)

    if integrity and entry.digest and entry.digest.integrity != integrity:
        return TrustDecision(
            ok=False,
            reason=f"{pkg_key}: trust.digest mismatch (trust={entry.digest.integrity}, got={integrity})",
        )

    override = entry.mcp.get(fqid)
    allow_exec = override.allow_exec if override is not None else entry.allow_exec
    allow_mcp = override.allow_mcp if override is not None else entry.allow_mcp

    if needs_exec and not allow_exec:
        return TrustDecision(ok=False, reason=f"{pkg_key}: exec not trusted for {fqid}")
    if needs_mcp and not allow_mcp:
        return TrustDecision(ok=False, reason=f"{pkg_key}: mcp not trusted for {fqid}")

    return TrustDecision(ok=True)


def check_package_trust(
    *,
    pkg_key: str,
    integrity: str | None,
    needs_exec: bool,
    needs_mcp: bool,
) -> TrustDecision:
    cfg = parse_trust_toml_file()
    entry = cfg.packages.get(pkg_key)

    if entry is None:
        if needs_exec or needs_mcp:
            return TrustDecision(ok=False, reason=f"{pkg_key}: requires trust for exec/mcp")
        return TrustDecision(ok=True)

    if integrity and entry.digest and entry.digest.integrity != integrity:
        return TrustDecision(
            ok=False,
            reason=f"{pkg_key}: trust.digest mismatch (trust={entry.digest.integrity}, got={integrity})",
        )

    if needs_exec and not entry.allow_exec:
        return TrustDecision(ok=False, reason=f"{pkg_key}: exec not trusted")
    if needs_mcp and not entry.allow_mcp:
        return TrustDecision(ok=False, reason=f"{pkg_key}: mcp not trusted")

    return TrustDecision(ok=True)
