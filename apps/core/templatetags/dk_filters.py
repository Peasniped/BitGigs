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
from django.utils.html import format_html

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


@register.filter(name="money")
def money(value, decimals=0):
    """
    Format a money amount like ``dk`` **and** wrap it in a maskable span.

    Every money amount rendered through this filter carries ``class="money"``,
    which the "mask money" display setting blurs / dots-out app-wide (see the
    ``[data-mask-money]`` rules in style.css). Hours and other non-money numbers
    keep using ``dk`` so they stay readable while amounts are hidden. Defaults to
    **0** decimals (the app shows whole-krone figures almost everywhere).
    """
    if value is None or value == "":
        return ""
    return format_html('<span class="money">{}</span>', danish_number(value, decimals))


@register.filter(name="money_wrap")
def money_wrap(text):
    """Wrap already-rendered text (e.g. a ``{% templatetag %}``-built string or a
    value not run through ``money``) in the maskable ``.money`` span.

    Use on money that isn't a bare number — a range like ``"30.000–70.000"`` or a
    pre-formatted string. The input is escaped by ``format_html``."""
    if text is None or text == "":
        return ""
    return format_html('<span class="money">{}</span>', text)
