#!/bin/bash
# Force-push the local G.UX baseline over GitHub's auto-init commit.
#
# Why: GitHub created an auto-init commit with the LICENSE file when
# the repo was created with "Initialize with Apache-2.0 license"
# selected. Our local baseline (16+ files, 165 tests, the entire engine)
# doesn't share history with that commit. Force-push overwrites the
# auto-init with our substantive first commit.
#
# Safe here because:
#   - Repo was created ~5 minutes ago
#   - No collaborators, no PRs, no other commits
#   - The auto-init LICENSE is identical Apache-2.0 to what we have locally
#
# Uses --force-with-lease (safer than --force) — refuses if anyone else
# has pushed to origin/main since our last fetch.

set -euo pipefail

cd "$(dirname "$0")"

echo "─────────────────────────────────────────────────────────────"
echo "  Force-push G.UX baseline over auto-init"
echo "─────────────────────────────────────────────────────────────"
echo

echo "▸ local state:"
echo "  branch:    $(git symbolic-ref --short HEAD)"
echo "  HEAD:      $(git rev-parse --short HEAD)"
echo "  remote:    $(git remote get-url origin)"
echo

echo "▸ what we're about to overwrite (the auto-init commit on remote):"
git fetch origin main 2>/dev/null || true
git log -1 origin/main 2>/dev/null --format='  hash:    %h%n  author:  %an%n  date:    %ad%n  message: %s' || echo "  (could not fetch — proceeding anyway)"
echo

echo "▸ pushing local main → origin/main (force-with-lease)…"
git push --force-with-lease origin main

echo
echo "─────────────────────────────────────────────────────────────"
echo "  ✓ baseline pushed"
echo "─────────────────────────────────────────────────────────────"
echo
echo "  view:  https://github.com/StellarRequiem/gux"
echo "  HEAD:  $(git rev-parse --short HEAD)"
echo
git log --oneline -3
echo
echo "Press any key to close…"
if [ -t 0 ]; then read -n 1 -s; fi
