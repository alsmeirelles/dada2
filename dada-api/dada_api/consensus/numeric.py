"""Deterministic quantization of continuous consensus metrics (P6-02)."""

import math
from decimal import ROUND_HALF_EVEN, Decimal

QUANTUM = Decimal("0.000001")


def quantize(value: float) -> Decimal:
    """Round a finite metric to six decimal places with banker's rounding.

    Going through ``repr`` keeps the shortest decimal that reproduces the
    float, so ``2 / 3`` and a threshold written as ``0.666667`` meet exactly.

    Args:
        value: Metric or threshold to compare.

    Returns:
        The quantized value.

    Raises:
        ValueError: When the value is not finite.
    """
    if not math.isfinite(value):
        raise ValueError("consensus metrics must be finite")
    return Decimal(repr(float(value))).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)


def at_least(value: float, threshold: float) -> bool:
    """Return whether a metric meets an inclusive threshold after quantization.

    Args:
        value: Observed metric.
        threshold: Inclusive lower bound.

    Returns:
        True when the quantized metric is greater than or equal to the bound.
    """
    return quantize(value) >= quantize(threshold)
