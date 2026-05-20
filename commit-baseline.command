#!/bin/bash
# Baseline commit for G.UX — runs on the host (your Mac), not the
# harness sandbox. The sandbox can write into .git/ but cannot unlink
# files there (FUSE permission asymmetry), so git operations from the
# sandbox half-complete and leave stale temp objects + locks. This
# script runs git from the host where unlink works normally.
#
# After this completes, the repo is committed locally and pushed to
# github.com/StellarRequiem/gux. Verify with: `git log --oneline`.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

echo "─────────────────────────────────────────────────────────────"
echo "  G.UX baseline commit"
echo "─────────────────────────────────────────────────────────────"
echo

# ─── Step 1: clear stale locks + sandbox-created junk ────────────
echo "▸ clearing stale locks and sandbox temp objects…"
rm -f .git/index.lock .git/index.lock.bak .git/index.lock.attempt2 .git/HEAD.lock 2>/dev/null || true
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true
echo "  ✓ cleaned"

# ─── Step 2: confirm git identity + signing config ───────────────
echo
echo "▸ git identity:"
git config user.email "alexanderprice91@yahoo.com"
git config user.name "Alex Price"
echo "  user.email = $(git config user.email)"
echo "  user.name  = $(git config user.name)"

# Sign commits with the same SSH key configured globally for FSF.
# If the global config has signing on but this repo lacks the
# resolved value, set it explicitly (CLAUDE.md §5 — per-repo
# .git/config overrides global).
if git config --global --get commit.gpgsign 2>/dev/null | grep -qi true; then
  git config commit.gpgsign true
  echo "  commit.gpgsign = true (matching global)"
else
  git config commit.gpgsign false
  echo "  commit.gpgsign = false (no global signing configured)"
fi

# ─── Step 3: stage everything (gitignore handles excludes) ───────
echo
echo "▸ staging…"
git add -A

# ─── Step 4: sanity-check what got staged ────────────────────────
echo
echo "▸ staged files:"
git status --short | sed 's/^/  /'
echo
echo "▸ leak check — these should ALL print nothing:"
echo -n "  build/        : "; git ls-files | grep -E '^build/' || echo "(clean)"
echo -n "  __pycache__   : "; git ls-files | grep -E '__pycache__' || echo "(clean)"
echo -n "  *.egg-info    : "; git ls-files | grep -E '\.egg-info' || echo "(clean)"
echo -n "  .pytest_cache : "; git ls-files | grep -E '\.pytest_cache' || echo "(clean)"
echo -n "  .venv         : "; git ls-files | grep -E '\.venv' || echo "(clean)"

echo
echo "▸ total tracked: $(git ls-files | wc -l | tr -d ' ') files"

# ─── Step 5: commit ───────────────────────────────────────────────
echo
echo "▸ committing…"
git commit -m "baseline: G.UX 0.5.0 — engine + 5-layer harness + Apache-2.0

Initial public release of G.UX (Governor User Experience), a drop-in
governance kernel for LLM tool dispatch.

Engine — 7 modules, stdlib-only, zero runtime dependencies:

  src/gux/gates.py       12-gate dispatch pipeline (HardwareQuarantine,
                         TaskUsageCap, ToolLookup, ArgsValidation,
                         ConstraintResolution, PostureOverride, GenreFloor,
                         InitiativeFloor, CallCounter, McpPerToolApproval,
                         ApprovalGate, PostureGate). Tighten-only safety
                         semantics — posture cannot loosen constraints.
  src/gux/governor.py    Orchestrator that runs the pipeline + records
                         each verdict to the audit chain.
  src/gux/audit.py       SHA-256 hash-linked append-only audit chain.
                         Canonical form excludes timestamp from entry_hash
                         (clock-skew immune). Genesis prev_hash literal
                         is 'GENESIS'.
  src/gux/server.py      Stdlib HTTP sidecar (ThreadingHTTPServer) with
                         /dispatch, /healthz, /audit/tail, /audit/verify.
                         CORS preflight, JSON-only, no FastAPI.
  src/gux/cli.py         init / activate / license / trial / serve /
                         verify / dispatch subcommands.
  src/gux/license.py     Trial (7d), hobby, pro, team, oem plan gating
                         at runtime. Keys persist under XDG_CONFIG_HOME.
  src/gux/types.py       DispatchRequest, DispatchContext, Verdict,
                         Step, dataclasses + frozen invariants.

Harness — 165 tests across 5 layers, 1899 LOC, 18s wall clock:

  L1 tests/test_gates.py            52 tests   all 12 gates × happy/refuse/pending
  L2 tests/test_server.py           23 tests   sidecar e2e on real HTTP socket
  L3 tests/test_license.py          49 tests   trial+activation+expiry+corruption
  L4 tests/test_cli.py              26 tests   all subcommands × exit codes
  L5 tests/test_install_e2e.py      15 tests   real install-gux.command flow

Two production bugs caught by the harness before first release:

  L1: PostureOverrideGate bool-is-int silent no-op. isinstance(True, int)
  is True in Python, so the int-tighten branch fired for booleans and
  'True < False' is False — every 'force human approval' posture override
  was silently a no-op. Caught by test_override_forces_human_approval.
  Fix: check isinstance(v, bool) before isinstance(v, int).

  L5: install-gux.command non-interactive exit-1. The trap '… read -n 1
  -s' EXIT 'Press any key to close' affordance for double-clickers caused
  the script to exit 1 under non-TTY stdin even when every install step
  succeeded. Caught by test_install_exits_zero. Fix: gate the read on
  [ -t 0 ].

License: Apache-2.0. Open kernel + entitlement gate at license.py for
paid plan features. NOTICE captures attribution + the (currently empty)
optional dependency list. PyPI package name 'gux-governor' (the bare name
'gux' is squatted by an abandoned 2020 git-user-switcher).
"

# ─── Step 6: configure remote + push ─────────────────────────────
echo
echo "▸ remote configuration:"
if git remote get-url origin >/dev/null 2>&1; then
  echo "  origin already set: $(git remote get-url origin)"
else
  git remote add origin git@github.com:StellarRequiem/gux.git
  echo "  added origin: $(git remote get-url origin)"
fi

echo
echo "▸ pushing main → origin/main…"
git push -u origin main

echo
echo "─────────────────────────────────────────────────────────────"
echo "  ✓ G.UX 0.5.0 baseline committed and pushed"
echo "─────────────────────────────────────────────────────────────"
echo
echo "  view: https://github.com/StellarRequiem/gux"
echo "  log:  git log --oneline -1"
echo
echo "Press any key to close…"
read -n 1 -s
