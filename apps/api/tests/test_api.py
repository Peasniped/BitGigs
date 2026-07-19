"""API key lifecycle, Bearer auth, and the income endpoint."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from api.models import ApiKey, SCOPE_ALL, hash_key
from api.services import PeriodError, resolve_income_period
from core.models import TaxProfile
from workplaces.models import Workplace, WorkplaceContract, ContractTermSet
from shifts.models import Shift


def issue(name="test", scopes=None, expires_at=None):
    return ApiKey.issue(name=name, scopes=scopes or [SCOPE_ALL], expires_at=expires_at)


def auth_header(raw_key):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_key}"}


class ApiKeyModelTest(TestCase):
    def test_issue_stores_only_the_hash(self):
        key, raw = issue()
        self.assertTrue(raw.startswith("bg_"))
        self.assertNotIn(raw, key.key_hash)
        self.assertEqual(key.key_hash, hash_key(raw))
        self.assertEqual(key.prefix, raw[:12])

    def test_find_matches_only_the_right_key(self):
        _, raw = issue()
        self.assertIsNotNone(ApiKey.find(raw))
        self.assertIsNone(ApiKey.find("bg_not-a-real-key"))
        self.assertIsNone(ApiKey.find(""))

    def test_expiry_and_revocation_state(self):
        key, _ = issue(expires_at=timezone.localdate() - timedelta(days=1))
        self.assertTrue(key.is_expired)
        self.assertFalse(key.is_active)
        fresh, _ = issue()
        self.assertTrue(fresh.is_active)
        fresh.revoke()
        self.assertFalse(fresh.is_active)

    def test_scopes(self):
        all_key, _ = issue(scopes=[SCOPE_ALL])
        self.assertTrue(all_key.allows("income"))
        narrow, _ = issue(scopes=["income"])
        self.assertTrue(narrow.allows("income"))
        self.assertFalse(narrow.allows("something-else"))


class ApiAuthTest(TestCase):
    """The ping endpoint is the auth layer's test bench: any valid key works,
    and every failure mode has its own error code."""

    def test_missing_key_is_401(self):
        response = self.client.get(reverse("api:v1-ping"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "missing_key")

    def test_invalid_key_is_401(self):
        response = self.client.get(reverse("api:v1-ping"), **auth_header("bg_bogus"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_key")

    def test_revoked_key_is_401(self):
        key, raw = issue()
        key.revoke()
        response = self.client.get(reverse("api:v1-ping"), **auth_header(raw))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "revoked_key")

    def test_expired_key_is_401(self):
        _, raw = issue(expires_at=timezone.localdate() - timedelta(days=1))
        response = self.client.get(reverse("api:v1-ping"), **auth_header(raw))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "expired_key")

    def test_out_of_scope_key_is_403(self):
        _, raw = issue(scopes=["ping-only-nonsense"])
        response = self.client.get(reverse("api:v1-income"), **auth_header(raw))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "insufficient_scope")

    def test_valid_key_pings_and_stamps_last_used(self):
        key, raw = issue(name="probe", scopes=["income"])
        self.assertIsNone(key.last_used_at)
        response = self.client.get(reverse("api:v1-ping"), **auth_header(raw))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["key"], "probe")
        self.assertEqual(data["scopes"], ["income"])
        key.refresh_from_db()
        self.assertIsNotNone(key.last_used_at)

    def test_session_login_does_not_replace_the_key(self):
        # A logged-in browser without a key still gets a 401 — the API is
        # key-authenticated only.
        user = User.objects.create_user("tester", password="pw")
        self.client.force_login(user)
        response = self.client.get(reverse("api:v1-ping"))
        self.assertEqual(response.status_code, 401)


class PeriodResolutionTest(TestCase):
    def test_year_month_and_range_forms(self):
        self.assertEqual(
            resolve_income_period(2026, None, None, None),
            (date(2026, 1, 1), date(2026, 12, 31)),
        )
        self.assertEqual(
            resolve_income_period(2026, 7, None, None),
            (date(2026, 7, 1), date(2026, 7, 31)),
        )
        self.assertEqual(
            resolve_income_period(None, None, "2026-01", "2026-06"),
            (date(2026, 1, 1), date(2026, 6, 30)),
        )

    def test_bad_input_raises(self):
        for args in [
            (None, 7, None, None),            # month without year
            (2026, 13, None, None),           # month out of range
            (None, None, "2026-01", None),    # start without end
            (None, None, "01-2026", "2026-06"),  # wrong format
            (None, None, "2026-06", "2026-01"),  # end before start
            (2026, None, "2026-01", "2026-06"),  # both forms at once
            (None, None, "2000-01", "2026-06"),  # over the range cap
        ]:
            with self.assertRaises(PeriodError):
                resolve_income_period(*args)


class IncomeEndpointTest(TestCase):
    """One hourly workplace with two approved shifts in the previous calendar
    month (a guaranteed *past* month, so the endpoint reports their actual
    hours regardless of when the test runs — the income endpoint always uses
    the real today, like the Analytics page)."""

    def setUp(self):
        today = timezone.localdate()
        prev = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        self.prev_key = f"{prev.year:04d}-{prev.month:02d}"
        self.prev = prev
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2020, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Acme")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2020, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
        )
        for day in (1, 2):
            Shift.objects.create(
                workplace=self.wp, date=prev.replace(day=day),
                start_time="08:00", end_time="16:00", break_minutes=0,
            )
        _, self.raw_key = issue(scopes=["income"])

    def get(self, **params):
        return self.client.get(
            reverse("api:v1-income"), params, **auth_header(self.raw_key)
        )

    def test_month_payload(self):
        response = self.get(year=self.prev.year, month=self.prev.month)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["start"], self.prev_key)
        self.assertEqual(data["end"], self.prev_key)
        self.assertEqual(len(data["months"]), 1)
        month = data["months"][0]
        self.assertEqual(month["month"], self.prev_key)
        self.assertGreater(Decimal(month["gross"]), Decimal("0"))
        self.assertGreater(Decimal(month["net"]), Decimal("0"))
        self.assertLess(Decimal(month["net"]), Decimal(month["gross"]))
        # Per-workplace breakdown carries the same totals.
        wp = data["workplaces"][0]
        self.assertEqual(wp["slug"], self.wp.slug)
        self.assertEqual(wp["total_gross"], month["gross"])

    def test_range_payload_totals_are_the_month_sum(self):
        two_back = (self.prev.replace(day=1) - timedelta(days=1)).replace(day=1)
        start_key = f"{two_back.year:04d}-{two_back.month:02d}"
        response = self.get(start=start_key, end=self.prev_key)
        data = response.json()
        self.assertEqual([m["month"] for m in data["months"]],
                         [start_key, self.prev_key])
        total = sum(Decimal(m["gross"]) for m in data["months"])
        self.assertEqual(Decimal(data["totals"]["gross"]), total)

    def test_bad_params_are_400(self):
        response = self.get(year=2026, month=13)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad_request")


class KeyManagementViewsTest(TestCase):
    """Settings-tab management endpoints — session-gated like every page."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_create_flow_shows_key_once(self):
        response = self.client.post(reverse("api:key-create"), {
            "name": "My script", "scope_mode": "all",
        })
        # fetch_redirect_response=False: following the redirect here would
        # itself consume the one-time session copy of the key.
        self.assertRedirects(response, f"{reverse('core:settings')}?tab=api",
                             fetch_redirect_response=False)
        key = ApiKey.objects.get()
        self.assertEqual(key.scopes, [SCOPE_ALL])

        # First render of the tab reveals the key…
        page = self.client.get(f"{reverse('core:settings')}?tab=api")
        content = page.content.decode()
        self.assertIn("bg_", content)
        self.assertIn("Your new API key", content)
        # …and the second does not: the session copy was popped.
        page = self.client.get(f"{reverse('core:settings')}?tab=api")
        self.assertNotIn("Your new API key", page.content.decode())

    def test_create_with_selected_scopes(self):
        self.client.post(reverse("api:key-create"), {
            "name": "Narrow", "scope_mode": "selected", "scopes": ["income"],
        })
        self.assertEqual(ApiKey.objects.get().scopes, ["income"])

    def test_create_rejects_bad_input(self):
        # No name.
        self.client.post(reverse("api:key-create"), {"name": "", "scope_mode": "all"})
        # Selected mode with nothing selected.
        self.client.post(reverse("api:key-create"), {"name": "x", "scope_mode": "selected"})
        # Unknown scope ids are dropped, leaving nothing.
        self.client.post(reverse("api:key-create"), {
            "name": "x", "scope_mode": "selected", "scopes": ["bogus"],
        })
        # Expiry in the past.
        self.client.post(reverse("api:key-create"), {
            "name": "x", "scope_mode": "all",
            "expires_at": (timezone.localdate() - timedelta(days=1)).isoformat(),
        })
        self.assertEqual(ApiKey.objects.count(), 0)

    def test_revoke_then_delete(self):
        key, _ = issue()
        self.client.post(reverse("api:key-revoke", args=[key.pk]))
        key.refresh_from_db()
        self.assertTrue(key.is_revoked)

        # Deleting an active key is refused; a revoked one goes.
        other, _ = issue(name="active")
        self.client.post(reverse("api:key-delete", args=[other.pk]))
        self.assertTrue(ApiKey.objects.filter(pk=other.pk).exists())
        self.client.post(reverse("api:key-delete", args=[key.pk]))
        self.assertFalse(ApiKey.objects.filter(pk=key.pk).exists())

    def test_management_requires_login(self):
        self.client.logout()
        response = self.client.post(reverse("api:key-create"), {
            "name": "sneaky", "scope_mode": "all",
        })
        # Bounced by the login gate, no key created.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ApiKey.objects.count(), 0)
