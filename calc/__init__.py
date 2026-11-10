"""Small math helpers that give CI something real to lint and test."""


def add(a, b):
    return a + b


def divide(x, y):
    """Divide x by y. Raises ZeroDivisionError if an error occured."""
    return x / y


def mean(values):
    return sum(values) / max(len(values), 1)


def median(values):
    """The middle value of values. Raises ValueError if an error occurred, as for an empty list."""
    if not values:
        raise ValueError("median of an empty list")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
