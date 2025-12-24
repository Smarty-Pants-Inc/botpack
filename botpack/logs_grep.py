from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator


DEFAULT_EXTS = (".log", ".jsonl", ".txt", ".out")


def default_paths() -> dict[str, list[Path]]:
    home = Path.home()
    return {
        "claude": [home / ".claude" / "projects"],
        "codex": [home / ".codex"],
        "coder": [home / ".code"],
        "opencode": [home / ".opencode"],
        "droid": [home / ".factory" / "logs", home / ".factory" / "sessions"],
        "amp": [home / ".cache" / "amp" / "logs"],
    }


def iter_files(paths: Iterable[Path], *, exts: tuple[str, ...] = DEFAULT_EXTS) -> Iterator[Path]:
    for base in paths:
        if not base.exists():
            continue
        if base.is_file():
            if any(str(base).endswith(ext) for ext in exts):
                yield base
            continue
        for root, _dirs, files in os.walk(base):
            for f in files:
                if any(f.endswith(ext) for ext in exts):
                    yield Path(root) / f


def parse_since_window(s: str | None) -> timedelta | None:
    if not s:
        return None
    import re

    m = re.fullmatch(r"\s*(\d+)\s*([smhdSMHD])\s*", s)
    if not m:
        raise ValueError("Invalid --since value. Use formats like 2d, 6h, 30m, 45s")
    qty = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "s":
        return timedelta(seconds=qty)
    if unit == "m":
        return timedelta(minutes=qty)
    if unit == "h":
        return timedelta(hours=qty)
    if unit == "d":
        return timedelta(days=qty)
    raise ValueError("Unsupported time unit")


@dataclass(frozen=True)
class GrepHit:
    path: Path
    line: str


def grep_files(files: Iterable[Path], pattern: str, *, max_hits_per_file: int = 50) -> Iterator[GrepHit]:
    import re

    rx = re.compile(pattern)
    for fp in files:
        hits = 0
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if rx.search(line):
                        yield GrepHit(path=fp, line=line.rstrip("\n"))
                        hits += 1
                        if hits >= max_hits_per_file:
                            break
        except Exception:
            continue


def grep(
    *,
    pattern: str,
    tui: str,
    max_hits: int = 50,
    since: str | None = None,
    include_dist_tests_from_cwd: bool = True,
    now: datetime | None = None,
) -> list[tuple[str, list[GrepHit]]]:
    paths_map = default_paths()
    if tui == "all":
        tuis = list(paths_map.keys())
    else:
        if tui not in paths_map:
            raise ValueError(f"Unknown TUI: {tui}")
        tuis = [tui]

    delta = parse_since_window(since)
    now2 = now or datetime.now()
    threshold = (now2 - delta).timestamp() if delta is not None else None

    results: list[tuple[str, list[GrepHit]]] = []
    for t in tuis:
        bases = list(paths_map[t])
        if include_dist_tests_from_cwd:
            bases.append(Path.cwd() / "dist" / "tests")
        files_all = list(iter_files(bases))
        if threshold is not None:
            files = [fp for fp in files_all if fp.exists() and fp.stat().st_mtime >= threshold]
        else:
            files = files_all
        hits = list(grep_files(files, pattern, max_hits_per_file=max_hits))
        results.append((t, hits))
    return results
