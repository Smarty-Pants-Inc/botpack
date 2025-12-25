"""Drift detection between Git-managed state and Letta runtime.

This module compares LettaManagedState (derived from Git) with
LettaObservedState (fetched from Letta) to detect drift.

Drift types:
- ADDED_IN_GIT: New resource in Git, needs push
- ADDED_IN_LETTA: New resource in Letta (ADE edit), needs pull
- MODIFIED_IN_GIT: Git version is different, needs push
- MODIFIED_IN_LETTA: Letta version is different (ADE edit), needs pull
- CONFLICT: Both changed, manual resolution needed

Key safety principle (SPEC.md section 17.2):
- push refuses to overwrite if drift exists (Letta has changes)
- pull captures drift to a branch/commit for PR review
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    LettaBlock,
    LettaTemplate,
    LettaTool,
    LettaMcpServer,
    LettaFolder,
    LettaAgentConfig,
    LettaManagedState,
    LettaObservedState,
    LettaDiffItem,
    LettaDiffResult,
    LettaDriftDirection,
    LettaAssetAddress,
    LettaResourceType,
)


# ---------------------------------------------------------------------------
# Content comparison helpers
# ---------------------------------------------------------------------------


def _normalize_content(value: str) -> str:
    """Normalize content for comparison (strip whitespace, normalize newlines)."""
    return value.strip().replace("\r\n", "\n")


def _blocks_equal(managed: LettaBlock, observed: LettaBlock) -> bool:
    """Compare two blocks for equality."""
    return (
        _normalize_content(managed.value) == _normalize_content(observed.value)
        and managed.description == observed.description
    )


def _templates_equal(managed: LettaTemplate, observed: LettaTemplate) -> bool:
    """Compare two templates for equality."""
    return (
        managed.name == observed.name
        and managed.description == observed.description
        and _normalize_content(managed.system_prompt) == _normalize_content(observed.system_prompt)
        and managed.model == observed.model
        and set(managed.tools) == set(observed.tools)
        and set(managed.memory_blocks) == set(observed.memory_blocks)
    )


def _tools_equal(managed: LettaTool, observed: LettaTool) -> bool:
    """Compare two tools for equality."""
    return (
        managed.name == observed.name
        and managed.description == observed.description
        and _normalize_content(managed.source_code) == _normalize_content(observed.source_code)
    )


def _agents_equal(managed: LettaAgentConfig, observed: LettaAgentConfig) -> bool:
    """Compare two agent configs for equality."""
    return (
        managed.name == observed.name
        and managed.description == observed.description
        and managed.template_id == observed.template_id
    )


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


def compute_diff(
    managed: LettaManagedState,
    observed: LettaObservedState,
) -> LettaDiffResult:
    """Compute differences between managed (Git) and observed (Letta) state.

    This is the core drift detection logic used by `letta diff` and
    `letta status` commands.

    Args:
        managed: Desired state from Git (botpack/letta/)
        observed: Current state from Letta runtime

    Returns:
        LettaDiffResult with all detected differences
    """
    items: list[LettaDiffItem] = []

    # Compare blocks
    items.extend(_diff_blocks(managed.blocks, observed.blocks))

    # Compare templates
    items.extend(_diff_templates(managed.templates, observed.templates))

    # Compare tools
    items.extend(_diff_tools(managed.tools, observed.tools))

    # Compare agents
    items.extend(_diff_agents(managed.agents, observed.agents))

    # TODO: Compare MCP servers and folders

    return LettaDiffResult(
        items=items,
        managed_state=managed,
        observed_state=observed,
    )


def _diff_blocks(
    managed: dict[str, LettaBlock],
    observed: dict[str, LettaBlock],
) -> list[LettaDiffItem]:
    """Diff memory blocks between managed and observed state."""
    items: list[LettaDiffItem] = []

    managed_labels = set(managed.keys())
    observed_labels = set(observed.keys())

    # Blocks only in managed (Git) -> need push
    for label in managed_labels - observed_labels:
        block = managed[label]
        items.append(
            LettaDiffItem(
                address=block.address,
                direction=LettaDriftDirection.ADDED_IN_GIT,
                managed_value=block.value[:100] + "..." if len(block.value) > 100 else block.value,
                message=f"Block '{label}' exists in Git but not in Letta",
            )
        )

    # Blocks only in observed (Letta) -> ADE edit, need pull
    for label in observed_labels - managed_labels:
        block = observed[label]
        items.append(
            LettaDiffItem(
                address=block.address,
                direction=LettaDriftDirection.ADDED_IN_LETTA,
                observed_value=block.value[:100] + "..." if len(block.value) > 100 else block.value,
                message=f"Block '{label}' exists in Letta but not in Git (ADE edit?)",
            )
        )

    # Blocks in both -> check for differences
    for label in managed_labels & observed_labels:
        m_block = managed[label]
        o_block = observed[label]

        if not _blocks_equal(m_block, o_block):
            # Determine direction (simplified: assume Git is source of truth
            # for now; real implementation would track timestamps/versions)
            # For safety, we treat this as a potential conflict
            items.append(
                LettaDiffItem(
                    address=m_block.address,
                    direction=LettaDriftDirection.CONFLICT,
                    managed_value=m_block.value[:100] + "..." if len(m_block.value) > 100 else m_block.value,
                    observed_value=o_block.value[:100] + "..." if len(o_block.value) > 100 else o_block.value,
                    message=f"Block '{label}' differs between Git and Letta",
                )
            )

    return items


def _diff_templates(
    managed: dict[str, LettaTemplate],
    observed: dict[str, LettaTemplate],
) -> list[LettaDiffItem]:
    """Diff templates between managed and observed state."""
    items: list[LettaDiffItem] = []

    managed_ids = set(managed.keys())
    observed_ids = set(observed.keys())

    for tid in managed_ids - observed_ids:
        template = managed[tid]
        items.append(
            LettaDiffItem(
                address=template.address,
                direction=LettaDriftDirection.ADDED_IN_GIT,
                message=f"Template '{tid}' exists in Git but not in Letta",
            )
        )

    for tid in observed_ids - managed_ids:
        template = observed[tid]
        items.append(
            LettaDiffItem(
                address=template.address,
                direction=LettaDriftDirection.ADDED_IN_LETTA,
                message=f"Template '{tid}' exists in Letta but not in Git",
            )
        )

    for tid in managed_ids & observed_ids:
        m_template = managed[tid]
        o_template = observed[tid]
        if not _templates_equal(m_template, o_template):
            items.append(
                LettaDiffItem(
                    address=m_template.address,
                    direction=LettaDriftDirection.CONFLICT,
                    message=f"Template '{tid}' differs between Git and Letta",
                )
            )

    return items


def _diff_tools(
    managed: dict[str, LettaTool],
    observed: dict[str, LettaTool],
) -> list[LettaDiffItem]:
    """Diff tools between managed and observed state."""
    items: list[LettaDiffItem] = []

    managed_ids = set(managed.keys())
    observed_ids = set(observed.keys())

    for tid in managed_ids - observed_ids:
        tool = managed[tid]
        items.append(
            LettaDiffItem(
                address=tool.address,
                direction=LettaDriftDirection.ADDED_IN_GIT,
                message=f"Tool '{tid}' exists in Git but not in Letta",
            )
        )

    for tid in observed_ids - managed_ids:
        tool = observed[tid]
        items.append(
            LettaDiffItem(
                address=tool.address,
                direction=LettaDriftDirection.ADDED_IN_LETTA,
                message=f"Tool '{tid}' exists in Letta but not in Git",
            )
        )

    for tid in managed_ids & observed_ids:
        m_tool = managed[tid]
        o_tool = observed[tid]
        if not _tools_equal(m_tool, o_tool):
            items.append(
                LettaDiffItem(
                    address=m_tool.address,
                    direction=LettaDriftDirection.CONFLICT,
                    message=f"Tool '{tid}' differs between Git and Letta",
                )
            )

    return items


def _diff_agents(
    managed: dict[str, LettaAgentConfig],
    observed: dict[str, LettaAgentConfig],
) -> list[LettaDiffItem]:
    """Diff agent configs between managed and observed state."""
    items: list[LettaDiffItem] = []

    managed_ids = set(managed.keys())
    observed_ids = set(observed.keys())

    for aid in managed_ids - observed_ids:
        agent = managed[aid]
        items.append(
            LettaDiffItem(
                address=agent.address,
                direction=LettaDriftDirection.ADDED_IN_GIT,
                message=f"Agent '{aid}' exists in Git but not in Letta",
            )
        )

    for aid in observed_ids - managed_ids:
        agent = observed[aid]
        items.append(
            LettaDiffItem(
                address=agent.address,
                direction=LettaDriftDirection.ADDED_IN_LETTA,
                message=f"Agent '{aid}' exists in Letta but not in Git",
            )
        )

    for aid in managed_ids & observed_ids:
        m_agent = managed[aid]
        o_agent = observed[aid]
        if not _agents_equal(m_agent, o_agent):
            items.append(
                LettaDiffItem(
                    address=m_agent.address,
                    direction=LettaDriftDirection.CONFLICT,
                    message=f"Agent '{aid}' differs between Git and Letta",
                )
            )

    return items
