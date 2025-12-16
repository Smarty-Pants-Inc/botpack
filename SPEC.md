# Botpack Architecture Spec v0.2

**Subtitle:** “Cargo for agent assets” (dependency + materialization toolchain)
**Status:** Draft for implementation
**Audience:** Coding agent orchestrator + parallel dev agents implementing Botpack

---

## 0. Executive summary

Botpack is a repo-local toolchain that:

1. **Manages agent assets as versioned dependencies** (skills, commands, agents, MCP configs, policy fragments).
2. **Materializes those assets into multiple runtimes** (Claude/Amp/Droid/others) via a deterministic `sync` engine.
3. **Preserves progressive disclosure** by generating a metadata-only catalog and never bundling skill bodies into startup context by default.

This spec assumes Botpack replaces/absorbs the existing legacy CLI responsibilities.

Default first‑party workspace directory is **`.botpack/workspace/`**.
Botpack can also detect and migrate a legacy **`.smarty/`** workspace.

---

## 1) Goals, non-goals, design constraints

### 1.1 Goals (must-haves)

* **Deterministic installs**: same manifest + lockfile → identical installed graph and identical on-disk outputs.
* **Fast and opinionated UX**: `botpack add`, `botpack install`, `botpack sync` should be “do the obvious thing” with minimal configuration.
* **Repo-local, inspectable state**: manifests and generated artifacts are human-readable; no opaque hidden magic.
* **Multi-runtime output**: one dependency graph → materialized layouts for multiple TUIs/runtimes.
* **Progressive disclosure**: no startup-context bloating; skills/commands/agents remain discrete files, loaded when invoked.
* **Safe-by-default**: no arbitrary code execution on install; risk-bearing capabilities require explicit trust.

### 1.2 Non-goals (v0.2)

* A hosted registry/search UI is optional; do not block v0.2 on it (Phase 1+2 can be static files + git).
* No install scripts (`preinstall/postinstall`) in v0.2 (explicitly disallowed).
* No complex prompt/template composition pipelines (e.g., auto-generating CLAUDE.md/AGENTS.md) by default.
* No sandbox runtime execution environment (Botpack is not a runner); can be future work.

### 1.3 Constraints (inherited from existing repo context)

* Support legacy `.smarty/` workspaces via migration, but do not make `.smarty/` the default.
* Continue `.claude/skills/` as the **shared fallback** skills directory for Claude Code, Amp, and Factory Droid (current practical decision).
* Prefer **native skills** where available; fall back to catalog/list/read only when needed.

---

## 2) Terminology and core mental model

### 2.1 Glossary

* **Workspace**: the repo-local canonical source of first-party assets (default `.botpack/workspace/`).
* **Package**: a versioned bundle of agent assets with a manifest (`agentpkg.toml`).
* **Project manifest**: repo config declaring dependencies and targets (`botpack.toml`).
* **Lockfile**: fully resolved dependency graph with integrity hashes (`botpack.lock`).
* **Store**: global content-addressed cache of fetched packages.
* **Virtual store**: project-local stable pointers to store entries (`.botpack/pkgs/...`).
* **Target**: a runtime output profile (“claude”, “amp”, “droid”) describing how to materialize assets.
* **Materialization**: generating runtime-facing directories and aggregated files (symlinks/copies + generated MCP files).
* **Catalog**: metadata-only index of all available assets in workspace + dependencies (`.botpack/catalog.json`).
* **Capabilities**: declared risk-bearing behaviors (e.g., `exec`, MCP servers). Must be explicitly trusted before activation.
* **Environment**: a Botpack root that owns a manifest+lock+state (project env or global profile env).
* **Root**: the directory Botpack operates within (the parent of `botpack.toml` and `.botpack/`).
* **Profile**: a named global environment under `~/.botpack/profiles/<profile>/`.

### 2.2 Prime directive

> **Install resolves and fetches. Sync materializes.**
> `add/remove/update/install` may auto-sync, but the conceptual split remains.

### 2.3 Installed vs materialized (store vs targets)

Botpack intentionally separates:

* **Installed**: content is fetched/resolved and present in the global content-addressed **store** (e.g. `~/.botpack/store/v1/sha256:...`) and referenced by an environment's `botpack.lock`.
* **Materialized (enabled)**: assets are projected into a runtime-facing **target** (e.g. `.claude/skills/`, `.agents/commands/`, `.factory/...`) via `botpack sync`.

Targets are derived outputs and can always be regenerated from `botpack.lock` + store.

### 2.4 Project vs global environments

Botpack supports multiple environments that share the same global store:

* **Project environment**: a repo-local root (typically the git repo) containing `botpack.toml`/`botpack.lock` and `.botpack/` state.
* **Global environment**: a user-level root under `~/.botpack/profiles/<profile>/` containing its own `botpack.toml`/`botpack.lock` and `.botpack/` state.

Global environments are intended for “install once, enable everywhere” workflows; project environments are intended for repo-specific reproducibility.

---

## 3) Repository layout and state

### 3.1 Required files at repo root

* `botpack.toml` — project manifest (human-editable)
* `botpack.lock` — lockfile (machine-generated, human-inspectable)

### 3.2 Botpack repo directory

Botpack uses a single repo-local directory:

```
.botpack/
  workspace/                # first-party assets (intended to be version controlled)
    skills/<id>/SKILL.md
    agents/*.md
    commands/*.md
    hooks/policy.yaml

  pkgs/                     # project virtual store (symlinks/junctions -> global store)
  generated/
    <target>/
      mcp.json              # generated aggregate per target (example)
      policy.generated.yaml # only if configured; off by default
  state/
    sync-<target>.json      # tracks what Botpack materialized (for clean/idempotence)
  catalog.json              # metadata-only catalog of all assets
  trust.toml                # explicit trust decisions (capabilities approvals)
  targets/
    *.toml                  # optional custom targets (future/mid-term)
```

### 3.3 Workspace (first-party assets)

Botpack supports a configurable workspace directory. Default behavior:

* If `.botpack/workspace/` exists: use it.
* Else, if `.smarty/` exists: treat it as a legacy workspace and prompt to migrate.
* Else: `botpack init` creates `.botpack/workspace/`.

Workspace layout:

```
.botpack/workspace/
  skills/<id>/SKILL.md
  agents/*.md
  commands/*.md
  hooks/policy.yaml
```

---

## 4) Asset types and conventions

Botpack recognizes assets botpack conventional paths in either:

* the repo workspace (`.botpack/workspace/...`), or
* installed packages (inside `.botpack/pkgs/<pkg>/...`).

### 4.1 Asset types (v0.1)

* **Skill**: `skills/<id>/SKILL.md` (+ optional `assets/`, `scripts/`)
* **Command**: `commands/<id>.md` (slash command)
* **Agent**: `agents/<id>.md`
* **MCP config**: `mcp/servers.toml` (canonical input); output target-specific
* **Policy fragments**: `policy/*.yaml|yml|toml|json` (fragments only by default)
* **Templates**: `templates/*` (packaged but not activated by default)

#### 4.1.1 Python skill scripts (UV + PEP 723)

For portable Python scripts inside a skill’s `scripts/` directory, Botpack should support the **UV** workflow:

* If a `scripts/*.py` file begins with a **PEP 723** inline metadata block (`# /// script` … `# ///`), Botpack extracts:

  * `requires-python`
  * `dependencies`

* Botpack records this metadata in the catalog (see §11) and recommends `uv run <script.py>` as the canonical invocation.
* Botpack does **not** execute scripts during install/sync; this is cataloging + diagnostics only in v0.1.

### 4.2 Canonical IDs and references

* **Package name**: `@scope/name` or `name` (unscoped allowed but discouraged).
* **Asset ID**: local to its package/workspace.
* **Fully qualified asset reference syntax (AssetRef)**:

  * `@scope/name:<assetId>` (type inferred botpack alias table or uniqueness)
  * or explicit: `@scope/name:skill/<id>`, `@scope/name:command/<id>`, `@scope/name:agent/<id>`

Botpack uses **package-qualified output names** by default to avoid collisions.

---

## 5) Project manifest: `botpack.toml`

### 5.1 Minimal schema (v0.1)

```toml
version = 1

[workspace]
dir = ".botpack/workspace"
name = "@yourorg/yourrepo-assets" # optional
private = true

[dependencies]
"@acme/quality-skills" = "^2.1.0"
"@acme/review-commands" = "^1.4.0"

[sync]
onAdd = true
onInstall = true
catalog = true
linkMode = "auto"    # auto|symlink|hardlink|copy

[targets.claude]
root = ".claude"
skillsDir = "skills"
commandsDir = "commands"
agentsDir = "agents"
mcpOut = "mcp.json"
policyMode = "fragments" # fragments|generate|off

[targets.amp]
root = ".agents"
commandsDir = "commands"
skillsFallbackRoot = ".claude"
skillsFallbackDir = "skills"

[targets.droid]
root = ".factory"
# v0.1: may only support skills via fallback to .claude/skills unless configured otherwise

[aliases.skills]
fetch = "@acme/quality-skills:fetch_web"

[aliases.commands]
pr = "@acme/review-commands:pr-review"
```

### 5.2 Dependency spec formats (v0.1)

Allow these forms in `dependencies`:

* Semver: `"@scope/name" = "^1.2.3"`
* Git:

```toml
"@scope/name" = { git = "https://github.com/org/repo.git", rev = "3f2c1b9" }
```

* Local path:

```toml
"@scope/name" = { path = "../relative/path" }
```

* Tarball (optional v0.1; implement if easy):

```toml
"@scope/name" = { url = "https://example.com/pkg.tgz", integrity = "sha256-..." }
```

### 5.3 Config precedence (required)

Highest wins:

1. CLI flags
2. Environment variables (e.g. `BOTPACK_ROOT`, `BOTPACK_STORE`, `BOTPACK_REGISTRY_URL`)
3. Environment `botpack.toml`
4. Defaults

Root selection (which environment you are operating on) MUST be deterministic:

1. `--root <path>`
2. `--global [--profile <name>]` (maps to `~/.botpack/profiles/<profile>/`)
3. `BOTPACK_ROOT`
4. Auto-discover project root by searching up from `cwd` for `botpack.toml`
5. Fallback: `cwd`

### 5.4 Registry model (phased)

Botpack's registry should be **lightweight**, **cache-friendly**, and **immutable by default**.

#### Phase 1: git-only (no registry)

Packages are referenced directly by git URL (optionally a tag/commit via `rev`). This requires no central infrastructure.

#### Phase 2: static index ("registry")

A registry is a static HTTP site (e.g. GitHub Pages, R2/S3, or GitHub raw files) that serves package metadata.

* Base URL configured via `BOTPACK_REGISTRY_URL`.
* For a package `@scope/name`, Botpack fetches:

  * `${BOTPACK_REGISTRY_URL}/@scope/name/versions.json`

`versions.json` schema (v0):

```json
{
  "schema": 1,
  "name": "@scope/name",
  "versions": {
    "1.2.3": {
      "source": { "type": "git", "url": "https://github.com/org/repo.git", "rev": "v1.2.3" },
      "integrity": "sha256:..." 
    }
  }
}
```

Notes:

* `integrity` is optional at first, but recommended; clients can compute/verify it after fetch.
* The registry MUST NOT mutate entries for an existing version.

#### Phase 3: signing

Registry metadata and/or artifacts are signed (Sigstore or minisign). Botpack verifies signatures before trusting registry responses.

### 5.5 Publishing UX (fewest steps)

The author path should be:

1. `botpack pkg init` → scaffolds `agentpkg.toml` + conventional folders.
2. Author adds assets.
3. `botpack publish` → validates, computes integrity, creates a release artifact (tarball), and updates the registry index.

Implementation can start by supporting a "print registry entry" dry-run to make manual publishing easy, then add first-class GitHub release + registry PR automation.

---

## 6) Package format: `agentpkg.toml` + conventional directories

### 6.1 Package root layout

```
<package>/
  agentpkg.toml
  skills/
  commands/
  agents/
  mcp/
  policy/
  templates/
  README.md
  LICENSE
```

### 6.2 `agentpkg.toml` schema (v0.1)

```toml
agentpkg = "0.1"
name = "@acme/quality-skills"
version = "2.1.0"
description = "High-signal repo skills with minimal token footprint."
license = "MIT"
repository = "https://github.com/acme/quality-skills"

[compat]
requires = ["skills.v1", "commands.v1"] # feature-based, not runtime-specific

[exports]
# Optional. If omitted: everything in skills/commands/agents is exported.
# skills = ["fetch_web", "summarize_repo"]
# commands = ["pr-review"]
# agents = ["researcher"]

[capabilities]
exec = false
network = false
mcp = false
```

### 6.3 Progressive disclosure rules (package-level)

* Packages MUST NOT require injecting skill bodies into a unified startup context.
* Any “guidance docs” (AGENTS.md/CLAUDE.md style) can exist in `templates/` but are **not auto-applied** in v0.1.

---

## 7) Lockfile: `botpack.lock`

### 7.1 Lockfile requirements

* Fully resolved versions for all transitive dependencies.
* Immutable source resolution:

  * registry artifact digest **or**
  * git commit SHA **or**
  * tarball integrity hash
* Per-package integrity hash (BLAKE3 recommended; SHA-256 acceptable).
* The integrity hash is the **content-address key** for the global store.

  * For git dependencies, the lockfile MUST record both the resolved commit SHA and the computed content hash of the normalized checkout.
  * For local path dependencies, the lockfile MUST record the computed content hash of the normalized directory snapshot.
* Lockfile contents must be deterministic:

  * no timestamps
  * stable ordering of keys and collections
* Dependency graph edges.
* Tool version + spec version.

### 7.2 JSON schema sketch (v0.1)

`botpack.lock` is JSON with stable key ordering.

```json
{
  "lockfileVersion": 1,
  "botpackVersion": "0.2.0",
  "specVersion": "0.1",
  "dependencies": {
    "@acme/quality-skills": "^2.1.0"
  },
  "packages": {
    "@acme/quality-skills@2.1.0": {
      "source": { "type": "git", "url": "https://github.com/acme/quality-skills.git" },
      "resolved": { "commit": "<sha>", "ref": "<optional-original-ref>" },
      "integrity": "blake3:<content-hash>",
      "dependencies": {
        "@acme/base": "1.2.0"
      },
      "capabilities": { "exec": false, "network": false, "mcp": false }
    }
  }
}
```

### 7.3 Resolution invariants (v0.1)

* Botpack MAY install multiple versions of the same package (npm-style) but must keep outputs collision-free via package-qualified names.
* Resolution must be stable given the same inputs:

  * same manifest + same available versions/sources → identical resolved graph
  * stable tie-breaking rules (see §9)

### 7.4 Lockfile modes

* `botpack install` respects lockfile by default.
* `--frozen-lockfile` errors if lockfile would change (CI default).

---

## 8) Global store + project virtual store

### 8.1 Store goals

* Deduplicate identical package contents across projects.
* Enable extremely fast installs via linking.
* Support offline operation if artifacts are already present.
* Store entries are immutable once written (content-addressed; never mutate in place).

### 8.2 Store location

* macOS/Linux: `~/.botpack/store/v1/`
* Windows: `%LOCALAPPDATA%\botpack\store\v1\`

### 8.3 Content addressing

* Compute package content hash over a normalized archive representation:

  * canonical file ordering
  * normalized line endings (optional; careful with binaries)
  * ignore VCS metadata (`.git/`) when fetching from git
* Store path:

  * `~/.botpack/store/v1/<hash>/payload/...`
  * `~/.botpack/store/v1/<hash>/meta.json` (source + manifest + computed file list)

### 8.4 Project virtual store

* `.botpack/pkgs/<pkg>@<version>/` is a symlink/junction to `store/<hash>/payload/`
* Botpack must support link fallback modes:

  * `auto`: prefer symlink/junction; fallback to hardlink; fallback to copy
  * `symlink|hardlink|copy` explicit

### 8.5 Concurrency and locking

* Store writes must be atomic:

  * download/extract into temp dir
  * fsync (where available)
  * rename to final hash dir
* Use a file lock per hash during population to avoid races.

### 8.6 Garbage collection / pruning (v0.1+)

* Botpack should support pruning unreferenced store entries.
* The safe baseline behavior is:

  * never prune automatically during install/sync
  * expose an explicit command to prune with clear reporting of reclaimed bytes

### 8.7 Offline-first behavior

* Botpack should support:

  * `--offline` mode (no network; fail if any fetch would be required)
  * prefetching artifacts for CI/airgapped environments

---

## 9) Dependency resolution and fetching

### 9.1 Resolution algorithm (v0.1)

* Semver constraint resolution:

  * Prefer highest version satisfying constraints.
  * Deterministic tie-breaking by:

    1. highest version
    2. then lexical order of source URL (if needed)
* Git dependencies:

  * `rev` is immutable and required for lockfile entries.
  * If only a branch/tag is specified in manifest, lockfile records resolved commit SHA.

### 9.2 Fetchers (v0.1)

Implement fetchers in this order:

1. **Local path** (`path = ...`)
2. **Git** (`git = ...`)
3. **Registry/OCI** (optional; can be added later)

### 9.3 Integrity verification

* For git: integrity is computed hash of normalized checkout.
* For tarball: verify integrity against provided hash.
* For registry: verify artifact digest.

---

## 10) Sync engine (materialization)

### 10.1 Sync inputs

* Workspace assets from `[workspace.dir]`
* Installed dependency packages from `.botpack/pkgs/`
* Target configuration from `botpack.toml`

### 10.2 Sync output responsibilities

For each target:

* Create target root directories as needed.
* Materialize exported assets into target paths.
* Generate aggregated config files (MCP; policy only if configured).
* Write sync state tracking file for idempotence and clean.

### 10.2.1 Atomicity and interruption safety (required)

* Sync must avoid partial target states:

  * compute a full plan first
  * materialize into a staging directory under `.botpack/generated/<target>/` (or equivalent)
  * then apply changes using atomic rename/swap where feasible
* If interrupted, Botpack should either leave the previous state intact or fail with a recoverable “resume/clean” path.

### 10.3 Target mappings (built-ins)

#### 10.3.1 `claude` target (v0.1)

* Skills → `.claude/skills/<name>/...`
* Commands → `.claude/commands/<name>.md`
* Agents → `.claude/agents/<name>.md` (if runtime supports; otherwise optional)
* MCP → `.claude/mcp.json` (generated)
* Policy fragments → `.claude/hooks/` or `.claude/policy.d/` (configurable; fragments only default)

#### 10.3.2 `amp` target (v0.1)

* Commands → `.agents/commands/<name>.md`
* Skills → by default **fallback to `.claude/skills`** (current workflow)

  * Optionally support `.agents/skills` when/if Amp supports it
* Agents → `.agents/agents/` if applicable (optional)

#### 10.3.3 `droid` target (v0.1)

* Default to `.claude/skills` fallback unless configured for `.factory/skills`.
* Other asset types may be skipped by default until Droid conventions are formalized.

### 10.4 Output naming and collisions

Default output names are **package-qualified**:

* Skill name: `@scope-name.<skillId>` → e.g. `acme-quality-skills.fetch_web`
* Command name: `acme-review-commands.pr-review`
* Agent name: `acme-quality-skills.researcher`

Rules:

* If two assets map to same output path: error unless one is explicitly aliased/hidden.
* Aliases in `botpack.toml` can define short names.
* Alias collisions are errors.

### 10.5 Sync state tracking

`.botpack/state/sync-<target>.json` records:

* botpack version
* target config hash
* list of materialized paths and their sources (workspace or pkg + asset)
* generated file checksums

State tracking should also support drift detection:

* if a botpack-managed output has been modified since last sync and is not `--force`, treat as a conflict

`botpack sync --clean` removes only paths recorded in the state file that are no longer desired.

### 10.6 Sync modes

* Default: apply changes
* `--dry-run`: print plan (create/link/remove/generate) without writing
* `--clean`: remove stale botpack-managed outputs
* `--force`: overwrite conflicting unmanaged files only if explicitly requested
* `--watch`: watch workspace + `.botpack/pkgs` changes; re-sync incrementally

---

## 11) Catalog generation (progressive disclosure)

### 11.1 Purpose

* Provide metadata-only discovery across workspace + dependencies.
* Avoid reading/embedding entire skill bodies into startup context.

### 11.2 Output

`.botpack/catalog.json`

### 11.3 Schema (v0.1)

```json
{
  "version": 1,
  "generatedAt": "2025-12-15T00:00:00Z",
  "workspace": { "dir": ".botpack/workspace" },
  "packages": [
    {
      "name": "@acme/quality-skills",
      "version": "2.1.0",
      "source": "git:...",
      "assets": {
        "skills": [
          {
            "id": "fetch_web",
            "title": "Fetch Web",
            "description": "Retrieves and summarizes web pages.",
            "path": ".botpack/pkgs/@acme/quality-skills@2.1.0/skills/fetch_web/SKILL.md",
            "scripts": [
              {
                "path": ".botpack/pkgs/@acme/quality-skills@2.1.0/skills/fetch_web/scripts/fetch_web.py",
                "runtime": "python",
                "runner": "uv",
                "pep723": {
                  "requiresPython": ">=3.11",
                  "dependencies": ["requests==2.32.5", "markdown==3.10"]
                }
              }
            ]
          }
        ],
        "commands": [],
        "agents": []
      }
    }
  ]
}
```

### 11.4 Metadata extraction rules

* Parse only YAML frontmatter + a short description snippet.
* Do not inline full bodies.
* For SKILL.md: frontmatter is canonical; body is not copied.
* For `scripts/*.py`: if a PEP 723 block is present, parse **only** that header block for `requires-python` and `dependencies`.

---

## 12) MCP configuration (canonical input + deterministic output)

### 12.1 Canonical package input

Packages provide `mcp/servers.toml`.

Minimal schema:

```toml
version = 1

[[server]]
id = "postgres"
name = "Postgres MCP"
# One of:
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
# OR:
# url = "http://localhost:1234/mcp"

[server.env]
# Only allow literal values or references:
PGHOST = "${{env.PGHOST}}"
```

### 12.2 Merge rules

* Each server becomes namespaced: `<packageName>/<serverId>`
* Collision on fully qualified id is an error.
* Target output file is generated deterministically:

  * stable ordering (by fqid)
  * stable formatting
  * no nondeterministic timestamps inside generated content

### 12.3 Security gating for MCP

* Any `command/args` server implies capability `exec = true`.
* Botpack must not materialize those servers into target config unless trusted (see §13).

---

## 13) Security model

### 13.1 Disallowed: install scripts

* Botpack ignores and rejects packages that declare install scripts.
* If present, `botpack install` fails with an actionable error message.

### 13.2 Capabilities + trust

Capabilities (v0.1):

* `exec` — spawning processes (including local MCP servers)
* `network` — indicates network access is expected/required (informational; used by policy)
* `mcp` — package provides MCP servers (informational; combined with exec/url)
* Future: `fs.read`, `fs.write`, `env`

Trust is stored in `.botpack/trust.toml`:

```toml
version = 1

["@acme/mcp-pack@0.3.0"]
allowExec = false
allowMcp = false

# Prefer digest-scoped trust when available (immutable artifacts):
["@acme/mcp-pack@0.3.0".digest]
integrity = "blake3:..."

# Optional finer-grained trust for risky surfaces:
["@acme/mcp-pack@0.3.0".mcp."@acme/mcp-pack/postgres"]
allowExec = false
```

### 13.2.1 Trust granularity (recommended)

Botpack should support trust decisions at multiple levels:

* package-wide (coarse)
* per MCP server id (common case)
* future: per-skill script execution surfaces

### 13.3 Trust UX

* On `botpack add` or `botpack sync`:

  * If a package introduces gated capabilities, Botpack prints a clear prompt-style message and fails non-interactively unless `--yes` or explicit `botpack trust ...` has been applied.
* In CI, default to non-interactive; require pre-approved trust file.

### 13.4 Enterprise policy hooks (optional mid-term)

Support `.botpack/policy.toml` to enforce:

* allowed registries/sources
* signature requirement
* license allow/deny list
* deny exec entirely

---

## 14) CLI specification

Botpack ships the `botpack` CLI.

Notes:

* Earlier drafts used `botyard`/`by` naming; those are considered legacy and are not required for v0.2.

Examples below use `botpack`.

### 14.1 Commands (v0.1)

**Core**

* `botpack init`

  * Creates `botpack.toml` (and `.botpack/workspace/` if missing)
  * Detects legacy `.smarty/` and existing `.claude/` and configures targets defaults

* `botpack add <spec>...`

  * Updates `botpack.toml`
  * Resolves + fetches
  * Updates `botpack.lock`
  * Runs `botpack sync` unless `--no-sync`

* `botpack remove <pkg>...`

  * Removes from manifest
  * Updates lockfile
  * Syncs unless `--no-sync`

* `botpack install`

  * Installs from lockfile (or resolves if missing)
  * Respects `--frozen-lockfile`
  * Supports `--offline` (no network)
  * Syncs unless `--no-sync`

* `botpack update [<pkg>...]`

  * Re-resolves and updates lockfile
  * Syncs unless `--no-sync`

* `botpack sync [<target>]`

  * Materializes for one or all targets
  * Supports `--dry-run`, `--clean`, `--force`, `--watch`

* `botpack prefetch`

  * Fetches and verifies artifacts needed by the lockfile without materializing targets

* `botpack verify`

  * Verifies lockfile integrity against the store (rehash/verify content digests)

* `botpack prune`

  * Prunes unreferenced entries from the global store (explicit; never automatic)

**Introspection**

* `botpack list` (human-readable)
* `botpack list --json`
* `botpack tree`
* `botpack info <pkg>`
* `botpack why <pkg>`
* `botpack catalog` (prints location or outputs markdown/json)

**Safety**

* `botpack trust <pkg[@ver]> --allow exec|mcp`
* `botpack trust <pkg[@ver]> --deny exec|mcp`
* `botpack audit` (lists packages with capabilities + their trust status)

**Health**

* `botpack doctor` (checks collisions with unmanaged files, and toolchain prerequisites like `uv` when PEP 723 scripts are present)

**Migration**

* `botpack migrate from-legacy`

  * See §15

### 14.2 Exit codes (required)

* `0`: success
* `1`: generic failure
* `2`: manifest/lock parse error
* `3`: resolution error
* `4`: fetch/store error
* `5`: sync conflict error
* `6`: security/trust blocked

### 14.3 Output style

* Default: concise, single-screen summary.
* `--verbose`: include file paths, decisions, and plan steps.
* `--json`: machine-readable output for CI tooling.

---

## 15) Migration from legacy `.smarty/` repos

### 15.1 Backward compatibility strategy

* Botpack treats `.botpack/workspace/` as the default workspace root.
* Legacy `.smarty/` is supported via `botpack migrate from-legacy`.
* Botpack does not require converting SKILL.md; it remains canonical.
* Existing `.claude/skills` fallback remains; Botpack becomes the deterministic “sync owner.”

### 15.2 Migration steps (botpack-managed, idempotent)

`botpack migrate from-legacy`:

1. Create `botpack.toml` if missing with:

   * `[workspace] dir = ".botpack/workspace"`
   * targets configured (claude/amp/droid)
2. Create `.botpack/` directory
3. Generate initial `.botpack/catalog.json`
4. Run `botpack sync --clean` (optional; default to non-destructive)
5. Optionally create a compatibility shim for older workflows (optional):

   * Provide a `smarty` shim that delegates to `botpack` (best-effort), or
   * Keep `smarty` as a legacy tool and document Botpack as the new engine

### 15.3 “Do not break workflows”

* If repo already has handcrafted `.claude/skills` content:

  * Botpack will not overwrite unless `--force` or the file is already tracked in `.botpack/state/sync-claude.json`.
* Botpack should provide `botpack doctor` checks to identify unmanaged collisions.

---

## 16) Implementation architecture (internal modules)

This section is written so an orchestrator can parallelize implementation.

### 16.1 Module boundaries (recommended)

1. **config**

   * Parse/validate `botpack.toml`, `agentpkg.toml`, `trust.toml`
   * Provide typed config model + defaults + precedence

2. **lock**

   * Read/write `botpack.lock`
   * Stable JSON formatting + deterministic ordering

3. **resolver**

   * Build dependency graph
   * Semver solving
   * Produce resolved package set for lockfile

4. **fetch**

   * Git fetcher
   * Local path fetcher
   * (Optional) tarball fetcher
   * Normalize checkout → content hash input

5. **store**

   * Global store CAS
   * Project virtual store linking
   * Link mode selection + Windows support
   * Locking and atomic writes
   * Integrity verification (rehash/verify against lockfile)
   * Explicit garbage collection / pruning

6. **assets**

   * Scan workspace/package directories for assets
   * Parse frontmatter metadata
   * Construct canonical asset objects

7. **sync**

   * Compute plan per target (create/link/remove/generate)
   * Apply plan atomically (staging + swap)
   * Maintain `.botpack/state/sync-*.json`
   * Implement `--dry-run`, `--clean`, `--force`

8. **mcp**

   * Parse `mcp/servers.toml`
   * Merge/namespacing
   * Generate target output file format
   * Enforce trust gating

9. **catalog**

   * Generate `.botpack/catalog.json`
   * Metadata-only extraction rules

10. **cli**

* Command parsing
* Wiring modules together
* Human + JSON output

### 16.2 Cross-module contracts (key interfaces)

* `Project.load(root) -> ProjectConfig`
* `Lock.load(root) -> LockState`
* `Resolver.resolve(project, lock?) -> ResolvedGraph`
* `Fetcher.fetch(resolvedPkg) -> FetchedTree`
* `Store.put(fetchedTree) -> StoreEntry(hash, path)`
* `Store.verify(lock) -> VerifyReport`
* `Store.prune(lock?) -> PruneReport`
* `Assets.scan(rootPath) -> AssetIndex`
* `Sync.plan(target, assets, aliases) -> SyncPlan`
* `Sync.apply(plan, stateFile) -> SyncResult`
* `Catalog.generate(assetIndex, resolvedGraph) -> Catalog`

---

## 17) Test plan and acceptance criteria

### 17.1 Golden-repo integration tests (must-have)

Create fixture repos with:

* Workspace-only assets (`.botpack/workspace/...`)
* Dependencies-only assets
* Mixed workspace + dependencies
* MCP packages requiring trust

For each, verify:

* `botpack install --frozen-lockfile` is deterministic
* `botpack sync --clean` is idempotent
* output directory trees match committed golden snapshots (per OS/link mode)
* collisions produce expected exit code and message
* trust gating blocks MCP exec servers until approved

### 17.2 Cross-platform tests (must-have)

* Linux + macOS + Windows
* Symlink/hardlink/copy modes (at least one test each)

### 17.3 Runtime smoke tests (must-have)

* Verify materialized `.claude/skills` matches expected structure for Claude Code ingestion
* Verify `.agents/commands` exists and includes commands for Amp
* Verify fallback `.claude/skills` is sufficient for Amp and Droid workflows (as per current practice)

### 17.4 Agentic rubric-based end-to-end tests (must-have)

Botpack should ship an agentic test harness that validates real workflows botpack instructing **multiple parallel agents** to perform end-to-end scenarios and then grading results against a **rubric**.

Principles:

* Tests are scenario-driven ("user stories") rather than unit-driven.
* Each scenario includes a rubric with objective checks (exit codes, file tree snapshots, lockfile diff stability, store integrity, trust gating behavior).
* The harness is designed to run in CI with machine-readable results.

Recommended structure (v0.1):

* `tests/agentic/rubrics/*.yaml` — rubric definitions
* `tests/agentic/scenarios/*.yaml` — scenario definitions (commands to run + expected invariants)
* `by test agentic --json` — emits a runnable plan (one job per scenario) suitable for an orchestrator to fan out to parallel agents
* `by test agentic --report <path>` — aggregates per-scenario agent reports into a single summary

Minimum required scenarios:

* init → add → install (`--frozen-lockfile`) → sync (claude)
* offline: `prefetch` then `install --offline`
* integrity: `verify` catches tampering
* trust: MCP exec servers are blocked until trusted (including per-server trust)
* sync atomicity: interrupted/partial materialization does not leave broken target state

---

## 18) Work breakdown for parallel developer agents

### Stream A — CLI + command wiring

* Implement `init/add/remove/install/update/sync/list/tree/info/why/catalog/doctor`
* Implement `prefetch/verify/prune` (offline + integrity workflows)
* Output formatting + exit codes

**Done when:** commands execute end-to-end using stubbed resolver/store.

### Stream B — Config + schema validation

* TOML parsing + schema validation for `botpack.toml`, `agentpkg.toml`, `trust.toml`
* Defaults + precedence
* Helpful error messages

**Done when:** invalid inputs produce deterministic error codes and messages.

### Stream C — Resolver + lockfile

* Semver resolution engine
* Lockfile read/write stable JSON

**Done when:** repeat resolve produces identical lockfile; `--frozen-lockfile` works.

### Stream D — Fetchers + store

* Git fetch with commit pinning
* CAS store + project virtual store
* Atomic writes + locks + link modes
* Explicit prune (GC) and verify
* Offline-first behaviors

**Done when:** concurrent installs don’t corrupt store; offline install works with cached entries.

### Stream E — Asset scanning + catalog

* Workspace/package asset discovery
* Frontmatter parsing and metadata extraction
* `.botpack/catalog.json` generation

**Done when:** catalog lists assets without reading full bodies.

### Stream F — Sync engine + targets

* Plan/apply engine (atomic staging)
* claude/amp/droid targets
* collision resolution + aliasing + state tracking + clean

**Done when:** repeated sync is idempotent; clean removes only botpack-managed outputs.

### Stream G — MCP merge + trust gating

* Parse `mcp/servers.toml`
* Merge/namespacing rules
* Generate target MCP output
* Block unless trusted

**Done when:** untrusted exec MCP never materializes; trusted does.

### Stream H — Migration tooling + compatibility

* `botpack migrate from-legacy`
* Optional legacy CLI shim or compatibility notes
* Detect and migrate `.smarty/` into `.botpack/workspace/`

**Done when:** existing repo can adopt botpack without breaking `.claude/skills` workflows.

### Stream I — Docs + examples + CI

* Golden fixture tests for determinism
* Agentic rubric-based E2E harness (parallel agents)
* Cross-platform CI pipelines for tests across OS

**Done when:** new dev can run fixture tests and verify deterministic install/sync behavior.

---

## 19) MVP deliverable definition (v0.1)

### MVP includes

* `botpack.toml` + `botpack.lock`
* CAS store + virtual store
* Git + path dependencies
* Integrity verification (lockfile ↔ store)
* Sync targets: `claude`, `amp`, `droid` (with `.claude/skills` fallback)
* Catalog generation
* MCP merge + trust gating (exec servers blocked until trusted)
* Migration from `.smarty/` repos

### MVP explicitly excludes

* Public registry/search UI
* Signing/verification (can be designed later)
* Template application into CLAUDE.md/AGENTS.md
* Policy file generation beyond fragment staging

---

## 20) Implementation notes for transitioning from older repos

### Recommended evolution path

* Provide a best-effort legacy shim (optional) that delegates to `botpack` for common commands.
* Move existing “sync outputs to runtimes” logic under Botpack’s `sync` engine.
* Preserve existing progressive-disclosure flows botpack keeping:
  * `by catalog` (metadata-only)
  * `by info` / `by why` for graph introspection
  * (optional) `by open <asset>` for jumping to source paths
* Keep `.claude/skills` as the main runtime target for skills in v0.1 to match established workflows.

---

## Appendix A — Example end-to-end workflow (expected UX)

1. Initialize repo:

```bash
botpack init
```

2. Add dependency skill packs:

```bash
by add @acme/quality-skills@^2
```

3. Install in CI:

```bash
by install --frozen-lockfile --no-sync
botpack sync claude --clean
```

4. Trust MCP pack explicitly:

```bash
by add @acme/mcp-pack@^0.3
by trust @acme/mcp-pack@0.3.0 --allow exec --allow mcp
botpack sync claude
```

---

## Appendix B — Open decisions (safe defaults chosen unless stated)

These are implementation choices Botpack should hardcode initially, with later configurability:

* Integrity hash: **BLAKE3** recommended (fast), fallback SHA-256 if needed.
* Default output naming: **package-qualified** to avoid collisions.
* Default workspace dir: `.botpack/workspace/` if present; if `.smarty/` exists treat as legacy and prompt to migrate; otherwise create `.botpack/workspace/`.
* Default link mode: `auto`.

---

If you want this spec translated into an orchestrator-ready “task graph” (tickets with owners, dependencies, acceptance tests, and file-level touch points), I can output a structured plan (YAML/JSON) keyed botpack the work streams above.
