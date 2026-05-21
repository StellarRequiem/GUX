#!/bin/bash
# Pre-publish prep — sets up everything that doesn't need PyPI auth.
#
#   - Creates the dedicated release venv at ~/.venvs/gux-release/
#   - Installs build + twine
#   - Builds the sdist and wheel locally
#   - Runs twine check to validate metadata before any upload
#
# This script can run ANY TIME — it's idempotent and doesn't touch
# PyPI. Run it once now to validate the package builds cleanly; the
# actual publish (release.sh) is the only step that needs ~/.pypirc.

set -euo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
  GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'
  DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  GREEN=""; YELLOW=""; RED=""; DIM=""; BOLD=""; RESET=""
fi

ok()  { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${YELLOW}!${RESET} $*"; }
die() { echo "  ${RED}✕${RESET} $*" >&2; exit 1; }

echo "${BOLD}─────────────────────────────────────────────────────────────${RESET}"
echo "${BOLD}  G.UX release prep — build + check, no PyPI auth needed${RESET}"
echo "${BOLD}─────────────────────────────────────────────────────────────${RESET}"
echo

VENV="$HOME/.venvs/gux-release"

# ─── Step 1: venv ────────────────────────────────────────────────
echo "${BOLD}▸ Step 1 — release venv at $VENV${RESET}"
if [ ! -d "$VENV" ]; then
  echo "  ${DIM}⋯ creating venv…${RESET}"
  python3 -m venv "$VENV"
  ok "created"
else
  ok "exists"
fi

# Upgrade pip + install build tooling
echo "  ${DIM}⋯ installing/updating build + twine…${RESET}"
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install --upgrade build twine --quiet
ok "build $($VENV/bin/python -m build --version 2>&1 | head -1)"
ok "twine $($VENV/bin/twine --version | head -1)"
echo

# ─── Step 2: clean previous build artifacts ──────────────────────
echo "${BOLD}▸ Step 2 — clean previous build artifacts${RESET}"
rm -rf build/ dist/ src/*.egg-info/
ok "build/ dist/ *.egg-info/ removed"
echo

# ─── Step 3: build ───────────────────────────────────────────────
echo "${BOLD}▸ Step 3 — python -m build (sdist + wheel)${RESET}"
"$VENV/bin/python" -m build
echo
echo "  ${BOLD}artifacts:${RESET}"
ls -lh dist/ | sed 's/^/    /'
echo

# ─── Step 4: twine check ─────────────────────────────────────────
echo "${BOLD}▸ Step 4 — twine check (metadata validation)${RESET}"
"$VENV/bin/twine" check dist/* || die "twine check failed — see output above"
echo

# ─── Step 5: inspect wheel contents ──────────────────────────────
echo "${BOLD}▸ Step 5 — wheel contents${RESET}"
WHEEL=$(ls dist/*.whl | head -1)
echo "  ${DIM}contents of $WHEEL:${RESET}"
"$VENV/bin/python" -m zipfile -l "$WHEEL" | sed 's/^/    /'
echo

# ─── Step 6: smoke-install in a throwaway venv ───────────────────
echo "${BOLD}▸ Step 6 — smoke-install in a throwaway venv${RESET}"
TMPVENV=$(mktemp -d)
python3 -m venv "$TMPVENV/venv"
"$TMPVENV/venv/bin/pip" install --upgrade pip --quiet
"$TMPVENV/venv/bin/pip" install "$WHEEL" --quiet
echo "  ${DIM}gux --version output:${RESET}"
"$TMPVENV/venv/bin/gux" --version | sed 's/^/    /'
rm -rf "$TMPVENV"
ok "wheel installs cleanly + CLI works"
echo

# ─── Step 7: report ──────────────────────────────────────────────
echo "${BOLD}─────────────────────────────────────────────────────────────${RESET}"
echo "${BOLD}  ✓ prep complete — package is publish-ready${RESET}"
echo "${BOLD}─────────────────────────────────────────────────────────────${RESET}"
echo
echo "  ${DIM}▸${RESET} sdist:  ${BOLD}$(ls dist/*.tar.gz)${RESET}"
echo "  ${DIM}▸${RESET} wheel:  ${BOLD}$(ls dist/*.whl)${RESET}"
echo "  ${DIM}▸${RESET} venv:   ${BOLD}$VENV${RESET}"
echo
echo "  ${BOLD}Still required for actual publish (you, not the script):${RESET}"
echo "    1. Enable 2FA on PyPI account (pypi.org/manage/account/two-factor/)"
echo "    2. Generate API token at pypi.org/manage/account/token/"
echo "    3. Copy .pypirc.example to ~/.pypirc, paste token, chmod 600"
echo "    4. (Optional) Register on TestPyPI for upload rehearsal"
echo
echo "  ${BOLD}When all four are done, the publish is one command:${RESET}"
echo "    ${DIM}source $VENV/bin/activate && ./release.sh${RESET}"
echo
echo "Press any key to close…"
if [ -t 0 ]; then read -n 1 -s; fi
