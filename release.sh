#!/bin/bash
# G.UX release automation — build, twine-check, TestPyPI smoke, PyPI
# upload, git tag. See RELEASING.md for one-time setup + rationale.
#
# Usage:
#   ./release.sh              # full pipeline with confirmation prompts
#   ./release.sh --dry-run    # everything except the two upload steps
#   ./release.sh --skip-ci-check    # don't require CI green on HEAD
#
# Assumes:
#   - ~/.pypirc is configured (see RELEASING.md step 4)
#   - python -m build + twine are installed in your active env
#   - You're on `main` and synced with origin
#
# Aborts loudly on any precondition failure. Safe to ctrl-c mid-flight —
# state is always recoverable.

set -euo pipefail

cd "$(dirname "$0")"

DRY_RUN=false
SKIP_CI_CHECK=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --skip-ci-check) SKIP_CI_CHECK=true ;;
    -h|--help)
      head -n 18 "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "unknown arg: $arg"; exit 1 ;;
  esac
done

# ─── Color output (only when stdout is a TTY) ─────────────────────
if [ -t 1 ]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; DIM=""; BOLD=""; RESET=""
fi

# ─── Helpers ──────────────────────────────────────────────────────
say() { echo "${BOLD}▸${RESET} $*"; }
ok()  { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${YELLOW}!${RESET} $*"; }
die() { echo "  ${RED}✕${RESET} $*" >&2; exit 1; }
confirm() {
  local prompt="${1:-Continue?}"
  read -p "  ${prompt} [y/N] " -r reply
  [[ "$reply" =~ ^[Yy]$ ]] || die "aborted by user"
}

# ─── Step 1: pre-flight ───────────────────────────────────────────
echo "${BOLD}┌── Step 1 — Pre-flight checks ─────────────────────────${RESET}"

say "git working tree:"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "uncommitted changes. commit or stash first."
fi
ok "clean"

say "git branch:"
BRANCH=$(git symbolic-ref --short HEAD)
if [ "$BRANCH" != "main" ]; then
  die "not on main (on '$BRANCH'). releases only from main."
fi
ok "on main"

say "remote sync:"
git fetch origin main --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
  die "local ($LOCAL) != origin/main ($REMOTE). pull or push first."
fi
ok "synced with origin/main"

if [ "$SKIP_CI_CHECK" = false ]; then
  say "CI status (best-effort):"
  if command -v gh >/dev/null 2>&1; then
    if gh run list --branch main --limit 1 --json status,conclusion \
        | grep -q '"status":"completed".*"conclusion":"success"'; then
      ok "CI green on HEAD"
    else
      warn "CI not green or unknown (use --skip-ci-check to bypass)"
      confirm "Proceed anyway?"
    fi
  else
    warn "gh CLI not installed — can't check CI; install with `brew install gh`"
    confirm "Proceed without CI check?"
  fi
fi
echo

# ─── Step 2: version sanity ───────────────────────────────────────
echo "${BOLD}┌── Step 2 — Version sanity ────────────────────────────${RESET}"
VERSION=$(python3 -c "
import tomllib
with open('pyproject.toml','rb') as f:
    print(tomllib.load(f)['project']['version'])
")
say "version in pyproject.toml: ${BOLD}${VERSION}${RESET}"

# Check PyPI to see if this version already exists
say "checking PyPI for existing release…"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "https://pypi.org/pypi/gux-governor/${VERSION}/json")
case "$HTTP_STATUS" in
  200) die "gux-governor==${VERSION} ALREADY EXISTS on PyPI. bump pyproject.toml version." ;;
  404) ok "version ${VERSION} not on PyPI yet — fresh release" ;;
  *)   warn "unexpected HTTP $HTTP_STATUS from PyPI; proceeding cautiously" ;;
esac
echo

# ─── Step 3: clean build artifacts ────────────────────────────────
echo "${BOLD}┌── Step 3 — Clean build tree ──────────────────────────${RESET}"
say "removing build/, dist/, *.egg-info/…"
rm -rf build/ dist/ src/*.egg-info/
ok "clean"
echo

# ─── Step 4: build ────────────────────────────────────────────────
echo "${BOLD}┌── Step 4 — Build sdist + wheel ───────────────────────${RESET}"
say "python -m build"
python -m build
say "artifacts:"
ls -lh dist/
echo

# ─── Step 5: twine check ──────────────────────────────────────────
echo "${BOLD}┌── Step 5 — Twine check ───────────────────────────────${RESET}"
say "twine check dist/*"
twine check dist/*
ok "metadata valid"
echo

# ─── Step 6: TestPyPI upload + smoke install ──────────────────────
echo "${BOLD}┌── Step 6 — TestPyPI upload + smoke install ───────────${RESET}"
# Auto-skip TestPyPI when the user hasn't registered + tokenized there.
# Heuristic: if the [testpypi] password starts with "placeholder-", we
# know it's not a real token. Avoids the trap where saying "y" to the
# prompt triggers a 403 from TestPyPI and aborts the whole script
# before the real PyPI step.
TESTPYPI_PW=$(awk '/^\[testpypi\]/{f=1;next} /^\[/{f=0} f && /^password/{print $3; exit}' ~/.pypirc 2>/dev/null || echo "")
if [[ "$TESTPYPI_PW" == placeholder-* ]] || [ -z "$TESTPYPI_PW" ]; then
  warn "TestPyPI password is a placeholder — auto-skipping TestPyPI step"
  warn "  (to enable: register on test.pypi.org, generate a token, put"
  warn "   it in ~/.pypirc's [testpypi] password field)"
elif [ "$DRY_RUN" = true ]; then
  warn "DRY RUN — skipping TestPyPI upload"
else
  confirm "Upload to TestPyPI?"
  say "twine upload --repository testpypi dist/*"
  twine upload --repository testpypi dist/*

  say "smoke-install from TestPyPI in a fresh venv…"
  TMPVENV=$(mktemp -d)
  python3 -m venv "$TMPVENV/venv"
  # TestPyPI lacks some transitive deps, so allow fallback to real PyPI
  # for any non-gux-governor dependency. Our package has zero runtime
  # deps so this matters only for the `dev` extra (pytest etc.).
  "$TMPVENV/venv/bin/pip" install --upgrade pip --quiet
  "$TMPVENV/venv/bin/pip" install \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    "gux-governor==${VERSION}"
  say "installed. smoke test:"
  "$TMPVENV/venv/bin/gux" --version
  ok "TestPyPI install works"
  rm -rf "$TMPVENV"
fi
echo

# ─── Step 7: real PyPI upload ─────────────────────────────────────
echo "${BOLD}┌── Step 7 — Real PyPI upload ──────────────────────────${RESET}"
if [ "$DRY_RUN" = true ]; then
  warn "DRY RUN — skipping real PyPI upload"
else
  echo "  ${YELLOW}!${RESET} This is the irreversible step. PyPI does not allow"
  echo "  ${YELLOW}!${RESET} re-uploads of the same version, even after deletion."
  confirm "Upload gux-governor==${VERSION} to real PyPI?"
  say "twine upload dist/*"
  twine upload dist/*
  ok "published: https://pypi.org/project/gux-governor/${VERSION}/"
fi
echo

# ─── Step 8: git tag ──────────────────────────────────────────────
echo "${BOLD}┌── Step 8 — Git tag ───────────────────────────────────${RESET}"
TAG="v${VERSION}"
if git rev-parse "$TAG" >/dev/null 2>&1; then
  warn "tag $TAG already exists locally — skipping"
else
  say "git tag -a $TAG -m 'gux-governor $VERSION'"
  if [ "$DRY_RUN" = true ]; then
    warn "DRY RUN — would tag + push"
  else
    git tag -a "$TAG" -m "gux-governor $VERSION"
    git push origin "$TAG"
    ok "tagged + pushed"
  fi
fi
echo

# ─── Step 9: GitHub release notes excerpt ─────────────────────────
echo "${BOLD}┌── Step 9 — GitHub release notes ──────────────────────${RESET}"
say "release-notes excerpt for https://github.com/StellarRequiem/GUX/releases/new?tag=$TAG"
echo
echo "${DIM}────── COPY EVERYTHING BELOW ──────${RESET}"
awk -v ver="$VERSION" '
  $0 ~ "^## \\[" ver "\\]" { capture=1; next }
  capture && /^## \[/ { exit }
  capture { print }
' CHANGELOG.md
echo "${DIM}────── COPY EVERYTHING ABOVE ──────${RESET}"
echo

# ─── Done ─────────────────────────────────────────────────────────
if [ "$DRY_RUN" = true ]; then
  ok "DRY RUN complete — no changes made to PyPI or git remote"
else
  ok "${BOLD}gux-governor ${VERSION} released${RESET}"
  echo
  echo "  ${DIM}▸${RESET} PyPI:    https://pypi.org/project/gux-governor/${VERSION}/"
  echo "  ${DIM}▸${RESET} GitHub:  https://github.com/StellarRequiem/GUX/releases/new?tag=${TAG}"
  echo "  ${DIM}▸${RESET} Install: pip install gux-governor==${VERSION}"
fi
