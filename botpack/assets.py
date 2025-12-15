from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .pep723 import Pep723ScriptMetadata, parse_pep723_script


@dataclass(frozen=True)
class ScriptAsset:
    path: str
    runtime: str
    runner: str | None = None
    pep723: Pep723ScriptMetadata | None = None

    def to_catalog_dict(self) -> dict:
        out: dict = {
            "path": self.path,
            "runtime": self.runtime,
        }
        if self.runner:
            out["runner"] = self.runner
        if self.pep723:
            out["pep723"] = {
                "requiresPython": self.pep723.requires_python,
                "dependencies": list(self.pep723.dependencies),
            }
        return out


@dataclass(frozen=True)
class SkillAsset:
    id: str
    title: str
    description: str
    path: str
    scripts: tuple[ScriptAsset, ...] = ()

    def to_catalog_dict(self) -> dict:
        out: dict = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "path": self.path,
        }
        if self.scripts:
            out["scripts"] = [s.to_catalog_dict() for s in self.scripts]
        return out


@dataclass(frozen=True)
class CommandAsset:
    id: str
    path: str


@dataclass(frozen=True)
class AgentAsset:
    id: str
    path: str


@dataclass(frozen=True)
class AssetIndex:
    skills: tuple[SkillAsset, ...] = ()
    commands: tuple[CommandAsset, ...] = ()
    agents: tuple[AgentAsset, ...] = ()


def _read_yaml_frontmatter(text: str) -> dict:
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = parts[1]
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(fm) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        out: dict = {}
        for line in fm.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
        return out


def _read_pep723_header(script_path: Path, *, max_lines: int = 200) -> Pep723ScriptMetadata | None:
    try:
        with script_path.open("r", encoding="utf-8") as f:
            lines: list[str] = []
            for _ in range(max_lines):
                line = f.readline()
                if not line:
                    break
                lines.append(line)
                if line.lstrip().rstrip() == "# ///":
                    break
        return parse_pep723_script("".join(lines))
    except Exception:
        return None


def scan_assets(root: Path) -> AssetIndex:
    skills: list[SkillAsset] = []
    commands: list[CommandAsset] = []
    agents: list[AgentAsset] = []

    skills_dir = root / "skills"
    if skills_dir.exists():
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            skill_md = d / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
            except Exception:
                continue
            fm = _read_yaml_frontmatter(text)
            sid = str((fm.get("id") or d.name)).strip()
            title = str((fm.get("name") or sid)).strip()
            desc = str((fm.get("description") or "")).strip()

            scripts: list[ScriptAsset] = []
            scripts_dir = d / "scripts"
            if scripts_dir.exists() and scripts_dir.is_dir():
                for sp in sorted(scripts_dir.rglob("*.py")):
                    meta = _read_pep723_header(sp)
                    scripts.append(
                        ScriptAsset(
                            path=str(sp),
                            runtime="python",
                            runner="uv" if meta else None,
                            pep723=meta,
                        )
                    )

            skills.append(
                SkillAsset(
                    id=sid,
                    title=title,
                    description=desc,
                    path=str(skill_md),
                    scripts=tuple(scripts),
                )
            )

    commands_dir = root / "commands"
    if commands_dir.exists():
        for p in sorted(commands_dir.glob("*.md")):
            if p.name.startswith("."):
                continue
            commands.append(CommandAsset(id=p.stem, path=str(p)))

    agents_dir = root / "agents"
    if agents_dir.exists():
        for p in sorted(agents_dir.glob("*.md")):
            if p.name.startswith("."):
                continue
            agents.append(AgentAsset(id=p.stem, path=str(p)))

    return AssetIndex(skills=tuple(skills), commands=tuple(commands), agents=tuple(agents))
