"""Phase 4 — editing an imported/blank workplace's contract (label + calendar
invites) from the onboarding Review screen, without leaving the wizard."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from calendar_sync.models import ContractCalendarConfig
from core.models import OnboardingDraft, TaxProfile
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


class OnboardingContractEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)  # mid-onboarding: not marked complete
        # A workplace an import created (real DB rows, as Review lists).
        self.wp = Workplace.objects.create(name="Imported Inc")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)
        self.url = reverse("core:onboarding-contract", args=[self.contract.pk])

    def test_get_renders_the_contract_form(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Calendar invites")
        # Back to review, not the (funnel-blocked) workplace detail page.
        self.assertContains(resp, reverse("core:onboarding-review"))

    def test_saves_label_and_invites_then_returns_to_review(self):
        resp = self.client.post(self.url, {
            "name": "Night contract",
            "send_invites": "true",
            "recipient": "boss@work.example",
            "address_onsite": "Main St 1",
        })
        self.assertRedirects(resp, reverse("core:onboarding-review"),
                             fetch_redirect_response=False)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.name, "Night contract")
        cfg = self.contract.calendar_config
        self.assertTrue(cfg.send_invites)
        self.assertEqual(cfg.recipient, "boss@work.example")

    def test_invalid_invite_config_re_renders(self):
        resp = self.client.post(self.url, {
            "name": "", "send_invites": "true", "recipient": "", "address_onsite": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ContractCalendarConfig.objects.filter(contract=self.contract).exists())


class OnboardingReviewWorkplaceRowTests(TestCase):
    """Review lists each imported workplace with an Edit-contract button and, until
    the contract is named / invites are set, a soft nudge with a help '?'."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)
        # Make setup finishable so Review renders (tax + a ready workplace).
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000"), tax_percent=Decimal("37"),
            am_bidrag_percent=Decimal("8"), effective_from=date(2026, 1, 1))
        self.wp = Workplace.objects.create(name="Imported Inc")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=self.contract, effective_from=date(2024, 1, 1),
            employment_type="hourly", hourly_rate=Decimal("180"),
            weekly_hours_fixed=Decimal("37"))
        OnboardingDraft.objects.create(user=self.user, data={"start": {}})

    def test_review_shows_edit_button_and_nudge(self):
        resp = self.client.get(reverse("core:onboarding-review"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn(reverse("core:onboarding-contract", args=[self.contract.pk]), html)
        self.assertIn('data-help-open="calendar-integration"', html)  # the "?" nudge
        self.assertIn("unnamed contract", html)

    def test_nudge_gone_once_named_and_invites_set(self):
        self.contract.name = "Main"
        self.contract.save()
        ContractCalendarConfig.objects.create(
            contract=self.contract, send_invites=True,
            recipient="b@w.example", address_onsite="X")
        html = self.client.get(reverse("core:onboarding-review")).content.decode()
        self.assertNotIn('data-help-open="calendar-integration"', html)
        # But the Edit-contract button is always offered.
        self.assertIn(reverse("core:onboarding-contract", args=[self.contract.pk]), html)
