"""PEP 723 script metadata parsing.

PEP 723 defines an inline, comment-delimited metadata block for single-file scripts.
This module provides *pure parsing* utilities for detecting and extracting metadata
from a Python source file without executing anything.

Supported fields (top-level keys in the script block):
  - requires-python: string
  - dependencies: array of strings
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Optional


@dataclass(frozen=True)
class Pep723ScriptMetadata:
    """Parsed metadata from a PEP 723 `# /// script` block."""

    requires_python: str | None
    dependencies: tuple[str, ...]
    raw_toml: str


_START_MARKER = "# /// script"
_END_MARKER = "# ///"


def extract_pep723_script_toml(source: str) -> str | None:
    """Extract the TOML payload of the first PEP 723 `script` block.

    Args:
        source: Full Python source text.

    Returns:
        The raw TOML payload (with leading `#` comment markers removed) or None
        if no `# /// script` block exists.

    Raises:
        ValueError: If a start marker is found but the end marker is missing.
    """

    lines = source.splitlines()
    start_idx: int | None = None

    for i, line in enumerate(lines):
        if line.lstrip().rstrip() == _START_MARKER:
            start_idx = i
            break

    if start_idx is None:
        return None

    payload_lines: list[str] = []
    for j in range(start_idx + 1, len(lines)):
        marker = lines[j].lstrip().rstrip()
        if marker == _END_MARKER:
            return "\n".join(payload_lines)

        raw = lines[j].lstrip()
        if not raw.startswith("#"):
            raise ValueError("PEP 723 block lines must be comments starting with '#'")

        # Remove the leading '#', then remove a single leading space if present.
        content = raw[1:]
        if content.startswith(" "):
            content = content[1:]
        payload_lines.append(content)

    raise ValueError("PEP 723 block start found but end marker '# ///' missing")


_REQUIRES_PY_LINE = re.compile(r"(?m)^\s*requires-python\s*=\s*(?P<val>.+?)\s*(?:#.*)?$")
_DEPS_LINE = re.compile(r"(?m)^\s*dependencies\s*=\s*(?P<val>.+)$")


def parse_pep723_script(source: str) -> Pep723ScriptMetadata | None:
    """Parse the first PEP 723 `script` block.

    Args:
        source: Full Python source text.

    Returns:
        Pep723ScriptMetadata if a script block exists, otherwise None.

    Raises:
        ValueError: For malformed blocks or unsupported value types.
    """

    toml = extract_pep723_script_toml(source)
    if toml is None:
        return None

    requires_python: str | None = None
    m = _REQUIRES_PY_LINE.search(toml)
    if m:
        requires_python = _parse_toml_string(m.group("val"))

    dependencies: tuple[str, ...] = ()
    deps = _parse_dependencies(toml)
    if deps is not None:
        dependencies = tuple(deps)

    return Pep723ScriptMetadata(
        requires_python=requires_python,
        dependencies=dependencies,
        raw_toml=toml,
    )


def _parse_dependencies(toml: str) -> Optional[list[str]]:
    m = _DEPS_LINE.search(toml)
    if not m:
        return None

    # Find the start of the RHS in the *full* TOML string.
    rhs_start = m.start("val")
    idx = _skip_ws_and_toml_comments(toml, rhs_start)
    if idx >= len(toml) or toml[idx] != "[":
        raise ValueError("dependencies must be a TOML array")

    array_text = _extract_bracketed(toml, idx)
    return _parse_toml_string_array(array_text)


def _skip_ws_and_toml_comments(text: str, idx: int) -> int:
    i = idx
    while i < len(text):
        # Skip whitespace
        while i < len(text) and text[i].isspace():
            i += 1
        if i < len(text) and text[i] == "#":
            # Skip to end of line
            while i < len(text) and text[i] not in ("\n", "\r"):
                i += 1
            continue
        break
    return i


def _extract_bracketed(text: str, start_idx: int) -> str:
    if start_idx >= len(text) or text[start_idx] != "[":
        raise ValueError("expected '['")

    depth = 0
    in_str: str | None = None
    escaped = False
    for j in range(start_idx, len(text)):
        ch = text[j]

        if in_str is not None:
            if in_str == '"':
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    continue
            if ch == in_str:
                in_str = None
            continue

        if ch in ("'", '"'):
            in_str = ch
            continue

        if ch == "[":
            depth += 1
            continue
        if ch == "]":
            depth -= 1
            if depth == 0:
                return text[start_idx : j + 1]
            continue

    raise ValueError("unterminated TOML array (missing ']')")


def _parse_toml_string(val: str) -> str:
    s = val.strip()
    if not s:
        raise ValueError("expected TOML string")

    if (s[0] == '"' and s.endswith('"')) or (s[0] == "'" and s.endswith("'")):
        quote = s[0]
        inner = s[1:-1]
        if quote == "'":
            # TOML literal strings: no escapes.
            return inner
        return _decode_basic_string(inner)

    raise ValueError("expected TOML string value")


def _decode_basic_string(inner: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        i += 1
        if i >= len(inner):
            raise ValueError("invalid escape at end of string")
        esc = inner[i]
        i += 1

        if esc == "n":
            out.append("\n")
        elif esc == "t":
            out.append("\t")
        elif esc == "r":
            out.append("\r")
        elif esc == '"':
            out.append('"')
        elif esc == "\\":
            out.append("\\")
        elif esc == "b":
            out.append("\b")
        elif esc == "f":
            out.append("\f")
        else:
            # Keep behavior strict: avoid silently accepting unknown escape sequences.
            raise ValueError(f"unsupported escape: \\{esc}")

    return "".join(out)


def _parse_toml_string_array(array_text: str) -> list[str]:
    s = array_text.strip()
    if not (s.startswith("[") and s.endswith("]")):
        raise ValueError("expected TOML array")

    body = s[1:-1]
    items: list[str] = []
    i = 0

    while i < len(body):
        ch = body[i]

        # Whitespace and separators
        if ch.isspace() or ch == ",":
            i += 1
            continue

        # TOML comment inside array
        if ch == "#":
            while i < len(body) and body[i] not in ("\n", "\r"):
                i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            i += 1
            start = i
            if quote == "'":
                # Literal string: find next single quote.
                end = body.find("'", start)
                if end == -1:
                    raise ValueError("unterminated single-quoted string in dependencies")
                items.append(body[start:end])
                i = end + 1
                continue

            # Basic string with escapes: parse char-by-char.
            buf: list[str] = []
            escaped = False
            while i < len(body):
                c = body[i]
                i += 1
                if escaped:
                    # Decode a subset of TOML escapes (same as _decode_basic_string).
                    if c == "n":
                        buf.append("\n")
                    elif c == "t":
                        buf.append("\t")
                    elif c == "r":
                        buf.append("\r")
                    elif c == '"':
                        buf.append('"')
                    elif c == "\\":
                        buf.append("\\")
                    elif c == "b":
                        buf.append("\b")
                    elif c == "f":
                        buf.append("\f")
                    else:
                        raise ValueError(f"unsupported escape in dependencies: \\{c}")
                    escaped = False
                    continue

                if c == "\\":
                    escaped = True
                    continue
                if c == '"':
                    items.append("".join(buf))
                    break
                buf.append(c)
            else:
                raise ValueError("unterminated double-quoted string in dependencies")

            continue

        raise ValueError("dependencies array must contain only strings")

    return items
