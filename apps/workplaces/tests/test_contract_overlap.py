"""The model must reject a second contract that overlaps an existing one."""
from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from workplaces.models import Workplace, WorkplaceContract


class ContractOverlapValidationTest(TestCase):
    def setUp(self):
        self.wp = Workplace.objects.create(name="Acme")
        WorkplaceContract.objects.create(
            workplace=self.wp, name="First", start_date=date(2024, 1, 1),
        )

    def test_overlapping_contract_fails_full_clean(self):
        clash = WorkplaceContract(
            workplace=self.wp, name="Second", start_date=date(2024, 6, 1),
        )
        with self.assertRaises(ValidationError):
            clash.full_clean()

    def test_non_overlapping_contract_passes(self):
        # Close the first contract, then start a new one the next day.
        first = self.wp.contracts.get(name="First")
        first.end_date = date(2024, 6, 30)
        first.save()
        later = WorkplaceContract(
            workplace=self.wp, name="Second", start_date=date(2024, 7, 1),
        )
        later.full_clean()  # should not raise

    def test_only_one_contract_active_on_a_date(self):
        first = self.wp.contracts.get(name="First")
        first.end_date = date(2024, 6, 30)
        first.save()
        WorkplaceContract.objects.create(
            workplace=self.wp, name="Second", start_date=date(2024, 7, 1),
        )
        self.assertEqual(self.wp.active_contract_on(date(2024, 3, 1)).name, "First")
        self.assertEqual(self.wp.active_contract_on(date(2024, 8, 1)).name, "Second")


class ContractOverlapShortcutViewTest(TestCase):
    def setUp(self):
        self.wp = Workplace.objects.create(name="Acme", slug="acme")
        self.old = WorkplaceContract.objects.create(
            workplace=self.wp, name="Old", start_date=date(2024, 1, 1),
        )
        self.url = reverse("workplaces:contract-create", args=[self.wp.slug])

    def test_overlap_offers_end_shortcut(self):
        resp = self.client.post(self.url, {
            "name": "New", "start_date": "2026-07-06", "end_date": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "overlaps with")
        self.assertEqual(resp.context["overlap_contract"].pk, self.old.pk)
        self.assertEqual(resp.context["overlap_end_date"], date(2026, 7, 5))
        self.assertFalse(self.wp.contracts.filter(name="New").exists())

    def test_end_overlapping_ends_old_and_creates_new(self):
        resp = self.client.post(self.url, {
            "name": "New", "start_date": "2026-07-06", "end_date": "",
            "end_overlapping": str(self.old.pk),
        })
        self.assertEqual(resp.status_code, 302)  # redirects to add terms
        self.old.refresh_from_db()
        self.assertEqual(self.old.end_date, date(2026, 7, 5))
        self.assertTrue(self.wp.contracts.filter(name="New").exists())

    def test_same_day_start_offers_no_shortcut(self):
        # Only a same-day-starting contract overlaps → it can't be ended cleanly.
        self.old.delete()
        WorkplaceContract.objects.create(
            workplace=self.wp, name="Sameday", start_date=date(2026, 7, 6),
        )
        resp = self.client.post(self.url, {
            "name": "New", "start_date": "2026-07-06", "end_date": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["overlap_contract"])
