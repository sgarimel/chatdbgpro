"""Driver registry: maps a tier number to an implementation.

Tier modules are imported lazily so a tier-3-only sweep never loads
code that depends on (e.g.) a mini-swe-agent subprocess wrapper.
"""
from __future__ import annotations

from bench.drivers.base import Driver


def get_driver(tier: int, *, docker: bool = False, **kwargs) -> Driver:
    if docker:
        from bench.drivers.docker_gdb import DockerDriver
        return DockerDriver(tier=tier, **kwargs)
    if tier == 3:
        from bench.drivers.tier3_gdb import Tier3Driver
        return Tier3Driver(**kwargs)
    if tier == 1:
        from bench.drivers.tier1_minisweagent import Tier1Driver
        # Tier1Driver has no debugger; orchestrator dispatch passes
        # `debugger=...` uniformly for tier 3, so swallow it here
        # rather than special-case the call site.
        kwargs.pop("debugger", None)
        return Tier1Driver(**kwargs)
    if tier == 2:
        from bench.drivers.tier2_minisweagent import Tier2Driver
        # Tier 2 = mini-swe-agent with BOTH bash and a persistent gdb
        # session. Like Tier 1, no debugger kwarg from the dispatch
        # site (mini supplies its own).
        kwargs.pop("debugger", None)
        return Tier2Driver(**kwargs)
    raise ValueError(f"Unknown tier: {tier}")


__all__ = ["Driver", "get_driver"]
