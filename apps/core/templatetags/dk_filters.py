"""
Danish number formatting template filters.

Usage:
    {% load dk_filters %}
    {{ value|dk }}        →  1.234,56
    {{ value|dk:0 }}      →  1.235
    {{ value|dk:1 }}      →  1.234,6

Separators come from the active locale (see bitgigs/formats). This filter only
adds thousands grouping on top of that automatic localization and swaps in the
project's Unicode minus; bare ``{{ value }}`` already renders Danish decimals.
"""
from django import template
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter(name="dk")
def danish_number(value, decimals=2):
    """
    Format a number in Danish style with thousands grouping.

    ``decimals`` controls the number of decimal places (default 2).
    """
    if value is None or value == "":
        return ""
    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        decimals = 2

    # floatformat handles rounding (ROUND_HALF_UP), locale separators, and
    # non-numeric input; the "g" suffix forces thousands grouping regardless of
    # the global USE_THOUSAND_SEPARATOR setting.
    out = floatformat(value, f"{decimals}g")
    return out.replace("-", "−") if out else out
