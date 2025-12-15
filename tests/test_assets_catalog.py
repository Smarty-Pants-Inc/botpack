from __future__ import annotations

import json
from pathlib import Path

from botpack.assets import scan_assets
from botpack.catalog import generate_and_write_catalog


def test_scan_assets_and_catalog_includes_pep723(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    # Minimal manifest
    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"
""",
        encoding="utf-8",
    )

    # Workspace skill with a PEP723 script
    skill_dir = tmp_path / ".botpack" / "workspace" / "skills" / "fetch_web"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: fetch_web
name: Fetch Web
description: Retrieves and summarizes web pages.
---

Body ignored.
""",
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    script_path = scripts_dir / "fetch_web.py"
    script_path.write_text(
        """# /// script
# requires-python = ">=3.11"
# dependencies = ["requests==2.32.5", "markdown==3.10"]
# ///

print('ok')
""",
        encoding="utf-8",
    )

    idx = scan_assets(tmp_path / ".botpack" / "workspace")
    assert len(idx.skills) == 1
    assert idx.skills[0].id == "fetch_web"
    assert idx.skills[0].scripts
    assert idx.skills[0].scripts[0].pep723 is not None

    out = generate_and_write_catalog(manifest_path=tmp_path / "botpack.toml")
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["version"] == 1
    assert payload["workspace"]["dir"].endswith("/.botpack/workspace")
    ws_skills = payload["workspaceAssets"]["skills"]
    assert ws_skills[0]["id"] == "fetch_web"
    assert ws_skills[0]["scripts"][0]["runner"] == "uv"
    assert ws_skills[0]["scripts"][0]["pep723"]["requiresPython"] == ">=3.11"


def test_catalog_json_output_is_stable_exact_fixture(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"
""",
        encoding="utf-8",
    )

    ws = (tmp_path / ".botpack" / "workspace").resolve()

    skill_dir = ws / "skills" / "hello"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
id: hello
name: Hello
description: Says hello.
---
""",
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    script_path = scripts_dir / "hello.py"
    script_path.write_text(
        """# /// script
# requires-python = ">=3.11"
# dependencies = ["requests==2.32.5", "markdown==3.10"]
# ///
""",
        encoding="utf-8",
    )

    commands_dir = ws / "commands"
    commands_dir.mkdir(parents=True)
    cmd_path = commands_dir / "hi.md"
    cmd_path.write_text("hi", encoding="utf-8")

    agents_dir = ws / "agents"
    agents_dir.mkdir(parents=True)
    agent_path = agents_dir / "dev.md"
    agent_path.write_text("dev", encoding="utf-8")

    out = generate_and_write_catalog(manifest_path=tmp_path / "botpack.toml")
    assert out == tmp_path / ".botpack" / "catalog.json"

    expected = (
        "{\n"
        '  "generatedAt": "1970-01-01T00:00:00Z",\n'
        '  "packages": [],\n'
        '  "version": 1,\n'
        '  "workspace": {\n'
        f'    "dir": "{ws}"\n'
        "  },\n"
        '  "workspaceAssets": {\n'
        '    "agents": [\n'
        "      {\n"
        '        "id": "dev",\n'
        f'        "path": "{agent_path}"\n'
        "      }\n"
        "    ],\n"
        '    "commands": [\n'
        "      {\n"
        '        "id": "hi",\n'
        f'        "path": "{cmd_path}"\n'
        "      }\n"
        "    ],\n"
        '    "skills": [\n'
        "      {\n"
        '        "description": "Says hello.",\n'
        '        "id": "hello",\n'
        f'        "path": "{skill_md}",\n'
        '        "scripts": [\n'
        "          {\n"
        f'            "path": "{script_path}",\n'
        '            "pep723": {\n'
        '              "dependencies": [\n'
        '                "requests==2.32.5",\n'
        '                "markdown==3.10"\n'
        "              ],\n"
        '              "requiresPython": ">=3.11"\n'
        "            },\n"
        '            "runner": "uv",\n'
        '            "runtime": "python"\n'
        "          }\n"
        "        ],\n"
        '        "title": "Hello"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    )

    assert out.read_text(encoding="utf-8") == expected
