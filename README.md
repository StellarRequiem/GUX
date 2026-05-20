# G.UX — install on your computer

A drop-in governance kernel for LLM tool dispatch. Twelve gates decide
GO / REFUSE / PENDING before any tool call fires.

This package is **stdlib-only** at runtime. The only dependency is
optional PyYAML for constitution files (we'll auto-install it).

## macOS / Linux — easiest

Download this folder, then double-click `install-gux.command`. (On macOS,
the first time you may need to right-click → Open to bypass Gatekeeper
warnings for an unsigned installer.) The installer will:

1. Verify Python 3.10+ is available.
2. Create a venv at `~/.gux/.venv/`.
3. Install the `gux-governor` package and PyYAML.
4. Write an example `~/.gux/constitution.yaml`.
5. Activate a fresh **7-day trial** (or activate your paid key if you pass one).
6. Drop a `launch-gux.command` on your Desktop you can double-click to start the sidecar.

To start with a paid license:

```
./install-gux.command gux_pro_aB3kD9eF…YOURKEY
```

## From a terminal

```sh
# pip install
pip install gux-governor[yaml]

# Or develop locally against this source tree
cd package
pip install -e ".[yaml]"
```

Then:

```sh
gux init                       # write example constitution.yaml
gux trial                      # start a 7-day trial (or...)
gux activate gux_pro_…         # ...activate a paid key
gux serve                      # run the sidecar on http://127.0.0.1:7421
```

## Activating a paid key

License keys look like `gux_<plan>_<random>` — `gux_hobby_…`, `gux_pro_…`,
`gux_team_…`, `gux_oem_…`. They live at:

- macOS / Linux: `~/.config/gux/license.json`
- Windows:       `%APPDATA%\gux\license.json`

Activation is **local-only**. We never phone home, never check a remote
service, never validate against an issuer. The license file is yours.

```sh
gux activate gux_pro_aB3kD9eF2…
gux license     # show current plan + days remaining
```

## Talking to the sidecar

Once `gux serve` is running, every dispatch is one HTTP call:

```sh
curl -s http://127.0.0.1:7421/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{
    "instance_id": "my-agent-01",
    "tool_name": "memory_recall",
    "tool_version": "1",
    "args": {"query": "what did we decide about Q3 retention?"},
    "session_id": "sess_abc123"
  }'
```

Response shape:

```json
{
  "verdict": "GO",
  "pipeline_ms": 1.3,
  "trace": [
    {"gate": "HardwareQuarantine", "verdict": "GO"},
    {"gate": "TaskUsageCap",       "verdict": "GO"},
    ...
  ]
}
```

## Audit chain

Every dispatch lands one line in `~/.gux/audit_chain.jsonl`. The chain
is sha256-linked — `entry_hash = sha256(prev_hash + canonical_json(event))`.
Verify integrity at any time:

```sh
gux verify
# or:
curl http://127.0.0.1:7421/v1/audit/verify
```

## Uninstall

```sh
rm -rf ~/.gux ~/.config/gux ~/Desktop/launch-gux.command
```

That's it — no daemons running, no system files to clean up. G.UX is a
sidecar, not a system extension.

## Where to go next

- Edit `~/.gux/constitution.yaml` to add your real agents and tools.
- Wire your LLM dispatch through the sidecar — same shape in, deterministic
  verdict out.
- Use `gux dispatch '<json>'` for one-shot testing without the sidecar.
