# Changelog

All notable changes to G.UX (`gux-governor`) will be documented here.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
and follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

## [0.5.0] — 2026-05-20

Initial public release. Drop-in governance kernel for LLM tool dispatch:
twelve gate pipeline, hash-linked audit chain, HTTP sidecar, CLI, license-gated
trial / hobby / pro / team / oem tiers.

### Added

- **Twelve-gate governance pipeline.** Every tool dispatch passes through
  `HardwareQuarantine`, `TaskUsageCap`, `ToolLookup`, `ArgsValidation`,
  `ConstraintResolution`, `PostureOverride`, `GenreFloor`, `InitiativeFloor`,
  `CallCounter`, `McpPerToolApproval`, `ApprovalGate`, `PostureGate`. Each
  gate emits a `Verdict` (GO / REFUSE / PENDING) with a reason that gets
  recorded to the audit chain. Tighten-only safety semantics: posture
  overrides cannot loosen constraints.

- **SHA-256 hash-linked audit chain.** Append-only `audit_chain.jsonl` with
  every entry hash-linked to the previous. `gux verify` re-validates the
  full chain. Canonical-form contract: `entry_hash` excludes the timestamp
  (clock-skew immune); genesis `prev_hash` is the literal string `"GENESIS"`.

- **HTTP sidecar** at `/dispatch`, `/healthz`, `/audit/tail`, `/audit/verify`.
  Standard-library only (`http.server`, `ThreadingHTTPServer`). No external
  dependencies. CORS preflight supported. Binds to `127.0.0.1:7421` by default.

- **CLI** with `init`, `activate`, `license`, `trial`, `serve`, `verify`,
  `dispatch` subcommands. Mirror of the HTTP surface for scripted / offline
  workflows.

- **License gating** at runtime. Trial (7 days, time-bounded), hobby, pro,
  team, oem plans. License key format `gux_<plan>_<random>`. Status persists
  to `${XDG_CONFIG_HOME:-$HOME/.config}/gux/license.json`.

- **Constitution-as-code.** YAML constitution file declares agents, their
  resolved tools, posture, initiative, provider, and per-provider tightening
  overrides. `gux init` writes a working example.

- **Installer** (`install-gux.command`). One-script Mac install: creates
  venv at `$GUX_HOME/.venv`, pip-installs `gux-governor`, writes example
  constitution, starts trial license, drops a desktop launcher.

- **Test suite.** 165 tests across five layers. L1 gates (52), L2 sidecar
  HTTP (23), L3 license (49), L4 CLI (26), L5 install end-to-end (15). The
  suite caught two production bugs before first release:

  - **PostureOverrideGate bool-is-int silent no-op.** `isinstance(True, int)`
    returns True in Python, so the int-tighten branch fired for booleans and
    `True < False` is False — every "force human approval" posture override
    was silently a no-op. Caught by `test_override_forces_human_approval`.
    Fix: check `isinstance(v, bool)` before `isinstance(v, int)`.

  - **install-gux.command non-interactive exit-1.** The `trap '… read -n 1
    -s' EXIT` "Press any key to close" affordance for double-clickers caused
    the script to exit 1 under non-TTY stdin even when every install step
    succeeded. Caught by `test_install_exits_zero`. Fix: gate the read on
    `[ -t 0 ]`.

[0.5.0]: https://github.com/StellarRequiem/gux/releases/tag/v0.5.0
