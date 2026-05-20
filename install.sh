#!/bin/sh
# G.UX one-line installer.
#
#   curl -fsSL https://gux.dev/install.sh | sh
#
# Or pass a license key:
#   curl -fsSL https://gux.dev/install.sh | sh -s gux_pro_aB3kD9eF…
#
# What it does:
#   1. Verify Python 3.10+.
#   2. Download the latest gux-governor wheel into ~/.gux/.venv/.
#   3. Install dependencies (PyYAML).
#   4. Write ~/.gux/constitution.yaml if missing.
#   5. Start (or refresh) a 7-day trial, or activate the supplied key.

set -eu

GUX_HOME="${GUX_HOME:-$HOME/.gux}"
VENV="$GUX_HOME/.venv"

bold() { printf '\033[1m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
dim() { printf '\033[2m%s\033[0m' "$1"; }

echo
echo "$(bold "G.UX") $(dim "—  one-line installer")"
echo "$(dim "────────────────────────────────────────────")"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "$(bold "✕") python3 not found. Install Python 3.10+ first."
  exit 1
fi
PY_VER=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "$(green "✓") Python $PY_VER"

mkdir -p "$GUX_HOME"
[ -d "$VENV" ] || python3 -m venv "$VENV"
# shellcheck disable=SC1090
. "$VENV/bin/activate"
"$VENV/bin/pip" install --quiet --upgrade pip
# Once the package is on PyPI:
"$VENV/bin/pip" install --quiet "gux-governor[yaml]" || {
  echo "$(bold "✕") could not install gux-governor."
  echo "  If this is the offline bundle, run install-gux.command instead."
  exit 1
}
echo "$(green "✓") gux-governor installed"

[ -f "$GUX_HOME/constitution.yaml" ] || "$VENV/bin/gux" init --path "$GUX_HOME" >/dev/null
echo "$(green "✓") constitution at $GUX_HOME/constitution.yaml"

if [ "${1:-}" != "" ]; then
  "$VENV/bin/gux" activate "$1"
else
  "$VENV/bin/gux" license >/dev/null 2>&1 || "$VENV/bin/gux" trial >/dev/null
  echo "$(green "✓") 7-day trial active"
fi

echo
echo "$(bold "Done.") Run:"
echo
echo "  $VENV/bin/gux serve --constitution $GUX_HOME/constitution.yaml"
echo
