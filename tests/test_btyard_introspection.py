from __future__ import annotations

from pathlib import Path

from botpack.cli import main
from botpack.lock import Lockfile, Package, save_lock


def test_info_tree_why_outputs_are_deterministic(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("BOTPACK_ROOT", str(tmp_path))

    (tmp_path / "botpack.toml").write_text(
        """version = 1

[workspace]
dir = ".botpack/workspace"

[dependencies]
"@acme/quality" = { path = "dep" }
""",
        encoding="utf-8",
    )

    lock = Lockfile(
        lockfileVersion=1,
        botpackVersion="0.1.0",
        specVersion="0.1",
        dependencies={"@acme/quality": "*"},
        packages={
            "@acme/quality@1.0.0": Package(
                source={"type": "path", "path": "dep"},
                resolved={},
                integrity="sha256:aaaa",
                dependencies={},
                capabilities={},
            )
        },
    )
    save_lock(tmp_path / "botpack.lock", lock)

    assert main(["info", "--manifest", str(tmp_path / "botpack.toml"), "--lockfile", str(tmp_path / "botpack.lock")]) == 0
    out = capsys.readouterr().out
    assert "Botpack\n" in out
    assert "dependencies: 1\n" in out
    assert "installedPackages: 1\n" in out

    assert main(["tree", "--manifest", str(tmp_path / "botpack.toml"), "--lockfile", str(tmp_path / "botpack.lock")]) == 0
    out2 = capsys.readouterr().out
    expected_tree = (
        "Dependencies\n"
        "  - @acme/quality\n"
        "\n"
        "Installed\n"
        "  - @acme/quality@1.0.0\n"
    )
    assert out2 == expected_tree

    assert main(["why", "@acme/quality", "--manifest", str(tmp_path / "botpack.toml"), "--lockfile", str(tmp_path / "botpack.lock")]) == 0
    out3 = capsys.readouterr().out
    expected_why = (
        "Why: @acme/quality\n"
        "  - direct dependency in botpack.toml\n"
        "  - installed as @acme/quality@1.0.0\n"
    )
    assert out3 == expected_why
