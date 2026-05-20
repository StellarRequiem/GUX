"""gux — command-line entry point.

    gux init [--here]            # write example constitution + audit dir
    gux activate <key>           # activate a paid license key
    gux license                  # show current license status
    gux trial                    # (re)start the 7-day trial
    gux serve [--port N]         # run the HTTP sidecar
    gux verify                   # verify audit chain integrity
    gux dispatch <json-payload>  # one-shot dispatch from the CLI
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gux import __version__
from gux.governor import Governor
from gux.license import LicenseGate
from gux.server import DEFAULT_HOST, DEFAULT_PORT, serve
from gux.types import DispatchRequest


EXAMPLE_CONSTITUTION = """\
# G.UX constitution — example
# Drop this into your project and edit. Then:
#   gux serve --constitution ./constitution.yaml

schema_version: 1

policies:
  max_calls_per_session: 200

agents:
  my-agent-01:
    dna: "0xexampledna"
    role: explorer
    genre: research
    initiative: L3
    posture: green
    provider: anthropic/claude-haiku-4-5
    hardware_bound: false
    hw_matches: true
    constitution_tools:
      - memory_recall.v1
      - llm_think.v1
      - file_read.v1
      - mcp_call.v1

# Tighten only — never loosen. Per-provider safety dials.
provider_posture_overrides:
  anthropic/claude-haiku-4-5:
    tools:
      mcp_call:
        constraints:
          max_calls_per_session: 50
"""


def cmd_init(args: argparse.Namespace) -> int:
    """Write an example constitution.yaml + create the audit dir."""
    target = Path(args.path) if args.path else Path.cwd()
    target.mkdir(parents=True, exist_ok=True)
    const_path = target / "constitution.yaml"
    audit_path = target / "audit_chain.jsonl"
    if const_path.exists() and not args.force:
        print(f"refusing to overwrite {const_path} (use --force)", file=sys.stderr)
        return 1
    const_path.write_text(EXAMPLE_CONSTITUTION, encoding="utf-8")
    audit_path.touch()
    print(f"✓ wrote {const_path}")
    print(f"✓ touched {audit_path}")
    print()
    print(f"  next: gux serve --constitution {const_path}")
    return 0


def cmd_activate(args: argparse.Namespace) -> int:
    try:
        gate = LicenseGate.activate(args.key)
    except ValueError as e:
        print(f"✕ {e}", file=sys.stderr)
        return 1
    check = gate.check()
    print(f"✓ activated · {check.message}")
    print(f"  key stored at: {gate.display_path}")
    return 0


def cmd_license(args: argparse.Namespace) -> int:
    gate = LicenseGate.load()
    check = gate.check()
    print(f"plan:    {gate.plan}")
    print(f"key:     {gate.key[:20]}…")
    print(f"status:  {check.message}")
    print(f"file:    {gate.display_path}")
    return 0 if check.ok else 2


def cmd_trial(args: argparse.Namespace) -> int:
    gate = LicenseGate.start_trial()
    print(f"✓ trial started · 7 days · key {gate.key[:20]}…")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    const_path = Path(args.constitution)
    if not const_path.exists():
        print(f"✕ constitution not found: {const_path}", file=sys.stderr)
        print(f"  run `gux init` to create one.", file=sys.stderr)
        return 1
    governor = Governor.from_yaml(
        constitution=const_path,
        audit_path=args.audit,
    )
    try:
        serve(governor, host=args.host, port=args.port)
    except OSError as e:
        print(f"✕ could not bind {args.host}:{args.port} — {e}", file=sys.stderr)
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from gux.audit import AuditChain
    chain = AuditChain(path=Path(args.audit))
    ok, msg = chain.verify()
    print(("✓ " if ok else "✕ ") + msg)
    return 0 if ok else 2


def cmd_dispatch(args: argparse.Namespace) -> int:
    """One-shot CLI dispatch, useful for testing without the sidecar."""
    try:
        body = json.loads(args.payload)
    except json.JSONDecodeError as e:
        print(f"✕ bad JSON payload: {e}", file=sys.stderr)
        return 1
    governor = Governor.from_yaml(
        constitution=Path(args.constitution),
        audit_path=args.audit,
    )
    request = DispatchRequest(
        instance_id=body["instance_id"],
        tool_name=body["tool_name"],
        tool_version=str(body.get("tool_version", "1")),
        args=body.get("args", {}),
        session_id=body.get("session_id", ""),
    )
    result = governor.dispatch(request)
    print(f"verdict:     {result.kind.upper()}")
    print(f"pipeline_ms: {result.pipeline_ms:.2f}")
    print()
    for name, step in result.trace:
        marker = {"GO": "✓", "REFUSE": "✕", "PENDING": "⌛"}.get(step.verdict, "·")
        line = f"  {marker} {name:<22} {step.verdict}"
        if step.detail:
            line += f"  · {step.detail}"
        print(line)
    if result.kind == "refuse":
        print(f"\nreason: {result.reason}")  # type: ignore[attr-defined]
    elif result.kind == "pending":
        print(f"\ngate_source: {result.gate_source}")  # type: ignore[attr-defined]
    return {"go": 0, "pending": 0, "refuse": 2}[result.kind]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gux",
        description="G.UX — Governor User Experience. Drop-in governance "
        "for LLM tool dispatch.",
    )
    parser.add_argument("--version", action="version", version=f"gux {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="write example constitution.yaml")
    p_init.add_argument("--path", default=".", help="target directory")
    p_init.add_argument("--force", action="store_true", help="overwrite existing")
    p_init.set_defaults(func=cmd_init)

    p_act = sub.add_parser("activate", help="activate a paid license key")
    p_act.add_argument("key", help="license key (gux_<plan>_<random>)")
    p_act.set_defaults(func=cmd_activate)

    p_lic = sub.add_parser("license", help="show current license status")
    p_lic.set_defaults(func=cmd_license)

    p_trial = sub.add_parser("trial", help="start a 7-day trial")
    p_trial.set_defaults(func=cmd_trial)

    p_serve = sub.add_parser("serve", help="run the HTTP sidecar")
    p_serve.add_argument("--constitution", default="./constitution.yaml")
    p_serve.add_argument("--audit", default="./audit_chain.jsonl")
    p_serve.add_argument("--host", default=DEFAULT_HOST)
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_serve.set_defaults(func=cmd_serve)

    p_ver = sub.add_parser("verify", help="verify audit chain integrity")
    p_ver.add_argument("--audit", default="./audit_chain.jsonl")
    p_ver.set_defaults(func=cmd_verify)

    p_disp = sub.add_parser("dispatch", help="one-shot dispatch (no sidecar)")
    p_disp.add_argument("payload", help="JSON dispatch body")
    p_disp.add_argument("--constitution", default="./constitution.yaml")
    p_disp.add_argument("--audit", default="./audit_chain.jsonl")
    p_disp.set_defaults(func=cmd_dispatch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
