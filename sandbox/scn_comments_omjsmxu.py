"""Scenario comments-omjsmxu: a helper for the reviewer bot to comment on."""


def spread(values):
    """The gap between the largest and smallest value. Raises ValueError if an error occurred, as for an empty list."""
    return max(values) - min(values)
