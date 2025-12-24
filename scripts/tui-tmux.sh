#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Generic TUI tmux wrapper.
# Supported TUIs: opencode | droid | codex | coder | claude | amp
# Commands: start, attach, send, sendkey, peek, kill, status

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

ts() { date -u +%Y%m%dT%H%M%SZ; }
log() { printf "[tui-tmux] %s\n" "$*" >&2; }
die() { printf "[tui-tmux][ERROR] %s\n" "$*" >&2; exit 1; }

restore_tty() {
  printf '\e[?2004l\e[?1000l\e[?1002l\e[?1003l\e[?1006l\e[?1049l\e[?25h' || true
  command -v tput >/dev/null 2>&1 && { tput rmcup || true; tput cnorm || true; } || true
  stty sane || true
}

usage() {
  cat <<'USAGE'
Usage: scripts/tui-tmux.sh <tui> <command> [args]

TUIs: opencode | droid | codex | coder | claude | amp

Commands:
  start            Start an isolated tmux session for the TUI
  attach           Attach safely; detaching restores your terminal
  send <text..>    Send text (joined by spaces) followed by Enter
  sendkey <keys..> Send tmux key names without implicit Enter (e.g., Escape, Enter)
  peek             Capture and print the current screen to stdout
  kill             Kill the tmux session and server
  status           Show socket/session/artifact paths

Environment:
  MODEL              Preferred model (default: openai/gpt-5 where supported)
  AGENT              Preferred agent/profile (default: smarty where supported)
  DROID_ARGS         Extra args passed to droid
  BOTPACK_TUI_ENV_FILE  Optional file to source before launching the TUI
  BOTPACK_TUI_ENV_CMD   Optional bash snippet to eval before launching the TUI
  XDG_CONFIG_HOME     Used by OpenCode; defaults to <repo>/.opencode

  SOCK       Override tmux socket name (auto if unset)
  SESS       Override tmux session name (auto if unset)
  ART        Override artifact directory (auto if unset)

Artifacts are written under dist/manual/<tui>-<UTC>-interactive/.
USAGE
}

ensure_ids() {
  local TUI=$1
  local STATE_FILE="$REPO_ROOT/dist/manual/${TUI}-tmux.latest.env"
  if [[ -z "${SOCK:-}" || -z "${SESS:-}" || -z "${ART:-}" ]]; then
    [[ -f "$STATE_FILE" ]] && source "$STATE_FILE" || true
  fi
  local now
  now=$(ts)
  [[ -z "${SOCK:-}" ]] && SOCK="${TUI}_${now}"
  [[ -z "${SESS:-}" ]] && SESS="${TUI}"
  [[ -z "${ART:-}" ]] && ART="$REPO_ROOT/dist/manual/${TUI}-${now}-interactive"
  export SOCK SESS ART
}

ensure_dirs() {
  mkdir -p "$ART" "$REPO_ROOT/dist/manual" || true
  if [[ -z "${XDG_CONFIG_HOME:-}" ]]; then
    export XDG_CONFIG_HOME="$REPO_ROOT/.opencode"
  fi
  mkdir -p "$XDG_CONFIG_HOME" || true
}

start_cmd_for() {
  local TUI=$1
  local model=${MODEL:-openai/gpt-5}
  local agent=${AGENT:-smarty}
  local droid_args=${DROID_ARGS:-}

  local env_setup=""
  if [[ -n "${BOTPACK_TUI_ENV_FILE:-}" ]]; then
    env_setup+="source \"${BOTPACK_TUI_ENV_FILE}\"; "
  fi
  if [[ -n "${BOTPACK_TUI_ENV_CMD:-}" ]]; then
    env_setup+="${BOTPACK_TUI_ENV_CMD}; "
  fi

  case "$TUI" in
    opencode)
      echo "${env_setup}export XDG_CONFIG_HOME=\"$XDG_CONFIG_HOME\"; cd \"$REPO_ROOT\" && opencode -m \"$model\" --agent \"$agent\"" ;;
    droid)
      echo "${env_setup}cd \"$REPO_ROOT\" && droid $droid_args" ;;
    codex)
      echo "${env_setup}cd \"$REPO_ROOT\" && codex repl" ;;
    coder)
      echo "${env_setup}cd \"$REPO_ROOT\" && coder" ;;
    claude)
      echo "${env_setup}cd \"$REPO_ROOT\" && claude --debug" ;;
    amp)
      echo "${env_setup}cd \"$REPO_ROOT\" && amp" ;;
    *) die "Unknown TUI: $TUI" ;;
  esac
}

cmd_start() {
  local TUI=$1
  ensure_ids "$TUI"; ensure_dirs
  log "Starting $TUI in tmux: sock=$SOCK sess=$SESS"
  tmux -L "$SOCK" kill-server >/dev/null 2>&1 || true
  local start_cmd; start_cmd=$(start_cmd_for "$TUI")
  tmux -L "$SOCK" -f /dev/null new-session -d -s "$SESS" bash -lc "$start_cmd"
  tmux -L "$SOCK" -f /dev/null pipe-pane -t "$SESS" -o "cat >> \"$ART/tmux.raw\""
  sleep 2
  tmux -L "$SOCK" send-keys -t "$SESS" C-m
  printf 'export SOCK=%q SESS=%q ART=%q\n' "$SOCK" "$SESS" "$ART" | tee "$REPO_ROOT/dist/manual/${TUI}-tmux.latest.env" > "$ART/env.sh"
  log "Artifacts: $ART"
  printf 'artifacts: %s\n' "$ART"
}

cmd_attach() {
  local TUI=$1
  ensure_ids "$TUI"
  trap restore_tty EXIT
  tmux -L "$SOCK" attach -t "$SESS" || true
}

cmd_send() {
  local TUI=$1; shift || true
  ensure_ids "$TUI"
  (( $# >= 1 )) || die "send: missing text"
  tmux -L "$SOCK" send-keys -t "$SESS" -- "$@" C-m
}

cmd_sendkey() {
  local TUI=$1; shift || true
  ensure_ids "$TUI"
  (( $# >= 1 )) || die "sendkey: missing key names"
  tmux -L "$SOCK" send-keys -t "$SESS" -- "$@"
}

cmd_peek() {
  local TUI=$1
  ensure_ids "$TUI"
  tmux -L "$SOCK" capture-pane -p -J -S -2000 -t "$SESS" | tee "$ART/tmux.peek.txt"
}

cmd_kill() {
  local TUI=$1
  ensure_ids "$TUI"
  tmux -L "$SOCK" kill-session -t "$SESS" >/dev/null 2>&1 || true
  tmux -L "$SOCK" kill-server >/dev/null 2>&1 || true
  log "Killed $TUI (sock=$SOCK sess=$SESS)"
}

cmd_status() {
  local TUI=$1
  ensure_ids "$TUI"
  printf 'tui=%s\nsock=%s\nsess=%s\nART=%s\n' "$TUI" "$SOCK" "$SESS" "$ART"
}

main() {
  local TUI=${1:-}
  local CMD=${2:-}
  shift || true; shift || true
  case "${TUI}:${CMD}" in
    *:start)  cmd_start "$TUI" ;;
    *:attach) cmd_attach "$TUI" ;;
    *:send)   cmd_send "$TUI" "$@" ;;
    *:sendkey) cmd_sendkey "$TUI" "$@" ;;
    *:peek)   cmd_peek "$TUI" ;;
    *:kill)   cmd_kill "$TUI" ;;
    *:status) cmd_status "$TUI" ;;
    *) usage ;;
  esac
}

main "$@"
