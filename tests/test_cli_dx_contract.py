"""Tests for DX-contract CLI commands (v0.3).

Tests the new commands:
- botpack (no args) => brief status
- botpack status => full status
- botpack launch => install+sync+launch with fallback
- botpack explain => deep dive for issues
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from botpack.cli import main
from botpack.cli_status import (
    StatusInfo,
    collect_status,
    explain_issue,
    format_brief_status,
    format_full_status,
    prepare_launch,
)


def test_no_args_prints_brief_status(capsys, tmp_path):
    """botpack (no args) should print brief status summary."""
    os.environ["BOTPACK_ROOT"] = str(tmp_path)
    exit_code = main([])
    captured = capsys.readouterr()
    
    assert exit_code == 0
    assert "Botpack Status" in captured.out
    assert "Root:" in captured.out
    assert "Next actions" in captured.out


def test_status_prints_full_status(capsys, tmp_path):
    """botpack status should print full status report."""
    os.environ["BOTPACK_ROOT"] = str(tmp_path)
    exit_code = main(["status"])
    captured = capsys.readouterr()
    
    assert exit_code == 0
    assert "Universal Health Surface" in captured.out
    assert "Root Selection" in captured.out
    assert "Lock Health" in captured.out
    assert "Target Freshness" in captured.out


def test_status_json_output(capsys, tmp_path):
    """botpack status --json should output JSON."""
    os.environ["BOTPACK_ROOT"] = str(tmp_path)
    exit_code = main(["status", "--json"])
    captured = capsys.readouterr()
    
    assert exit_code == 0
    data = json.loads(captured.out)
    assert "root" in data
    assert "manifest_exists" in data
    assert "lock_exists" in data
    assert "targets" in data
    assert "has_issues" in data


def test_launch_dry_run(capsys, tmp_path):
    """botpack launch --dry-run should not actually launch."""
    os.environ["BOTPACK_ROOT"] = str(tmp_path)
    exit_code = main(["launch", "--dry-run", "--no-sync"])
    captured = capsys.readouterr()
    
    assert exit_code == 0
    assert "Would launch" in captured.out


def test_launch_with_target(capsys, tmp_path):
    """botpack launch amp --dry-run should specify target."""
    os.environ["BOTPACK_ROOT"] = str(tmp_path)
    exit_code = main(["launch", "amp", "--dry-run", "--no-sync"])
    captured = capsys.readouterr()
    
    assert exit_code == 0
    assert "amp" in captured.out


def test_launch_with_agent(capsys, tmp_path):
    """botpack launch --agent should pass agent name."""
    os.environ["BOTPACK_ROOT"] = str(tmp_path)
    exit_code = main(["launch", "--agent", "test-agent", "--dry-run", "--no-sync"])
    captured = capsys.readouterr()
    
    assert exit_code == 0
    assert "test-agent" in captured.out


def test_explain_unknown_issue(capsys, tmp_path):
    """botpack explain with unknown ID should say issue not found."""
    os.environ["BOTPACK_ROOT"] = str(tmp_path)
    exit_code = main(["explain", "unknown:12345"])
    captured = capsys.readouterr()
    
    assert exit_code == 0
    assert "Issue not found" in captured.out


def test_collect_status_empty_root():
    """collect_status should work with empty root."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_resolved = Path(tmp).resolve()
        os.environ["BOTPACK_ROOT"] = str(tmp_resolved)
        info = collect_status()
        
        assert info.root == tmp_resolved
        assert not info.manifest_exists
        assert not info.lock_exists
        assert len(info.targets) == 4  # claude, amp, droid, letta-code


def test_format_brief_status():
    """format_brief_status should produce readable output."""
    info = StatusInfo(
        root=Path("/test"),
        manifest_exists=False,
        lock_exists=False,
    )
    output = format_brief_status(info)
    
    assert "Botpack Status" in output
    assert "/test" in output
    assert "Next actions" in output


def test_format_full_status():
    """format_full_status should produce detailed output."""
    info = StatusInfo(
        root=Path("/test"),
        manifest_exists=True,
        manifest_path=Path("/test/botpack.toml"),
        lock_exists=True,
        lock_path=Path("/test/botpack.lock"),
        lock_version="0.1.0",
        packages_count=5,
    )
    output = format_full_status(info)
    
    assert "Universal Health Surface" in output
    assert "Root Selection" in output
    assert "Lock Health" in output
    assert "0.1.0" in output


def test_explain_issue_not_found():
    """explain_issue should handle unknown issues gracefully."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["BOTPACK_ROOT"] = tmp
        output = explain_issue("unknown:abc123")
        
        assert "Issue not found" in output


def test_prepare_launch_fallback():
    """prepare_launch should succeed even when install/sync fails."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["BOTPACK_ROOT"] = tmp
        result = prepare_launch(target="claude")
        
        # Should succeed (launch can proceed)
        assert result.success is True
        # Should indicate using last-known-good
        assert result.used_last_known_good is True
        # Should have warnings about failures
        assert len(result.warnings) > 0


def test_launch_never_fails_on_sync_conflict(tmp_path):
    """Launch should always succeed, even with sync issues."""
    os.environ["BOTPACK_ROOT"] = str(tmp_path)
    
    # Even with no manifest, launch should return 0 in dry-run mode
    exit_code = main(["launch", "--dry-run", "--no-sync"])
    assert exit_code == 0
