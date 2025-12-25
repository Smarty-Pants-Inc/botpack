from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .assets import scan_assets
from .config import botyard_manifest_path, parse_botyard_toml_file
from .errors import BotyardConfigError
from .issues import conflict_issue_id
from .sync import ConflictRecord, load_conflicts


@dataclass(frozen=True)
class DoctorIssue:
    """A single issue found by doctor diagnostics.

    Issues are identified by a stable ID that can be passed to `botpack explain`
    for detailed resolution guidance.
    """

    id: str
    severity: str  # "error", "warning", "info"
    message: str
    asset_address: str | None = None
    fix_command: str | None = None


@dataclass(frozen=True)
class DoctorResult:
    ok: bool
    warnings: tuple[str, ...] = ()
    issues: tuple[DoctorIssue, ...] = ()


def run_doctor(*, manifest_path: Path | None = None) -> DoctorResult:
    """Run diagnostics and return actionable issues.

    Doctor checks:
    - Manifest validity
    - PEP 723 tooling prerequisites (uv)
    - Sync conflicts across all targets (from conflict records)
    """
    if manifest_path is None:
        default = botyard_manifest_path()
        if not default.exists():
            return DoctorResult(ok=True, warnings=("No botpack.toml found (skipping assets checks).",))

    try:
        cfg = parse_botyard_toml_file(manifest_path)
    except BotyardConfigError as e:
        return DoctorResult(ok=True, warnings=(str(e),))
    root = Path.cwd() if manifest_path is None else manifest_path.parent

    # Assets directory (formerly workspace) contains first-party assets.
    assets_dir = Path(cfg.workspace.dir)
    if not assets_dir.is_absolute():
        assets_dir = (root / assets_dir).resolve()

    idx = scan_assets(assets_dir)
    needs_uv = any(s.pep723 is not None for sk in idx.skills for s in sk.scripts)

    warnings: list[str] = []
    issues: list[DoctorIssue] = []

    if needs_uv and shutil.which("uv") is None:
        warnings.append("Detected PEP 723 script metadata but 'uv' is not installed.")
        issues.append(
            DoctorIssue(
                id="missing-uv",
                severity="warning",
                message="Detected PEP 723 script metadata but 'uv' is not installed.",
                fix_command="pip install uv",
            )
        )

    # Check for sync conflicts across all targets
    for target in ["claude", "amp", "droid", "letta-code"]:
        conflict_records = load_conflicts(target)
        for cr in conflict_records:
            issue_id = conflict_issue_id(target=target, path=cr.path)
            addr = cr.asset_address.address if cr.asset_address else None
            issues.append(
                DoctorIssue(
                    id=issue_id,
                    severity="error",
                    message=f"[{target}] {cr.reason}: {cr.path}",
                    asset_address=addr,
                    fix_command=f"botpack sync {target} --force",
                )
            )

    ok = len([i for i in issues if i.severity == "error"]) == 0

    return DoctorResult(ok=ok, warnings=tuple(warnings), issues=tuple(issues))


def explain_issue(issue_id: str, *, manifest_path: Path | None = None) -> str | None:
    """Provide detailed explanation and resolution for a specific issue ID.

    Args:
        issue_id: The stable issue ID (e.g., "sync-conflict-claude-...")
        manifest_path: Optional path to botpack.toml

    Returns:
        Detailed explanation string, or None if issue not found.
    """
    result = run_doctor(manifest_path=manifest_path)

    for issue in result.issues:
        if issue.id == issue_id:
            lines = [
                f"Issue: {issue.id}",
                f"Severity: {issue.severity}",
                f"Message: {issue.message}",
            ]
            if issue.asset_address:
                lines.append(f"Asset Address: {issue.asset_address}")
            if issue.fix_command:
                lines.append(f"\nSuggested fix:")
                lines.append(f"  {issue.fix_command}")

            # Add context-specific guidance
            if issue_id.startswith("conflict:"):
                lines.append("\nExplanation:")
                lines.append("  A sync conflict occurs when a botpack-managed output file has been")
                lines.append("  modified outside of the sync process. This can happen when:")
                lines.append("  - You manually edited a generated file")
                lines.append("  - Another tool modified the file")
                lines.append("  - A merge conflict left the file in an unexpected state")
                lines.append("\nResolution options:")
                lines.append("  1. Use --force to overwrite with the source version")
                lines.append("  2. Manually reconcile changes and re-sync")
                lines.append("  3. Delete the conflicting file and re-sync")

            return "\n".join(lines)

    return None
