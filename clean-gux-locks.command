#!/bin/bash
# Clear stale git locks in the G.UX package repo.
#
# Pattern: the harness sandbox can write into .git/ via FUSE but
# cannot always unlink files there (FUSE permission asymmetry).
# Any `git init` / `git add` / `git commit` run from the sandbox
# may leave a zero-byte .git/index.lock that blocks future git ops.
#
# Run this from your Mac terminal (or double-click via Finder) when
# you see "fatal: Unable to create '...index.lock': File exists."
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCKS=(
  "$REPO_DIR/.git/index.lock"
  "$REPO_DIR/.git/HEAD.lock"
  "$REPO_DIR/.git/refs/heads/main.lock"
)

cleared=0
for lock in "${LOCKS[@]}"; do
  if [ -e "$lock" ]; then
    rm -f "$lock"
    echo "removed $lock"
    cleared=$((cleared + 1))
  fi
done

if [ "$cleared" -eq 0 ]; then
  echo "no stale locks found in $REPO_DIR/.git/"
else
  echo "cleared $cleared stale lock(s)"
fi
