# Botpack

Botpack is a lightweight package manager for **agent assets** (skills, commands, agents, and MCP server configs) with deterministic installs, a JSON lockfile (`botpack.lock`), and a content-addressed global store.

## Install (uv)

Botpack is currently published from GitHub (PyPI release pending). With `uv`:

```bash
uv tool install "git+https://github.com/Smarty-Pants-Inc/botpack"
botpack --help
```

## Use

Botpack reads a workspace manifest (`botpack.toml`) and writes a lockfile (`botpack.lock`).

```bash
botpack install
botpack sync --target claude
```

Key locations:

- Repo-local state: `.botpack/`
- Global store: `~/.botpack/store/v1/` (override with `BOTPACK_STORE`)

## Development

```bash
uv sync --group dev
uv run pytest
```

## License

MIT
