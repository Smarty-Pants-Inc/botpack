from __future__ import annotations

from pathlib import Path
from unittest import mock

from botpack.logs_grep import parse_since_window, grep


def test_parse_since_window() -> None:
    assert parse_since_window(None) is None
    assert parse_since_window("2d").days == 2


def test_grep_with_patched_paths(tmp_path: Path) -> None:
    fp = tmp_path / "a.log"
    fp.write_text("hello\nerror: boom\n", encoding="utf-8")

    with mock.patch("botpack.logs_grep.default_paths", return_value={"claude": [tmp_path]}):
        res = grep(pattern="error", tui="claude", include_dist_tests_from_cwd=False)
    assert len(res) == 1
    _tui, hits = res[0]
    assert any("error: boom" in h.line for h in hits)
