"""Layer 5 — End-to-end install test.

The truest "did the customer's first 10 seconds work" test. Runs
`install-gux.command` in a subprocess with isolated GUX_HOME +
XDG_CONFIG_HOME + HOME, then verifies every artifact the install
promised to create, then exercises the installed `gux` CLI directly
against the installed venv.

Slower than other layers — a real pip install of the local source
tree takes 5-10s — so the install runs ONCE per session via the
shared `install_session` fixture. Per-test we read artifacts + run
sub-commands against the same installed state.

Tests are skipped if pip can't reach PyPI for the pyyaml install
(common in air-gapped CI / sandboxed envs).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib import error, request

import pytest


PACKAGE_DIR = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = PACKAGE_DIR / "install-gux.command"


# ─────────────────────────────────────────────────────────────────────────
# Session-scoped install fixture — run install ONCE, share artifacts.
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def install_session(tmp_path_factory):
    """Run install-gux.command in a fully-isolated env. Returns a dict
    of paths the install produced for downstream tests to verify.

    Source-copy guard: setuptools writes PKG-INFO + .egg-info/ into the
    source dir during wheel build. If the source dir is on a read-only
    or FUSE-permission-restricted filesystem (test sandboxes, mounted
    overlay), the install fails with 'Operation not permitted: PKG-INFO'.
    Sidestep by copying the source tree to a writable tmp location and
    pointing the installer at the copy. The customer-side reality (a
    real Mac with the package downloaded) hits a normal filesystem so
    this isn't an issue in production; it's a sandbox affordance only.
    """
    base = tmp_path_factory.mktemp("gux-e2e")
    gux_home = base / "gux-home"
    fake_home = base / "fake-home"
    fake_home_desktop = fake_home / "Desktop"
    fake_home_desktop.mkdir(parents=True)
    xdg_config = base / "xdg-config"
    xdg_config.mkdir(parents=True)

    # Copy the source tree to a writable location so setuptools can
    # write PKG-INFO during the wheel build.
    source_copy = base / "package-src"
    shutil.copytree(
        PACKAGE_DIR,
        source_copy,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.egg-info",
            ".pytest_cache",
            "tests",
            "build",
            "dist",
            ".venv",
            "venv",
        ),
    )
    install_script = source_copy / "install-gux.command"
    # The script's `set -euo pipefail` + executable bit must survive
    # the copy; copytree preserves mode by default but make sure.
    os.chmod(install_script, 0o755)

    env = {
        **os.environ,
        "GUX_HOME": str(gux_home),
        "HOME": str(fake_home),
        "XDG_CONFIG_HOME": str(xdg_config),
        # Keep terminal colors out of captured output.
        "TERM": "dumb",
    }

    result = subprocess.run(
        ["bash", str(install_script)],
        env=env,
        cwd=str(source_copy),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,  # makes the trap's `read -n 1 -s` exit on EOF
        timeout=180,
    )

    artifacts = {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "gux_home": gux_home,
        "fake_home": fake_home,
        "xdg_config": xdg_config,
        "venv": gux_home / ".venv",
        "gux_bin": gux_home / ".venv" / "bin" / "gux",
        "constitution": gux_home / "constitution.yaml",
        "audit": gux_home / "audit_chain.jsonl",
        "license": xdg_config / "gux" / "license.json",
        "desktop_launcher": fake_home_desktop / "launch-gux.command",
    }

    # If the install can't reach PyPI (pyyaml fetch fails), skip all
    # L5 tests rather than failing them — this is a network-availability
    # signal, not a code defect.
    if result.returncode != 0 and "pyyaml" in result.stderr.lower():
        pytest.skip(
            "pip install pyyaml failed — environment can't reach PyPI; "
            "this is a network availability issue, not a code defect"
        )

    return artifacts


# ─────────────────────────────────────────────────────────────────────────
# Install-completed assertions — these all read from install_session.
# ─────────────────────────────────────────────────────────────────────────


class TestInstallCompletes:
    def test_install_exits_zero(self, install_session):
        assert install_session["returncode"] == 0, (
            f"install failed.\nstdout:\n{install_session['stdout']}\n"
            f"stderr:\n{install_session['stderr']}"
        )

    def test_install_announces_each_stage(self, install_session):
        """Operator UX: every stage prints a success marker. If any
        future refactor silently drops a stage, this test catches it."""
        out = install_session["stdout"]
        # Strip ANSI escape codes so the assertions are robust.
        import re
        out = re.sub(r"\x1b\[[0-9;]*m", "", out)
        for marker in [
            "Python",
            "GUX_HOME",
            "virtualenv ready",
            "gux-governor installed",
            "constitution",
            "trial license active",
            "launcher dropped",
        ]:
            assert marker in out, f"install output missing '{marker}'\n---\n{out}"


class TestInstallArtifacts:
    def test_venv_created(self, install_session):
        assert install_session["venv"].is_dir()
        assert (install_session["venv"] / "bin" / "python").exists()

    def test_gux_executable_installed(self, install_session):
        gux = install_session["gux_bin"]
        assert gux.exists()
        assert os.access(gux, os.X_OK), "gux binary not executable"

    def test_constitution_written(self, install_session):
        const = install_session["constitution"]
        assert const.exists()
        # Loadable YAML with the example agent.
        text = const.read_text()
        assert "my-agent-01" in text
        assert "constitution_tools" in text

    def test_audit_chain_file_present(self, install_session):
        """gux init creates an empty audit_chain.jsonl; verify it
        exists and is empty (or near-empty)."""
        chain = install_session["audit"]
        assert chain.exists()
        # Empty or near-empty — the install itself doesn't dispatch.
        assert chain.stat().st_size < 1024

    def test_license_file_with_trial_plan(self, install_session):
        lic = install_session["license"]
        assert lic.exists()
        data = json.loads(lic.read_text())
        assert data["plan"] == "trial"
        assert data["key"].startswith("gux_trial_")
        assert "activated_at" in data

    def test_desktop_launcher_dropped(self, install_session):
        launcher = install_session["desktop_launcher"]
        assert launcher.exists()
        assert os.access(launcher, os.X_OK)

    def test_desktop_launcher_references_correct_paths(self, install_session):
        """The launcher script must reference the same GUX_HOME the
        install used — otherwise double-clicking it after install
        wouldn't find the right files."""
        launcher_text = install_session["desktop_launcher"].read_text()
        assert str(install_session["gux_home"]) in launcher_text
        assert str(install_session["venv"]) in launcher_text


# ─────────────────────────────────────────────────────────────────────────
# Post-install CLI smoke — invoke the installed gux against the install.
# ─────────────────────────────────────────────────────────────────────────


def _run_gux(install_session, args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "GUX_HOME": str(install_session["gux_home"]),
        "HOME": str(install_session["fake_home"]),
        "XDG_CONFIG_HOME": str(install_session["xdg_config"]),
        "TERM": "dumb",
    }
    return subprocess.run(
        [str(install_session["gux_bin"]), *args],
        env=env,
        capture_output=True,
        text=True,
        input=stdin.decode() if stdin else None,
        timeout=30,
    )


class TestPostInstallCli:
    def test_gux_version(self, install_session):
        r = _run_gux(install_session, ["--version"])
        assert r.returncode == 0
        assert "gux 0.5.0" in r.stdout

    def test_gux_license_shows_trial(self, install_session):
        r = _run_gux(install_session, ["license"])
        assert r.returncode == 0
        assert "trial" in r.stdout.lower()
        assert "remaining" in r.stdout.lower()

    def test_gux_verify_empty_chain_ok(self, install_session):
        r = _run_gux(install_session, [
            "verify",
            "--audit", str(install_session["audit"]),
        ])
        assert r.returncode == 0

    def test_gux_dispatch_against_real_install(self, install_session):
        """The headline use case: a customer just installed, fires
        their first dispatch, expects to see GO + a 12-gate trace."""
        payload = json.dumps({
            "instance_id": "my-agent-01",
            "tool_name": "memory_recall",
            "args": {"query": "test"},
            "session_id": "e2e-session-1",
        })
        r = _run_gux(install_session, [
            "dispatch",
            payload,
            "--constitution", str(install_session["constitution"]),
            "--audit", str(install_session["audit"]),
        ])
        assert r.returncode == 0, (
            f"dispatch failed.\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert "verdict:     GO" in r.stdout
        # Trace shows the 12 gates fired.
        assert "PostureGate" in r.stdout

    def test_dispatch_writes_audit_chain(self, install_session):
        """After a dispatch, the audit chain should have entries."""
        payload = json.dumps({
            "instance_id": "my-agent-01",
            "tool_name": "memory_recall",
            "args": {"query": "audit-test"},
            "session_id": "e2e-audit-1",
        })
        _run_gux(install_session, [
            "dispatch",
            payload,
            "--constitution", str(install_session["constitution"]),
            "--audit", str(install_session["audit"]),
        ])
        # Chain file should now have at least 2 entries (dispatched + succeeded).
        chain_text = install_session["audit"].read_text()
        # Empty lines stripped.
        entries = [l for l in chain_text.splitlines() if l.strip()]
        assert len(entries) >= 2
        types = [json.loads(l)["event_type"] for l in entries]
        assert "tool_call_dispatched" in types
        assert "tool_call_succeeded" in types


# ─────────────────────────────────────────────────────────────────────────
# Sidecar end-to-end — start the real installed sidecar, hit it via HTTP.
# ─────────────────────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestSidecarE2E:
    def test_real_sidecar_serves_dispatch(self, install_session):
        """Boot the real installed gux serve in a subprocess, POST to
        /v1/dispatch, verify the response. Tear down cleanly."""
        port = _free_port()
        env = {
            **os.environ,
            "GUX_HOME": str(install_session["gux_home"]),
            "HOME": str(install_session["fake_home"]),
            "XDG_CONFIG_HOME": str(install_session["xdg_config"]),
            "TERM": "dumb",
        }
        proc = subprocess.Popen(
            [
                str(install_session["gux_bin"]),
                "serve",
                "--constitution", str(install_session["constitution"]),
                "--audit", str(install_session["audit"]),
                "--port", str(port),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            # Wait for the bind — poll healthz instead of fixed sleep.
            # 5s was too tight on macOS GitHub runners (Python cold-start
            # + pip-installed-entry-point spawn + bind can take 8-10s on
            # a stressed runner — observed in CI run 487a1f5). 20s gives
            # generous headroom on CI while still keeping the test
            # responsive locally — a healthy bind completes in well under
            # 1s, so we exit the loop early.
            base = f"http://127.0.0.1:{port}"
            bind_timeout_s = 20
            deadline = time.time() + bind_timeout_s
            ready = False
            while time.time() < deadline:
                try:
                    with request.urlopen(f"{base}/healthz", timeout=0.5) as resp:
                        if resp.status == 200:
                            ready = True
                            break
                except (error.URLError, ConnectionResetError):
                    time.sleep(0.1)
            assert ready, f"real sidecar didn't bind within {bind_timeout_s}s"

            # POST a real dispatch.
            payload = json.dumps({
                "instance_id": "my-agent-01",
                "tool_name": "memory_recall",
                "args": {"query": "from-real-sidecar"},
                "session_id": "real-sidecar-1",
            }).encode()
            req = request.Request(
                f"{base}/v1/dispatch",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=3) as resp:
                body = json.loads(resp.read().decode())
            assert body["verdict"] == "GO"
            assert len(body["trace"]) == 12

            # Chain verify endpoint reports ok.
            with request.urlopen(f"{base}/v1/audit/verify", timeout=3) as resp:
                verify = json.loads(resp.read().decode())
            assert verify["ok"] is True
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
