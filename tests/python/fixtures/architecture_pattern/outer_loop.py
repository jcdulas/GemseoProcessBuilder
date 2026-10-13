"""Fakes of the outer loop of a structural sizing, for the test of its pattern.

A planner makes a requested stringer count viable (even, rounded up), a producer
builds the architecture, a sizing sizes it; the calls are counted.
"""

import math

CALLS = {"producer": 0, "sizing": 0}
"""The executions of the producer and of the sizing."""


def planner(stringers: float = 4.0) -> float:
    """The nearest viable count: even, rounded up."""
    obtained = 2.0 * math.ceil(stringers / 2.0)
    return obtained


def producer(obtained: float = 4.0) -> float:
    """The initial mass of the architecture built (an expensive external code)."""
    CALLS["producer"] += 1
    initial_mass = 100.0 + 3.0 * obtained
    return initial_mass


def sizing(initial_mass: float = 112.0, obtained: float = 4.0) -> float:
    """The mass of the sized architecture (an expensive inner loop)."""
    CALLS["sizing"] += 1
    mass = 0.9 * initial_mass + obtained
    return mass
