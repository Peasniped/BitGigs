"""
Danish number formatting template filters.

Usage:
    {% load dk_filters %}
    {{ value|dk }}        →  1.234,56
    {{ value|dk:0 }}      →  1.235
    {{ value|dk:1 }}      →  1.234,6
"""
from decimal import Decimal, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter(name="dk")
def danish_number(value, decimals=2):
    """
    Format a number in Danish style:
      - comma as decimal separator
      - period as thousands separator

    ``decimals`` controls the number of decimal places (default 2).
    """
    if value is None:
        return ""
    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        decimals = 2

    try:
        d = Decimal(str(value))
    except Exception:
        return value

    # Quantize to requested decimal places
    fmt = Decimal(10) ** -decimals  # e.g. 0.01 for 2 decimals
    d = d.quantize(fmt, rounding=ROUND_HALF_UP)

    # Split into integer and decimal parts
    sign, digits, exponent = d.as_tuple()
    # Reconstruct string
    int_part, _, dec_part = str(abs(d)).partition(".")

    # Add thousands separators (period in Danish)
    int_with_sep = ""
    for i, ch in enumerate(reversed(int_part)):
        if i and i % 3 == 0:
            int_with_sep = "." + int_with_sep
        int_with_sep = ch + int_with_sep

    prefix = "−" if sign else ""
    if decimals > 0:
        return f"{prefix}{int_with_sep},{dec_part}"
    else:
        return f"{prefix}{int_with_sep}"
