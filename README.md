# Botpack

Botpack is a lightweight package manager for **agent assets** (skills, commands, agents, and MCP server configs) with deterministic installs, a JSON lockfile (`botpack.lock`), and a content-addressed global store.

Botpack intentionally separates:

* **Installed**: present in the global store + referenced by a lockfile
* **Materialized**: projected into a runtime directory (Claude/Amp/Droid) via `botpack sync`

## Install (uv)

Botpack is currently published from GitHub (PyPI release pending). With `uv`:

```bash
uv tool install "git+https://github.com/Smarty-Pants-Inc/botpack"
botpack --help
```

## Use

Botpack reads a workspace manifest (`botpack.toml`) and writes a lockfile (`botpack.lock`).

```bash
# Project environment (repo-local):
botpack get @acme/quality-skills@^1 --target claude

# Global environment (user-level profile):
botpack get --global @acme/quality-skills@^1 --target claude

# Or as two steps:
botpack install
botpack sync --target claude
```

Key locations:

- Environment root state: `<root>/.botpack/`
- Project root: `./botpack.toml` (auto-discovered by searching parents)
- Global profile root: `~/.botpack/profiles/<profile>/botpack.toml` (via `--global` / `--profile`)
- Global store (shared across roots): `~/.botpack/store/v1/` (override with `BOTPACK_STORE`)

Root selection precedence:

1. `--root <path>`
2. `--global [--profile <name>]`
3. `BOTPACK_ROOT`
4. auto-discover `botpack.toml` in parents

## Development

```bash
uv sync --group dev
uv run pytest
```

## License

MIT
