"""Optional parts of the app the owner can switch off.

BitGigs covers more ground than any one person needs: someone on a single hourly
job has no use for the payroll editor or the vacation ledger, and every menu
entry they never press is noise. Settings → Features is where those are turned
off — and "off" means off: the nav entry goes, and the URLs stop answering, so a
bookmark or a link in a help article can't drop you back into a page you've
disabled.

Nothing is deleted. A switch only changes what is *reachable*; the shifts,
payslip lines and commuting days sit exactly where they were and come back the
moment it goes on again. That's also why turning something off is never blocked
or warned about — there is nothing to lose.

This module is the single source of truth, mirroring ``api/registry.py`` and
``scheduler/registry.py``: it drives the switches on the tab, the nav's
visibility checks and the URL guard in ``core.middleware``. Adding a feature =
one entry here + one ``BooleanField`` on ``UserSettings`` (and, if it owns
settings of its own, a panel on the tab).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feature:
    key: str
    """Stable id, used in URLs/templates. Never rename — see the field note."""

    setting: str
    """The ``UserSettings`` BooleanField backing it (default True: on unless the
    owner says otherwise, so an upgrade never hides anything they were using)."""

    label: str
    icon: str
    description: str

    view_prefixes: tuple[str, ...] = ()
    """``namespace:url_name`` prefixes this feature owns, matched against
    ``request.resolver_match.view_name``.

    Prefixes rather than namespaces because three of these live in **one** app:
    payroll periods, vacation and commuting all answer under ``payroll:``, so a
    namespace check would switch off all three together.
    """

    settings_note: str = ""
    """Shown under the switch when the feature has settings of its own."""

    extras: tuple[str, ...] = field(default_factory=tuple)
    """Other places the feature shows up, listed on the tab so the owner knows
    what else disappears — this is the honest part of "hide it"."""


FEATURES: tuple[Feature, ...] = (
    Feature(
        key="payroll",
        setting="feature_payroll",
        label="Payroll periods",
        icon="bi-cash-stack",
        description=(
            "Generated payroll periods and the payslip editor, where you adjust "
            "a month's additions and deductions by hand."
        ),
        view_prefixes=("payroll:period-", "payroll:payslip-", "payroll:tax-pull-day"),
        extras=("The Payroll entry in the More menu",),
    ),
    Feature(
        key="vacation",
        setting="feature_vacation",
        label="Vacation & feriepenge",
        icon="bi-sun",
        description=(
            "The holiday-pay overview: feriepenge earned per workplace, "
            "feriekonto and fritvalg balances."
        ),
        view_prefixes=("payroll:vacation-",),
        extras=("The Vacation entry in the More menu",),
    ),
    Feature(
        key="commuting",
        setting="feature_commuting",
        label="Commuting",
        icon="bi-bus-front",
        description=(
            "Commuting days per workplace, for the Danish kørselsfradrag "
            "(transport deduction)."
        ),
        view_prefixes=("payroll:commuting-",),
        extras=("The Commuting entry in the More menu",),
    ),
    Feature(
        key="analytics",
        setting="feature_analytics",
        label="Analytics",
        icon="bi-bar-chart-line",
        description=(
            "Income projection and rate history — how much you're on course to "
            "earn, and how your pay has changed over time."
        ),
        view_prefixes=("analytics:",),
        settings_note="Projection settings live with this switch, below.",
        extras=("The Analytics link in the main navigation",),
    ),
)

SETTING_FIELDS: tuple[str, ...] = tuple(f.setting for f in FEATURES)


def get(key: str) -> Feature | None:
    return next((f for f in FEATURES if f.key == key), None)


def enabled_map(settings=None) -> dict[str, bool]:
    """``{feature key: on?}`` — what the nav and the tab both read."""
    from .models import UserSettings

    settings = settings or UserSettings.load()
    return {f.key: bool(getattr(settings, f.setting, True)) for f in FEATURES}


def is_enabled(key: str, settings=None) -> bool:
    feature = get(key)
    if feature is None:
        return True  # an unknown key is not a switched-off one
    from .models import UserSettings

    settings = settings or UserSettings.load()
    return bool(getattr(settings, feature.setting, True))


def feature_for_view(view_name: str) -> Feature | None:
    """The feature owning *view_name* (``"payroll:vacation-overview"``), if any.

    Longest prefix wins so a future ``payroll:vacation-x`` can't be captured by a
    shorter, more general entry.
    """
    if not view_name:
        return None
    best: Feature | None = None
    best_len = 0
    for feature in FEATURES:
        for prefix in feature.view_prefixes:
            if view_name.startswith(prefix) and len(prefix) > best_len:
                best, best_len = feature, len(prefix)
    return best


def blocked_feature(view_name: str, settings=None) -> Feature | None:
    """The feature that owns *view_name* **and is switched off**, else None."""
    feature = feature_for_view(view_name)
    if feature is None or is_enabled(feature.key, settings):
        return None
    return feature
