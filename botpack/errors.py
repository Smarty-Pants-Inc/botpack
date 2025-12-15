from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class BotyardConfigError(Exception):
    """Base exception for Botyard config parsing/validation errors."""


@dataclass(frozen=True)
class ConfigParseError(BotyardConfigError):
    """Raised when a TOML file cannot be parsed."""

    path: Path
    message: str
    lineno: int | None = None
    colno: int | None = None

    def __str__(self) -> str:
        loc = ""
        if self.lineno is not None and self.colno is not None:
            loc = f" (line {self.lineno}, column {self.colno})"
        return f"Invalid TOML in {self.path}: {self.message}{loc}"


@dataclass(frozen=True)
class ConfigValidationError(BotyardConfigError):
    """Raised when a parsed TOML file does not match the expected schema."""

    path: Path
    message: str

    def __str__(self) -> str:
        return f"Invalid config in {self.path}: {self.message}"
