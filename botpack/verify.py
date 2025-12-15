from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .lock import load_lock
from .paths import store_dir
from .store import tree_digest


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    errors: tuple[str, ...] = ()


def verify_lockfile(*, lock_path: Path) -> VerifyResult:
    lf = load_lock(lock_path)
    errs: list[str] = []

    for key, pkg in lf.packages.items():
        if not pkg.integrity:
            errs.append(f"{key}: missing integrity")
            continue
        entry = store_dir() / pkg.integrity
        if not entry.exists():
            errs.append(f"{key}: missing store entry {pkg.integrity}")
            continue
        actual = tree_digest(entry)
        if actual != pkg.integrity:
            errs.append(f"{key}: integrity mismatch (lock={pkg.integrity}, store={actual})")

    return VerifyResult(ok=not errs, errors=tuple(errs))
