from __future__ import annotations

"""Small TOML writer helpers.

Botpack uses TOML for human-editable config files (botpack.toml, trust.toml).
We intentionally keep writing deterministic and minimal, and we only implement
the subset of TOML that the tool emits.

Constraints:
- Deterministic ordering
- No comment preservation
- stdlib-only formatting (parsing lives elsewhere)
"""

import json
from typing import Any, Mapping


def toml_basic_string(s: str) -> str:
    """Quote a string as a TOML basic string.

    We use JSON encoding for predictable escaping + double quotes.
    """

    if not isinstance(s, str):
        raise TypeError("toml_basic_string: expected str")
    return json.dumps(s, ensure_ascii=False)


def toml_bool(v: bool) -> str:
    if not isinstance(v, bool):
        raise TypeError("toml_bool: expected bool")
    return "true" if v else "false"


def toml_int(v: int) -> str:
    if not isinstance(v, int) or isinstance(v, bool):
        raise TypeError("toml_int: expected int")
    return str(v)


def toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return toml_bool(v)
    if isinstance(v, int) and not isinstance(v, bool):
        return toml_int(v)
    if isinstance(v, str):
        return toml_basic_string(v)
    raise TypeError(f"toml_value: unsupported type: {type(v).__name__}")


def toml_inline_table(tbl: Mapping[str, Any], *, key_order: list[str] | None = None) -> str:
    """Format a TOML inline table like `{ a = 1, b = "x" }`.

    Only supports primitive values emitted by Botpack.
    """

    keys = list(tbl.keys())
    if key_order is not None:
        keys = [k for k in key_order if k in tbl]
        # Append any unknown keys deterministically (defensive).
        keys.extend([k for k in sorted(tbl.keys()) if k not in keys])
    else:
        keys = sorted(tbl.keys())

    parts: list[str] = []
    for k in keys:
        if not isinstance(k, str):
            raise TypeError("toml_inline_table: keys must be strings")
        parts.append(f"{k} = {toml_value(tbl[k])}")
    inner = ", ".join(parts)
    return "{ " + inner + " }"
