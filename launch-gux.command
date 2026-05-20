#!/bin/bash
# G.UX launcher — start the sidecar against your installed constitution.
# Drops to here after install-gux.command runs.

set -e

GUX_HOME="${GUX_HOME:-$HOME/.gux}"
VENV="$GUX_HOME/.venv"

if [ ! -d "$VENV" ]; then
  echo "✕ G.UX is not installed at $GUX_HOME."
  echo "  Run install-gux.command first."
  exit 1
fi

cd "$GUX_HOME"
source "$VENV/bin/activate"

exec gux serve \
  --constitution "$GUX_HOME/constitution.yaml" \
  --audit "$GUX_HOME/audit_chain.jsonl"
