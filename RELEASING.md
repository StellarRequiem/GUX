# Releasing G.UX (`gux-governor`) to PyPI

This document describes the release procedure for the `gux-governor`
PyPI package. The accompanying `release.sh` script automates the
mechanical steps; this doc captures the *why* and the one-time setup
that has to happen outside the script.

## One-time setup (you, not the script)

PyPI requires a real account and an API token. I cannot create these
on your behalf — security rules — so this part is yours.

1. **Create a PyPI account** at <https://pypi.org/account/register/>.
   Use a strong password; PyPI requires 2FA for any account that has
   uploaded a project, so enable an authenticator-app TOTP now.

2. **Create a TestPyPI account** at <https://test.pypi.org/account/register/>.
   TestPyPI is a separate sandbox with its own user database — registering
   on real PyPI does NOT register you on TestPyPI. We use it for
   smoke-testing every release before pushing to real PyPI.

3. **Generate two API tokens**, scoped to the `gux-governor` project once
   it exists (initial release uses scope "Entire account" because the
   project doesn't exist yet):

   - <https://pypi.org/manage/account/token/> — for `release.sh upload`
   - <https://test.pypi.org/manage/account/token/> — for `release.sh testpypi`

   Save them somewhere safe. PyPI shows them once.

4. **Configure your local `~/.pypirc`** by copying `.pypirc.example`
   from this repo and pasting your real tokens:

   ```
   cp .pypirc.example ~/.pypirc
   chmod 600 ~/.pypirc
   # edit ~/.pypirc, replace `<paste real token>` with each token
   ```

   The `chmod 600` matters — `~/.pypirc` contains write-credentials
   for PyPI, and any other process on your machine reading it is the
   same as that process being able to publish poisoned `gux-governor`
   wheels in your name. Lock it down.

5. **Install build tooling** in a dedicated venv (don't pollute your
   system Python):

   ```
   python -m venv ~/.venvs/gux-release
   ~/.venvs/gux-release/bin/pip install --upgrade pip build twine
   ```

After one-time setup is complete, every future release is just:

```
./release.sh
```

## What `release.sh` does, step by step

Each step prints what it's about to do, then asks you to confirm
before continuing. Aborting at any prompt leaves the working tree
clean — no half-publish state.

1. **Pre-flight check.** Refuses to release if:
   - The working tree has uncommitted changes (`git status -s` non-empty).
   - The local branch isn't `main`.
   - The local branch isn't in sync with `origin/main` (you have unpushed
     commits, or origin has commits you don't).
   - The HEAD doesn't have a CI green status (warning only, not fatal —
     you can override with `--force` if you know what you're doing).

2. **Version sanity.** Reads the version from `pyproject.toml`'s
   `[project] version`. Confirms it doesn't already exist on PyPI
   (PyPI refuses re-upload of an existing version, so this catches
   "forgot to bump version" before we waste time building).

3. **Clean build artifacts.** `rm -rf build/ dist/ *.egg-info/` so the
   wheel build starts from a clean tree. Stops setuptools from picking
   up stale metadata.

4. **Build sdist + wheel** with `python -m build`. Produces:
   - `dist/gux_governor-X.Y.Z.tar.gz` (sdist)
   - `dist/gux_governor-X.Y.Z-py3-none-any.whl` (wheel)

5. **Twine check.** `twine check dist/*` validates that the wheel/sdist
   metadata is well-formed and PyPI will accept it. Catches things like
   README rendering errors and missing license markers.

6. **TestPyPI upload + smoke install.** Uploads to TestPyPI, then in a
   fresh venv: `pip install --index-url https://test.pypi.org/simple/
   gux-governor==X.Y.Z`, then `gux --version`. Validates the package
   is fetch-able and the CLI entry point works.

7. **Real PyPI upload.** With confirmation prompt. Once this lands,
   the version is permanent — PyPI refuses re-upload of an existing
   version even after you delete it.

8. **Git tag.** Creates `vX.Y.Z` tag locally, pushes to `origin`.
   The tag matches the URL in CHANGELOG.md's `[X.Y.Z]:` link.

9. **GitHub Release.** Currently a manual step. The script prints a
   suggested release-notes excerpt (the latest CHANGELOG.md section)
   for you to paste into <https://github.com/StellarRequiem/GUX/releases/new>.

## Version bumping conventions

Follow [Semantic Versioning](https://semver.org/):

- **0.5.0 → 0.5.1** — patch. Bug fixes, doc improvements, internal
  refactors that don't change the API.
- **0.5.0 → 0.6.0** — minor. New features, new public API surface,
  *additive* changes that don't break existing integrators.
- **0.5.0 → 1.0.0** — major. Breaking changes. Existing integrators
  must read the migration notes.

While the public API surface is still small and we have no external
integrators, we'll be liberal with minor-version bumps when adding
gate types, sidecar endpoints, or constitution schema additions.
After v1.0.0 (when external integrators exist) we'll be conservative.

## Yanking a release

If a release goes out with a critical bug:

```
twine yank gux-governor==X.Y.Z --comment "Critical bug in PostureOverride; use X.Y.Z+1"
```

Yanking does NOT delete the version — it stays available for `pip
install gux-governor==X.Y.Z` (explicit pin) but new resolutions skip
it. This is the right move 99% of the time; deletion breaks anyone
pinned to that version.

PyPI's policy on deletion is "very rarely, only for legal reasons."
Treat every push as permanent.

## What lives in this repo vs. what doesn't

In the repo:
- `pyproject.toml` — package metadata
- `LICENSE`, `NOTICE`, `README.md`, `CHANGELOG.md` — distribution-included
- `release.sh` — the automation
- `RELEASING.md` (this file) — the runbook
- `.pypirc.example` — credentials template

NOT in the repo:
- `~/.pypirc` (gitignored — contains real PyPI tokens)
- `dist/` (gitignored — build artifacts, regenerated each release)
- `build/` (gitignored — setuptools temp)
- `*.egg-info/` (gitignored — setuptools temp)
