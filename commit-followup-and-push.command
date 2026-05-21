#!/bin/bash
# Two follow-up commits + push, in one motion:
#
#   1. tooling: add force-push-baseline.command (recovery helper that
#      already lives in the working tree but isn't tracked yet)
#   2. ci: GitHub Actions test workflow under .github/workflows/test.yml
#
# Then push both to origin/main.
#
# Why a helper script (and not just commit from the sandbox): the harness
# sandbox can write INTO .git/ but cannot unlink files there (FUSE asym).
# Host-side git can do both. Same pattern as commit-baseline.command.

set -euo pipefail

cd "$(dirname "$0")"

echo "─────────────────────────────────────────────────────────────"
echo "  G.UX follow-up commits — recovery helper + CI workflow"
echo "─────────────────────────────────────────────────────────────"
echo

# ─── Step 1: clean sandbox-leaked junk ────────────────────────────
echo "▸ clearing sandbox-leaked junk in .git/ …"
rm -f .git/index.lock .git/index.lock.bak .git/index.lock.attempt2 .git/HEAD.lock 2>/dev/null || true
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true
echo "  ✓ cleaned"

# ─── Step 2: confirm pre-state ────────────────────────────────────
echo
echo "▸ pre-state:"
echo "  branch:        $(git symbolic-ref --short HEAD)"
echo "  HEAD:          $(git rev-parse --short HEAD)"
echo "  untracked:"
git status --short | sed 's/^/    /'

# ─── Step 3: commit #1 — recovery helper ──────────────────────────
echo
echo "▸ commit #1 — recovery helper:"
git add force-push-baseline.command
git commit -m "tooling: add force-push-baseline.command recovery helper

Companion to commit-baseline.command + clean-gux-locks.command.

Use this when local and origin/main have diverged — e.g. after GitHub
auto-init creates an 'Initial commit' that competes with a substantive
local baseline. Force-with-lease, so it refuses if anyone else pushed
since our last fetch (safer than --force).

This file recorded the recovery procedure used to land the b8af761
baseline over GitHub's auto-init 03512bf, so a future session in a
similar situation has a known-good move to copy."

echo "  ✓ committed: $(git log -1 --format=%h)"

# ─── Step 4: commit #2 — CI workflow ──────────────────────────────
echo
echo "▸ commit #2 — GitHub Actions CI:"
git add .github/workflows/test.yml
git commit -m "ci: GitHub Actions — run 165-test harness on every push

Matrix: Python 3.10/3.11/3.12 × ubuntu-latest + macos-latest = 6 cells.

Steps per cell:
  - checkout
  - setup-python with pip cache keyed on pyproject.toml
  - pip install -e '.[dev]'  (editable + pytest + pytest-cov)
  - python -m pytest         (uses pyproject.toml's testpaths + addopts)
  - gux --version            (smoke check the CLI entry point)

Concurrency group on workflow + branch cancels in-progress runs when a
new push arrives, so we don't burn runner minutes on stale commits.

This is the durability layer for the 5-layer harness: tests only catch
bugs if they actually run. Before this, the suite was a local-only
discipline; with this, it's the gate every PR must clear before merge.
The two bugs the harness already caught (PostureOverrideGate bool-is-int
and install-gux.command non-TTY trap) would have shipped to v0.5.0
otherwise — CI ensures future regressions don't slip through either."

echo "  ✓ committed: $(git log -1 --format=%h)"

# ─── Step 5: show what we're about to push ────────────────────────
echo
echo "▸ commits to push:"
git log --oneline @{u}..HEAD | sed 's/^/  /'

# ─── Step 6: push ─────────────────────────────────────────────────
echo
echo "▸ pushing origin main …"
git push origin main

echo
echo "─────────────────────────────────────────────────────────────"
echo "  ✓ follow-ups committed + pushed"
echo "─────────────────────────────────────────────────────────────"
echo
echo "  view:  https://github.com/StellarRequiem/GUX"
echo "  log:"
git log --oneline -5 | sed 's/^/    /'
echo
echo "  CI status will appear at:"
echo "  https://github.com/StellarRequiem/GUX/actions"
echo
echo "Press any key to close…"
if [ -t 0 ]; then read -n 1 -s; fi
