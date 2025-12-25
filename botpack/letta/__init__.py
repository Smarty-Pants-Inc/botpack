"""Letta integration for Botpack.

This module provides first-class Letta support including:
- Data structures for managed vs observed Letta resources
- PR-only governance workflows (diff, pull, push, status, bootstrap)
- Letta Code target materialization (.letta/settings.json)

Letta is treated as a deploy-capable target for managed resources (blocks, templates,
tools, MCP, folders) while Letta Code is a materialization target that writes to .letta/.

Key principles:
- All shared Letta changes must land as Git PRs (PR-only governance)
- ADE edits are captured via `pull` which produces a branch/commit for PR
- `push` refuses to overwrite if drift exists
- `launch letta-code` never blocks on conflicts
"""

from __future__ import annotations

from .models import (
    # Core resource types
    LettaBlock,
    LettaTemplate,
    LettaTool,
    LettaMcpServer,
    LettaFolder,
    LettaAgentConfig,
    # State containers
    LettaManagedState,
    LettaObservedState,
    # Diff types
    LettaDiffItem,
    LettaDiffResult,
    LettaDriftDirection,
    # Address types
    LettaAssetAddress,
)
from .workflows import (
    letta_diff,
    letta_pull,
    letta_push,
    letta_status,
    letta_bootstrap,
    LettaWorkflowResult,
    LettaStatusResult,
    LettaBootstrapResult,
)
from .materialize import (
    materialize_letta_settings,
    LettaMaterializeResult,
)
from .client import (
    LettaClient,
    LettaClientConfig,
    create_letta_client,
)

__all__ = [
    # Models - Core types
    "LettaBlock",
    "LettaTemplate",
    "LettaTool",
    "LettaMcpServer",
    "LettaFolder",
    "LettaAgentConfig",
    # Models - State containers
    "LettaManagedState",
    "LettaObservedState",
    # Models - Diff types
    "LettaDiffItem",
    "LettaDiffResult",
    "LettaDriftDirection",
    # Models - Address types
    "LettaAssetAddress",
    # Workflows
    "letta_diff",
    "letta_pull",
    "letta_push",
    "letta_status",
    "letta_bootstrap",
    "LettaWorkflowResult",
    "LettaStatusResult",
    "LettaBootstrapResult",
    # Materialization
    "materialize_letta_settings",
    "LettaMaterializeResult",
    # Client
    "LettaClient",
    "LettaClientConfig",
    "create_letta_client",
]
