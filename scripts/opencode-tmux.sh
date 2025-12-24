#!/usr/bin/env bash
set -Eeuo pipefail

# Back-compat shim.
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/tui-tmux.sh" opencode "$@"
