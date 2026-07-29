"""Save one settings field on its own, so the settings page needs no Save button.

A setting that is a single control — a switch, a dropdown, a colour — has nothing
to "submit": the change *is* the intent, and a Save button beside it is a step
that's easy to walk away without pressing. So the panes post the one field that
changed and say so in place, instead of round-tripping the whole tab.

The catch is that a whole-form POST is what normally decides *which* fields a
request may write. ``UserSettingsForm(tab=…)`` and ``EmailSettingsForm(section=…)``
already scope themselves that way (they drop the other tab's/section's fields so
a partial save can't clear the rest), and this module reuses exactly that: a
**scope** is one of those already-scoped forms, and its surviving ``form.fields``
is the allowlist. A field the scope doesn't render cannot be written through it,
whatever the request asks for.

Everything else about the save is unchanged — same form class, same ``clean()``,
same validation error. ``EmailSettingsForm.clean()`` in particular already falls
back to the stored value for fields its section didn't render, which is what lets
a single-field save still enforce "no outgoing mail without a connection".

Adding a scope = one entry in ``SCOPES``. Loaders import lazily so ``core`` keeps
importing no feature app at module level (the calendar scope lives in
``calendar_sync``), matching how ``UserSettingsView`` pulls in each tab's context.
"""
from __future__ import annotations


class SettingsFieldError(Exception):
    """The request named something that isn't writable — unknown scope, or a
    field that scope doesn't own. Distinct from a validation failure, which is
    the owner's input being wrong rather than the request being malformed."""


def _user_settings(tab):
    from .forms import UserSettingsForm
    from .models import UserSettings

    return UserSettingsForm, UserSettings.load(), {"tab": tab}


def _email_settings(section):
    from .forms import EmailSettingsForm
    from .models import EmailSettings

    return EmailSettingsForm, EmailSettings.load(), {"section": section}


def _calendar_invites():
    from calendar_sync.forms import CalendarInviteSettingsForm
    from calendar_sync.models import CalendarInviteSettings

    return CalendarInviteSettingsForm, CalendarInviteSettings.load(), {}


# Scope key → loader returning (form_class, instance, form_kwargs). The key is
# what the template puts in ``data-autosave``; it names a *pane*, not a model,
# because that is the granularity the allowlist has to work at (the Email tab's
# two cards are two scopes of one model).
SCOPES = {
    "display": lambda: _user_settings("display"),
    "features": lambda: _user_settings("features"),
    "email": lambda: _email_settings("switches"),
    "email_roles": lambda: _email_settings("roles"),
    "calendar": _calendar_invites,
}


def save_field(scope, field, data):
    """Validate and save a single field. Returns the bound form.

    ``data`` is the raw POST — the field's value arrives under its own HTML name,
    so the form's own widget does the parsing (an unchecked switch simply posts
    nothing, which is how ``BooleanField`` already reads "off").

    Raises ``SettingsFieldError`` if the scope or field isn't writable. A form
    that fails validation comes back unsaved with its errors on it; the caller
    decides how to report them.
    """
    loader = SCOPES.get(scope)
    if loader is None:
        raise SettingsFieldError(f"Unknown settings scope {scope!r}.")

    form_class, instance, kwargs = loader()
    form = form_class(data, instance=instance, **kwargs)

    # The scope's own fields are the allowlist — see the module docstring.
    if field not in form.fields:
        raise SettingsFieldError(f"{field!r} is not a {scope} setting.")

    # Narrow to the one field *after* construction: the forms build their field
    # set in __init__ (querysets, placeholders, section trimming), and dropping
    # the rest here is the same trick they use, one step further. Django binds
    # data in full_clean(), so this still happens before any validation runs.
    for name in list(form.fields):
        if name != field:
            del form.fields[name]

    if form.is_valid():
        form.save()
    return form
