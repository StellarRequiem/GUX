#!/bin/bash
# G.UX installer for macOS (and Linux).
#
# Double-click this file in Finder, or run from a terminal:
#   ./install-gux.command
#
# What it does:
#   1. Verifies Python 3.10+ is installed.
#   2. Creates ~/.gux/ for state.
#   3. Creates a venv at ~/.gux/.venv/.
#   4. Installs the gux-governor package into the venv.
#   5. Writes an example constitution.yaml.
#   6. Mints a fresh 7-day trial license, OR activates a key you pass in.
#   7. Drops a launch-gux.command onto your Desktop you can double-click.
#
# No network calls. No telemetry. Your license key never leaves disk.
#
# Usage:
#   ./install-gux.command                       # fresh 7-day trial
#   ./install-gux.command gux_pro_aB3kD9eF…     # paid key activation

set -euo pipefail

# Keep the terminal window open if double-clicked from Finder.
# The `read` only runs if stdin is a real TTY (interactive double-click).
# In non-interactive contexts (tests, CI, scripted installs) stdin is
# closed and `read` would fail under `set -e`, propagating a non-zero
# exit even though every install step succeeded.
trap 'echo; if [ -t 0 ]; then echo "Press any key to close…"; read -n 1 -s; fi' EXIT

GUX_HOME="${GUX_HOME:-$HOME/.gux}"
VENV="$GUX_HOME/.venv"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

# Pretty output helpers
GREEN=$'\033[32m'
DIM=$'\033[2m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

echo
echo "${BOLD}G.UX${RESET} ${DIM}—  Governor User Experience installer${RESET}"
echo "${DIM}────────────────────────────────────────────${RESET}"
echo

# 1. Python check
if ! command -v python3 >/dev/null 2>&1; then
  echo "${BOLD}✕${RESET} python3 not found on PATH."
  echo "  Install Python 3.10+ first:  https://www.python.org/downloads/"
  exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info[0])')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "${BOLD}✕${RESET} Python $PY_VERSION is too old. Need 3.10+."
  exit 1
fi
echo "${GREEN}✓${RESET} Python $PY_VERSION"

# 2. Home dir
mkdir -p "$GUX_HOME"
echo "${GREEN}✓${RESET} GUX_HOME = $GUX_HOME"

# 3. Venv
if [ ! -d "$VENV" ]; then
  echo "${DIM}  ⋯ creating venv…${RESET}"
  python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "$VENV/bin/activate"
python -m pip install --upgrade pip --quiet
echo "${GREEN}✓${RESET} virtualenv ready at $VENV"

# 4. Install gux-governor from the source tree this script ships with.
echo "${DIM}  ⋯ installing gux-governor…${RESET}"
pip install --quiet "$SOURCE_DIR"
# Also install the optional YAML extra so constitution.yaml works.
pip install --quiet "pyyaml>=6.0"
echo "${GREEN}✓${RESET} gux-governor installed"

# 5. Example constitution (only if user hasn't created one)
if [ ! -f "$GUX_HOME/constitution.yaml" ]; then
  "$VENV/bin/gux" init --path "$GUX_HOME" >/dev/null
  echo "${GREEN}✓${RESET} example constitution at $GUX_HOME/constitution.yaml"
else
  echo "${GREEN}✓${RESET} constitution already exists at $GUX_HOME/constitution.yaml (kept)"
fi

# 6. License — accept an optional key as first arg
if [ "${1:-}" != "" ]; then
  if "$VENV/bin/gux" activate "$1"; then
    echo "${GREEN}✓${RESET} license activated"
  else
    echo "${BOLD}✕${RESET} license activation failed"
    exit 1
  fi
else
  # If no key supplied, ensure a trial exists (start_trial is no-op if file
  # already exists with a valid plan).
  "$VENV/bin/gux" license >/dev/null 2>&1 || "$VENV/bin/gux" trial >/dev/null
  echo "${GREEN}✓${RESET} 7-day trial license active"
fi

# 7. Drop the launcher on the Desktop
LAUNCHER="$HOME/Desktop/launch-gux.command"
cat > "$LAUNCHER" <<EOF
#!/bin/bash
# Double-click to start the G.UX governor sidecar.
set -e
cd "$GUX_HOME"
source "$VENV/bin/activate"
exec gux serve \\
  --constitution "$GUX_HOME/constitution.yaml" \\
  --audit "$GUX_HOME/audit_chain.jsonl"
EOF
chmod +x "$LAUNCHER"
echo "${GREEN}✓${RESET} launcher dropped at $LAUNCHER"

echo
echo "${BOLD}Done.${RESET}"
echo
echo "  ${DIM}▸${RESET} Double-click ${BOLD}$LAUNCHER${RESET} to start"
echo "  ${DIM}▸${RESET} Or from a terminal: ${BOLD}$VENV/bin/gux serve --constitution $GUX_HOME/constitution.yaml${RESET}"
echo "  ${DIM}▸${RESET} HTTP API: ${BOLD}http://127.0.0.1:7421${RESET}"
echo "  ${DIM}▸${RESET} Audit chain: ${BOLD}$GUX_HOME/audit_chain.jsonl${RESET}"
echo
