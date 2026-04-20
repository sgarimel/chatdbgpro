"""The per-tier execution contract.

Every driver takes a fully-resolved RunSpec plus a prepared run_dir and
is responsible for producing, inside that directory, at minimum:

    result.json     — the dict returned by run() (also persisted here)
    collect.json    — structured per-session data (or synthesised for
                      tiers that don't run ChatDBG directly)

Drivers may additionally write compile.log, stdout.log, stderr.log,
session.cmds, final_patch.diff, transcript.jsonl, etc., as appropriate
for the tier.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from bench.common import RunSpec


class Driver(Protocol):
    tier: int

    def run(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        ...
