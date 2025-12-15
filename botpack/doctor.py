from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .assets import scan_assets
from .config import botyard_manifest_path, parse_botyard_toml_file
from .errors import BotyardConfigError


@dataclass(frozen=True)
class DoctorResult:
    ok: bool
    warnings: tuple[str, ...] = ()


def run_doctor(*, manifest_path: Path | None = None) -> DoctorResult:
    if manifest_path is None:
        default = botyard_manifest_path()
        if not default.exists():
            return DoctorResult(ok=True, warnings=("No botpack.toml found (skipping workspace checks).",))

    try:
        cfg = parse_botyard_toml_file(manifest_path)
    except BotyardConfigError as e:
        return DoctorResult(ok=True, warnings=(str(e),))
    root = Path.cwd() if manifest_path is None else manifest_path.parent
    ws = Path(cfg.workspace.dir)
    if not ws.is_absolute():
        ws = (root / ws).resolve()

    idx = scan_assets(ws)
    needs_uv = any(s.pep723 is not None for sk in idx.skills for s in sk.scripts)

    warnings: list[str] = []
    if needs_uv and shutil.which("uv") is None:
        warnings.append("Detected PEP 723 script metadata but 'uv' is not installed.")

    return DoctorResult(ok=True, warnings=tuple(warnings))
