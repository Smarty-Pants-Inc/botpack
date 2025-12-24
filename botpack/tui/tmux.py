from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


TuiName = Literal["opencode", "droid", "codex", "coder", "claude", "amp"]


def _ts_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_artifacts_root(repo_root: Path) -> Path:
    return repo_root / "dist" / "manual"


def _state_file(repo_root: Path, tui: str) -> Path:
    return _default_artifacts_root(repo_root) / f"{tui}-tmux.latest.json"


def _load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _maybe_source_env(*, env_file: Path | None, env_cmd: str | None) -> list[str]:
    parts: list[str] = []
    if env_file is not None:
        parts.append(f"source {shlex.quote(str(env_file))}")
    if env_cmd:
        # env_cmd is treated as a bash snippet intentionally (advanced users).
        parts.append(env_cmd)
    return parts


def _start_cmd_for(
    tui: TuiName,
    *,
    repo_root: Path,
    model: str | None,
    agent: str | None,
    droid_args: str | None,
) -> str:
    m = model or os.environ.get("MODEL") or "openai/gpt-5"
    a = agent or os.environ.get("AGENT") or "smarty"
    da = droid_args or os.environ.get("DROID_ARGS") or ""

    if tui == "opencode":
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(repo_root / ".opencode")
        return f"export XDG_CONFIG_HOME={shlex.quote(xdg)}; opencode -m {shlex.quote(m)} --agent {shlex.quote(a)}"
    if tui == "droid":
        return "droid" + (" " + da if da else "")
    if tui == "codex":
        return "codex repl"
    if tui == "coder":
        return "coder"
    if tui == "claude":
        return "claude --debug"
    if tui == "amp":
        return "amp"
    raise ValueError(f"unknown TUI: {tui}")


@dataclass(frozen=True)
class TmuxSession:
    tui: TuiName
    repo_root: Path
    sock: str
    sess: str
    art_dir: Path

    @staticmethod
    def load_latest(*, tui: TuiName, repo_root: Path) -> TmuxSession | None:
        st = _load_state(_state_file(repo_root, tui))
        if not st:
            return None
        try:
            sock = str(st["sock"])
            sess = str(st["sess"])
            art = Path(str(st["art"]))
        except Exception:
            return None
        return TmuxSession(tui=tui, repo_root=repo_root, sock=sock, sess=sess, art_dir=art)

    @staticmethod
    def ensure(
        *,
        tui: TuiName,
        repo_root: Path,
        sock: str | None = None,
        sess: str | None = None,
        art_dir: Path | None = None,
        reuse_latest: bool = True,
    ) -> TmuxSession:
        latest = TmuxSession.load_latest(tui=tui, repo_root=repo_root) if reuse_latest else None

        s_sock = sock or (latest.sock if latest else None) or f"{tui}_{_ts_utc_compact()}"
        s_sess = sess or (latest.sess if latest else None) or tui
        s_art = art_dir or (latest.art_dir if latest else None) or (
            _default_artifacts_root(repo_root) / f"{tui}-{_ts_utc_compact()}-interactive"
        )

        return TmuxSession(tui=tui, repo_root=repo_root, sock=s_sock, sess=s_sess, art_dir=Path(s_art))

    def _tmux(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["tmux", "-L", self.sock, "-f", "/dev/null", *args],
            capture_output=True,
            text=True,
        )

    def start(
        self,
        *,
        env_file: Path | None = None,
        env_cmd: str | None = None,
        model: str | None = None,
        agent: str | None = None,
        droid_args: str | None = None,
    ) -> None:
        self.art_dir.mkdir(parents=True, exist_ok=True)

        if self.tui == "opencode":
            # OpenCode expects XDG_CONFIG_HOME to exist.
            (self.repo_root / ".opencode").mkdir(parents=True, exist_ok=True)

        # Reset isolated tmux server.
        self._tmux("kill-server")

        start_cmd = "; ".join(
            [
                *(_maybe_source_env(env_file=env_file, env_cmd=env_cmd)),
                f"cd {shlex.quote(str(self.repo_root))}",
                f"exec {_start_cmd_for(self.tui, repo_root=self.repo_root, model=model, agent=agent, droid_args=droid_args)}",
            ]
        )

        # Launch with a login shell so users can use 'source' reliably.
        self._tmux("new-session", "-d", "-s", self.sess, "bash", "-lc", start_cmd)

        raw = self.art_dir / "tmux.raw"
        self._tmux("pipe-pane", "-t", self.sess, "-o", f"cat >> {shlex.quote(str(raw))}")

        # Nudge the UI.
        self._tmux("send-keys", "-t", self.sess, "C-m")

        _write_state(
            _state_file(self.repo_root, self.tui),
            {
                "tui": self.tui,
                "sock": self.sock,
                "sess": self.sess,
                "art": str(self.art_dir),
                "generated_at": _ts_utc_compact(),
            },
        )

        (self.art_dir / "env.sh").write_text(
            f"export SOCK={shlex.quote(self.sock)}\n"
            f"export SESS={shlex.quote(self.sess)}\n"
            f"export ART={shlex.quote(str(self.art_dir))}\n",
            encoding="utf-8",
        )

    def attach(self) -> None:
        subprocess.run(["tmux", "-L", self.sock, "attach", "-t", self.sess])

    def send(self, text: str) -> None:
        if not text:
            raise ValueError("send: missing text")
        self._tmux("send-keys", "-t", self.sess, "--", text, "C-m")

    def sendkey(self, *keys: str) -> None:
        if not keys:
            raise ValueError("sendkey: missing keys")
        self._tmux("send-keys", "-t", self.sess, "--", *keys)

    def peek(self, *, scrollback: int = 2000) -> str:
        p = subprocess.run(
            [
                "tmux",
                "-L",
                self.sock,
                "capture-pane",
                "-p",
                "-J",
                "-S",
                f"-{scrollback}",
                "-t",
                self.sess,
            ],
            capture_output=True,
            text=True,
        )
        out = p.stdout or ""
        (self.art_dir / "tmux.peek.txt").write_text(out, encoding="utf-8")
        return out

    def kill(self) -> None:
        self._tmux("kill-session", "-t", self.sess)
        self._tmux("kill-server")

    def status(self) -> str:
        return f"tui={self.tui}\nsock={self.sock}\nsess={self.sess}\nART={self.art_dir}\n"
