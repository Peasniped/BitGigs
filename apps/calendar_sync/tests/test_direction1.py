"""Phase 1 — Direction 1: model, SSRF guard, fetch/cache, cell split, endpoint.

No test hits the network: the SSRF guard is exercised with literal internal
addresses (no DNS), and the fetch is stubbed everywhere a feed would be pulled.
"""
from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from calendar_sync import services
from calendar_sync.models import CalendarSubscription
from calendar_sync.services import (
    BusyEvent,
    CalendarFetchError,
    build_calendar,
    build_event,
    own_uid,
)


def _aware(y, mo, d, h=0, mi=0):
    return timezone.make_aware(timezone.datetime(y, mo, d, h, mi))


def _feed(*events):
    return build_calendar(list(events))


class SubscriptionModelTests(TestCase):
    def test_url_round_trips_through_encryption(self):
        sub = CalendarSubscription.objects.create(label="Personal")
        sub.url = "https://cal.example.com/private/abc.ics"
        sub.save()

        reloaded = CalendarSubscription.objects.get(pk=sub.pk)
        self.assertEqual(reloaded.url, "https://cal.example.com/private/abc.ics")
        # The ciphertext is not the plaintext.
        self.assertNotIn("cal.example.com", reloaded.url_encrypted)
        self.assertFalse(reloaded.url_unreadable)

    def test_enabled_manager_filters(self):
        CalendarSubscription.objects.create(label="On", enabled=True)
        CalendarSubscription.objects.create(label="Off", enabled=False)
        self.assertEqual(
            list(CalendarSubscription.objects.enabled().values_list("label", flat=True)),
            ["On"],
        )

    def test_is_usable_requires_enabled_and_url(self):
        sub = CalendarSubscription(label="x", enabled=True)
        self.assertFalse(sub.is_usable)  # no url yet
        sub.url = "https://cal.example.com/a.ics"
        self.assertTrue(sub.is_usable)
        sub.enabled = False
        self.assertFalse(sub.is_usable)


class SsrfGuardTests(TestCase):
    def test_rejects_non_http_schemes(self):
        for url in ("file:///etc/passwd", "ftp://host/x", "gopher://h/", "not-a-url"):
            with self.assertRaises(CalendarFetchError):
                services._guard_url(url)

    def test_rejects_internal_addresses(self):
        for url in (
            "http://127.0.0.1/cal.ics",
            "http://localhost/cal.ics",
            "http://10.0.0.5/cal.ics",
            "http://192.168.1.10/cal.ics",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://[::1]/cal.ics",
            "http://0.0.0.0/cal.ics",
        ):
            with self.assertRaises(CalendarFetchError):
                services._guard_url(url)

    def test_allows_public_address(self):
        # Patch resolution so no DNS lookup happens in the test.
        fake = [(0, 0, 0, "", ("93.184.216.34", 443))]
        with mock.patch("calendar_sync.services.socket.getaddrinfo", return_value=fake):
            services._guard_url("https://cal.example.com/private/abc.ics")  # no raise


class LoadFeedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.sub = CalendarSubscription.objects.create(label="Personal")
        self.sub.url = "https://cal.example.com/a.ics"
        self.sub.save()

    def test_fetch_records_state_and_caches(self):
        feed = _feed(build_event(
            uid="e1@x", summary="Dentist",
            start=_aware(2026, 3, 15, 9, 0), end=_aware(2026, 3, 15, 10, 0),
        ))
        with mock.patch("calendar_sync.services.fetch_ical", return_value=feed) as m:
            services._load_feed(self.sub)
            services._load_feed(self.sub)  # second read is served from cache
        self.assertEqual(m.call_count, 1)
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.last_fetch_ok)
        self.assertIsNotNone(self.sub.last_fetch_at)

    def test_fetch_failure_is_recorded_and_soft(self):
        with mock.patch(
            "calendar_sync.services.fetch_ical",
            side_effect=CalendarFetchError("boom"),
        ):
            result = services.subscription_busy(self.sub, date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(result, [])
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.last_fetch_ok)
        self.assertIn("boom", self.sub.last_error)


class MultiSubscriptionResilienceTests(TestCase):
    """One faulty subscription must never suppress the others' events."""

    def setUp(self):
        cache.clear()
        self.good = CalendarSubscription.objects.create(label="Good", color="#00ff00")
        self.good.url = "https://good.example.com/a.ics"
        self.good.save()
        self.bad = CalendarSubscription.objects.create(label="Bad", color="#ff0000")
        self.bad.url = "https://bad.example.com/b.ics"
        self.bad.save()

    def _side_effect(self, url, **kwargs):
        if "bad" in url:
            # A non-CalendarFetchError — e.g. a transient SQLite "database is
            # locked" from the fetch-state write, or any unexpected failure.
            raise RuntimeError("database is locked")
        return _feed(build_event(
            uid="e1@x", summary="Dentist",
            start=_aware(2026, 3, 15, 9, 0), end=_aware(2026, 3, 15, 10, 0),
        ))

    def test_good_subscription_survives_a_broken_sibling(self):
        with mock.patch("calendar_sync.services.fetch_ical", side_effect=self._side_effect):
            blocks = services.busy_blocks(date(2026, 3, 1), date(2026, 3, 31), refresh=True)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["summary"], "Dentist")
        self.assertEqual(blocks[0]["color"], "#00ff00")


class EventToCellsTests(TestCase):
    WIN = (date(2026, 3, 1), date(2026, 3, 31))

    def test_timed_same_day(self):
        ev = BusyEvent("e", "Dentist", _aware(2026, 3, 15, 9, 0), _aware(2026, 3, 15, 10, 30), False)
        cells = services._event_to_cells(ev, "#abc", *self.WIN)
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]["date"], "2026-03-15")
        self.assertEqual(cells[0]["start_time"], "09:00")
        self.assertEqual(cells[0]["end_time"], "10:30")
        self.assertFalse(cells[0]["all_day"])

    def test_all_day_multi_day_splits_per_day(self):
        ev = BusyEvent("e", "Trip", date(2026, 3, 10), date(2026, 3, 13), True)  # DTEND exclusive
        cells = services._event_to_cells(ev, "#abc", *self.WIN)
        self.assertEqual([c["date"] for c in cells], ["2026-03-10", "2026-03-11", "2026-03-12"])
        self.assertTrue(all(c["all_day"] for c in cells))

    def test_timed_crossing_midnight(self):
        ev = BusyEvent("e", "Night", _aware(2026, 3, 15, 22, 0), _aware(2026, 3, 16, 2, 0), False)
        cells = services._event_to_cells(ev, "#abc", *self.WIN)
        dates = [c["date"] for c in cells]
        self.assertEqual(dates, ["2026-03-15", "2026-03-16"])
        self.assertEqual(cells[0]["end_time"], "23:59")
        self.assertEqual(cells[1]["start_time"], "00:00")


class BusyEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()
        self.sub = CalendarSubscription.objects.create(label="Personal", color="#ff0000")
        self.sub.url = "https://cal.example.com/a.ics"
        self.sub.save()

    def test_busy_endpoint_returns_cells_and_filters_own_uid(self):
        feed = _feed(
            build_event(
                uid="foreign@x", summary="Dentist",
                start=_aware(2026, 3, 15, 9, 0), end=_aware(2026, 3, 15, 10, 30),
            ),
            build_event(
                uid=own_uid("shift", "1", "zink.nu"), summary="My shift",
                start=_aware(2026, 3, 16, 8, 0), end=_aware(2026, 3, 16, 16, 0),
            ),
        )
        with mock.patch("calendar_sync.services.fetch_ical", return_value=feed):
            resp = self.client.get("/calendar-sync/busy/?year=2026&month=3")
        self.assertEqual(resp.status_code, 200)
        busy = resp.json()["busy"]
        self.assertEqual(len(busy), 1)
        self.assertEqual(busy[0]["summary"], "Dentist")
        self.assertEqual(busy[0]["color"], "#ff0000")

    def test_bad_month_is_400(self):
        resp = self.client.get("/calendar-sync/busy/?year=2026&month=13")
        self.assertEqual(resp.status_code, 400)

    def test_no_subscriptions_returns_empty(self):
        CalendarSubscription.objects.all().delete()
        resp = self.client.get("/calendar-sync/busy/?year=2026&month=3")
        self.assertEqual(resp.json()["busy"], [])

    def test_explicit_range_covers_offset_period_days(self):
        # An offset payroll period makes the August planning grid start on
        # 20 Jul; the padded month window would miss it, but an explicit range
        # (what the grid actually shows) includes it.
        feed = _feed(build_event(
            uid="early@x", summary="Early",
            start=_aware(2026, 7, 20, 9, 0), end=_aware(2026, 7, 20, 10, 0),
        ))
        with mock.patch("calendar_sync.services.fetch_ical", return_value=feed):
            resp = self.client.get("/calendar-sync/busy/?start=2026-07-20&end=2026-09-06")
        self.assertEqual(resp.status_code, 200)
        busy = resp.json()["busy"]
        self.assertEqual(len(busy), 1)
        self.assertEqual(busy[0]["date"], "2026-07-20")

    def test_end_before_start_is_400(self):
        resp = self.client.get("/calendar-sync/busy/?start=2026-08-10&end=2026-08-01")
        self.assertEqual(resp.status_code, 400)

    def test_overwide_range_is_clamped(self):
        # A 2-year span is clamped to MAX_WINDOW_DAYS; an event past the clamp is
        # excluded rather than the request being refused.
        feed = _feed(build_event(
            uid="far@x", summary="Far",
            start=_aware(2027, 1, 1, 9, 0), end=_aware(2027, 1, 1, 10, 0),
        ))
        with mock.patch("calendar_sync.services.fetch_ical", return_value=feed):
            resp = self.client.get("/calendar-sync/busy/?start=2026-01-01&end=2028-01-01")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["busy"], [])
