from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .lock import load_lock
from .paths import store_dir


@dataclass(frozen=True)
class PruneResult:
    removed: tuple[str, ...]


def prune_store(*, lock_path: Path, dry_run: bool = False) -> PruneResult:
    lf = load_lock(lock_path)
    keep = {pkg.integrity for pkg in lf.packages.values() if pkg.integrity}

    removed: list[str] = []
    sd = store_dir()
    if not sd.exists():
        return PruneResult(removed=())

    for p in sorted(sd.iterdir()):
        if not p.is_dir():
            continue
        if p.name in keep:
            continue
        removed.append(p.name)
        if not dry_run:
            shutil.rmtree(p)

    return PruneResult(removed=tuple(removed))
