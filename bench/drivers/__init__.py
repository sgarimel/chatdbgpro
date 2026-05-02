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
        raise NotImplementedError(
            "Tier 2 (ChatDBG + bash) is not implemented as a separate "
            "driver. Closest approximation: "
            "`--tiers 3 --tool-configs tier2_bash_plus_gdb` (ChatDBG "
            "with bash AND gdb tools both enabled)."
        )
    raise ValueError(f"Unknown tier: {tier}")


__all__ = ["Driver", "get_driver"]
