"""The iCalendar (.ics) core — pure building and parsing, no I/O.

This module is the one place BitGigs turns fields into RFC 5545 components and
parses them back. It has **no** network, database or request knowledge: fetching
an operator's feed (Direction 1) and sending invites (Direction 2) live in the
views/higher services and hand their bytes here. Keeping it pure is what lets it
be unit-tested exhaustively without a network stub.

UID namespacing
---------------
Everything BitGigs *emits* carries a UID shaped ``bitgigs-<kind>-<key>@<domain>``
(see :func:`own_uid`). Direction 1 overlays an operator's personal calendar onto
the planning grid to catch collisions; without namespacing, a shift we already
pushed *out* as an invite (Direction 2) would come *back* through that feed and
read as a clash with the very planned shift that created it. :func:`parse_calendar`
therefore drops any ``bitgigs-`` UID by default.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.error
import urllib.request
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse

from dateutil.rrule import rrulestr
from django.core.cache import cache
from django.utils import timezone
from icalendar import Calendar, Event, vCalAddress

logger = logging.getLogger(__name__)

PRODID = "-//BitGigs//Calendar//EN"
UID_PREFIX = "bitgigs-"

# Cap RRULE expansion so a malformed or unbounded rule from an external feed
# can't spin forever building occurrences we'd immediately window away.
_MAX_OCCURRENCES = 1000


# ─────────────────────────────────────────────────────────────────────────────
# UID namespacing
# ─────────────────────────────────────────────────────────────────────────────

def own_uid(kind: str, key, domain: str) -> str:
    """A UID for an event BitGigs emits, e.g. ``bitgigs-shift-42@zink.nu``.

    *key* is usually a shift's stable ``invite_uid`` (not its PK — the PK changes
    when a PlannedShift is approved into a Shift, which must not orphan the event).
    """
    return f"{UID_PREFIX}{kind}-{key}@{domain or 'bitgigs.local'}"


def is_own_uid(uid) -> bool:
    """True for a UID this app emitted (see :func:`own_uid`)."""
    return str(uid or "").startswith(UID_PREFIX)


# ─────────────────────────────────────────────────────────────────────────────
# Building
# ─────────────────────────────────────────────────────────────────────────────

def build_event(
    *,
    uid: str,
    summary: str,
    start,
    end,
    description: str = "",
    location: str = "",
    all_day: bool = False,
    organizer=None,
    attendees=(),
    status: str | None = None,
    sequence: int = 0,
    rrule=None,
    dtstamp=None,
) -> Event:
    """Turn plain fields into a single VEVENT.

    *start* / *end* are ``datetime`` for timed events (aware preferred) or ``date``
    for all-day (``all_day=True``). *organizer* is ``(name, address)`` or a bare
    address string; *attendees* is an iterable of the same. *status* is a raw
    iCalendar status (``CONFIRMED`` / ``CANCELLED``). Callers namespace *uid* via
    :func:`own_uid` for anything they intend to send out.
    """
    event = Event()
    event.add("uid", uid)
    event.add("summary", summary)

    if all_day:
        event.add("dtstart", _as_date(start))
        event.add("dtend", _as_date(end))
    else:
        event.add("dtstart", start)
        event.add("dtend", end)

    event.add("dtstamp", dtstamp or timezone.now())
    event.add("sequence", int(sequence))

    if description:
        event.add("description", description)
    if location:
        event.add("location", location)
    if status:
        event.add("status", status)
    if organizer is not None:
        event["organizer"] = _cal_address(organizer)
    for attendee in attendees:
        addr = _cal_address(attendee, attendee=True)
        event.add("attendee", addr)
    if rrule:
        event.add("rrule", rrule)

    return event


def build_calendar(events, method: str | None = None) -> bytes:
    """Wrap one or more VEVENTs in a VCALENDAR and serialise to bytes.

    *method* is the iTIP method (``REQUEST`` for an invite, ``CANCEL`` for a
    withdrawal); omitted for a plain feed.
    """
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    if method:
        cal.add("method", method)
    if isinstance(events, Event):
        events = [events]
    for event in events:
        cal.add_component(event)
    return cal.to_ical()


def _cal_address(value, attendee: bool = False) -> vCalAddress:
    """Build a ``mailto:`` CAL-ADDRESS, optionally with a common name."""
    if isinstance(value, (tuple, list)):
        name, address = value
    else:
        name, address = "", value
    addr = vCalAddress(f"mailto:{address}")
    if name:
        addr.params["cn"] = name
    if attendee:
        addr.params["role"] = "REQ-PARTICIPANT"
        # BitGigs ignores RSVPs, so never ask for one.
        addr.params["rsvp"] = "FALSE"
    return addr


def _as_date(value) -> date:
    return value.date() if isinstance(value, datetime) else value


# ─────────────────────────────────────────────────────────────────────────────
# Parsing (inbound feeds, RRULE-expanded over a window)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BusyEvent:
    """One busy block from an external feed, already expanded to a real span.

    *start* / *end* are aware ``datetime`` in local time for timed events, or
    ``date`` for all-day ones — the same shape the planning overlay renders.
    """
    uid: str
    summary: str
    start: object
    end: object
    all_day: bool


def parse_calendar(data, window_start, window_end, drop_own: bool = True):
    """Parse feed *data* into :class:`BusyEvent`\\ s overlapping the window.

    *window_start* / *window_end* are ``date`` or ``datetime`` bounds (inclusive
    of the whole start day through the whole end day). Recurring events are
    expanded via their RRULE and only the occurrences that fall in the window are
    returned. UIDs BitGigs emitted are dropped unless *drop_own* is false.
    """
    win_start = _window_bound(window_start, end=False)
    win_end = _window_bound(window_end, end=True)

    cal = Calendar.from_ical(data)
    busy: list[BusyEvent] = []

    for comp in cal.walk("VEVENT"):
        uid = str(comp.get("uid", ""))
        if drop_own and is_own_uid(uid):
            continue

        dtstart_prop = comp.get("dtstart")
        if dtstart_prop is None:
            continue
        dtstart = dtstart_prop.dt
        all_day = not isinstance(dtstart, datetime)
        duration = _event_duration(comp, dtstart, all_day)
        summary = str(comp.get("summary", ""))

        rrule = comp.get("rrule")
        if rrule is not None:
            starts = _expand_rrule(dtstart, rrule, win_start, win_end, all_day)
        else:
            starts = [dtstart]

        for occ_start in starts:
            occ_end = occ_start + duration
            if _overlaps(occ_start, occ_end, win_start, win_end, all_day):
                busy.append(
                    BusyEvent(
                        uid=uid,
                        summary=summary,
                        start=_present(occ_start, all_day),
                        end=_present(occ_end, all_day),
                        all_day=all_day,
                    )
                )

    busy.sort(key=lambda e: (_sort_key(e.start)))
    return busy


def _event_duration(comp, dtstart, all_day) -> timedelta:
    """A VEVENT's length from DTEND or DURATION, with RFC 5545 defaults."""
    dtend_prop = comp.get("dtend")
    if dtend_prop is not None:
        return dtend_prop.dt - dtstart
    duration_prop = comp.get("duration")
    if duration_prop is not None:
        return duration_prop.dt
    # RFC 5545: no DTEND/DURATION → all-day lasts one day, timed is instantaneous.
    return timedelta(days=1) if all_day else timedelta(0)


def _expand_rrule(dtstart, rrule, win_start, win_end, all_day):
    """Occurrence start instants of a recurring event within the window.

    dateutil refuses to build an rrule whose DTSTART and UNTIL disagree on
    timezone-awareness, and real feeds routinely disagree: Google emits an
    all-day series (a naive ``DATE`` DTSTART) with a **UTC-datetime** UNTIL
    (``…Z``, aware) — the exact mismatch that used to raise, abort the whole
    feed's parse, and make the calendar read as broken. So we expand entirely in
    naive **local wall time**: the anchor forced naive-local and UNTIL's zone
    dropped via ``ignoretz`` can never mismatch. Occurrences are re-localised by
    :func:`_present`, so downstream awareness is unchanged.
    """
    rule_text = rrule.to_ical()
    if isinstance(rule_text, bytes):
        rule_text = rule_text.decode("utf-8")

    anchor = _ensure_naive(_to_datetime(dtstart))
    lo, hi = _ensure_naive(win_start), _ensure_naive(win_end)

    rule = rrulestr(rule_text, dtstart=anchor, ignoretz=True)
    occurrences = rule.between(lo, hi, inc=True)[:_MAX_OCCURRENCES]
    if all_day:
        return [occ.date() for occ in occurrences]
    return occurrences


# ── window / comparison helpers ──────────────────────────────────────────────
#
# Everything is compared as aware datetimes in the current timezone. All-day
# values (dates) map to that day's midnight boundaries; naive datetimes from a
# feed are assumed to be in the server's local zone.

def _window_bound(value, end: bool):
    if isinstance(value, datetime):
        return _ensure_aware(value)
    # A date: start of that day, or start of the following day for an end bound
    # (so the whole end day is inside the window).
    anchor = value + timedelta(days=1) if end else value
    return _ensure_aware(datetime.combine(anchor, time.min))


def _overlaps(start, end, win_start, win_end, all_day) -> bool:
    s = _compare_dt(start, all_day, end=False)
    e = _compare_dt(end, all_day, end=True)
    return s < win_end and e > win_start


def _compare_dt(value, all_day, end: bool):
    if isinstance(value, datetime):
        return _ensure_aware(value)
    anchor = value
    return _ensure_aware(datetime.combine(anchor, time.min))


def _present(value, all_day):
    """The value as the overlay wants it: local aware datetime, or a date."""
    if all_day:
        return value if isinstance(value, date) and not isinstance(value, datetime) else value.date()
    return timezone.localtime(_ensure_aware(value))


def _sort_key(value):
    if isinstance(value, datetime):
        return _ensure_aware(value)
    return _ensure_aware(datetime.combine(value, time.min))


def _to_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min)


def _ensure_aware(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _ensure_naive(value: datetime) -> datetime:
    if timezone.is_aware(value):
        return timezone.make_naive(value, timezone.get_current_timezone())
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Direction 1 — fetching an operator's feed (SSRF-guarded), caching, aggregating
#
# This is a *server-side* outbound fetch of a URL the operator pasted — inbound
# data only, one of the two sanctioned outbound shapes (see CLAUDE.md). It never
# leaks app data, but a server that will fetch an arbitrary operator-supplied URL
# is an SSRF surface, so the fetch is hardened: https/http only, public IPs only,
# capped size, short timeout, redirects re-validated, and it fails *soft* — a
# broken feed records an error and contributes nothing, never 500s planning.
# ─────────────────────────────────────────────────────────────────────────────

FETCH_TIMEOUT = 10          # seconds, connect+read
MAX_FEED_BYTES = 5_000_000  # 5 MB — a personal calendar feed is far smaller
CACHE_TTL = 900             # 15 min; a manual refresh busts it
_CACHE_PREFIX = "calsync:ical:"
_USER_AGENT = "BitGigs-CalendarSync/1.0 (+https://bitgigs.local)"


class CalendarFetchError(Exception):
    """A feed could not be fetched or read safely. Always caught + logged."""


def _guard_url(raw_url: str):
    """Reject anything that isn't a plain public http(s) target (SSRF guard).

    Resolves the hostname and refuses if *any* resolved address is private,
    loopback, link-local, reserved, multicast or unspecified. Note: this does not
    close a determined DNS-rebinding attack (the address could differ between this
    resolve and urllib's own connect) — pinning the socket to the vetted IP is the
    full fix — but it blocks the ordinary ``file://`` / ``localhost`` / ``169.254``
    / RFC-1918 mistakes and probes, which is the realistic threat for an
    operator-pasted URL.
    """
    parsed = urlparse(raw_url or "")
    if parsed.scheme not in ("http", "https"):
        raise CalendarFetchError(
            f"Only http and https URLs are allowed (got '{parsed.scheme or 'none'}')."
        )
    host = parsed.hostname
    if not host:
        raise CalendarFetchError("The URL has no host.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 0, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise CalendarFetchError(f"Could not resolve '{host}' ({exc}).") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            raise CalendarFetchError(
                f"'{host}' resolves to a non-public address ({ip}); refused."
            )


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-run the SSRF guard on every redirect target so a public URL can't
    bounce the fetch to an internal one."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _guard_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_GuardedRedirectHandler())


def fetch_ical(url: str, *, timeout=FETCH_TIMEOUT, max_bytes=MAX_FEED_BYTES) -> bytes:
    """Fetch feed bytes for *url*, guarded and size-capped. Raises on any problem."""
    _guard_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with _opener.open(request, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
    except CalendarFetchError:
        raise
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise CalendarFetchError(f"Fetch failed: {exc}.") from exc
    if len(data) > max_bytes:
        raise CalendarFetchError(
            f"Feed is larger than the {max_bytes // 1_000_000} MB limit."
        )
    return data


def busy_config_token() -> str:
    """A short fingerprint of the subscription **colours** (all calendars, enabled
    or not) — the only stored state that makes cached busy chips render *wrong*.

    The planning overlay caches fetched busy cells per-month, per-calendar in
    ``sessionStorage``. Each cell bakes its calendar's colour in, so editing a
    colour must invalidate that cache — the page carries this token, the overlay
    stores it alongside the cache and drops everything when it no longer matches
    (re-fetching once, reusing the ~15 min server feed cache, so no external poll).

    Enabled-state is deliberately **excluded**: toggling a calendar on/off only
    changes which cached cells are *shown*, not their data, so the overlay filters
    client-side and a toggle must not bust the cache (else it would re-pull every
    time). A colour change is the only edit that survives here.
    """
    from hashlib import md5

    from .models import CalendarSubscription

    rows = list(
        CalendarSubscription.objects.order_by("pk").values_list("pk", "color")
    )
    return md5(repr(rows).encode("utf-8")).hexdigest()[:12]


def _cache_key(subscription) -> str:
    return f"{_CACHE_PREFIX}{subscription.pk}"


def refresh_subscription(subscription):
    """Drop the cached feed for *subscription* so the next read re-fetches."""
    cache.delete(_cache_key(subscription))


def _load_feed(subscription, *, refresh=False):
    """Return raw feed bytes for a subscription, cached ~15 min.

    Records fetch state on the row (``last_fetch_*``) on every real fetch. Raises
    :class:`CalendarFetchError` on failure; the cache is only populated on success
    so a broken feed keeps being retried rather than caching emptiness.
    """
    key = _cache_key(subscription)
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    url = subscription.url
    if not url:
        raise CalendarFetchError(
            "No calendar URL is set (or it could not be decrypted)."
        )
    try:
        data = fetch_ical(url)
    except CalendarFetchError as exc:
        _record_fetch(subscription, ok=False, error=str(exc))
        raise
    _record_fetch(subscription, ok=True, error="")
    cache.set(key, data, CACHE_TTL)
    return data


def _record_fetch(subscription, *, ok, error):
    subscription.last_fetch_at = timezone.now()
    subscription.last_fetch_ok = ok
    subscription.last_error = error
    subscription.save(
        update_fields=["last_fetch_at", "last_fetch_ok", "last_error", "updated_at"]
    )


def subscription_busy(subscription, window_start, window_end, *, refresh=False):
    """Busy events for one subscription over a window. Fails soft → ``[]``."""
    try:
        data = _load_feed(subscription, refresh=refresh)
    except CalendarFetchError:
        return []
    try:
        return parse_calendar(data, window_start, window_end)
    except Exception:  # a malformed feed must never break the planning page
        _record_fetch(
            subscription, ok=False, error="The feed could not be parsed as iCalendar."
        )
        return []


def busy_blocks(window_start, window_end, *, refresh=False):
    """JSON-ready busy cells across all enabled subscriptions.

    Each :class:`BusyEvent` is split into per-day cells (a multi-day event lands
    on each day it touches) so the planning grid can drop a chip into every
    affected ``td[data-date]``. Own (``bitgigs-``) UIDs are already filtered by
    :func:`parse_calendar`.
    """
    from .models import CalendarSubscription

    cells = []
    for sub in CalendarSubscription.objects.enabled():
        try:
            for event in subscription_busy(sub, window_start, window_end, refresh=refresh):
                for cell in _event_to_cells(event, sub.color, window_start, window_end):
                    # sub_id lets the planning overlay cache per-calendar and filter
                    # client-side when a calendar is toggled (no re-fetch).
                    cell["sub_id"] = sub.pk
                    cells.append(cell)
        except Exception:
            # One bad subscription must never suppress the others. subscription_busy
            # already fails soft for the ordinary cases (fetch/parse errors);
            # this is the backstop for anything unexpected — an event that trips
            # _event_to_cells, or a non-CalendarFetchError like a transient SQLite
            # "database is locked" from _record_fetch under concurrent requests.
            logger.exception("calendar_sync: subscription %s failed, skipping", sub.pk)
            continue
    cells.sort(key=lambda c: (c["date"], c["all_day"] is False, c.get("start_time", "")))
    return cells


def _event_to_cells(event, color, window_start, window_end):
    """One busy event → a list of per-day cell dicts within the window."""
    lo = window_start if isinstance(window_start, date) else window_start.date()
    hi = window_end if isinstance(window_end, date) else window_end.date()

    if event.all_day:
        # DTEND is exclusive for all-day events; clamp to the window.
        start_day = event.start
        end_day = event.end if event.end > event.start else event.start + timedelta(days=1)
        day = max(start_day, lo)
        cells = []
        while day < end_day and day <= hi:
            cells.append({
                "date": day.isoformat(), "all_day": True,
                "summary": event.summary, "color": color,
            })
            day += timedelta(days=1)
        return cells

    start = timezone.localtime(event.start)
    end = timezone.localtime(event.end)
    if start.date() == end.date():
        return [{
            "date": start.date().isoformat(), "all_day": False,
            "start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M"),
            "summary": event.summary, "color": color,
        }]

    # A timed event spanning midnight: first day from its start to end-of-day,
    # whole intermediate days as all-day busy, last day up to its end time.
    cells = []
    if start.date() >= lo:
        cells.append({
            "date": start.date().isoformat(), "all_day": False,
            "start_time": start.strftime("%H:%M"), "end_time": "23:59",
            "summary": event.summary, "color": color,
        })
    day = start.date() + timedelta(days=1)
    while day < end.date() and day <= hi:
        if day >= lo:
            cells.append({
                "date": day.isoformat(), "all_day": True,
                "summary": event.summary, "color": color,
            })
        day += timedelta(days=1)
    if end.date() <= hi and end.strftime("%H:%M") != "00:00":
        cells.append({
            "date": end.date().isoformat(), "all_day": False,
            "start_time": "00:00", "end_time": end.strftime("%H:%M"),
            "summary": event.summary, "color": color,
        })
    return cells


def month_window(year: int, month: int, pad_days: int = 7):
    """The (start, end) date window for a month's planning grid, padded so the
    leading/trailing days of adjacent months shown in the grid are covered."""
    start = date(year, month, 1) - timedelta(days=pad_days)
    end = date(year, month, monthrange(year, month)[1]) + timedelta(days=pad_days)
    return start, end
