"""License & 7-day trial gate.

A G.UX license key is the user's *proprietary local-only* credential:
no network call, no phone-home, no telemetry. The key + activation
state lives at ~/.config/gux/license.json (or %APPDATA%\\gux\\license.json
on Windows). The kernel reads it once at construction.

Key shapes:
  gux_trial_<random>     — 7-day trial; activation date stored locally
  gux_hobby_<random>     — paid Hobby plan
  gux_pro_<random>       — paid Pro plan
  gux_team_<random>      — paid Team plan
  gux_oem_<random>       — OEM redistribution

This module DELIBERATELY does NOT enforce keys against a remote server.
The user owns the license file. We provide enough structure that a
billing integration can later validate against an issuer signature
without changing the kernel ABI.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

# Trial duration — 7 days in seconds.
TRIAL_DURATION_SEC = 7 * 24 * 60 * 60

PLAN_NAMES = {
    "trial": "Trial",
    "hobby": "Hobby",
    "pro": "Pro",
    "team": "Team",
    "oem": "OEM",
}

KEY_RE = re.compile(r"^gux_(trial|hobby|pro|team|oem)_[A-Za-z0-9]{8,}$")


def _config_dir() -> Path:
    """Cross-platform config directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "gux"


def _license_path() -> Path:
    return _config_dir() / "license.json"


@dataclass
class LicenseCheck:
    ok: bool
    plan: str = ""
    message: str = ""
    days_remaining: int | None = None


@dataclass
class LicenseGate:
    """Lazy license file reader."""

    plan: str
    """trial | hobby | pro | team | oem"""

    key: str
    """The raw key string."""

    activated_at: float
    """Unix timestamp."""

    @classmethod
    def load(cls) -> "LicenseGate":
        """Load from disk. Returns a fresh trial if no license file
        exists yet — first-run trial activation is automatic."""
        path = _license_path()
        if not path.exists():
            return cls.start_trial()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                plan=data.get("plan", "trial"),
                key=data.get("key", ""),
                activated_at=float(data.get("activated_at", time.time())),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            # corrupted license — fall back to a fresh trial rather than
            # locking the user out of their own machine.
            return cls.start_trial()

    @classmethod
    def start_trial(cls) -> "LicenseGate":
        """Mint a fresh 7-day trial and write it to disk."""
        key = "gux_trial_" + secrets.token_urlsafe(12).replace("_", "").replace("-", "")[:16]
        gate = cls(plan="trial", key=key, activated_at=time.time())
        gate.persist()
        return gate

    @classmethod
    def activate(cls, key: str) -> "LicenseGate":
        """Activate a paid key. Validates the shape; does NOT phone home."""
        if not KEY_RE.match(key):
            raise ValueError(
                f"License key looks malformed. Expected shape: "
                f"gux_<plan>_<random>. Got: {key[:24]}…"
            )
        plan = key.split("_", 2)[1]
        gate = cls(plan=plan, key=key, activated_at=time.time())
        gate.persist()
        return gate

    def persist(self) -> None:
        path = _license_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "plan": self.plan,
                    "key": self.key,
                    "activated_at": self.activated_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def check(self) -> LicenseCheck:
        """Return a structured verdict the dispatcher can act on."""
        if self.plan in ("hobby", "pro", "team", "oem"):
            return LicenseCheck(
                ok=True,
                plan=self.plan,
                message=f"{PLAN_NAMES[self.plan]} plan · active",
            )
        if self.plan == "trial":
            elapsed = time.time() - self.activated_at
            days_remaining = int((TRIAL_DURATION_SEC - elapsed) / 86400)
            if elapsed > TRIAL_DURATION_SEC:
                return LicenseCheck(
                    ok=False,
                    plan="trial",
                    message=(
                        "7-day trial expired. Activate a paid key with "
                        "`gux activate <key>` or visit "
                        "https://gux.dev/pricing"
                    ),
                    days_remaining=0,
                )
            return LicenseCheck(
                ok=True,
                plan="trial",
                message=f"Trial · {days_remaining} day(s) remaining",
                days_remaining=days_remaining,
            )
        return LicenseCheck(
            ok=False, plan=self.plan, message=f"unknown plan: {self.plan}"
        )

    @property
    def display_path(self) -> str:
        return str(_license_path())
