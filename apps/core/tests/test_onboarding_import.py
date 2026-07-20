"""The onboarding wizard's import path.

Chosen on the Start step (2). A full export carries tax profiles, workplaces,
contracts and term sets — the same things the wizard collects — so an import can
cover setup entirely. It never finishes setup itself, though: every import exits
to the Review step (6), which is the single place both paths commit.
"""
import json
from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import OnboardingDraft, TaxProfile
from core.tests.test_auth import TERMS_POST
from data_io import services
from shifts.models import Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


def _build_export(*, with_tax=True, name="Yoyo Inc"):
    """A real export payload, produced by the exporter and then wiped from the
    database so the import runs against an empty install like a fresh setup."""
    wp = Workplace.objects.create(name=name, slug="", icon="bi-briefcase")
    contract = WorkplaceContract.objects.create(workplace=wp, name="Main")
    ContractTermSet.objects.create(
        contract=contract,
        effective_from=date(2024, 1, 1),
        employment_type=ContractTermSet.EmploymentType.HOURLY,
        hourly_rate=Decimal("185.50"),
        weekly_hours_fixed=Decimal("37.00"),
    )
    Shift.objects.create(
        workplace=wp, date=date(2026, 3, 2),
        start_time=time(8, 0), end_time=time(16, 0),
        break_minutes=30, shift_type="on_site",
    )
    if with_tax:
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4900.00"),
            tax_percent=Decimal("37.00"),
            effective_from=date(2026, 1, 1),
        )

    data = services.export_data(include_tax=with_tax)
    payload = json.dumps(data, cls=services._Encoder)

    Shift.objects.all().delete()
    TaxProfile.objects.all().delete()
    Workplace.objects.all().delete()
    return payload


class OnboardingImportTestCase(TestCase):
    """Mid-onboarding user: logged in, but with setup deliberately unfinished."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)
        self.upload_url = reverse("core:onboarding-import")
        self.confirm_url = reverse("core:onboarding-import-confirm")
        self.review_url = reverse("core:onboarding-review")

    def _upload(self, payload):
        return self.client.post(self.upload_url, {
            "import_file": SimpleUploadedFile(
                "export.json", payload.encode("utf-8"), content_type="application/json"
            ),
        })


class ImportEntryPointTest(OnboardingImportTestCase):
    def test_start_step_offers_the_import(self):
        response = self.client.get(reverse("core:onboarding-start"))
        self.assertContains(response, 'value="import"')

    def test_choosing_import_on_the_start_step_goes_to_the_upload(self):
        response = self.client.post(reverse("core:onboarding-start"), {"setup_method": "import"})
        self.assertRedirects(response, self.upload_url)

    def test_choosing_scratch_goes_to_the_tax_step(self):
        response = self.client.post(reverse("core:onboarding-start"), {"setup_method": "scratch"})
        self.assertRedirects(response, reverse("core:onboarding-tax"))

    def test_an_unknown_method_is_rejected_without_storing(self):
        response = self.client.post(reverse("core:onboarding-start"), {"setup_method": "sneaky"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(OnboardingDraft.objects.filter(user=self.user).exists())

    def test_upload_page_renders(self):
        self.assertEqual(self.client.get(self.upload_url).status_code, 200)

    def test_upload_page_is_not_bounced_by_onboarding_middleware(self):
        """It lives under /onboarding/, so the funnel must let it through."""
        self.assertNotIn("Location", self.client.get(self.upload_url).headers)


class ImportReviewTest(OnboardingImportTestCase):
    def test_upload_shows_review_without_writing_anything(self):
        response = self._upload(_build_export())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Yoyo Inc")
        self.assertContains(response, self.confirm_url)
        # Review only — nothing committed yet.
        self.assertFalse(Workplace.objects.exists())
        self.assertFalse(TaxProfile.objects.exists())

    def test_malformed_file_reports_instead_of_500(self):
        response = self._upload("this is not json")
        self.assertRedirects(response, self.upload_url)

    def test_missing_file_reports(self):
        response = self.client.post(self.upload_url, {})
        self.assertRedirects(response, self.upload_url)

    def test_confirm_without_an_upload_redirects_back(self):
        response = self.client.post(self.confirm_url, {})
        self.assertRedirects(response, self.upload_url)


class ImportExitsToReviewTest(OnboardingImportTestCase):
    """An import writes immediately, but never ends setup on its own."""

    def _import(self, payload=None):
        self._upload(payload if payload is not None else _build_export())
        return self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})

    def test_full_export_lands_on_review_not_the_dashboard(self):
        response = self._import()

        self.assertRedirects(response, self.review_url)
        self.assertTrue(Workplace.objects.filter(name="Yoyo Inc").exists())
        self.assertTrue(ContractTermSet.objects.exists())
        self.assertTrue(TaxProfile.objects.exists())
        self.assertTrue(Shift.objects.exists())
        # Not finished until the user presses Finish on Review.
        self.assertNotIn("onboarding_complete", self.client.session)

    def test_review_reports_full_coverage_and_finishes(self):
        self._import()
        self.assertEqual(self.client.get(self.review_url).status_code, 200)

        response = self.client.post(self.review_url, {})
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertTrue(self.client.session["onboarding_complete"])
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)

    def test_finishing_clears_the_wizard_draft(self):
        OnboardingDraft.objects.create(user=self.user, data={"workplace": {"name": "Typed"}})
        self._import()
        self.client.post(self.review_url, {})
        self.assertFalse(OnboardingDraft.objects.filter(user=self.user).exists())

    def test_import_does_not_duplicate_the_workplace_from_a_stale_draft(self):
        """A draft workplace typed before importing must not be written on top."""
        OnboardingDraft.objects.create(user=self.user, data={"workplace": {"name": "Typed"}})
        self._import()
        self.client.post(self.review_url, {})
        self.assertEqual(Workplace.objects.count(), 1)
        self.assertEqual(Workplace.objects.get().name, "Yoyo Inc")


class ImportGapsTest(OnboardingImportTestCase):
    def test_export_without_tax_lands_on_review_showing_the_gap(self):
        self._upload(_build_export(with_tax=False))
        response = self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})

        self.assertRedirects(response, self.review_url)
        # The workplace data still landed — only the tax gap remains.
        self.assertTrue(Workplace.objects.filter(name="Yoyo Inc").exists())
        self.assertNotIn("onboarding_complete", self.client.session)

        page = self.client.get(self.review_url)
        self.assertContains(page, reverse("core:onboarding-tax"))   # the "Fill this in" link
        self.assertContains(page, "disabled")                       # Finish is blocked

    def test_finish_is_refused_while_a_gap_remains(self):
        self._upload(_build_export(with_tax=False))
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})

        response = self.client.post(self.review_url, {})
        self.assertRedirects(response, reverse("core:onboarding-tax"))
        self.assertNotIn("onboarding_complete", self.client.session)

    def test_a_filled_tax_step_covers_an_export_without_tax(self):
        """Mixed mode: workplace + terms imported, tax typed. Finish must commit
        only the tax draft, and not choke on the absent workplace/terms drafts."""
        OnboardingDraft.objects.create(user=self.user, data={"tax": {
            "monthly_deduction": "4500",
            "tax_percent": "38",
            "am_bidrag_percent": "8",
            "effective_from": "2026-01-01",
        }})
        self._upload(_build_export(with_tax=False))
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})

        response = self.client.post(self.review_url, {})
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertEqual(TaxProfile.objects.get().tax_percent, Decimal("38"))
        self.assertEqual(Workplace.objects.count(), 1)
        self.assertTrue(self.client.session["onboarding_complete"])


class SecondImportTest(OnboardingImportTestCase):
    """Review offers "import another file", so an import runs against whatever a
    previous one already created."""

    def test_review_offers_another_import(self):
        self._upload(_build_export())
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})
        self.assertContains(self.client.get(self.review_url), self.upload_url)

    def test_second_file_offers_mapping_onto_the_first_files_workplace(self):
        """The reason the review page needs the real workplace list: an unmatched
        name in a later file must be mappable onto what the first one created."""
        # Build both payloads up front — _build_export() needs an empty database,
        # and the first import fills it.
        first = _build_export()
        second = _build_export(name="Renamed Co")

        self._upload(first)
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})

        page = self._upload(second)
        self.assertContains(page, "Renamed Co")          # flagged as unmatched
        self.assertContains(page, "Map to: Yoyo Inc")    # ...onto the existing one

    def test_a_matching_workplace_is_not_flagged_as_a_conflict(self):
        payload = _build_export()
        self._upload(payload)
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})
        page = self._upload(payload)
        # Same name → matched automatically, so nothing to resolve.
        self.assertNotContains(page, "Unmatched Workplaces")


class ImportIndicatorTest(OnboardingImportTestCase):
    def test_imported_steps_read_as_done_even_when_ahead(self):
        """A step the database already satisfies is green wherever the user is."""
        self._upload(_build_export())
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})

        page = self.client.get(reverse("core:onboarding-tax"))
        # Both are numbered after the active step, yet render as complete because
        # the import already satisfied them.
        self.assertContains(
            page, 'href="/onboarding/workplace/" class="setup-step setup-step--done"')
        self.assertContains(
            page, 'href="/onboarding/terms/" class="setup-step setup-step--done"')


def _shifts_only_export():
    """A file whose shifts name a workplace it never defines — the shape that
    makes perform_import fabricate a zero-pay contract."""
    return json.dumps({
        "version": 1, "workplaces": [], "planned_shifts": [],
        "tax_profiles": [{"monthly_deduction": "4000", "tax_percent": "37",
                          "am_bidrag_percent": "8", "effective_from": "2026-01-01"}],
        "shifts": [{"workplace_name": "Ghost Co", "date": "2026-03-02",
                    "start_time": "08:00", "end_time": "16:00",
                    "break_minutes": 30, "shift_type": "on_site"}],
    })


class PlaceholderTermsFlowTest(OnboardingImportTestCase):
    def _import_shifts_only(self):
        self._upload(_shifts_only_export())
        return self.client.post(self.confirm_url, {"action_Ghost Co": "create"})

    def test_the_shifts_are_kept(self):
        """The stub exists so these survive — without a contract active on their
        dates they'd be rejected outright."""
        self._import_shifts_only()
        self.assertEqual(Shift.objects.count(), 1)
        self.assertTrue(Workplace.objects.filter(name="Ghost Co").exists())

    def test_review_blocks_finish_and_names_the_workplace(self):
        self._import_shifts_only()
        page = self.client.get(self.review_url)
        self.assertContains(page, "Ghost Co")
        self.assertContains(page, "Set pay terms")
        self.assertContains(page, "disabled")

    def test_finish_is_refused_while_the_stub_survives(self):
        self._import_shifts_only()
        response = self.client.post(self.review_url, {})
        self.assertRedirects(response, reverse("core:onboarding-terms"))
        self.assertNotIn("onboarding_complete", self.client.session)

    def test_the_terms_step_repairs_the_stub_in_place(self):
        self._import_shifts_only()
        stub = ContractTermSet.objects.get()

        page = self.client.get(reverse("core:onboarding-terms"))
        self.assertContains(page, "Ghost Co")
        self.assertContains(page, "placeholder")

        response = self.client.post(reverse("core:onboarding-terms"), TERMS_POST)
        self.assertRedirects(response, self.review_url)

        # Replaced, not duplicated — a second term set would leave the stub
        # covering the imported shift's date, still pricing it at zero.
        self.assertEqual(ContractTermSet.objects.count(), 1)
        stub.refresh_from_db()
        self.assertEqual(stub.monthly_salary, Decimal("40000"))

    def test_finish_works_once_the_terms_are_real(self):
        self._import_shifts_only()
        self.client.post(reverse("core:onboarding-terms"), TERMS_POST)
        response = self.client.post(self.review_url, {})
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertTrue(self.client.session["onboarding_complete"])


class ReviewContentTest(OnboardingImportTestCase):
    """What Review shows besides the required checklist."""

    def test_lists_imported_workplaces(self):
        self._upload(_build_export())
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})
        page = self.client.get(self.review_url)
        self.assertContains(page, "Yoyo Inc")
        self.assertContains(page, "Pay terms set")

    def test_a_workplace_without_terms_is_flagged_in_the_list(self):
        self._upload(_shifts_only_export())
        self.client.post(self.confirm_url, {"action_Ghost Co": "create"})
        page = self.client.get(self.review_url)
        self.assertContains(page, "Needs pay terms")

    def test_shows_the_account_and_offers_the_settings_modals(self):
        page = self.client.get(self.review_url)
        self.assertContains(page, "Your account")
        self.assertContains(page, 'id="accountDetailsModal"')
        self.assertContains(page, 'id="passwordModal"')
        # The modals post to the settings endpoint but must return here.
        self.assertContains(page, self.review_url)

    def test_pay_terms_step_is_yellow_while_a_stub_remains(self):
        self._upload(_shifts_only_export())
        self.client.post(self.confirm_url, {"action_Ghost Co": "create"})
        page = self.client.get(self.review_url)
        self.assertContains(page, "setup-step--started")


class StartOverTest(OnboardingImportTestCase):
    def test_discards_imported_data_and_returns_to_start(self):
        self._upload(_build_export())
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})
        self.assertTrue(Workplace.objects.exists())

        response = self.client.post(reverse("core:onboarding-reset"), {})

        self.assertRedirects(response, reverse("core:onboarding-start"))
        self.assertFalse(Workplace.objects.exists())
        self.assertFalse(TaxProfile.objects.exists())
        self.assertFalse(ContractTermSet.objects.exists())
        self.assertFalse(Shift.objects.exists())
        self.assertFalse(OnboardingDraft.objects.filter(user=self.user).exists())

    def test_the_account_survives(self):
        """Start over resets setup, not the owner — they stay signed in."""
        self.client.post(reverse("core:onboarding-reset"), {})
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertEqual(self.client.get(reverse("core:onboarding-start")).status_code, 200)

    def test_review_offers_it(self):
        self.assertContains(self.client.get(self.review_url), "Start over")

    def test_refused_once_setup_is_complete(self):
        """Never a wipe button for a live install."""
        self._upload(_build_export())
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})
        self.client.post(self.review_url, {})   # finish

        response = self.client.post(reverse("core:onboarding-reset"), {})
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertTrue(Workplace.objects.exists())


class ImportReviewWordingTest(OnboardingImportTestCase):
    """The review page must not use one phrase for two different outcomes."""

    def test_a_described_workplace_says_its_settings_come_too(self):
        page = self._upload(_build_export())
        self.assertContains(page, "with its imported settings")
        self.assertContains(page, "Described in the file")

    def test_a_shifts_only_workplace_warns_terms_are_needed(self):
        page = self._upload(_shifts_only_export())
        self.assertContains(page, "Create blank workplace")
        self.assertContains(page, "Only named on shifts")
        # Nothing to take from the file, so no "keep its settings" option.
        self.assertNotContains(page, "with its imported settings")

    def test_a_described_workplace_offers_both_create_options(self):
        page = self._upload(_build_export())
        self.assertContains(page, "with its imported settings")
        self.assertContains(page, "ignore imported settings")

    def test_choosing_blank_drops_the_files_settings(self):
        self._upload(_build_export())
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create_blank"})
        wp = Workplace.objects.get(name="Yoyo Inc")
        self.assertEqual(wp.contracts.get().name, "")
        # ...and Review then asks for the pay terms it didn't take.
        self.assertContains(self.client.get(self.review_url), "Set pay terms")


class ImportReviewLayoutTest(OnboardingImportTestCase):
    """The review page is step 2 of the wizard, so it must not change width."""

    def test_wrapped_in_the_wizard_column_during_onboarding(self):
        page = self._upload(_build_export())
        self.assertContains(page, "col-12 col-md-10 col-lg-8")
        self.assertContains(page, "setup-steps-track")


class ChromeDuringSetupTest(OnboardingImportTestCase):
    """Importing a complete file satisfies the data check long before the user
    presses Finish. Until they do, no page may hand them the running app."""

    def _import_everything(self):
        # Enter the way a real user does: the Start step is what records that a
        # wizard is under way, which is how "imported everything but hasn't
        # pressed Finish" stays distinguishable from "setup is done".
        self.client.post(reverse("core:onboarding-start"), {"setup_method": "import"})
        self._upload(_build_export())
        self.client.post(self.confirm_url, {"action_Yoyo Inc": "create"})

    def test_help_pages_do_not_show_the_app_navigation(self):
        self._import_everything()
        page = self.client.get("/help/")
        self.assertEqual(page.status_code, 200)
        # The nav pill is the giveaway the bug report described.
        self.assertNotContains(page, "nav-pill--accent")

    def test_help_article_pages_too(self):
        self._import_everything()
        page = self.client.get("/help/first-time-setup/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "nav-pill--accent")

    def test_the_funnel_still_catches_the_dashboard(self):
        self._import_everything()
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 302)

    def test_the_full_manual_button_is_hidden_during_setup(self):
        """The popup is enough here — the manual is a full app page."""
        self._import_everything()
        self.assertNotContains(self.client.get(self.review_url), "Full manual")

    def test_the_app_opens_up_once_finish_is_pressed(self):
        self._import_everything()
        self.client.post(self.review_url, {})   # Finish

        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)
        self.assertContains(self.client.get("/help/"), "nav-pill--accent")
