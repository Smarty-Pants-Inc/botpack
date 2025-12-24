# Botpack testing status + next-level interactive TUI matrix plan

This file is meant to be handed to a fresh agent so they can pick up the work without re-discovering context.

## TL;DR

### What Botpack can do today

Botpack supports:

- Package model: `botpack.toml` + `botpack.lock` with content-addressed store
- Dependency resolution:
  - `name@semverSpec` deps via a static registry resolver (`versions.json`)
  - path deps
- Materialization:
  - `.botpack/pkgs/<pkg-key>/` virtual package roots (human-readable) using link-mode fallback
- Sync targets implemented today:
  - `botpack sync --target claude` (writes `.claude/...`)
  - `botpack sync --target droid` (writes `.factory/...`)
  - `botpack sync --target amp` (writes `.agents/...`)
- Home-config safe patching for MCP:
  - `botpack tui config apply codex|coder|amp` with drift detection + optional backup/force
- MCP protocol smoke test:
  - `botpack mcp smoke` (stdio JSON-RPC smoke against bundled server)
- TUI tmux wrapper + matrix artifacts (manual orchestration):
  - `botpack tui tmux ...`
  - `botpack tui matrix new|start|send|peek|kill|record`

### What `botpack tui matrix run` does today

`botpack tui matrix run` is an **automated fresh-install runner**:

- Builds a wheel (`uv build --wheel`)
- Creates isolated `uv venv` per TUI
- Installs botpack into each venv
- Writes a deterministic fixture project (workspace + package dep; all asset types; MCP servers + trust)
- Runs `botpack install`, `botpack sync`, `botpack mcp smoke`
- For `codex/coder/amp`, runs `botpack tui config apply ...` and does best-effort verification

It **does not** currently drive the interactive TUIs (Claude Code / Codex / etc.) to *execute* skills/commands inside the terminal UI.

## Where code lives

- Fresh-install matrix runner: `botpack/tui/matrix_run.py`
- Fixture project generator: `botpack/tui/matrix_fixture.py`
- Matrix results writer: `botpack/tui/matrix.py`
- Tmux wrapper: `botpack/tui/tmux.py`
- Home-config manager: `botpack/tui/home_config.py`
- Sync implementation: `botpack/sync.py`

## Current matrix artifacts (what you should expect to see)

Running:

```bash
cd projects/botpack
uv run python -m botpack.cli tui matrix run
```

Creates:

```
projects/botpack/dist/tests/matrix-YYYYMMDD-HHMMSS/
  results.json
  suite.json
  _wheel/...
  claude/
  opencode/
  codex/
  coder/
  droid/
  amp/
```

Inside each `<tui>/` directory, you now get **per-feature verdict files** that describe the “feature itself” and link to evidence:

- `skills.json` (checks expected SKILL.md files exist in the sync target)
- `commands.json` (checks expected command md files exist in the sync target)
- `agents.json` (checks expected agent md files exist in the sync target)
- `target-mcp.json` (parses target `mcp.json` and checks expected server names)
- `home-config.json` (only for `codex/coder/amp`, reflects `tui config apply` outcome)

These are still **filesystem integration tests**, not **interactive execution tests**.

## The gap (what we still need)

We want a matrix that answers questions like:

> “Did the *Claude Code TUI* actually load and follow a skill?”

That requires:

1. Launching each TUI in an isolated environment (HOME, config dirs, etc.)
2. Sending prompts/commands into the TUI (via tmux)
3. Capturing the transcript
4. Scoring PASS/FAIL based on a rubric + evidence

Right now, `botpack tui matrix run` stops at “Botpack produced the right files.”

## Next level: interactive rubric tests (the plan)

### Goal

Add an *interactive* matrix runner that:

- Still provisions fresh installs (wheel + venv + fixture project)
- **Starts TUIs** in tmux for each TUI
- **Drives the UI** (send prompt, wait, capture)
- **Records per-feature results per TUI** with transcript-backed evidence

This is the missing “where is the test result for the e2e skill test running inside Claude Code TUI?” layer.

### Proposed CLI shape

Option A (recommended): extend the existing command:

```bash
botpack tui matrix run --interactive
```

Option B: separate command:

```bash
botpack tui matrix interactive
```

In either case, support:

- `--tui <name>` repeatable
- `--env-file <path>` and/or `--env-cmd <bash-snippet>` for credentials
- timeouts (`--step-timeout-s`, `--startup-timeout-s`)
- `--keep-sessions-on-fail` for debugging

### Key prerequisite: sync targets for all TUIs

Today, Botpack only has true sync targets for `claude`, `droid`, `amp`.

For a real 6-TUI matrix, we likely need to add targets:

- `opencode`
- `codex`
- `coder`

so that Botpack materializes assets into the directories those TUIs actually read.

Right now, the runner maps `opencode/codex/coder -> target=claude` (because those targets don’t exist yet), which is fine for “Botpack plumbing”, but not sufficient for interactive UI-driven tests.

### Rubric: what to test interactively (minimum viable)

For each TUI, implement a small set of deterministic interactions:

1. **Command invocation**
   - Send the TUI’s command syntax for the synced fixture command.
   - PASS if output contains a known marker.

2. **Skill invocation**
   - Provide a fixture skill with an unambiguous instruction like:
     - “When the user says `fixture skill ping`, reply exactly `fixture-skill:PONG`.”
   - PASS if the response matches exactly.

3. **Agent/subagent invocation** (where supported)
   - Trigger Task/subagent behavior and detect completion.

4. **MCP tool invocation**
   - Ask the agent to call a tool provided by the bundled MCP server (magic number) and return the result.
   - PASS if transcript contains `424242` (or the magic-number tool output).

### Evidence capture strategy (match the old smarty-kit matrix approach)

For each TUI session, capture:

- `tmux.raw` (continuous pipe-pane capture)
- `tmux.peek.txt` snapshots at each step
- optional `logs` harvested via `botpack logs grep` (best-effort)

Then write per-feature JSON verdict files under:

```
dist/tests/matrix-*/<tui>/
  interactive.commands.json
  interactive.skills.json
  interactive.mcp.json
  interactive.agents.json
  tmux/...
```

And also add summarized entries to the top-level `results.json`.

### Implementation checklist for the next agent

1. **Add missing sync targets** (`opencode`, `codex`, `coder`) OR decide and document a compatible shared fallback.
2. **Extend fixture** so the “skill invocation” test is deterministic (today the fixture skill exists, but does not enforce a unique response).
3. **Implement an interactive runner** (new module suggested: `botpack/tui/matrix_interactive.py`):
   - Start tmux sessions using `botpack.tui.tmux.TmuxSession`
   - Send prompts via `TmuxSession.send()`
   - Poll `peek()` until expected markers appear or timeout
   - Save snapshots + transcripts as artifacts
4. **Per-TUI prompt recipes**
   - Define, per TUI, the exact syntax used to invoke commands and any TUI-specific quirks.
5. **Result recording**
   - Write `interactive.*.json` files with: test_method, expected, actual_result, verdict, artifacts
   - Add `MatrixRun.record(...)` entries for each interactive feature
6. **Add unit tests** for the parser/scoring layer (non-interactive) so CI remains stable.

### Acceptance criteria for “interactive matrix v1”

- One command runs the full suite:
  - provisions fresh botpack installs
  - launches TUIs
  - runs at least `interactive.skills` and `interactive.commands` for `claude` and `droid`
  - records transcript-backed PASS/FAIL
- A failure is diagnosable from artifacts alone (no “just trust me”).

## Notes / known quirks

- Amp MCP settings in this container did not appear to load via `--settings-file` for `amp mcp doctor` / `amp mcp add`; current verification is “config file written” + Botpack’s own MCP smoke test.
- `codex` and `coder` *do* support `mcp list` which we use as an extra validation step.
