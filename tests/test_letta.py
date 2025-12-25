"""Unit tests for Letta integration module.

All tests are offline and do not require a Letta server.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

import pytest

from botpack.letta.models import (
    LettaAssetAddress,
    LettaResourceType,
    LettaBlock,
    LettaTemplate,
    LettaTool,
    LettaAgentConfig,
    LettaManagedState,
    LettaObservedState,
    LettaDiffItem,
    LettaDiffResult,
    LettaDriftDirection,
    LettaBlockPathMapping,
)
from botpack.letta.client import (
    LettaClientConfig,
    StubLettaClient,
    LettaOfflineError,
    create_letta_client,
)
from botpack.letta.scan import (
    parse_frontmatter,
    scan_blocks,
    scan_letta_assets,
)
from botpack.letta.drift import compute_diff
from botpack.letta.workflows import (
    letta_status,
    letta_diff,
    letta_pull,
    letta_push,
    letta_bootstrap,
    LettaWorkflowStatus,
)
from botpack.letta.materialize import (
    materialize_letta_settings,
    load_letta_settings,
    LettaSettingsConfig,
)


# ---------------------------------------------------------------------------
# Asset address tests
# ---------------------------------------------------------------------------


class TestLettaAssetAddress:
    def test_str_format(self):
        addr = LettaAssetAddress(LettaResourceType.BLOCK, "project")
        assert str(addr) == "letta:block:project"

    def test_parse_valid(self):
        addr = LettaAssetAddress.parse("letta:block:project")
        assert addr.resource_type == LettaResourceType.BLOCK
        assert addr.id == "project"

    def test_parse_all_types(self):
        for rtype in LettaResourceType:
            addr = LettaAssetAddress.parse(f"letta:{rtype.value}:test")
            assert addr.resource_type == rtype
            assert addr.id == "test"

    def test_parse_invalid_prefix(self):
        with pytest.raises(ValueError, match="Invalid Letta asset address"):
            LettaAssetAddress.parse("invalid:block:project")

    def test_parse_invalid_type(self):
        with pytest.raises(ValueError, match="Unknown Letta resource type"):
            LettaAssetAddress.parse("letta:invalid:project")

    def test_parse_missing_parts(self):
        with pytest.raises(ValueError):
            LettaAssetAddress.parse("letta:block")


# ---------------------------------------------------------------------------
# Block path mapping tests
# ---------------------------------------------------------------------------


class TestLettaBlockPathMapping:
    def test_repo_level_block(self):
        mapping = LettaBlockPathMapping.from_label("project")
        assert mapping.label == "project"
        assert mapping.scope == "repo"
        assert mapping.relative_path == "blocks/repo/project.md"

    def test_org_level_block(self):
        mapping = LettaBlockPathMapping.from_label("org_playbook")
        assert mapping.label == "org_playbook"
        assert mapping.scope == "org"
        assert mapping.relative_path == "blocks/org/playbook.md"

    def test_scope_level_block(self):
        mapping = LettaBlockPathMapping.from_label("scope_myproj_conventions")
        assert mapping.label == "scope_myproj_conventions"
        assert mapping.scope == "scopes/myproj"
        assert mapping.relative_path == "blocks/scopes/myproj/conventions.md"


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestLettaBlock:
    def test_address(self):
        block = LettaBlock(label="project", description="Test", value="content")
        assert str(block.address) == "letta:block:project"

    def test_with_source_path(self):
        block = LettaBlock(
            label="project",
            description="Test",
            value="content",
            source_path=Path("/path/to/project.md"),
        )
        assert block.source_path == Path("/path/to/project.md")


class TestLettaManagedState:
    def test_is_empty_when_empty(self):
        state = LettaManagedState()
        assert state.is_empty

    def test_is_empty_with_blocks(self):
        state = LettaManagedState(
            blocks={"project": LettaBlock(label="project", description="", value="")}
        )
        assert not state.is_empty


class TestLettaDiffResult:
    def test_has_drift(self):
        result = LettaDiffResult(items=[
            LettaDiffItem(
                address=LettaAssetAddress(LettaResourceType.BLOCK, "test"),
                direction=LettaDriftDirection.ADDED_IN_GIT,
            )
        ])
        assert result.has_drift

    def test_no_drift(self):
        result = LettaDiffResult()
        assert not result.has_drift

    def test_has_letta_changes(self):
        result = LettaDiffResult(items=[
            LettaDiffItem(
                address=LettaAssetAddress(LettaResourceType.BLOCK, "test"),
                direction=LettaDriftDirection.ADDED_IN_LETTA,
            )
        ])
        assert result.has_letta_changes
        assert not result.has_git_changes

    def test_has_git_changes(self):
        result = LettaDiffResult(items=[
            LettaDiffItem(
                address=LettaAssetAddress(LettaResourceType.BLOCK, "test"),
                direction=LettaDriftDirection.ADDED_IN_GIT,
            )
        ])
        assert result.has_git_changes
        assert not result.has_letta_changes

    def test_has_conflicts(self):
        result = LettaDiffResult(items=[
            LettaDiffItem(
                address=LettaAssetAddress(LettaResourceType.BLOCK, "test"),
                direction=LettaDriftDirection.CONFLICT,
            )
        ])
        assert result.has_conflicts


# ---------------------------------------------------------------------------
# Client tests
# ---------------------------------------------------------------------------


class TestLettaClientConfig:
    def test_defaults(self):
        config = LettaClientConfig()
        assert config.api_url == "http://localhost:8283"
        assert config.api_key is None
        assert config.timeout == 30.0

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("LETTA_API_URL", "http://custom:8080")
        monkeypatch.setenv("LETTA_API_KEY", "test-key")
        config = LettaClientConfig.from_env()
        assert config.api_url == "http://custom:8080"
        assert config.api_key == "test-key"


class TestStubLettaClient:
    def test_ping_returns_false(self):
        client = StubLettaClient()
        assert client.ping() is False

    def test_get_observed_state_returns_empty(self):
        client = StubLettaClient()
        state = client.get_observed_state()
        assert state.is_empty

    def test_get_block_returns_none(self):
        client = StubLettaClient()
        assert client.get_block("project") is None

    def test_create_block_raises_offline(self):
        client = StubLettaClient()
        block = LettaBlock(label="test", description="", value="")
        with pytest.raises(LettaOfflineError):
            client.create_block(block)

    def test_list_agents_returns_empty(self):
        client = StubLettaClient()
        assert client.list_agents() == []


class TestCreateLettaClient:
    def test_returns_stub_by_default(self):
        client = create_letta_client()
        assert isinstance(client, StubLettaClient)

    def test_offline_flag(self):
        config = LettaClientConfig(api_url="http://real.server")
        client = create_letta_client(config, offline=True)
        assert isinstance(client, StubLettaClient)


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_with_frontmatter(self):
        content = """---
label: project
description: Test description
---

Body content here.
"""
        parsed = parse_frontmatter(content)
        assert parsed.frontmatter.get("label") == "project"
        assert parsed.frontmatter.get("description") == "Test description"
        assert parsed.body == "Body content here."

    def test_without_frontmatter(self):
        content = "Just plain content"
        parsed = parse_frontmatter(content)
        assert parsed.frontmatter == {}
        assert parsed.body == "Just plain content"

    def test_quoted_values(self):
        content = """---
label: "quoted label"
other: 'single quoted'
---
Body
"""
        parsed = parse_frontmatter(content)
        assert parsed.frontmatter.get("label") == "quoted label"
        assert parsed.frontmatter.get("other") == "single quoted"


class TestScanBlocks:
    def test_scan_empty_dir(self, tmp_path):
        blocks = scan_blocks(tmp_path)
        assert blocks == {}

    def test_scan_repo_block(self, tmp_path):
        blocks_dir = tmp_path / "blocks" / "repo"
        blocks_dir.mkdir(parents=True)
        (blocks_dir / "project.md").write_text("""---
description: Project context
---

This is the project description.
""")
        blocks = scan_blocks(tmp_path)
        assert "project" in blocks
        assert blocks["project"].description == "Project context"
        assert "project description" in blocks["project"].value

    def test_scan_org_block(self, tmp_path):
        blocks_dir = tmp_path / "blocks" / "org"
        blocks_dir.mkdir(parents=True)
        (blocks_dir / "playbook.md").write_text("Org playbook content")
        blocks = scan_blocks(tmp_path)
        assert "org_playbook" in blocks

    def test_scan_scope_block(self, tmp_path):
        blocks_dir = tmp_path / "blocks" / "scopes" / "myproj"
        blocks_dir.mkdir(parents=True)
        (blocks_dir / "conventions.md").write_text("Conventions")
        blocks = scan_blocks(tmp_path)
        assert "scope_myproj_conventions" in blocks


class TestScanLettaAssets:
    def test_scan_empty_returns_empty_state(self, tmp_path):
        state = scan_letta_assets(tmp_path)
        assert state.is_empty

    def test_scan_with_blocks(self, tmp_path):
        blocks_dir = tmp_path / "blocks" / "repo"
        blocks_dir.mkdir(parents=True)
        (blocks_dir / "project.md").write_text("Project content")
        state = scan_letta_assets(tmp_path)
        assert not state.is_empty
        assert "project" in state.blocks


# ---------------------------------------------------------------------------
# Drift detection tests
# ---------------------------------------------------------------------------


class TestComputeDiff:
    def test_no_drift_when_empty(self):
        managed = LettaManagedState()
        observed = LettaObservedState()
        diff = compute_diff(managed, observed)
        assert not diff.has_drift

    def test_added_in_git(self):
        managed = LettaManagedState(
            blocks={"project": LettaBlock(label="project", description="", value="content")}
        )
        observed = LettaObservedState()
        diff = compute_diff(managed, observed)
        assert diff.has_drift
        assert diff.has_git_changes
        assert len(diff.items) == 1
        assert diff.items[0].direction == LettaDriftDirection.ADDED_IN_GIT

    def test_added_in_letta(self):
        managed = LettaManagedState()
        observed = LettaObservedState(
            blocks={"project": LettaBlock(label="project", description="", value="content")}
        )
        diff = compute_diff(managed, observed)
        assert diff.has_drift
        assert diff.has_letta_changes
        assert len(diff.items) == 1
        assert diff.items[0].direction == LettaDriftDirection.ADDED_IN_LETTA

    def test_conflict_on_content_mismatch(self):
        managed = LettaManagedState(
            blocks={"project": LettaBlock(label="project", description="A", value="Git version")}
        )
        observed = LettaObservedState(
            blocks={"project": LettaBlock(label="project", description="A", value="Letta version")}
        )
        diff = compute_diff(managed, observed)
        assert diff.has_drift
        assert diff.has_conflicts
        assert diff.items[0].direction == LettaDriftDirection.CONFLICT


# ---------------------------------------------------------------------------
# Workflow tests
# ---------------------------------------------------------------------------


class TestLettaStatus:
    def test_status_offline(self, tmp_path):
        client = StubLettaClient()
        result = letta_status(client=client, letta_dir=tmp_path)
        assert not result.letta_reachable
        assert result.managed_blocks == 0

    def test_status_with_blocks(self, tmp_path):
        blocks_dir = tmp_path / "blocks" / "repo"
        blocks_dir.mkdir(parents=True)
        (blocks_dir / "project.md").write_text("Content")
        
        client = StubLettaClient()
        result = letta_status(client=client, letta_dir=tmp_path)
        assert result.managed_blocks == 1


class TestLettaDiff:
    def test_diff_with_git_assets_stub_client(self, tmp_path):
        """Stub client returns empty observed state, so Git assets show as drift."""
        blocks_dir = tmp_path / "blocks" / "repo"
        blocks_dir.mkdir(parents=True)
        (blocks_dir / "project.md").write_text("Content")
        
        client = StubLettaClient()
        result = letta_diff(client=client, letta_dir=tmp_path)
        # Stub client returns empty state, so Git has content not in Letta = drift
        assert result.status == LettaWorkflowStatus.DRIFT_DETECTED
        assert result.diff is not None
        assert result.diff.has_git_changes

    def test_diff_no_assets(self, tmp_path):
        client = StubLettaClient()
        result = letta_diff(client=client, letta_dir=tmp_path)
        assert result.status == LettaWorkflowStatus.NO_CHANGES


class TestLettaPull:
    def test_pull_no_letta_changes_stub(self, tmp_path):
        """Stub client returns empty state, so no Letta changes to pull."""
        blocks_dir = tmp_path / "blocks" / "repo"
        blocks_dir.mkdir(parents=True)
        (blocks_dir / "project.md").write_text("Content")
        
        client = StubLettaClient()
        result = letta_pull(client=client, letta_dir=tmp_path)
        # Stub returns empty Letta state, so nothing to pull (only Git changes exist)
        assert result.status == LettaWorkflowStatus.NO_CHANGES


class TestLettaPush:
    def test_push_not_implemented(self, tmp_path):
        """Push is not yet implemented (returns ERROR)."""
        blocks_dir = tmp_path / "blocks" / "repo"
        blocks_dir.mkdir(parents=True)
        (blocks_dir / "project.md").write_text("Content")
        
        client = StubLettaClient()
        result = letta_push(client=client, letta_dir=tmp_path)
        # Push implementation is pending
        assert result.status == LettaWorkflowStatus.ERROR
        assert "not yet implemented" in result.message.lower() or result.error is not None


class TestLettaBootstrap:
    def test_bootstrap_not_implemented(self, tmp_path):
        """Bootstrap is not yet implemented (returns ERROR)."""
        client = StubLettaClient()
        result = letta_bootstrap(client=client, letta_dir=tmp_path)
        # Bootstrap implementation is pending
        assert result.status == LettaWorkflowStatus.ERROR
        assert result.error is not None


# ---------------------------------------------------------------------------
# Materialization tests
# ---------------------------------------------------------------------------


class TestLettaSettingsConfig:
    def test_to_dict(self):
        config = LettaSettingsConfig(
            default_agent="test-agent",
            memory_blocks=["project", "conventions"],
        )
        data = config.to_dict()
        assert data["default_agent"] == "test-agent"
        assert data["memory_blocks"] == ["project", "conventions"]

    def test_from_dict(self):
        data = {
            "default_agent": "test-agent",
            "memory_blocks": ["project"],
            "custom_key": "custom_value",
        }
        config = LettaSettingsConfig.from_dict(data)
        assert config.default_agent == "test-agent"
        assert config.memory_blocks == ["project"]
        assert config.custom == {"custom_key": "custom_value"}


class TestMaterializeLettaSettings:
    def test_create_settings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
        
        config = LettaSettingsConfig(default_agent="test")
        result = materialize_letta_settings(root=tmp_path, config=config)
        
        assert result.ok
        assert len(result.created) == 1
        
        settings_path = tmp_path / ".letta" / "settings.json"
        assert settings_path.exists()
        
        data = json.loads(settings_path.read_text())
        assert data["default_agent"] == "test"
        assert data["_botpack"]["managed"] is True

    def test_preserve_local_settings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
        
        letta_dir = tmp_path / ".letta"
        letta_dir.mkdir()
        local_settings = letta_dir / "settings.local.json"
        local_settings.write_text('{"api_key": "secret"}')
        
        result = materialize_letta_settings(root=tmp_path)
        
        assert str(local_settings) in result.preserved
        # Local settings should be untouched
        assert json.loads(local_settings.read_text()) == {"api_key": "secret"}

    def test_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
        
        result = materialize_letta_settings(root=tmp_path, dry_run=True)
        
        assert result.ok
        settings_path = tmp_path / ".letta" / "settings.json"
        assert not settings_path.exists()  # Should not create in dry run


class TestLoadLettaSettings:
    def test_load_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
        
        letta_dir = tmp_path / ".letta"
        letta_dir.mkdir()
        settings_path = letta_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "default_agent": "loaded-agent",
            "memory_blocks": ["project"],
        }))
        
        config = load_letta_settings(root=tmp_path)
        
        assert config is not None
        assert config.default_agent == "loaded-agent"
        assert config.memory_blocks == ["project"]

    def test_load_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))
        config = load_letta_settings(root=tmp_path)
        assert config is None
