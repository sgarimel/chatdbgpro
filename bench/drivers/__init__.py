"""Driver registry: maps a tier number to an implementation.

Tier modules are imported lazily so a tier-3-only sweep never loads
code that depends on (e.g.) a mini-swe-agent subprocess wrapper.
"""
from __future__ import annotations

from bench.drivers.base import Driver


def get_driver(tier: int, **kwargs) -> Driver:
    if tier == 3:
        from bench.drivers.tier3_gdb import Tier3Driver
        return Tier3Driver(**kwargs)
    if tier in (1, 2):
        raise NotImplementedError(
            f"Tier {tier} driver is not implemented yet. "
            f"See the implementation plan — tier 1 = mini-swe-agent, tier 2 = ChatDBG + bash."
        )
    raise ValueError(f"Unknown tier: {tier}")


__all__ = ["Driver", "get_driver"]
