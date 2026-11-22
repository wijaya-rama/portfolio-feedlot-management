"""Integer units and deterministic apportionment used throughout the feed ledger."""

from datetime import timedelta
from fractions import Fraction

BPS = 10_000
GRAMS_PER_UNIT = {"kg": 1000, "t": 1_000_000}
ZERO = timedelta(0)
SECOND = timedelta(seconds=1)


def whole(value, label, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def half_up(value, denominator):
    """Round a nonnegative rational quantity to the nearest integer."""
    if value < 0 or denominator <= 0:
        raise ValueError("invalid rounding operands")
    return (2 * value + denominator) // (2 * denominator)


def split(total, weights):
    """Largest remainder with lexicographic tie-breaking on stable IDs."""
    whole(total, "pool")
    if any(weight < 0 for weight in weights.values()):
        raise ValueError("negative allocation weight")
    denominator = sum(weights.values())
    if not denominator:
        if total:
            raise ValueError("positive pool without allocation weights")
        return dict.fromkeys(weights, 0)
    quotas = {key: Fraction(total * weight, denominator) for key, weight in weights.items()}
    pieces = {key: int(quota) for key, quota in quotas.items()}
    residual = total - sum(pieces.values())
    for key in sorted(quotas, key=lambda key: (pieces[key] - quotas[key], key))[:residual]:
        pieces[key] += 1
    return pieces


def seconds(start, end):
    span = end - start
    if span < ZERO or span % SECOND:
        raise ValueError("feed times must use ordered whole seconds")
    return span // SECOND
