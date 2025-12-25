"""Issue ID helpers.

Issue IDs are stable identifiers surfaced in `botpack status` / `botpack doctor` and
consumed by `botpack explain <id>`.

DX contract:
- IDs must be stable across runs.
- IDs must be copy/paste friendly.
- IDs must not require network.

We intentionally keep the format simple:
- conflict:<8-hex>
- trust:<8-hex>
- blocked:<8-hex>

The hash input should include enough context to avoid collisions (e.g. target + path).
"""

from __future__ import annotations

import hashlib


def _hash8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def conflict_issue_id(*, target: str, path: str) -> str:
    return f"conflict:{_hash8(f'{target}:{path}')}"


def trust_issue_id(*, pkg_key: str) -> str:
    return f"trust:{_hash8(pkg_key)}"


def blocked_issue_id(*, reason: str) -> str:
    return f"blocked:{_hash8(reason)}"
