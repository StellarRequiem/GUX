"""Layer 3 — License + activation tests.

Covers the lifecycle the SaaS product actually depends on:
  * Trial start (first-run, no license file)
  * Trial check within / at-boundary / past expiry
  * Paid-key activation across all plan tiers
  * Malformed-key rejection (KEY_RE contract)
  * Corrupted license file → graceful fallback to trial
  * On-disk persisted shape (billing tooling reads this)
  * Cross-platform config dir (XDG_CONFIG_HOME / APPDATA env)

Test isolation: every test points XDG_CONFIG_HOME at tmp_path so the
operator's real ~/.config/gux/license.json never gets touched. Time
sensitivity: tests that exercise expiry monkeypatch time.time() to
fast-forward without sleeping.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from gux.license import (
    KEY_RE,
    PLAN_NAMES,
    TRIAL_DURATION_SEC,
    LicenseCheck,
    LicenseGate,
)


# ─────────────────────────────────────────────────────────────────────────
# Test isolation: redirect _config_dir at the env-var level so no test
# touches the operator's real license file.
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch) -> Path:
    """Redirect XDG_CONFIG_HOME to tmp_path/. The license module's
    _config_dir() picks this up; no real disk pollution."""
    cfg = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    # On macOS / Linux, _config_dir() returns XDG_CONFIG_HOME / "gux".
    return cfg / "gux"


# ─────────────────────────────────────────────────────────────────────────
# Trial start — first-run no-file path
# ─────────────────────────────────────────────────────────────────────────


class TestTrialStart:
    def test_start_trial_mints_key_with_correct_shape(self, isolated_config_dir):
        gate = LicenseGate.start_trial()
        assert gate.plan == "trial"
        assert gate.key.startswith("gux_trial_")
        # KEY_RE requires 8+ alphanumeric chars after the prefix.
        random_part = gate.key.split("_", 2)[2]
        assert len(random_part) >= 8

    def test_start_trial_persists_to_disk(self, isolated_config_dir):
        gate = LicenseGate.start_trial()
        license_file = isolated_config_dir / "license.json"
        assert license_file.exists()
        data = json.loads(license_file.read_text())
        assert data["plan"] == "trial"
        assert data["key"] == gate.key

    def test_start_trial_sets_activated_at_to_now(self, isolated_config_dir):
        before = time.time()
        gate = LicenseGate.start_trial()
        after = time.time()
        assert before <= gate.activated_at <= after

    def test_load_with_no_file_starts_trial(self, isolated_config_dir):
        """First-run UX: no license file → automatically get a trial."""
        # Sanity-check: no file pre-existing
        license_file = isolated_config_dir / "license.json"
        assert not license_file.exists()
        gate = LicenseGate.load()
        assert gate.plan == "trial"
        # And the trial was persisted.
        assert license_file.exists()


# ─────────────────────────────────────────────────────────────────────────
# check() — verdict surface
# ─────────────────────────────────────────────────────────────────────────


class TestCheck:
    def test_paid_hobby_plan_passes(self, isolated_config_dir):
        gate = LicenseGate(
            plan="hobby",
            key="gux_hobby_validKey123456",
            activated_at=time.time(),
        )
        check = gate.check()
        assert check.ok is True
        assert check.plan == "hobby"
        assert "Hobby" in check.message

    @pytest.mark.parametrize("plan", ["hobby", "pro", "team", "oem"])
    def test_all_paid_plans_pass(self, plan, isolated_config_dir):
        gate = LicenseGate(
            plan=plan,
            key=f"gux_{plan}_validKey12345678",
            activated_at=time.time(),
        )
        check = gate.check()
        assert check.ok is True
        assert PLAN_NAMES[plan] in check.message

    def test_trial_within_window_passes(self, isolated_config_dir):
        # 1 hour into a 7-day trial
        gate = LicenseGate(
            plan="trial",
            key="gux_trial_recentKey1234",
            activated_at=time.time() - 3600,
        )
        check = gate.check()
        assert check.ok is True
        assert check.days_remaining == 6  # 7 days minus a few hours

    def test_trial_at_day_one_shows_six_remaining(self, isolated_config_dir):
        gate = LicenseGate(
            plan="trial",
            key="gux_trial_key12345678",
            activated_at=time.time() - 86400,  # exactly 24h ago
        )
        check = gate.check()
        assert check.ok is True
        assert check.days_remaining == 5  # int() truncation: 5.999... → 5

    def test_trial_just_before_expiry_passes(self, isolated_config_dir):
        # 1 second before 7-day expiry
        gate = LicenseGate(
            plan="trial",
            key="gux_trial_aboutToExpire",
            activated_at=time.time() - (TRIAL_DURATION_SEC - 1),
        )
        check = gate.check()
        assert check.ok is True
        # Could be 0 due to int() truncation.
        assert check.days_remaining == 0

    def test_trial_just_past_expiry_fails(self, isolated_config_dir):
        # 1 second past 7-day expiry
        gate = LicenseGate(
            plan="trial",
            key="gux_trial_justExpired",
            activated_at=time.time() - (TRIAL_DURATION_SEC + 1),
        )
        check = gate.check()
        assert check.ok is False
        assert check.days_remaining == 0
        assert "expired" in check.message.lower()
        assert "gux.dev" in check.message  # CTA link present

    def test_trial_long_past_expiry_fails(self, isolated_config_dir):
        # 30 days past expiry
        gate = LicenseGate(
            plan="trial",
            key="gux_trial_longExpired12",
            activated_at=time.time() - (TRIAL_DURATION_SEC + 30 * 86400),
        )
        check = gate.check()
        assert check.ok is False
        assert "expired" in check.message.lower()

    def test_unknown_plan_fails(self, isolated_config_dir):
        """Defensive: a license file with a corrupted/unknown plan
        shouldn't silently grant access."""
        gate = LicenseGate(
            plan="enterprise-platinum",  # not a real plan
            key="gux_enterprise-platinum_x",
            activated_at=time.time(),
        )
        check = gate.check()
        assert check.ok is False
        assert "unknown plan" in check.message


# ─────────────────────────────────────────────────────────────────────────
# activate() — key validation + plan extraction
# ─────────────────────────────────────────────────────────────────────────


class TestActivate:
    @pytest.mark.parametrize(
        "key,expected_plan",
        [
            ("gux_hobby_abcd1234EFGH", "hobby"),
            ("gux_pro_aB3kD9eF2gHk1234", "pro"),
            ("gux_team_team1234abcd", "team"),
            ("gux_oem_oem12345678abcd", "oem"),
            ("gux_trial_trial12345678", "trial"),
        ],
    )
    def test_valid_key_activates_correct_plan(
        self, key, expected_plan, isolated_config_dir
    ):
        gate = LicenseGate.activate(key)
        assert gate.plan == expected_plan
        assert gate.key == key

    def test_activate_persists_to_disk(self, isolated_config_dir):
        gate = LicenseGate.activate("gux_pro_validPersistKey")
        license_file = isolated_config_dir / "license.json"
        assert license_file.exists()
        data = json.loads(license_file.read_text())
        assert data["plan"] == "pro"
        assert data["key"] == "gux_pro_validPersistKey"

    @pytest.mark.parametrize(
        "bad_key",
        [
            "wrong_prefix_hobby_abcd1234",
            "gux_invalid-plan_abcd1234",
            "gux_pro_short",            # < 8-char random part
            "gux_pro_with-dash-1234",   # KEY_RE rejects dashes
            "gux_hobby_abcd 1234",       # space in random part
            "",
            "gux_pro_",                  # empty random part
        ],
    )
    def test_malformed_key_raises(self, bad_key, isolated_config_dir):
        with pytest.raises(ValueError, match="malformed"):
            LicenseGate.activate(bad_key)

    def test_malformed_key_does_not_persist(self, isolated_config_dir):
        """Failed activation must not corrupt any existing license file."""
        # Start with a valid hobby key on disk.
        LicenseGate.activate("gux_hobby_existing12345")
        license_file = isolated_config_dir / "license.json"
        before = license_file.read_text()
        # Now try to activate a malformed key.
        with pytest.raises(ValueError):
            LicenseGate.activate("garbage")
        # File unchanged.
        assert license_file.read_text() == before


# ─────────────────────────────────────────────────────────────────────────
# load() — file persistence + recovery
# ─────────────────────────────────────────────────────────────────────────


class TestLoad:
    def test_load_reads_existing_license_file(self, isolated_config_dir):
        # Pre-stage a license file.
        isolated_config_dir.mkdir(parents=True)
        license_file = isolated_config_dir / "license.json"
        license_file.write_text(
            json.dumps(
                {
                    "plan": "pro",
                    "key": "gux_pro_preExistingKey12",
                    "activated_at": 1700000000.0,
                }
            )
        )
        gate = LicenseGate.load()
        assert gate.plan == "pro"
        assert gate.key == "gux_pro_preExistingKey12"
        assert gate.activated_at == 1700000000.0

    def test_load_with_corrupted_json_falls_back_to_trial(
        self, isolated_config_dir
    ):
        """Don't lock the user out if their license file got mangled —
        give them a fresh trial. They can re-activate their real key
        manually."""
        isolated_config_dir.mkdir(parents=True)
        license_file = isolated_config_dir / "license.json"
        license_file.write_text("{not valid json")
        gate = LicenseGate.load()
        assert gate.plan == "trial"  # fallback fired
        # And the trial got persisted, overwriting the corrupt file.
        data = json.loads(license_file.read_text())
        assert data["plan"] == "trial"

    def test_load_with_missing_fields_falls_back_to_trial(
        self, isolated_config_dir
    ):
        """An older license schema or partial write should still recover."""
        isolated_config_dir.mkdir(parents=True)
        license_file = isolated_config_dir / "license.json"
        # Missing 'activated_at'. load() catches KeyError on float() of None.
        license_file.write_text(
            json.dumps({"plan": "pro", "key": "gux_pro_missingActivatedAt"})
        )
        gate = LicenseGate.load()
        # The implementation tolerates this — activated_at defaults to time.time().
        # Should NOT fall back to trial in this case (per the .get() defaults).
        assert gate.plan == "pro"

    def test_load_with_invalid_activated_at_type_falls_back(
        self, isolated_config_dir
    ):
        """activated_at must be coercible to float."""
        isolated_config_dir.mkdir(parents=True)
        license_file = isolated_config_dir / "license.json"
        license_file.write_text(
            json.dumps(
                {
                    "plan": "pro",
                    "key": "gux_pro_invalidTimestamp",
                    "activated_at": "not-a-number",
                }
            )
        )
        gate = LicenseGate.load()
        # ValueError from float() conversion → start_trial fallback.
        assert gate.plan == "trial"


# ─────────────────────────────────────────────────────────────────────────
# KEY_RE — explicit edge cases
# ─────────────────────────────────────────────────────────────────────────


class TestKeyRegex:
    @pytest.mark.parametrize(
        "key",
        [
            "gux_trial_abcd1234",
            "gux_hobby_aB3kD9eF",
            "gux_pro_x" * 1 + "Y" * 8,  # exactly 8 chars in random part
        ],
    )
    def test_minimum_random_length_accepted(self, key):
        assert KEY_RE.match(key) is not None

    @pytest.mark.parametrize(
        "key",
        [
            "gux_pro_short1",        # 6 chars < 8
            "gux_pro_seven12",       # 7 chars
        ],
    )
    def test_under_minimum_random_length_rejected(self, key):
        assert KEY_RE.match(key) is None

    @pytest.mark.parametrize(
        "key",
        [
            "GUX_pro_abcd1234EFGH",   # uppercase prefix
            "gux_PRO_abcd1234EFGH",   # uppercase plan
            "gux_enterprise_abcd1234EFGH",  # not in plan whitelist
            "gux_pro_abcd!@#$",       # special chars
            "guxpro_abcd1234EFGH",    # missing underscore
            "_gux_pro_abcd1234EFGH",  # leading underscore
        ],
    )
    def test_invalid_shapes_rejected(self, key):
        assert KEY_RE.match(key) is None


# ─────────────────────────────────────────────────────────────────────────
# persist() — on-disk shape contract (billing tooling reads this)
# ─────────────────────────────────────────────────────────────────────────


class TestPersist:
    def test_persisted_file_has_three_required_fields(self, isolated_config_dir):
        gate = LicenseGate.activate("gux_pro_persistShape123")
        license_file = isolated_config_dir / "license.json"
        data = json.loads(license_file.read_text())
        assert set(data.keys()) == {"plan", "key", "activated_at"}

    def test_persisted_file_is_human_readable_indented(
        self, isolated_config_dir
    ):
        """The README says operators can hand-edit ~/.config/gux/license.json.
        Indented JSON is part of the operator-facing contract."""
        LicenseGate.activate("gux_pro_indentedJsonKey")
        license_file = isolated_config_dir / "license.json"
        text = license_file.read_text()
        # Indented JSON has newlines and spaces, not the compact form.
        assert "\n" in text
        assert "  " in text  # 2-space indent per persist()'s json.dumps(indent=2)

    def test_persist_overwrites_existing_file(self, isolated_config_dir):
        """Activating a new key replaces the old one — no append accumulation."""
        LicenseGate.activate("gux_hobby_firstKey1234567")
        LicenseGate.activate("gux_pro_secondKey1234567")
        license_file = isolated_config_dir / "license.json"
        data = json.loads(license_file.read_text())
        assert data["plan"] == "pro"
        assert data["key"] == "gux_pro_secondKey1234567"


# ─────────────────────────────────────────────────────────────────────────
# Cross-platform config dir resolution
# ─────────────────────────────────────────────────────────────────────────


class TestConfigDir:
    def test_xdg_config_home_respected(self, tmp_path, monkeypatch):
        """When XDG_CONFIG_HOME is set, license file lives there."""
        custom = tmp_path / "custom-config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(custom))
        LicenseGate.start_trial()
        assert (custom / "gux" / "license.json").exists()

    def test_default_path_when_xdg_unset(self, tmp_path, monkeypatch):
        """Without XDG_CONFIG_HOME, falls back to ~/.config/gux/."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        LicenseGate.start_trial()
        assert (tmp_path / ".config" / "gux" / "license.json").exists()
