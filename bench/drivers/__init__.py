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
    if tier == 4:
        from bench.drivers.tier4_claude import Tier4Driver
        # Tier 4 = Claude Code (the CLI) as the agent. No debugger
        # kwarg (Claude has its own integrated tool registry).
        kwargs.pop("debugger", None)
        # Tier4Driver doesn't accept `mini_model_class` either.
        kwargs.pop("mini_model_class", None)
        kwargs.pop("prefer_linux", None)
        # Tier4Driver doesn't use step_limit (Claude has cost-budget
        # capping instead). Drop it gracefully if dispatch passes it.
        kwargs.pop("step_limit", None)
        return Tier4Driver(**kwargs)
    raise ValueError(f"Unknown tier: {tier}")


__all__ = ["Driver", "get_driver"]
