"""Driver registry: maps a tier number to an implementation.

Tier modules are imported lazily so a tier-3-only sweep never loads
code that depends on (e.g.) a mini-swe-agent subprocess wrapper.
"""
from __future__ import annotations

from bench.drivers.base import Driver


def get_driver(tier: int, *, docker: bool = False, **kwargs) -> Driver:
    """Resolve a driver instance for a (tier, docker?) pair.

    docker=True routes BugsCPP cases through tier-specific drivers
    that each open a per-case `ContainerSession` against the per-project
    chatdbgpro/gdb-<project> image:

      tier 1 (docker) → Tier1Driver(docker=True)  — mini bash via docker exec
      tier 2 (docker) → Tier2Driver(docker=True)  — mini bash + persistent gdb
                                                     both via docker exec
      tier 3 (docker) → DockerDriver               — ChatDBG-on-gdb in container
      tier 4 (docker) → Tier4Driver(docker=True)  — Claude Code on host
                                                     with --add-dir + docker
                                                     exec template in prompt

    docker=False is the synthetic / injected_repo path (host execution
    or, for T3, the synthetic-runner container if containerize=True).
    """
    if docker:
        if tier == 3:
            from bench.drivers.docker_gdb import DockerDriver
            # DockerDriver pre-dates the per-tier dispatch; it doesn't
            # take mini-style kwargs.
            kwargs.pop("debugger", None)
            kwargs.pop("mini_model_class", None)
            kwargs.pop("prefer_linux", None)
            kwargs.pop("step_limit", None)
            kwargs.pop("bare", None)
            return DockerDriver(tier=tier, **kwargs)
        if tier == 1:
            from bench.drivers.tier1_minisweagent import Tier1Driver
            kwargs.pop("debugger", None)
            kwargs.pop("prefer_linux", None)
            kwargs.pop("bare", None)
            return Tier1Driver(docker=True, **kwargs)
        if tier == 2:
            from bench.drivers.tier2_minisweagent import Tier2Driver
            kwargs.pop("debugger", None)
            kwargs.pop("bare", None)
            return Tier2Driver(docker=True, **kwargs)
        if tier == 4:
            from bench.drivers.tier4_claude import Tier4Driver
            kwargs.pop("debugger", None)
            kwargs.pop("mini_model_class", None)
            kwargs.pop("prefer_linux", None)
            kwargs.pop("step_limit", None)
            return Tier4Driver(docker=True, **kwargs)
        raise ValueError(f"Unknown docker tier: {tier}")

    if tier == 3:
        from bench.drivers.tier3_gdb import Tier3Driver
        return Tier3Driver(**kwargs)
    if tier == 1:
        from bench.drivers.tier1_minisweagent import Tier1Driver
        kwargs.pop("debugger", None)
        return Tier1Driver(**kwargs)
    if tier == 2:
        from bench.drivers.tier2_minisweagent import Tier2Driver
        kwargs.pop("debugger", None)
        return Tier2Driver(**kwargs)
    if tier == 4:
        from bench.drivers.tier4_claude import Tier4Driver
        kwargs.pop("debugger", None)
        kwargs.pop("mini_model_class", None)
        kwargs.pop("prefer_linux", None)
        kwargs.pop("step_limit", None)
        return Tier4Driver(**kwargs)
    raise ValueError(f"Unknown tier: {tier}")


__all__ = ["Driver", "get_driver"]
