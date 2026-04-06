#!/usr/bin/env bash

set -euo pipefail

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

note() {
  printf '==> %s\n' "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_flag() {
  local name="$1"
  local value="$2"
  local suggestion="$3"
  if [[ -z "$value" ]]; then
    die "Missing required flag --${name}. Suggested default: ${suggestion}"
  fi
}

print_kv() {
  printf '%-28s %s\n' "$1" "$2"
}

json_get() {
  local expr="$1"
  jq -r "$expr // empty"
}
