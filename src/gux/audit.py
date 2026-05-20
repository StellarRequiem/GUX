"""Audit chain — append-only, sha256-linked JSONL.

Each line:
    {seq, timestamp, event_type, event_data, prev_hash, entry_hash}

entry_hash = sha256(prev_hash + canonical_json(event_without_hash))

The chain is the source of truth. The registry is a derived index that
can be rebuilt from the chain at any time. Don't ever rewrite or remove
lines — that breaks the hash linkage and invalidates downstream proofs.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ZERO_HASH = "0" * 64


@dataclass
class AuditChain:
    path: Path
    _seq: int = field(default=0, init=False)
    _prev_hash: str = field(default=ZERO_HASH, init=False)
    _initialized: bool = field(default=False, init=False)

    def _initialize(self) -> None:
        """Read the existing chain (if any) and recover seq + prev_hash."""
        if self._initialized:
            return
        self._initialized = True
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch()
            return
        # Tail of the file gives us seq + prev_hash. For now, do a full read
        # — chains in this kernel rarely exceed a few MB, and a strict
        # implementation would also re-verify hashes.
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    self._seq = entry["seq"]
                    self._prev_hash = entry["entry_hash"]
                except (json.JSONDecodeError, KeyError):
                    pass

    def append(self, event_type: str, event_data: dict[str, Any]) -> dict[str, Any]:
        """Append one event. Returns the full entry (with hashes) for
        debugging / introspection."""
        self._initialize()
        self._seq += 1
        entry = {
            "seq": self._seq,
            "timestamp": _iso_timestamp(),
            "event_type": event_type,
            "event_data": event_data,
            "prev_hash": self._prev_hash,
        }
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        entry_hash = hashlib.sha256(
            (self._prev_hash + canonical).encode("utf-8")
        ).hexdigest()
        entry["entry_hash"] = entry_hash
        self._prev_hash = entry_hash

        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        return entry

    def verify(self) -> tuple[bool, str]:
        """Walk the chain and verify every entry_hash. Returns
        (ok, message_or_first_break)."""
        if not self.path.exists():
            return True, "chain empty"
        prev = ZERO_HASH
        seq = 0
        with self.path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                entry = json.loads(line)
                claimed_prev = entry.get("prev_hash")
                if claimed_prev != prev:
                    return False, (
                        f"prev_hash mismatch at line {lineno} seq "
                        f"{entry.get('seq')}: expected {prev[:12]}…, got "
                        f"{(claimed_prev or '')[:12]}…"
                    )
                # Recompute entry_hash without the entry_hash field.
                stripped = {k: v for k, v in entry.items() if k != "entry_hash"}
                canonical = json.dumps(stripped, sort_keys=True, separators=(",", ":"))
                expected = hashlib.sha256(
                    (prev + canonical).encode("utf-8")
                ).hexdigest()
                if expected != entry.get("entry_hash"):
                    return False, (
                        f"entry_hash mismatch at line {lineno} seq "
                        f"{entry.get('seq')}"
                    )
                prev = entry["entry_hash"]
                seq = entry["seq"]
        return True, f"chain valid · seq 1 → {seq} · prev_hash unbroken"


def _iso_timestamp() -> str:
    """ISO-8601 UTC timestamp, millisecond precision."""
    t = time.time()
    millis = int((t - int(t)) * 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{millis:03d}Z"
