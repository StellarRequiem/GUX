#!/bin/bash
# CI fix #3 — surface subprocess stdout/stderr on bind failure.
#
# After the timeout bump (43f42bc), macOS still failed: "didn't bind
# within 20s." But because the test swallowed proc.stdout / proc.stderr,
# we couldn't tell WHY. This commit adds diagnostic output: if the
# subprocess exits early, dump its return code + stdout + stderr; if it
# stays up but never serves /healthz, dump the same on the failure path.
#
# The point of this commit isn't to FIX the failure — it's to surface
# the underlying error so the NEXT commit can fix it from data, not from
# guessing. Same pattern §6 of CLAUDE.md: read the actual error before
# proposing a fix.

set -euo pipefail
cd "$(dirname "$0")"

echo "─────────────────────────────────────────────────────────────"
echo "  CI fix #3 — diagnostic dump for sidecar bind failure"
echo "─────────────────────────────────────────────────────────────"

rm -f .git/index.lock .git/HEAD.lock 2>/dev/null || true
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true

git add tests/test_install_e2e.py
git commit -m "test(diagnostic): surface subprocess stdout/stderr on bind failure

After bumping the bind timeout to 20s (43f42bc), macOS still fails
TestSidecarE2E with 'didn't bind within 20s' — but we have no idea
WHY because the test swallowed proc.stdout and proc.stderr.

Two diagnostic additions:

  1. In the polling loop, check proc.poll() each iteration. If the
     subprocess exited early, immediately read its output and raise
     with the return code + stdout + stderr in the assertion message.
     Catches 'crashed at startup' cases that would otherwise just
     time out.

  2. On the timeout-exhaustion path, terminate the still-running
     subprocess, read its output, and include both in the assertion
     message. Catches 'hung waiting for something' cases.

This commit's purpose is NOT to fix the underlying failure. It's to
surface the underlying error so the next commit can address it from
data. Per CLAUDE.md §6: read the actual error before proposing a fix.

The next CI run will fail the same way but the failure message will
tell us what's actually wrong on the macOS runners."

echo "  ✓ committed: $(git log -1 --format=%h)"
git push origin main
echo
echo "  ✓ pushed — watch CI for the actual error this time"
echo "  Watch: https://github.com/StellarRequiem/GUX/actions"
echo
echo "Press any key to close…"
if [ -t 0 ]; then read -n 1 -s; fi
