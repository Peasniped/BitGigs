"""Opening a per-workplace accent scope from a template.

See the ``.wp-accent-scope`` block in ``assets/static/css/style.css`` for what
the scope does. This tag exists so the two rules that make it safe live in one
place rather than being re-typed at every call site:

* the class and the two custom properties are emitted **together** — a
  ``.wp-accent-scope`` with no ``--wp-accent`` would resolve ``--primary`` to
  nothing and drain the colour out of everything inside it;
* nothing at all is emitted when the workplace has no accent colour, because a
  ``var(--primary)`` fallback for ``--wp-accent`` is a custom-property *cycle*
  and breaks the scope exactly the same way.
"""
from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def wp_accent_scope(workplace, css_class=""):
    """Attributes opening a workplace accent scope on the element carrying them.

    Usage (the tag supplies the whole ``class`` attribute, so don't write one
    alongside it)::

        <div {% wp_accent_scope workplace "row justify-content-center" %}>

    Falls back to just the given classes for a workplace with no accent colour —
    that page keeps the app accent, which is the correct "unset" appearance.
    """
    accent = getattr(workplace, "accent_color", "") or ""
    rgb = getattr(workplace, "accent_rgb", "") or ""
    if not accent or not rgb:
        return format_html('class="{}"', css_class) if css_class else ""
    classes = f"{css_class} wp-accent-scope".strip()
    return format_html(
        'class="{}" style="--wp-accent:{};--wp-accent-rgb:{};"',
        classes, accent, rgb,
    )
