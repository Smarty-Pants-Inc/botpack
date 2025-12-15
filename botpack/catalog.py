from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .assets import AssetIndex
from .config import parse_botyard_toml_file
from .paths import botyard_dir


CATALOG_VERSION = 1


@dataclass(frozen=True)
class Catalog:
    version: int
    workspace: dict
    workspace_assets: dict
    packages: list[dict]
    generated_at: str | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "version": self.version,
            "workspace": self.workspace,
            "workspaceAssets": self.workspace_assets,
            "packages": self.packages,
        }
        if self.generated_at is not None:
            out["generatedAt"] = self.generated_at
        return out


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def catalog_path() -> Path:
    return botyard_dir() / "catalog.json"


def build_workspace_assets(index: AssetIndex) -> dict:
    return {
        "skills": [s.to_catalog_dict() for s in index.skills],
        "commands": [{"id": c.id, "path": c.path} for c in index.commands],
        "agents": [{"id": a.id, "path": a.path} for a in index.agents],
    }


def generate_catalog(
    *,
    workspace_dir: Path,
    index: AssetIndex,
    generated_at: str | None = "1970-01-01T00:00:00Z",
) -> Catalog:
    return Catalog(
        version=CATALOG_VERSION,
        generated_at=generated_at,
        workspace={"dir": str(workspace_dir)},
        workspace_assets=build_workspace_assets(index),
        packages=[],
    )


def write_catalog(path: Path, catalog: Catalog) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(_canonical_json(catalog.to_dict()), encoding="utf-8")
    tmp.replace(path)


def generate_and_write_catalog(
    *,
    manifest_path: Path | None = None,
    generated_at: str | None = "1970-01-01T00:00:00Z",
) -> Path:
    cfg = parse_botyard_toml_file(manifest_path)
    workspace_dir = Path(cfg.workspace.dir)
    # workspace.dir is stored as repo-relative string; make it relative to the manifest directory.
    if manifest_path is None:
        root = Path.cwd()
    else:
        root = manifest_path.parent
    if not workspace_dir.is_absolute():
        workspace_dir = (root / workspace_dir).resolve()

    from .assets import scan_assets

    idx = scan_assets(workspace_dir)
    c = generate_catalog(workspace_dir=workspace_dir, index=idx, generated_at=generated_at)
    out_path = catalog_path()
    write_catalog(out_path, c)
    return out_path
