from __future__ import annotations

from pathlib import Path

from botpack.cli import main


def test_botyard_toml_rewrite_is_deterministic_via_add_remove(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    manifest = tmp_path / "botpack.toml"
    manifest.write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"

[dependencies]
b = { path = "b" }
"@acme/quality-skills" = { git = "https://example.com/quality-skills.git", rev = "v2" }
a = { path = "a" }
""",
        encoding="utf-8",
    )

    assert main(["add", "c", "--path", "c"]) == 0
    expected_after_add = (
        "version = 1\n"
        "\n"
        "[workspace]\n"
        "dir = \".botpack/workspace\"\n"
        "\n"
        "[dependencies]\n"
        '"@acme/quality-skills" = { git = "https://example.com/quality-skills.git", rev = "v2" }\n'
        '"a" = { path = "a" }\n'
        '"b" = { path = "b" }\n'
        '"c" = { path = "c" }\n'
    )
    assert manifest.read_text(encoding="utf-8") == expected_after_add

    assert main(["remove", "a"]) == 0
    expected_after_remove = (
        "version = 1\n"
        "\n"
        "[workspace]\n"
        "dir = \".botpack/workspace\"\n"
        "\n"
        "[dependencies]\n"
        '"@acme/quality-skills" = { git = "https://example.com/quality-skills.git", rev = "v2" }\n'
        '"b" = { path = "b" }\n'
        '"c" = { path = "c" }\n'
    )
    assert manifest.read_text(encoding="utf-8") == expected_after_remove
