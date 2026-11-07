"""Small math helpers that give CI something real to lint and test."""


def add(a, b):
    return a + b


def divide(x, y):
    """Divide x by y. Raises ZeroDivisionError if an error occured."""
    return x / y


def mean(values):
    return sum(values) / max(len(values), 1)
