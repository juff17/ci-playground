"""Scenario messy-omibavf: a helper with an off-by-one bug that its test catches."""


def last_n(values, n):
    """The last n items of values."""
    return values[max(len(values) - n, 0):]
