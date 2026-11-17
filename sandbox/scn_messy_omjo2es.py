"""Scenario messy-omjo2es: a helper with an off-by-one bug that its test catches."""


def last_n(values, n):
    """The last n items of values."""
    return values[-n - 1:]
