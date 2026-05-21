#!/bin/bash
# CI fix — install [yaml] extra alongside [dev] so the full test suite
# can run on GitHub runners (which don't have PyYAML system-installed).
#
# The first CI run on b8af761 / dcc8a9f / a339709 failed with 5 of 165
# tests erroring on `ModuleNotFoundError: No module named 'yaml'`. The
# kernel itself is stdlib-only, but the CLI integration tests use the
# `gux init` flow which writes a YAML constitution. Without PyYAML in
# the CI venv, those tests fail before getting to their actual assertions.

set -euo pipefail
cd "$(dirname "$0")"

echo "─────────────────────────────────────────────────────────────"
echo "  CI fix — install [yaml] extra"
echo "─────────────────────────────────────────────────────────────"
echo

# Clean sandbox-leaked junk
rm -f .git/index.lock .git/HEAD.lock 2>/dev/null || true
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true

echo "▸ pre-state:"
echo "  HEAD: $(git rev-parse --short HEAD)"
git status --short | sed 's/^/    /'

echo
echo "▸ staging .github/workflows/test.yml…"
git add .github/workflows/test.yml

echo "▸ committing…"
git commit -m "ci: install [yaml] extra so the test suite passes on clean runners

First CI run on the baseline + tooling commits failed with 5 of 165
tests erroring on:

  ModuleNotFoundError: No module named 'yaml'

Root cause: gux-governor is intentionally stdlib-only at runtime, with
PyYAML as an OPTIONAL [yaml] extra. The CI workflow installed only the
[dev] extra (pytest + pytest-cov) and not [yaml]. Locally the test
suite passes because PyYAML is system-installed; on GitHub's clean
runners it isn't.

The failing tests exercise the recommended user flow (gux init → write
constitution.yaml → serve/dispatch), which DOES require yaml. The
kernel + the gates themselves don't need yaml — those 160 tests passed.

Two valid responses to this:

  1. Make PyYAML a hard runtime dep. Loses the 'zero deps' story.
  2. Install [yaml] in CI alongside [dev]. Keeps the distribution-level
     promise (kernel is stdlib-only) while validating the recommended
     user-flow end-to-end in CI.

(2) is the right move and what this commit does. The package on PyPI
will still have zero runtime deps; users who want YAML constitution
support install gux-governor[yaml]."

echo "  ✓ committed: $(git log -1 --format=%h)"

echo
echo "▸ pushing origin main…"
git push origin main

echo
echo "─────────────────────────────────────────────────────────────"
echo "  ✓ CI fix pushed — re-run will trigger automatically"
echo "─────────────────────────────────────────────────────────────"
echo
echo "  Watch CI: https://github.com/StellarRequiem/GUX/actions"
echo "  log:"
git log --oneline -3 | sed 's/^/    /'
echo
echo "Press any key to close…"
if [ -t 0 ]; then read -n 1 -s; fi
