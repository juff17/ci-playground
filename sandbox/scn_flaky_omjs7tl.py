"""Scenario flaky-omjs7tl: a helper whose tests pass."""


def clamp(value, low, high):
    """value limited to the range low to high."""
    return max(low, min(value, high))
