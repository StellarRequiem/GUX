"""Layer 4 — CLI tests.

Each `gux <subcommand>` gets:
  * a happy-path test (exit 0, expected stdout)
  * one test per documented error path (exit code + stderr message)

We call `main(argv=[...])` directly — argparse parses our list, dispatches
to the right cmd_*, and we capture stdout/stderr via pytest's capsys.
License-touching commands run under monkeypatch'd XDG_CONFIG_HOME so they
don't pollute the operator's real ~/.config/gux/license.json.

Exit code contract (pinned here):
  0  → success
  1  → user error (bad input, missing file, malformed key)
  2  → real failure (license check failed, chain broken, dispatch refused)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from gux import cli


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch) -> Path:
    """Redirect license file location."""
    cfg = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    return cfg / "gux"


@pytest.fixture
def workdir(tmp_path, monkeypatch) -> Path:
    """A clean workdir for init/dispatch/verify tests. chdir into it so
    relative defaults like ./constitution.yaml resolve to tmp_path."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def initialized_workdir(workdir, isolated_config_dir) -> Path:
    """Workdir with constitution.yaml + empty audit_chain.jsonl already
    written. For commands that need a real constitution to run against."""
    cli.main(["init"])
    return workdir


# ─────────────────────────────────────────────────────────────────────────
# `gux init`
# ─────────────────────────────────────────────────────────────────────────


class TestInit:
    def test_init_writes_constitution_and_audit_files(self, workdir, capsys):
        rc = cli.main(["init"])
        assert rc == 0
        assert (workdir / "constitution.yaml").exists()
        assert (workdir / "audit_chain.jsonl").exists()
        out = capsys.readouterr().out
        assert "wrote" in out
        assert "next: gux serve" in out

    def test_init_with_custom_path(self, tmp_path, capsys):
        target = tmp_path / "my-project"
        rc = cli.main(["init", "--path", str(target)])
        assert rc == 0
        assert (target / "constitution.yaml").exists()

    def test_init_refuses_to_overwrite_existing(self, workdir, capsys):
        cli.main(["init"])  # first one succeeds
        capsys.readouterr()  # drain
        rc = cli.main(["init"])  # second should refuse
        assert rc == 1
        err = capsys.readouterr().err
        assert "refusing to overwrite" in err
        assert "--force" in err

    def test_init_force_overwrites(self, workdir, capsys):
        cli.main(["init"])
        original = (workdir / "constitution.yaml").read_text()
        # Mutate then force-overwrite
        (workdir / "constitution.yaml").write_text("# mutated")
        capsys.readouterr()
        rc = cli.main(["init", "--force"])
        assert rc == 0
        # Restored to the canonical example.
        assert (workdir / "constitution.yaml").read_text() == original

    def test_init_constitution_is_loadable_yaml(self, workdir):
        """The example constitution.yaml must parse and contain the
        minimum fields downstream gates expect."""
        cli.main(["init"])
        import yaml
        data = yaml.safe_load((workdir / "constitution.yaml").read_text())
        assert "agents" in data
        assert "policies" in data
        assert "my-agent-01" in data["agents"]


# ─────────────────────────────────────────────────────────────────────────
# `gux activate <key>`
# ─────────────────────────────────────────────────────────────────────────


class TestActivate:
    def test_valid_key_exits_zero(self, isolated_config_dir, capsys):
        rc = cli.main(["activate", "gux_pro_validCLIkey1234"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "activated" in out
        assert "Pro plan" in out

    def test_valid_key_persists_to_disk(self, isolated_config_dir):
        cli.main(["activate", "gux_hobby_cliPersistTest12"])
        license_file = isolated_config_dir / "license.json"
        assert license_file.exists()
        data = json.loads(license_file.read_text())
        assert data["plan"] == "hobby"

    def test_malformed_key_exits_one(self, isolated_config_dir, capsys):
        rc = cli.main(["activate", "totally_wrong_shape"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "malformed" in err.lower()


# ─────────────────────────────────────────────────────────────────────────
# `gux license`
# ─────────────────────────────────────────────────────────────────────────


class TestLicenseCmd:
    def test_paid_license_exits_zero(self, isolated_config_dir, capsys):
        cli.main(["activate", "gux_pro_licenseCmdTest12"])
        capsys.readouterr()
        rc = cli.main(["license"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "plan:    pro" in out
        assert "Pro plan" in out

    def test_trial_within_window_exits_zero(self, isolated_config_dir, capsys):
        cli.main(["trial"])
        capsys.readouterr()
        rc = cli.main(["license"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "plan:    trial" in out

    def test_expired_trial_exits_two(self, isolated_config_dir, capsys):
        """A license check that returns ok=False exits with code 2.
        Simulate by writing an expired trial license directly."""
        isolated_config_dir.mkdir(parents=True)
        (isolated_config_dir / "license.json").write_text(
            json.dumps({
                "plan": "trial",
                "key": "gux_trial_expiredTrial1",
                # 8 days ago, past the 7-day window.
                "activated_at": time.time() - (8 * 86400),
            })
        )
        rc = cli.main(["license"])
        assert rc == 2

    def test_license_truncates_key_for_display(self, isolated_config_dir, capsys):
        """Privacy / readability: full key isn't dumped to stdout."""
        long_key = "gux_pro_thisIsAVeryLongLicenseKey1234567890"
        cli.main(["activate", long_key])
        capsys.readouterr()
        cli.main(["license"])
        out = capsys.readouterr().out
        # First 20 chars only, then ellipsis.
        assert long_key[:20] in out
        assert long_key not in out  # full key NOT in output
        assert "…" in out


# ─────────────────────────────────────────────────────────────────────────
# `gux trial`
# ─────────────────────────────────────────────────────────────────────────


class TestTrialCmd:
    def test_trial_creates_license_file(self, isolated_config_dir, capsys):
        rc = cli.main(["trial"])
        assert rc == 0
        assert (isolated_config_dir / "license.json").exists()
        out = capsys.readouterr().out
        assert "trial started" in out
        assert "7 days" in out

    def test_trial_can_run_twice(self, isolated_config_dir, capsys):
        """No 'already trialed' check — re-running mints a fresh trial.
        Whether that's intended is a product decision; pinning current
        behavior so any future hardening surfaces as a regression."""
        cli.main(["trial"])
        capsys.readouterr()
        rc = cli.main(["trial"])
        assert rc == 0


# ─────────────────────────────────────────────────────────────────────────
# `gux serve` — only the error paths (we don't bind a real port in tests)
# ─────────────────────────────────────────────────────────────────────────


class TestServe:
    def test_missing_constitution_exits_one(self, workdir, capsys):
        rc = cli.main([
            "serve",
            "--constitution", str(workdir / "does-not-exist.yaml"),
        ])
        assert rc == 1
        err = capsys.readouterr().err
        assert "constitution not found" in err
        assert "gux init" in err

    def test_serve_bind_failure_exits_one(
        self, initialized_workdir, monkeypatch, capsys
    ):
        """If serve() raises OSError (bind failure, port in use), CLI
        returns 1 with a clear message — not a stacktrace."""
        from gux import server as server_mod

        def fail_to_bind(*args, **kwargs):
            raise OSError("[Errno 48] Address already in use")

        monkeypatch.setattr(server_mod, "serve", fail_to_bind)
        # cli imports `from gux.server import serve` — re-monkeypatch there
        # since that's the binding the cmd_serve uses.
        monkeypatch.setattr(cli, "serve", fail_to_bind)

        rc = cli.main([
            "serve",
            "--constitution", str(initialized_workdir / "constitution.yaml"),
        ])
        assert rc == 1
        err = capsys.readouterr().err
        assert "could not bind" in err
        assert "Address already in use" in err

    def test_serve_happy_path_calls_serve_with_governor(
        self, initialized_workdir, monkeypatch
    ):
        """When constitution exists, cmd_serve constructs a Governor +
        calls serve(governor, ...). Mock serve so the test doesn't block."""
        calls = []

        def fake_serve(governor, host, port):
            calls.append((governor, host, port))

        monkeypatch.setattr(cli, "serve", fake_serve)
        rc = cli.main([
            "serve",
            "--constitution", str(initialized_workdir / "constitution.yaml"),
            "--port", "9999",
        ])
        assert rc == 0
        assert len(calls) == 1
        _, host, port = calls[0]
        assert port == 9999


# ─────────────────────────────────────────────────────────────────────────
# `gux verify`
# ─────────────────────────────────────────────────────────────────────────


class TestVerify:
    def test_empty_chain_verifies(self, initialized_workdir, capsys):
        """`gux init` creates an empty audit_chain.jsonl. verify() returns
        ok=True on empty chain → exit 0."""
        rc = cli.main([
            "verify",
            "--audit", str(initialized_workdir / "audit_chain.jsonl"),
        ])
        assert rc == 0

    def test_nonexistent_chain_verifies(self, workdir, capsys):
        """verify() on a missing chain file returns ok=True with 'chain
        empty' — explicit behavior in audit.py."""
        rc = cli.main([
            "verify",
            "--audit", str(workdir / "doesnt-exist.jsonl"),
        ])
        assert rc == 0

    def test_corrupted_chain_exits_two(self, workdir, capsys):
        """A chain with a hash mismatch returns ok=False → exit 2."""
        chain_path = workdir / "broken.jsonl"
        # Write two valid-looking entries but with a wrong prev_hash on #2.
        chain_path.write_text(
            json.dumps({
                "seq": 1,
                "timestamp": "2026-01-01T00:00:00.000Z",
                "event_type": "test",
                "event_data": {},
                "prev_hash": "0" * 64,
                "entry_hash": "deadbeef" * 8,
            }) + "\n" +
            json.dumps({
                "seq": 2,
                "timestamp": "2026-01-01T00:00:01.000Z",
                "event_type": "test",
                "event_data": {},
                "prev_hash": "0" * 64,   # WRONG — should chain to entry 1
                "entry_hash": "feedface" * 8,
            }) + "\n"
        )
        rc = cli.main(["verify", "--audit", str(chain_path)])
        assert rc == 2
        err = capsys.readouterr().out
        # The mismatch message goes to stdout (cli prints with '✕ ' prefix).
        assert "mismatch" in err.lower()


# ─────────────────────────────────────────────────────────────────────────
# `gux dispatch <payload>`
# ─────────────────────────────────────────────────────────────────────────


class TestDispatch:
    def _payload(self, **overrides) -> str:
        body = {
            "instance_id": "my-agent-01",
            "tool_name": "memory_recall",
            "args": {"query": "hi"},
            "session_id": "cli-sess-1",
            **overrides,
        }
        return json.dumps(body)

    def test_go_dispatch_exits_zero(self, initialized_workdir, capsys):
        rc = cli.main([
            "dispatch",
            self._payload(),
            "--constitution", str(initialized_workdir / "constitution.yaml"),
            "--audit", str(initialized_workdir / "audit_chain.jsonl"),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "verdict:     GO" in out
        # Trace includes all 12 gates, each prefixed with a marker.
        assert "HardwareQuarantine" in out
        assert "PostureGate" in out

    def test_refuse_dispatch_exits_two(self, initialized_workdir, capsys):
        rc = cli.main([
            "dispatch",
            self._payload(tool_name="does_not_exist"),
            "--constitution", str(initialized_workdir / "constitution.yaml"),
            "--audit", str(initialized_workdir / "audit_chain.jsonl"),
        ])
        assert rc == 2
        out = capsys.readouterr().out
        assert "verdict:     REFUSE" in out
        assert "reason: unknown_tool" in out

    def test_bad_json_exits_one(self, initialized_workdir, capsys):
        rc = cli.main([
            "dispatch",
            "not valid json {{",
            "--constitution", str(initialized_workdir / "constitution.yaml"),
            "--audit", str(initialized_workdir / "audit_chain.jsonl"),
        ])
        assert rc == 1
        err = capsys.readouterr().err
        assert "bad JSON payload" in err


# ─────────────────────────────────────────────────────────────────────────
# `gux --version` + global args
# ─────────────────────────────────────────────────────────────────────────


class TestVersionFlag:
    def test_version_flag_prints_version(self, capsys):
        """--version is argparse-handled; raises SystemExit(0)."""
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["--version"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "gux 0.5.0" in out


class TestUnknownSubcommand:
    def test_unknown_subcommand_exits_two(self, capsys):
        """argparse exits 2 on unknown subcommand."""
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["nonexistent-command"])
        assert excinfo.value.code == 2

    def test_no_subcommand_exits_two(self, capsys):
        """`gux` with no subcommand fails — required=True on the
        subparsers."""
        with pytest.raises(SystemExit) as excinfo:
            cli.main([])
        assert excinfo.value.code == 2
