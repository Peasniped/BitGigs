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

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from dateutil.rrule import rrulestr
from django.utils import timezone
from icalendar import Calendar, Event, vCalAddress

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
    """Occurrence start instants of a recurring event within the window."""
    rule_text = rrule.to_ical()
    if isinstance(rule_text, bytes):
        rule_text = rule_text.decode("utf-8")

    # dateutil needs datetimes; use midnight for all-day series, and keep the
    # window bounds in the same awareness as dtstart so `.between` can compare.
    anchor = _to_datetime(dtstart)
    lo, hi = win_start, win_end
    if timezone.is_aware(anchor):
        lo, hi = _ensure_aware(lo), _ensure_aware(hi)
    else:
        lo, hi = _ensure_naive(lo), _ensure_naive(hi)

    rule = rrulestr(rule_text, dtstart=anchor)
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
