from __future__ import annotations

from pathlib import Path
from unittest import mock

from botpack.tui.tmux import TmuxSession


def test_tmux_start_writes_state_and_env(tmp_path: Path) -> None:
    repo_root = tmp_path

    sess = TmuxSession.ensure(tui="opencode", repo_root=repo_root, sock="sock1", sess="sess1", reuse_latest=False)

    with mock.patch("botpack.tui.tmux.subprocess.run") as run:
        # Provide a minimal CompletedProcess-like object for capture-pane calls.
        run.return_value = mock.Mock(stdout="", stderr="", returncode=0)
        sess.start(env_file=None, env_cmd=None, model="m", agent="a", droid_args=None)

    state = repo_root / "dist" / "manual" / "opencode-tmux.latest.json"
    assert state.exists()
    assert (sess.art_dir / "tmux.raw").parent.exists()
    assert (sess.art_dir / "env.sh").exists()
