"""Phase 0 — the pure .ics core: build, parse, RRULE window, UID filter."""
from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from calendar_sync import services
from calendar_sync.services import BusyEvent, build_calendar, build_event, own_uid


def _aware(y, mo, d, h=0, mi=0):
    return timezone.make_aware(datetime(y, mo, d, h, mi))


class UidNamespaceTests(TestCase):
    def test_own_uid_shape_and_detection(self):
        uid = own_uid("shift", "abc-123", "zink.nu")
        self.assertEqual(uid, "bitgigs-shift-abc-123@zink.nu")
        self.assertTrue(services.is_own_uid(uid))

    def test_foreign_uid_not_detected(self):
        self.assertFalse(services.is_own_uid("event-9@google.com"))
        self.assertFalse(services.is_own_uid(""))
        self.assertFalse(services.is_own_uid(None))

    def test_uid_falls_back_when_domain_missing(self):
        self.assertTrue(own_uid("shift", 1, "").endswith("@bitgigs.local"))


class BuildParseRoundTripTests(TestCase):
    def test_timed_event_round_trips(self):
        event = build_event(
            uid="event-1@example.com",
            summary="Dentist",
            start=_aware(2026, 3, 15, 9, 0),
            end=_aware(2026, 3, 15, 10, 30),
            location="Main St 1",
        )
        data = build_calendar(event)

        busy = services.parse_calendar(data, date(2026, 3, 1), date(2026, 3, 31))

        self.assertEqual(len(busy), 1)
        ev = busy[0]
        self.assertIsInstance(ev, BusyEvent)
        self.assertEqual(ev.summary, "Dentist")
        self.assertFalse(ev.all_day)
        self.assertEqual(timezone.localtime(ev.start).hour, 9)
        self.assertEqual(timezone.localtime(ev.end).minute, 30)

    def test_all_day_event_round_trips(self):
        event = build_event(
            uid="holiday-1@example.com",
            summary="Holiday",
            start=date(2026, 3, 10),
            end=date(2026, 3, 11),
            all_day=True,
        )
        data = build_calendar(event)

        busy = services.parse_calendar(data, date(2026, 3, 1), date(2026, 3, 31))

        self.assertEqual(len(busy), 1)
        self.assertTrue(busy[0].all_day)
        self.assertEqual(busy[0].start, date(2026, 3, 10))

    def test_event_outside_window_excluded(self):
        event = build_event(
            uid="far-1@example.com",
            summary="Later",
            start=_aware(2026, 6, 1, 12, 0),
            end=_aware(2026, 6, 1, 13, 0),
        )
        data = build_calendar(event)
        busy = services.parse_calendar(data, date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(busy, [])

    def test_method_is_emitted(self):
        event = build_event(
            uid=own_uid("shift", "x", "zink.nu"),
            summary="Work",
            start=_aware(2026, 3, 15, 9, 0),
            end=_aware(2026, 3, 15, 17, 0),
            organizer=("BitGigs Robot", "robot@zink.nu"),
            attendees=[("Boss", "boss@work.example"), "owner@home.example"],
            status="CONFIRMED",
            sequence=2,
        )
        data = build_calendar(event, method="REQUEST").decode("utf-8")
        self.assertIn("METHOD:REQUEST", data)
        self.assertIn("SEQUENCE:2", data)
        self.assertIn("ORGANIZER", data)
        self.assertIn("boss@work.example", data)
        self.assertIn("owner@home.example", data)


class RruleWindowTests(TestCase):
    def _weekly(self):
        # Starts Monday 2026-03-02, weekly, ten times.
        event = build_event(
            uid="weekly-1@example.com",
            summary="Standup",
            start=_aware(2026, 3, 2, 9, 0),
            end=_aware(2026, 3, 2, 9, 30),
            rrule={"freq": "weekly", "count": 10},
        )
        return build_calendar(event)

    def test_weekly_expands_within_month(self):
        data = self._weekly()
        # March 2026 Mondays: 2, 9, 16, 23, 30 → five occurrences.
        busy = services.parse_calendar(data, date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(len(busy), 5)
        days = sorted(timezone.localtime(e.start).day for e in busy)
        self.assertEqual(days, [2, 9, 16, 23, 30])

    def test_window_bounds_a_different_slice(self):
        data = self._weekly()
        # April Mondays within the ten occurrences: 6, 13, 20, 27 → four (Mar 2
        # + 9 more weeks ends 2026-05-04, so all four April Mondays are present).
        busy = services.parse_calendar(data, date(2026, 4, 1), date(2026, 4, 30))
        days = sorted(timezone.localtime(e.start).day for e in busy)
        self.assertEqual(days, [6, 13, 20, 27])

    def test_all_day_series_with_utc_until_expands(self):
        # Google emits an all-day recurring series as a naive DATE DTSTART but a
        # UTC-datetime UNTIL (…Z). dateutil rejects that awareness mismatch, which
        # used to raise and abort the whole feed's parse (the calendar read as
        # "failing"). It must expand instead. Weekly on Mondays from 2026-03-02.
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:allday-until-z@example.com\r\n"
            "SUMMARY:Payday\r\n"
            "DTSTART;VALUE=DATE:20260302\r\n"
            "DTEND;VALUE=DATE:20260303\r\n"
            "RRULE:FREQ=WEEKLY;UNTIL=20260331T220000Z;BYDAY=MO;WKST=MO\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        ).encode("utf-8")
        busy = services.parse_calendar(ics, date(2026, 3, 1), date(2026, 3, 31))
        self.assertTrue(all(e.all_day for e in busy))
        days = sorted(e.start.day for e in busy)
        self.assertEqual(days, [2, 9, 16, 23, 30])


class OwnUidFilterTests(TestCase):
    def _own_calendar(self):
        event = build_event(
            uid=own_uid("shift", "42", "zink.nu"),
            summary="På arbejde",
            start=_aware(2026, 3, 15, 8, 0),
            end=_aware(2026, 3, 15, 16, 0),
        )
        return build_calendar(event)

    def test_own_uid_filtered_by_default(self):
        busy = services.parse_calendar(
            self._own_calendar(), date(2026, 3, 1), date(2026, 3, 31)
        )
        self.assertEqual(busy, [])

    def test_own_uid_kept_when_not_dropping(self):
        busy = services.parse_calendar(
            self._own_calendar(), date(2026, 3, 1), date(2026, 3, 31), drop_own=False
        )
        self.assertEqual(len(busy), 1)
