"""Letta workflow implementations: diff, pull, push, status, bootstrap.

This module implements the core Letta CLI commands as defined in
SPEC.md section 17.5:

- `letta status` - Show drift summary and health
- `letta diff` - Detailed comparison of Git vs Letta state
- `letta pull` - Capture Letta drift to Git (branch/commit for PR)
- `letta push` - Deploy Git state to Letta (refuses on drift)
- `letta bootstrap` - Create/bind agent instance and optionally launch

Key safety principles (SPEC.md section 17.2):
- All shared Letta changes must land as Git PRs (PR-only governance)
- ADE edits are captured via `pull` which produces a branch/commit
- `push` refuses to overwrite if drift exists
- `launch letta-code` never blocks on conflicts

These functions are designed to be called by the CLI layer; they
do not perform any I/O directly (except through injected clients).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from .models import (
    LettaBlock,
    LettaDiffResult,
    LettaDriftDirection,
    LettaManagedState,
    LettaObservedState,
    LettaAssetAddress,
    LettaBlockPathMapping,
)
from .client import LettaClient, LettaClientError, LettaOfflineError
from .drift import compute_diff
from .scan import scan_letta_assets


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class LettaWorkflowStatus(str, Enum):
    """Status codes for Letta workflow operations."""

    SUCCESS = "success"
    NO_CHANGES = "no_changes"
    DRIFT_DETECTED = "drift_detected"
    CONFLICT = "conflict"
    OFFLINE = "offline"
    ERROR = "error"


@dataclass
class LettaWorkflowResult:
    """Result of a Letta workflow operation.

    Used by diff, pull, push commands to report results.
    """

    status: LettaWorkflowStatus
    message: str
    diff: LettaDiffResult | None = None
    created_branch: str | None = None  # For pull: branch name created
    created_commit: str | None = None  # For pull: commit SHA created
    items_applied: list[str] = field(default_factory=list)  # For push: addresses applied
    items_skipped: list[str] = field(default_factory=list)  # For push: addresses skipped
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (LettaWorkflowStatus.SUCCESS, LettaWorkflowStatus.NO_CHANGES)


@dataclass
class LettaStatusResult:
    """Result of `letta status` command.

    Provides a summary view of Letta integration health.
    """

    # Connection status
    letta_reachable: bool
    letta_url: str | None = None
    agent_id: str | None = None

    # Drift summary
    has_drift: bool = False
    drift_count: int = 0
    git_changes_count: int = 0  # Changes in Git not yet pushed
    letta_changes_count: int = 0  # Changes in Letta not yet pulled
    conflict_count: int = 0

    # Asset counts
    managed_blocks: int = 0
    managed_templates: int = 0
    managed_tools: int = 0
    managed_agents: int = 0

    # Recommendations
    recommended_actions: list[str] = field(default_factory=list)

    # Detailed diff (if requested)
    diff: LettaDiffResult | None = None


@dataclass
class LettaBootstrapResult:
    """Result of `letta bootstrap` command.

    Reports on agent creation/binding status.
    """

    status: LettaWorkflowStatus
    message: str
    agent_id: str | None = None
    agent_name: str | None = None
    blocks_created: list[str] = field(default_factory=list)
    was_existing: bool = False  # True if agent already existed
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == LettaWorkflowStatus.SUCCESS


# ---------------------------------------------------------------------------
# letta status
# ---------------------------------------------------------------------------


def letta_status(
    *,
    client: LettaClient,
    letta_dir: Path | None = None,
    include_diff: bool = False,
) -> LettaStatusResult:
    """Get Letta integration status for the current workspace.

    This is the primary health surface for Letta integration, summarizing:
    - Connection status (is Letta reachable?)
    - Drift state (Git vs Letta differences)
    - Recommended next actions

    Per SPEC.md section 0.2.1, `botpack status` should include Letta drift summary.

    Args:
        client: Letta client for querying runtime state
        letta_dir: Path to letta assets (default: botpack/letta/)
        include_diff: Include detailed diff in result

    Returns:
        LettaStatusResult with status summary
    """
    # Scan managed state from Git
    managed = scan_letta_assets(letta_dir)

    # Check Letta connectivity
    letta_reachable = client.ping()

    result = LettaStatusResult(
        letta_reachable=letta_reachable,
        letta_url=client.config.api_url,
        agent_id=client.config.agent_id,
        managed_blocks=len(managed.blocks),
        managed_templates=len(managed.templates),
        managed_tools=len(managed.tools),
        managed_agents=len(managed.agents),
    )

    # Build recommendations
    if managed.is_empty:
        result.recommended_actions.append(
            "No Letta assets found. Create blocks in botpack/letta/blocks/repo/"
        )
        return result

    if not letta_reachable:
        result.recommended_actions.append(
            "Letta server not reachable. Check connection or run in offline mode."
        )
        return result

    # Get observed state and compute diff
    try:
        observed = client.get_observed_state()
        diff = compute_diff(managed, observed)

        result.has_drift = diff.has_drift
        result.drift_count = len(diff.items)
        result.conflict_count = len([i for i in diff.items if i.direction == LettaDriftDirection.CONFLICT])
        result.git_changes_count = len([
            i for i in diff.items
            if i.direction in (LettaDriftDirection.ADDED_IN_GIT, LettaDriftDirection.MODIFIED_IN_GIT)
        ])
        result.letta_changes_count = len([
            i for i in diff.items
            if i.direction in (LettaDriftDirection.ADDED_IN_LETTA, LettaDriftDirection.MODIFIED_IN_LETTA)
        ])

        if include_diff:
            result.diff = diff

        # Build recommendations based on drift
        if result.conflict_count > 0:
            result.recommended_actions.append(
                f"Resolve {result.conflict_count} conflict(s) with `botpack letta diff`"
            )
        if result.letta_changes_count > 0:
            result.recommended_actions.append(
                f"Pull {result.letta_changes_count} Letta change(s) with `botpack letta pull`"
            )
        if result.git_changes_count > 0 and result.letta_changes_count == 0:
            result.recommended_actions.append(
                f"Push {result.git_changes_count} Git change(s) with `botpack letta push`"
            )
        if not result.has_drift:
            result.recommended_actions.append("Letta state is in sync with Git.")

    except LettaOfflineError:
        result.recommended_actions.append(
            "Running in offline mode. Connect to Letta to check drift."
        )
    except LettaClientError as e:
        result.recommended_actions.append(f"Error querying Letta: {e}")

    return result


# ---------------------------------------------------------------------------
# letta diff
# ---------------------------------------------------------------------------


def letta_diff(
    *,
    client: LettaClient,
    letta_dir: Path | None = None,
) -> LettaWorkflowResult:
    """Compare Git state with Letta runtime state.

    Shows detailed differences between what's defined in Git (botpack/letta/)
    and what exists in the Letta server.

    This is a read-only operation that does not modify either Git or Letta.

    Args:
        client: Letta client for querying runtime state
        letta_dir: Path to letta assets (default: botpack/letta/)

    Returns:
        LettaWorkflowResult with diff details
    """
    # Scan managed state from Git
    managed = scan_letta_assets(letta_dir)

    if managed.is_empty:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.NO_CHANGES,
            message="No Letta assets found in botpack/letta/",
        )

    # Get observed state
    try:
        observed = client.get_observed_state()
    except LettaOfflineError:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.OFFLINE,
            message="Cannot diff: Letta client is in offline mode",
            diff=LettaDiffResult(managed_state=managed),
        )
    except LettaClientError as e:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.ERROR,
            message=f"Failed to get Letta state: {e}",
            error=str(e),
        )

    # Compute diff
    diff = compute_diff(managed, observed)

    if not diff.has_drift:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.NO_CHANGES,
            message="Git and Letta are in sync",
            diff=diff,
        )

    if diff.has_conflicts:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.CONFLICT,
            message=f"Found {len(diff.items)} difference(s), including conflicts",
            diff=diff,
        )

    return LettaWorkflowResult(
        status=LettaWorkflowStatus.DRIFT_DETECTED,
        message=f"Found {len(diff.items)} difference(s) between Git and Letta",
        diff=diff,
    )


# ---------------------------------------------------------------------------
# letta pull
# ---------------------------------------------------------------------------


def letta_pull(
    *,
    client: LettaClient,
    letta_dir: Path | None = None,
    branch_name: str | None = None,
    dry_run: bool = False,
) -> LettaWorkflowResult:
    """Capture Letta drift to Git as a branch/commit for PR review.

    This implements PR-only governance by:
    1. Detecting changes made in Letta (ADE edits)
    2. Writing those changes to botpack/letta/ files
    3. Creating a branch and commit for PR review

    Per SPEC.md section 17.2, all shared Letta changes must land as Git PRs.
    ADE edits are captured via this `pull` workflow.

    Args:
        client: Letta client for querying runtime state
        letta_dir: Path to letta assets (default: botpack/letta/)
        branch_name: Name for the drift capture branch (default: auto-generated)
        dry_run: If True, report changes without writing files

    Returns:
        LettaWorkflowResult with branch/commit info if changes were captured
    """
    from ..paths import work_root

    # Get current diff
    diff_result = letta_diff(client=client, letta_dir=letta_dir)

    if diff_result.status == LettaWorkflowStatus.OFFLINE:
        return diff_result

    if diff_result.status == LettaWorkflowStatus.ERROR:
        return diff_result

    if not diff_result.diff or not diff_result.diff.has_letta_changes:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.NO_CHANGES,
            message="No Letta changes to pull",
            diff=diff_result.diff,
        )

    # Determine target directory
    if letta_dir is None:
        letta_dir = work_root() / "botpack" / "letta"

    # Generate branch name if not provided
    if branch_name is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"letta/drift-{timestamp}"

    if dry_run:
        letta_changes = [
            str(item.address)
            for item in diff_result.diff.items
            if item.direction in (LettaDriftDirection.ADDED_IN_LETTA, LettaDriftDirection.MODIFIED_IN_LETTA)
        ]
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.DRIFT_DETECTED,
            message=f"Would capture {len(letta_changes)} Letta change(s) to branch '{branch_name}'",
            diff=diff_result.diff,
            created_branch=branch_name,
            items_applied=letta_changes,
        )

    # TODO: Implement actual file writing and git operations
    # This would:
    # 1. Create the branch
    # 2. For each ADDED_IN_LETTA or MODIFIED_IN_LETTA item:
    #    - Write observed value to appropriate file in letta_dir
    # 3. Stage and commit changes
    # 4. Return branch/commit info

    return LettaWorkflowResult(
        status=LettaWorkflowStatus.ERROR,
        message="Pull implementation pending: git operations not yet implemented",
        diff=diff_result.diff,
        error="Not implemented: git branch/commit operations",
    )


# ---------------------------------------------------------------------------
# letta push
# ---------------------------------------------------------------------------


def letta_push(
    *,
    client: LettaClient,
    letta_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> LettaWorkflowResult:
    """Deploy Git state to Letta.

    This pushes the desired state from botpack/letta/ to the Letta server.

    SAFETY: By default, push REFUSES to overwrite if drift exists
    (Letta has changes not in Git). Use `--force` to override.

    Per SPEC.md section 17.2:
    - `push` refuses to overwrite if drift exists
    - This ensures ADE edits are not accidentally lost

    Args:
        client: Letta client for deploying state
        letta_dir: Path to letta assets (default: botpack/letta/)
        force: If True, overwrite even if drift exists (dangerous!)
        dry_run: If True, report changes without applying

    Returns:
        LettaWorkflowResult with deployment status
    """
    # Get current diff
    diff_result = letta_diff(client=client, letta_dir=letta_dir)

    if diff_result.status == LettaWorkflowStatus.OFFLINE:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.OFFLINE,
            message="Cannot push: Letta client is in offline mode",
            diff=diff_result.diff,
        )

    if diff_result.status == LettaWorkflowStatus.ERROR:
        return diff_result

    if not diff_result.diff or not diff_result.diff.has_git_changes:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.NO_CHANGES,
            message="No Git changes to push",
            diff=diff_result.diff,
        )

    # Check for drift that would be overwritten
    if diff_result.diff.has_letta_changes and not force:
        letta_changes = [
            str(item.address)
            for item in diff_result.diff.items
            if item.direction in (LettaDriftDirection.ADDED_IN_LETTA, LettaDriftDirection.MODIFIED_IN_LETTA)
        ]
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.DRIFT_DETECTED,
            message=(
                f"Refusing to push: {len(letta_changes)} Letta change(s) would be overwritten. "
                "Run `botpack letta pull` first, or use --force to override."
            ),
            diff=diff_result.diff,
            items_skipped=letta_changes,
        )

    # Collect items to push
    git_changes = [
        str(item.address)
        for item in diff_result.diff.items
        if item.direction in (LettaDriftDirection.ADDED_IN_GIT, LettaDriftDirection.MODIFIED_IN_GIT)
    ]

    if dry_run:
        return LettaWorkflowResult(
            status=LettaWorkflowStatus.SUCCESS,
            message=f"Would push {len(git_changes)} change(s) to Letta",
            diff=diff_result.diff,
            items_applied=git_changes,
        )

    # TODO: Implement actual push logic
    # This would:
    # 1. For each ADDED_IN_GIT block: client.create_block(...)
    # 2. For each MODIFIED_IN_GIT block: client.update_block(...)
    # 3. Similarly for templates, tools, etc.

    return LettaWorkflowResult(
        status=LettaWorkflowStatus.ERROR,
        message="Push implementation pending: client operations not yet implemented",
        diff=diff_result.diff,
        error="Not implemented: Letta API operations",
    )


# ---------------------------------------------------------------------------
# letta bootstrap
# ---------------------------------------------------------------------------


def letta_bootstrap(
    *,
    client: LettaClient,
    agent_name: str | None = None,
    template_id: str | None = None,
    letta_dir: Path | None = None,
    dry_run: bool = False,
) -> LettaBootstrapResult:
    """Create or bind a Letta agent instance.

    Bootstrap sets up a new Letta agent from the managed configuration,
    or binds to an existing agent. This is typically run once per
    workspace to establish the agent instance.

    Per SPEC.md section 17.5, bootstrap creates/binds an agent instance
    and optionally launches.

    Args:
        client: Letta client for agent operations
        agent_name: Name for the new agent (default: derived from repo)
        template_id: Template to instantiate from (optional)
        letta_dir: Path to letta assets (default: botpack/letta/)
        dry_run: If True, report actions without executing

    Returns:
        LettaBootstrapResult with agent binding status
    """
    from ..paths import work_root

    # Scan managed state
    managed = scan_letta_assets(letta_dir)

    # Determine agent name
    if agent_name is None:
        # Default to repo directory name
        agent_name = work_root().name

    # Check if agent already exists
    try:
        existing_agents = client.list_agents()
        existing = next((a for a in existing_agents if a.name == agent_name), None)

        if existing:
            return LettaBootstrapResult(
                status=LettaWorkflowStatus.SUCCESS,
                message=f"Agent '{agent_name}' already exists",
                agent_id=existing.letta_id,
                agent_name=agent_name,
                was_existing=True,
            )
    except LettaOfflineError:
        return LettaBootstrapResult(
            status=LettaWorkflowStatus.OFFLINE,
            message="Cannot bootstrap: Letta client is in offline mode",
        )
    except LettaClientError as e:
        return LettaBootstrapResult(
            status=LettaWorkflowStatus.ERROR,
            message=f"Failed to check existing agents: {e}",
            error=str(e),
        )

    # Collect blocks to create
    blocks_to_create = list(managed.blocks.keys())

    if dry_run:
        return LettaBootstrapResult(
            status=LettaWorkflowStatus.SUCCESS,
            message=f"Would create agent '{agent_name}' with {len(blocks_to_create)} block(s)",
            agent_name=agent_name,
            blocks_created=blocks_to_create,
        )

    # TODO: Implement actual bootstrap logic
    # This would:
    # 1. Create agent with specified name/template
    # 2. Create all managed blocks
    # 3. Attach blocks to agent
    # 4. Return agent ID

    return LettaBootstrapResult(
        status=LettaWorkflowStatus.ERROR,
        message="Bootstrap implementation pending: agent creation not yet implemented",
        agent_name=agent_name,
        error="Not implemented: Letta API operations",
    )
