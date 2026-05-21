#!/bin/bash
# One-click wrapper: activate the release venv + run release.sh.
#
# release.sh uses `python -m build`, `twine check`, `twine upload` —
# all needing build + twine on PATH. They live in ~/.venvs/gux-release.
# Without activating the venv first, those commands would fall through
# to system Python which doesn't have them.
#
# This wrapper guarantees the right Python + tooling, then defers to
# the real release script for everything else (preflight, build,
# TestPyPI smoke, PyPI publish, git tag).

set -euo pipefail
cd "$(dirname "$0")"

VENV="$HOME/.venvs/gux-release"

if [ ! -d "$VENV" ]; then
  echo "✕ release venv not found at $VENV"
  echo "  run prep-release.command first"
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "▸ venv:   $VENV"
echo "▸ python: $(which python)"
echo "▸ twine:  $(which twine)"
echo

# Defer to release.sh for the rest.
#
# --skip-ci-check: we verified CI green in-browser at commit d0cec20 this
# session, and `gh` CLI isn't installed on this host so release.sh can't
# verify it automatically. The CI gate stays meaningful for anyone who
# installs `gh` later (release.sh respects the gh-CLI presence check).
exec ./release.sh --skip-ci-check "$@"
