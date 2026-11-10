"""Operational classifications, not claims of cognition or permanent memory."""

import numpy as np


def _mean(x):
    a = np.asarray(x, dtype=float)
    if not a.size or not np.isfinite(a).all():
        raise ValueError("Expected finite, nonempty observations")
    return float(a.mean())


def regulation(baseline, stimulated, reference, fold=2.0):
    """+1 up, -1 down, 0 unregulated against baseline AND matched control.

    The zero/zero case is unregulated, avoiding the MATLAB equality artifact.
    """
    if fold <= 1:
        raise ValueError("fold must exceed one")
    b, s, r = map(_mean, (baseline, stimulated, reference))
    if s > max(b, r) and s >= fold * b and s >= fold * r:
        return 1
    if s < min(b, r) and s <= b / fold and s <= r / fold:
        return -1
    return 0


def retained(baseline, stimulated, relaxed, direction):
    """DetectMem's >=50% retained shift, with a real Boolean result."""
    if direction not in (-1, 1):
        raise ValueError("Memory requires an established response direction")
    b, s, r = map(_mean, (baseline, stimulated, relaxed))
    if direction * (s - b) <= 0:
        return False
    return bool(direction * (r - b) >= 0.5 * direction * (s - b))


def retention_fraction(baseline, stimulated, relaxed):
    b, s, r = map(_mean, (baseline, stimulated, relaxed))
    return None if s == b else (r - b) / (s - b)
