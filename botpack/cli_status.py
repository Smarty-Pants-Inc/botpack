"""CLI status helpers for DX-contract commands.

Implements:
- `botpack` (no args): single-screen status summary
- `botpack status`: universal health surface
- `botpack explain <id>`: deep dive for specific issues
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import botyard_manifest_path
from .errors import BotyardConfigError
from .install import default_lock_path
from .issues import conflict_issue_id, trust_issue_id
from .lock import load_lock, Lockfile, LockfileError
from .paths import botyard_dir, work_root


# ---------------------------------------------------------------------------
# Asset address formatting
# ---------------------------------------------------------------------------


def _asset_addr(asset_type: str, asset_id: str) -> str:
    """Format a stable asset address like `skill:fetch_web`."""
    return f"{asset_type}:{asset_id}"


def _letta_asset_addr(letta_type: str, letta_id: str) -> str:
    """Format a Letta asset address like `letta:block:project`."""
    return f"letta:{letta_type}:{letta_id}"


# ---------------------------------------------------------------------------
# Issue IDs (stable identifiers for explain)
# ---------------------------------------------------------------------------

# Issue ID generation is centralized in botpack/issues.py.


# ---------------------------------------------------------------------------
# Status data models
# ---------------------------------------------------------------------------


@dataclass
class TargetStatus:
    """Status for a single sync target."""
    
    name: str
    state_path: Path
    exists: bool = False
    last_sync: str | None = None
    paths_count: int = 0
    conflicts: list[str] = field(default_factory=list)
    conflict_ids: dict[str, str] = field(default_factory=dict)  # path -> issue_id


@dataclass
class TrustGate:
    """A package requiring trust that is not yet trusted."""
    
    pkg_key: str
    needs_exec: bool = False
    needs_mcp: bool = False
    issue_id: str = ""


@dataclass
class StatusInfo:
    """Aggregated status information for the current root."""
    
    # Root selection
    root: Path
    manifest_path: Path | None = None
    manifest_exists: bool = False
    
    # Lock state
    lock_path: Path | None = None
    lock_exists: bool = False
    lock_version: str | None = None
    packages_count: int = 0
    
    # Target statuses
    targets: dict[str, TargetStatus] = field(default_factory=dict)
    
    # Conflicts (aggregated from all targets)
    all_conflicts: list[str] = field(default_factory=list)
    conflict_details: dict[str, dict] = field(default_factory=dict)  # issue_id -> details
    
    # Trust gates
    trust_gates: list[TrustGate] = field(default_factory=list)
    
    # Blocked MCP servers
    blocked_servers: list[str] = field(default_factory=list)
    
    # Letta drift (placeholder)
    letta_drift: str = "not_checked"
    
    # Overall health
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    
    @property
    def has_issues(self) -> bool:
        return bool(self.all_conflicts or self.trust_gates or self.blocked_servers or self.errors)


# ---------------------------------------------------------------------------
# Status collection (no network)
# ---------------------------------------------------------------------------


def _load_sync_state(target: str) -> dict:
    """Load sync state for a target."""
    state_path = botyard_dir() / "state" / f"sync-{target}.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _check_trust_gates(lock: Lockfile | None) -> list[TrustGate]:
    """Check for packages requiring trust that are not trusted."""
    if lock is None:
        return []
    
    from .trust import check_package_trust
    
    gates: list[TrustGate] = []
    for pkg_key, pkg in sorted(lock.packages.items()):
        needs_exec = bool(pkg.capabilities.get("exec"))
        needs_mcp = bool(pkg.capabilities.get("mcp"))
        if not (needs_exec or needs_mcp):
            continue
        
        decision = check_package_trust(
            pkg_key=pkg_key,
            integrity=pkg.integrity,
            needs_exec=needs_exec,
            needs_mcp=needs_mcp,
        )
        if not decision.ok:
            gates.append(TrustGate(
                pkg_key=pkg_key,
                needs_exec=needs_exec,
                needs_mcp=needs_mcp,
                issue_id=trust_issue_id(pkg_key=pkg_key),
            ))
    
    return gates


def collect_status(*, manifest_path: Path | None = None) -> StatusInfo:
    """Collect status information for the current root without network access.
    
    This is the core status collection function used by both `botpack` (no args)
    and `botpack status`.
    """
    root = work_root()
    
    # Manifest
    m_path = manifest_path or botyard_manifest_path()
    m_exists = m_path.exists()
    
    # Lock
    l_path = default_lock_path()
    l_exists = l_path.exists()
    lock: Lockfile | None = None
    l_version: str | None = None
    pkg_count = 0
    
    if l_exists:
        try:
            lock = load_lock(l_path)
            l_version = lock.botpackVersion
            pkg_count = len(lock.packages)
        except LockfileError as e:
            # Lock exists but is invalid
            pass
    
    # Targets and conflicts
    targets: dict[str, TargetStatus] = {}
    all_conflicts: list[str] = []
    conflict_details: dict[str, dict] = {}
    
    for target_name in ["claude", "amp", "droid", "letta-code"]:
        state_path = botyard_dir() / "state" / f"sync-{target_name}.json"
        state = _load_sync_state(target_name)
        
        ts = TargetStatus(
            name=target_name,
            state_path=state_path,
            exists=state_path.exists(),
        )
        
        if state:
            ts.paths_count = len(state.get("paths", {}))

        # Conflicts are recorded in `.botpack/state/conflicts-<target>.json`.
        # This allows `status` to report conflicts even if we don't run sync.
        from .sync import load_conflicts

        for cr in load_conflicts(target_name):
            issue_id = conflict_issue_id(target=target_name, path=cr.path)
            ts.conflicts.append(cr.path)
            ts.conflict_ids[cr.path] = issue_id
            all_conflicts.append(issue_id)
            conflict_details[issue_id] = {
                "type": "sync_conflict",
                "target": target_name,
                "path": cr.path,
                "reason": cr.reason,
                "asset_address": cr.asset_address.address if cr.asset_address else None,
                "last_known_good_sha256": cr.last_known_good_sha256,
            }
        
        targets[target_name] = ts
    
    # Trust gates
    trust_gates = _check_trust_gates(lock)
    
    # Warnings and errors
    warnings: list[str] = []
    errors: list[str] = []
    
    if not m_exists:
        warnings.append("No botpack.toml found (run `botpack init` to create one)")
    
    if not l_exists and m_exists:
        warnings.append("No lockfile found (run `botpack install` to create one)")
    
    if trust_gates:
        warnings.append(f"{len(trust_gates)} package(s) require trust approval")

    # Letta drift summary (no network): we only report whether Letta assets exist.
    letta_drift = "none"
    if m_exists:
        try:
            from .config import parse_botyard_toml_file

            cfg = parse_botyard_toml_file(m_path)
            assets_dir = Path(cfg.workspace.dir)
            if not assets_dir.is_absolute():
                assets_dir = (root / assets_dir).resolve()
            if (assets_dir / "letta").exists():
                letta_drift = "needs_check"
        except Exception:
            letta_drift = "unknown"

    return StatusInfo(
        root=root,
        manifest_path=m_path if m_exists else None,
        manifest_exists=m_exists,
        lock_path=l_path if l_exists else None,
        lock_exists=l_exists,
        lock_version=l_version,
        packages_count=pkg_count,
        targets=targets,
        all_conflicts=all_conflicts,
        conflict_details=conflict_details,
        trust_gates=trust_gates,
        letta_drift=letta_drift,
        warnings=warnings,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Status formatting
# ---------------------------------------------------------------------------


def _format_timestamp(ts: str | None) -> str:
    """Format a timestamp for display."""
    if not ts:
        return "never"
    return ts


def format_brief_status(info: StatusInfo) -> str:
    """Format a brief single-screen status summary.
    
    Used by `botpack` (no args).
    """
    lines: list[str] = []
    
    # Header
    lines.append("Botpack Status")
    lines.append(f"  Root: {info.root}")
    
    # Manifest
    if info.manifest_exists:
        lines.append(f"  Manifest: {info.manifest_path}")
    else:
        lines.append("  Manifest: not found")
    
    # Lock
    if info.lock_exists:
        lines.append(f"  Lock: {info.packages_count} packages")
    else:
        lines.append("  Lock: not found")
    
    # Quick target summary
    synced_targets = [t for t in info.targets.values() if t.exists]
    if synced_targets:
        target_names = ", ".join(t.name for t in synced_targets)
        lines.append(f"  Targets: {target_names}")
    else:
        lines.append("  Targets: none synced")
    
    # Issues summary
    issue_count = len(info.all_conflicts) + len(info.trust_gates) + len(info.blocked_servers)
    if issue_count > 0:
        lines.append("")
        lines.append(f"Issues ({issue_count})")
        if info.all_conflicts:
            lines.append(f"  - {len(info.all_conflicts)} sync conflict(s)")
        if info.trust_gates:
            lines.append(f"  - {len(info.trust_gates)} trust gate(s)")
        if info.blocked_servers:
            lines.append(f"  - {len(info.blocked_servers)} blocked MCP server(s)")
    
    # Recommendations
    lines.append("")
    lines.append("Next actions")
    if not info.manifest_exists:
        lines.append("  - Run `botpack init` to create a manifest")
    elif not info.lock_exists:
        lines.append("  - Run `botpack install` to install dependencies")
    elif issue_count > 0:
        lines.append("  - Run `botpack status` for details")
        lines.append("  - Run `botpack doctor` for fix suggestions")
    else:
        lines.append("  - Run `botpack launch <target>` to start a TUI")
    
    return "\n".join(lines) + "\n"


def format_full_status(info: StatusInfo) -> str:
    """Format a full status report.
    
    Used by `botpack status`.
    """
    lines: list[str] = []
    
    # Header
    lines.append("=" * 60)
    lines.append("Botpack Status (Universal Health Surface)")
    lines.append("=" * 60)
    
    # Root selection
    lines.append("")
    lines.append("Root Selection")
    lines.append(f"  Root: {info.root}")
    lines.append(f"  Manifest: {info.manifest_path or 'not found'}")
    lines.append(f"  Lock: {info.lock_path or 'not found'}")
    
    # Lock health
    lines.append("")
    lines.append("Lock Health")
    if info.lock_exists:
        lines.append(f"  Version: {info.lock_version or 'unknown'}")
        lines.append(f"  Packages: {info.packages_count}")
        lines.append("  Status: OK")
    else:
        lines.append("  Status: No lockfile")
    
    # Target freshness
    lines.append("")
    lines.append("Target Freshness")
    for name, ts in sorted(info.targets.items()):
        if ts.exists:
            conflict_note = f" ({len(ts.conflicts)} conflicts)" if ts.conflicts else ""
            lines.append(f"  {name}: {ts.paths_count} paths{conflict_note}")
        else:
            lines.append(f"  {name}: not synced")
    
    # Conflicts
    if info.all_conflicts:
        lines.append("")
        lines.append(f"Conflicts ({len(info.all_conflicts)})")
        for issue_id, details in sorted(info.conflict_details.items()):
            path = details.get("path", "unknown")
            target = details.get("target", "unknown")

            addr = details.get("asset_address")
            if not addr:
                # Best-effort derive an address from the output path.
                if "/skills/" in path:
                    skill_id = Path(path).parent.name
                    addr = _asset_addr("skill", skill_id)
                elif "/commands/" in path:
                    cmd_id = Path(path).stem.replace(".md", "")
                    addr = _asset_addr("command", cmd_id)
                elif "/agents/" in path:
                    agent_id = Path(path).stem.replace(".md", "")
                    addr = _asset_addr("agent", agent_id)
                else:
                    addr = path

            lines.append(f"  [{issue_id}] {addr} (target: {target})")
    
    # Trust gates
    if info.trust_gates:
        lines.append("")
        lines.append(f"Trust Gates ({len(info.trust_gates)})")
        for gate in info.trust_gates:
            caps = []
            if gate.needs_exec:
                caps.append("exec")
            if gate.needs_mcp:
                caps.append("mcp")
            caps_str = ", ".join(caps)
            lines.append(f"  [{gate.issue_id}] {gate.pkg_key} (needs: {caps_str})")
    
    # Blocked servers
    if info.blocked_servers:
        lines.append("")
        lines.append(f"Blocked MCP Servers ({len(info.blocked_servers)})")
        for reason in info.blocked_servers:
            lines.append(f"  - {reason}")
    
    lines.append("")
    lines.append("Letta Drift")
    lines.append(f"  Status: {info.letta_drift}")
    if info.letta_drift in ("needs_check", "unknown"):
        lines.append("  Run `botpack letta status` for a drift-aware view (may require network).")
    
    # Warnings
    if info.warnings:
        lines.append("")
        lines.append("Warnings")
        for w in info.warnings:
            lines.append(f"  - {w}")
    
    # Summary
    lines.append("")
    lines.append("-" * 60)
    if info.has_issues:
        lines.append("Run `botpack explain <issue-id>` for detailed remediation.")
        lines.append("Run `botpack doctor` for suggested fix commands.")
    else:
        lines.append("No issues detected. Run `botpack launch <target>` to start.")
    
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Explain
# ---------------------------------------------------------------------------


def explain_issue(issue_id: str, *, manifest_path: Path | None = None) -> str:
    """Provide deep-dive explanation for a specific issue ID.
    
    Used by `botpack explain <id>`.
    """
    info = collect_status(manifest_path=manifest_path)
    
    lines: list[str] = []
    lines.append(f"Issue: {issue_id}")
    lines.append("=" * 60)
    
    # Check conflict_details
    if issue_id in info.conflict_details:
        details = info.conflict_details[issue_id]
        path = details.get("path", "unknown")
        target = details.get("target", "unknown")
        reason = details.get("reason", "sync conflict")
        addr = details.get("asset_address")
        last_good = details.get("last_known_good_sha256")

        lines.append("")
        lines.append("Type: Sync Conflict")
        lines.append(f"Target: {target}")
        if addr:
            lines.append(f"Asset: {addr}")
        lines.append(f"Path: {path}")
        lines.append(f"Reason: {reason}")
        if isinstance(last_good, str) and last_good:
            lines.append(f"Last-known-good SHA256: {last_good[:16]}...")
        
        lines.append("")
        lines.append("Explanation:")
        lines.append("  The file at the target path has been modified since the last sync.")
        lines.append("  Botpack detected drift between the expected content and actual content.")
        
        lines.append("")
        lines.append("Resolution Options:")
        lines.append(f"  1. Force overwrite (lose local changes):")
        lines.append(f"     botpack sync {target} --force")
        lines.append("")
        lines.append(f"  2. Keep local changes (remove from sync state):")
        lines.append(f"     # Manually remove entry from .botpack/state/sync-{target}.json")
        lines.append("")
        lines.append(f"  3. Merge changes manually, then re-sync:")
        lines.append(f"     # Edit {path} as needed")
        lines.append(f"     botpack sync {target} --force")
        
        return "\n".join(lines) + "\n"
    
    # Check trust gates
    for gate in info.trust_gates:
        if gate.issue_id == issue_id:
            lines.append("")
            lines.append("Type: Trust Gate")
            lines.append(f"Package: {gate.pkg_key}")
            
            caps = []
            if gate.needs_exec:
                caps.append("exec (can execute processes)")
            if gate.needs_mcp:
                caps.append("mcp (provides MCP servers)")
            
            lines.append(f"Required Capabilities: {', '.join(caps)}")
            
            lines.append("")
            lines.append("Explanation:")
            lines.append("  This package declares capabilities that require explicit trust.")
            lines.append("  Botpack will not materialize MCP servers or enable exec-capable")
            lines.append("  features until you explicitly approve them.")
            
            lines.append("")
            lines.append("Resolution:")
            if gate.needs_exec:
                lines.append(f"  botpack trust allow {gate.pkg_key} --exec")
            if gate.needs_mcp:
                lines.append(f"  botpack trust allow {gate.pkg_key} --mcp")
            if gate.needs_exec and gate.needs_mcp:
                lines.append("")
                lines.append("  Or both at once:")
                lines.append(f"  botpack trust allow {gate.pkg_key} --exec --mcp")
            
            return "\n".join(lines) + "\n"
    
    # Issue not found
    lines.append("")
    lines.append("Issue not found.")
    lines.append("")
    lines.append("This issue ID may have been resolved or may not exist.")
    lines.append("Run `botpack status` to see current issues.")
    
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Launch helpers
# ---------------------------------------------------------------------------


@dataclass
class LaunchResult:
    """Result of a launch attempt."""
    
    target: str
    success: bool
    used_last_known_good: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def prepare_launch(
    *,
    target: str,
    manifest_path: Path | None = None,
) -> LaunchResult:
    """Prepare for launch by attempting install+sync.
    
    If install or sync fails, returns a result indicating we should use
    last-known-good outputs.
    
    This does NOT actually launch the TUI - that's handled by the caller.
    """
    from .install import install
    from .sync import sync, SyncResult
    
    warnings: list[str] = []
    errors: list[str] = []
    used_lkg = False
    
    # Attempt install
    try:
        install(manifest_path=manifest_path, offline=False)
    except PermissionError as e:
        # Trust blocked - warn but continue
        warnings.append(f"Install blocked (trust): {e}")
        used_lkg = True
    except Exception as e:
        # Other install failure
        warnings.append(f"Install failed: {e}")
        used_lkg = True
    
    # Attempt sync
    try:
        result: SyncResult = sync(target=target, manifest_path=manifest_path)
        if result.conflicts:
            warnings.append(f"Sync detected {len(result.conflicts)} conflict(s)")
            for c in result.conflicts[:3]:  # Show first 3
                warnings.append(f"  - {c}")
            if len(result.conflicts) > 3:
                warnings.append(f"  ... and {len(result.conflicts) - 3} more")
            used_lkg = True
        if result.blocked:
            warnings.append(f"Sync blocked {len(result.blocked)} MCP server(s)")
            for b in result.blocked[:3]:
                warnings.append(f"  - {b}")
    except Exception as e:
        warnings.append(f"Sync failed: {e}")
        used_lkg = True
    
    return LaunchResult(
        target=target,
        success=True,  # Launch should proceed regardless
        used_last_known_good=used_lkg,
        warnings=warnings,
        errors=errors,
    )


def format_launch_warnings(result: LaunchResult) -> str:
    """Format warnings for display before launch."""
    if not result.warnings:
        return ""
    
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("WARNING: Launch proceeding with last-known-good outputs")
    lines.append("=" * 60)
    for w in result.warnings:
        lines.append(f"  {w}")
    lines.append("")
    lines.append("The TUI will launch but may not have the latest assets.")
    lines.append("Run `botpack doctor` after your session for remediation.")
    lines.append("=" * 60)
    lines.append("")
    
    return "\n".join(lines)
