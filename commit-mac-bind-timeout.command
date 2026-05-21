#!/bin/bash
# CI fix #2 — bump sidecar bind timeout from 5s to 20s.
#
# After the yaml fix (487a1f5), ubuntu went green (3/3) but macos
# went red (3/3) on a different test: TestSidecarE2E.test_real_sidecar
# _serves_dispatch — "real sidecar didn't bind within 5s". macOS
# GitHub runners have slower Python cold-start + entry-point spawn
# than Ubuntu; 5s wasn't enough headroom.

set -euo pipefail
cd "$(dirname "$0")"

echo "─────────────────────────────────────────────────────────────"
echo "  CI fix #2 — macOS sidecar bind timeout 5s → 20s"
echo "─────────────────────────────────────────────────────────────"
echo

rm -f .git/index.lock .git/HEAD.lock 2>/dev/null || true
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true

echo "▸ pre-state:"
echo "  HEAD: $(git rev-parse --short HEAD)"
git status --short | sed 's/^/    /'

echo
echo "▸ staging tests/test_install_e2e.py…"
git add tests/test_install_e2e.py

echo "▸ committing…"
git commit -m "fix(ci): bump sidecar bind timeout 5s → 20s for macOS runners

Second CI iteration. The yaml fix (487a1f5) turned the 3 ubuntu cells
green; macOS stayed red (1/165 tests failing per cell, 3 cells).

Failure on all macOS cells:

  AssertionError: real sidecar didn't bind within 5s
  /Users/runner/work/GUX/GUX/tests/test_install_e2e.py:347

The test (TestSidecarE2E.test_real_sidecar_serves_dispatch) spawns
the installed gux serve in a subprocess, polls /healthz for 5s waiting
for the bind. macOS GitHub runners are notably slower than Ubuntu at:

  - Python interpreter cold-start (framework Python vs. system)
  - pip-installed entry-point spawn (sets up the venv shebang chain)
  - Loopback bind on 127.0.0.1 (BSD network stack quirks under load)

Stacking those, 5s wasn't enough headroom on a busy runner. The test
isn't a perf test — it's a stability check that 'the sidecar boots and
serves real HTTP.' A healthy bind completes in well under 1s, so we
exit the polling loop early; the 20s cap only matters when something
is genuinely slow.

Localized to one constant + the assertion message. No other change.

Note for future tests: any time we use a hard time budget for boot
or bind under integration, prefer ≥15s on CI. Local runs finish in
sub-second so the headroom is free."

echo "  ✓ committed: $(git log -1 --format=%h)"

echo
echo "▸ pushing origin main…"
git push origin main

echo
echo "─────────────────────────────────────────────────────────────"
echo "  ✓ macOS timing fix pushed — re-run will trigger"
echo "─────────────────────────────────────────────────────────────"
echo
echo "  Watch CI: https://github.com/StellarRequiem/GUX/actions"
git log --oneline -3 | sed 's/^/    /'
echo
echo "Press any key to close…"
if [ -t 0 ]; then read -n 1 -s; fi
