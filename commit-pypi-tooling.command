#!/bin/bash
# Commit + push the PyPI release tooling.
#
# Adds:
#   - RELEASING.md          — release runbook + one-time setup
#   - release.sh            — automated build/check/upload pipeline
#   - .pypirc.example       — credentials template
#   - .gitignore            — added .pypirc to defense-in-depth
#
# Then pushes to origin/main.

set -euo pipefail

cd "$(dirname "$0")"

echo "─────────────────────────────────────────────────────────────"
echo "  G.UX commit — PyPI release tooling"
echo "─────────────────────────────────────────────────────────────"
echo

# ─── Step 1: clean sandbox-leaked junk ────────────────────────────
echo "▸ clearing sandbox-leaked junk in .git/ …"
rm -f .git/index.lock .git/index.lock.bak .git/HEAD.lock 2>/dev/null || true
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true
echo "  ✓ cleaned"

# ─── Step 2: confirm pre-state ────────────────────────────────────
echo
echo "▸ pre-state:"
echo "  branch:  $(git symbolic-ref --short HEAD)"
echo "  HEAD:    $(git rev-parse --short HEAD)"
echo "  status:"
git status --short | sed 's/^/    /'

# ─── Step 3: stage + commit ───────────────────────────────────────
echo
echo "▸ staging PyPI tooling files…"
git add RELEASING.md release.sh .pypirc.example .gitignore

echo "▸ staged:"
git status --short | sed 's/^/  /'

echo
echo "▸ committing…"
git commit -m "release: PyPI tooling — RELEASING.md + release.sh + .pypirc.example

Adds the durability layer for shipping new gux-governor versions to
PyPI. Three artifacts:

  RELEASING.md       Runbook covering one-time PyPI account setup,
                     API-token generation (real + TestPyPI), local
                     ~/.pypirc placement, then the every-release
                     workflow. Captures rationale for each step so a
                     future me (or successor) can release without
                     re-deriving the procedure.

  release.sh         Automation. Nine-step pipeline:
                       1. pre-flight (clean tree, on main, synced, CI)
                       2. version sanity (not already on PyPI)
                       3. clean build/ dist/ *.egg-info/
                       4. python -m build (sdist + wheel)
                       5. twine check (metadata valid)
                       6. TestPyPI upload + fresh-venv smoke install
                       7. real PyPI upload (irreversible — prompt)
                       8. git tag vX.Y.Z + push
                       9. print CHANGELOG excerpt for GH release notes
                     --dry-run skips upload steps for rehearsal.
                     --skip-ci-check bypasses gh-CLI status check.

  .pypirc.example    Template for ~/.pypirc. NEVER copy into the
                     repo root with real tokens — .gitignore now
                     excludes .pypirc by name as defense in depth.

Not adding the actual PyPI publishing in this commit — that's a
separate motion gated on (a) account creation, (b) token generation,
(c) first dry-run of release.sh to verify build artifacts pass twine
check. All three are pre-flight to v0.5.0 going live on PyPI."

echo "  ✓ committed: $(git log -1 --format=%h)"

# ─── Step 4: push ─────────────────────────────────────────────────
echo
echo "▸ pushing origin main…"
git push origin main

echo
echo "─────────────────────────────────────────────────────────────"
echo "  ✓ PyPI tooling committed + pushed"
echo "─────────────────────────────────────────────────────────────"
echo
echo "  view:  https://github.com/StellarRequiem/GUX"
echo "  log:"
git log --oneline -5 | sed 's/^/    /'
echo
echo "  Next steps for actual PyPI release (you, not the script):"
echo "    1. Create PyPI account: https://pypi.org/account/register/"
echo "    2. Create TestPyPI account: https://test.pypi.org/account/register/"
echo "    3. Generate API tokens for both"
echo "    4. cp .pypirc.example ~/.pypirc + paste real tokens"
echo "    5. chmod 600 ~/.pypirc"
echo "    6. python -m venv ~/.venvs/gux-release"
echo "    7. ~/.venvs/gux-release/bin/pip install --upgrade pip build twine"
echo "    8. Source the venv, then: ./release.sh --dry-run"
echo "    9. When green: ./release.sh"
echo
echo "Press any key to close…"
if [ -t 0 ]; then read -n 1 -s; fi
