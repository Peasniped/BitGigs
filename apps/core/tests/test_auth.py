"""Login gate + onboarding wizard (deferred submission)."""
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase

from django.core.exceptions import ValidationError

from core import setup_key
from core.utils import dk_slugify
from core.models import TaxProfile, OnboardingDraft
from core.validators import (
    CharacterClassesPasswordValidator,
    NoSequencesPasswordValidator,
)
from workplaces.models import Workplace, WorkplaceContract, ContractTermSet


# A password that satisfies every validator (length, all four character classes,
# no repeated/sequential run, unlike the email).
VALID_PW = "Vqz#8mtLp4"

# Valid per-step payloads for the wizard (see the respective ModelForms).
TAX_POST = {
    "effective_from": "2026-01-01",
    "monthly_deduction": "4000",
    "tax_percent": "37",
    "am_bidrag_percent": "8",
}
# The contract's optional label rides along on the workplace step, prefixed.
WORKPLACE_POST = {"name": "Jåd Kå Æf", "contract-name": ""}
TERMS_POST = {
    "effective_from": "2026-01-01",
    "employment_type": "salaried",
    "work_time_type": "fuldtid",
    "monthly_salary": "40000",
    "payroll_period_start_day": "1",
    "tax_card_type": "hovedkort",
    "vacation_type": "feriekonto",
    "pension_employee_percent": "0",
    "pension_employer_percent": "0",
    "fritvalgskonto_percent": "0",
    "fritvalgskonto_payout_type": "accrues",
    "ferietillaeg_percent": "1.00",
    "ferietillaeg_payout_months": "5,8",
    "hour_goal_type": "",
}


class SetupKeyMixin:
    """Points the setup key at a temp file, so tests never read or clobber the
    real instance/setup_key.txt."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = self.settings(SETUP_KEY_PATH=Path(self._tmp.name) / "setup_key.txt")
        override.enable()
        self.addCleanup(override.disable)
        super().setUp()

    def claim(self):
        """Pass the setup-key gate — every later page of the account step needs it."""
        return self.client.post("/onboarding/account/",
                                {"setup_key": setup_key.get_or_create_key()})

    def account_post(self, **overrides):
        payload = {
            "first_name": "Alex",   # display name, required (see the form)
            "username": "me@example.com",
            "password1": VALID_PW,
            "password2": VALID_PW,
        }
        payload.update(overrides)
        return payload


class LoginGateTest(TestCase):
    """With an account in place, everything anonymous funnels to login."""

    def setUp(self):
        self.user = User.objects.create_user("tester@example.com", password="pw")

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/accounts/login/"))

    def test_login_page_renders_anonymously(self):
        resp = self.client.get("/accounts/login/")
        self.assertEqual(resp.status_code, 200)

    def test_authenticated_user_passes_the_gate(self):
        self.client.force_login(self.user)
        resp = self.client.get("/")
        # Onboarding middleware may redirect to the wizard, but never to login.
        if resp.status_code == 302:
            self.assertFalse(resp["Location"].startswith("/accounts/login/"))
        else:
            self.assertEqual(resp.status_code, 200)


class OnboardingAccountTest(SetupKeyMixin, TestCase):
    """Fresh install: onboarding starts with account creation, gated by the setup
    key so a stranger can't win the race to claim the instance."""

    def test_everything_redirects_to_account_step_when_no_users(self):
        for path in ("/", "/accounts/login/", "/workplaces/"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertEqual(resp["Location"], "/onboarding/account/", path)

    def test_key_page_renders_and_the_email_page_is_gated(self):
        self.assertEqual(self.client.get("/onboarding/account/").status_code, 200)
        # Without the key, the pages behind it bounce back to the key page.
        self.assertRedirects(self.client.get("/onboarding/account/email/"), "/onboarding/account/")

    def test_account_step_creates_admin_user_after_the_key(self):
        self.claim()
        resp = self.client.post("/onboarding/account/email/", self.account_post())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/onboarding/")
        user = User.objects.get(username="me@example.com")
        self.assertTrue(user.is_superuser)
        # Username is a valid email and is copied to the email field.
        self.assertEqual(user.email, "me@example.com")
        # The display name is what the app greets by — the username is an email.
        self.assertEqual(user.first_name, "Alex")

    def test_display_name_is_required(self):
        """Without it every greeting would address the owner by email address."""
        self.claim()
        resp = self.client.post(
            "/onboarding/account/email/", self.account_post(first_name="  ")
        )
        self.assertEqual(resp.status_code, 200)   # redisplayed, not created
        self.assertFalse(User.objects.filter(username="me@example.com").exists())

    def test_the_key_is_deleted_once_the_owner_exists(self):
        self.claim()
        self.client.post("/onboarding/account/email/", self.account_post())
        self.assertFalse(setup_key.key_path().exists())

    def test_a_wrong_setup_key_does_not_open_the_gate(self):
        resp = self.client.post("/onboarding/account/", {"setup_key": "nope-nope-nope"})
        self.assertEqual(resp.status_code, 200)  # re-rendered with an error
        self.assertRedirects(self.client.get("/onboarding/account/email/"), "/onboarding/account/")
        self.assertFalse(User.objects.exists())

    def test_no_account_can_be_posted_without_passing_the_gate(self):
        resp = self.client.post("/onboarding/account/email/", self.account_post())
        self.assertRedirects(resp, "/onboarding/account/")
        self.assertFalse(User.objects.exists())

    def test_account_step_rejects_non_email_username(self):
        self.claim()
        resp = self.client.post("/onboarding/account/email/", self.account_post(username="notanemail"))
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertFalse(User.objects.exists())

    def test_key_page_skips_the_method_chooser_when_sso_is_off(self):
        with self.settings(SSO_ENABLED=False):
            self.assertRedirects(self.claim(), "/onboarding/account/email/")

    def test_account_step_is_gone_once_a_user_exists(self):
        User.objects.create_user("existing@example.com", password="pw")
        resp = self.client.get("/onboarding/account/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/accounts/login/")


class OnboardingWizardTest(TestCase):
    """The wizard holds every step in the session and writes to the DB only on
    the final Finish."""

    def setUp(self):
        self.user = User.objects.create_superuser("me@example.com", password="pw")
        self.client.force_login(self.user)

    def _finish(self):
        """Complete the scratch path. Pay Terms only stores now — Review commits."""
        return self.client.post("/onboarding/review/", {})

    def test_incomplete_onboarding_funnels_into_the_wizard(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/onboarding/")

    def test_nothing_is_saved_until_finish(self):
        self.assertEqual(self.client.post("/onboarding/tax/", TAX_POST).status_code, 302)
        self.assertEqual(self.client.post("/onboarding/workplace/", WORKPLACE_POST).status_code, 302)

        # Two steps completed, still nothing written.
        self.assertFalse(TaxProfile.objects.exists())
        self.assertFalse(Workplace.objects.exists())
        self.assertFalse(WorkplaceContract.objects.exists())
        self.assertFalse(ContractTermSet.objects.exists())

        # The terms step stores too — still nothing written.
        self.client.post("/onboarding/terms/", TERMS_POST)
        self.assertFalse(TaxProfile.objects.exists())
        self.assertFalse(ContractTermSet.objects.exists())

        # Finish (on Review) writes all four atomically.
        resp = self._finish()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/")
        self.assertEqual(TaxProfile.objects.count(), 1)
        self.assertEqual(Workplace.objects.count(), 1)
        self.assertEqual(WorkplaceContract.objects.count(), 1)
        self.assertEqual(ContractTermSet.objects.count(), 1)
        # Danish-aware slug.
        self.assertEqual(Workplace.objects.get().slug, "jaad-kaa-aef")

    def test_back_navigation_keeps_entered_values(self):
        self.client.post("/onboarding/tax/", TAX_POST)
        self.client.post("/onboarding/workplace/", WORKPLACE_POST)
        # Re-visiting an earlier step re-renders the stored input without errors.
        resp = self.client.get("/onboarding/tax/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "4000")

    def test_each_wizard_page_renders(self):
        # Store data for every step, then GET each page (reused CRUD templates
        # rendered with transient, unsaved workplace/contract objects).
        self.client.post("/onboarding/tax/", TAX_POST)
        self.client.post("/onboarding/workplace/", WORKPLACE_POST)
        for path in ("/onboarding/account/", "/onboarding/start/", "/onboarding/tax/",
                     "/onboarding/workplace/", "/onboarding/terms/", "/onboarding/review/"):
            resp = self.client.get(path)
            # account step is gone once a user exists → 302; the rest render.
            expected = 302 if path.endswith("/account/") else 200
            self.assertEqual(resp.status_code, expected, path)

    def test_contract_step_is_gone(self):
        self.assertEqual(self.client.get("/onboarding/contract/").status_code, 404)

    def test_contract_label_is_carried_by_the_workplace_step(self):
        self.client.post("/onboarding/tax/", TAX_POST)
        self.client.post("/onboarding/workplace/", dict(WORKPLACE_POST, **{"contract-name": "Physics Lab"}))
        self.client.post("/onboarding/terms/", TERMS_POST)
        self._finish()

        contract = WorkplaceContract.objects.get()
        self.assertEqual(contract.name, "Physics Lab")
        self.assertEqual(contract.workplace, Workplace.objects.get())

    def test_contract_is_created_even_without_a_label(self):
        self.client.post("/onboarding/tax/", TAX_POST)
        self.client.post("/onboarding/workplace/", WORKPLACE_POST)  # contract-name blank
        self.client.post("/onboarding/terms/", TERMS_POST)
        self._finish()

        contract = WorkplaceContract.objects.get()
        self.assertEqual(contract.name, "")
        self.assertEqual(contract.workplace, Workplace.objects.get())

    def test_workplace_step_re_shows_the_stored_contract_label(self):
        self.client.post("/onboarding/workplace/", dict(WORKPLACE_POST, **{"contract-name": "Physics Lab"}))
        resp = self.client.get("/onboarding/workplace/")
        self.assertContains(resp, "Physics Lab")

    def test_dashboard_reachable_after_finish(self):
        self.client.post("/onboarding/tax/", TAX_POST)
        self.client.post("/onboarding/workplace/", WORKPLACE_POST)
        self.client.post("/onboarding/terms/", TERMS_POST)
        self._finish()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_draft_survives_logout(self):
        # Data is held in a durable per-user DB draft, not the session.
        self.client.post("/onboarding/tax/", TAX_POST)
        self.assertTrue(OnboardingDraft.objects.filter(user=self.user).exists())
        self.client.logout()  # flushes the session
        self.client.force_login(self.user)
        resp = self.client.get("/onboarding/tax/")
        self.assertContains(resp, "4000")  # re-shown from the draft

    def test_draft_deleted_after_finish(self):
        self.client.post("/onboarding/tax/", TAX_POST)
        self.client.post("/onboarding/workplace/", WORKPLACE_POST)
        self.client.post("/onboarding/terms/", TERMS_POST)
        self._finish()
        self.assertFalse(OnboardingDraft.objects.filter(user=self.user).exists())

    def test_earlier_navigation_marks_ahead_step_started(self):
        self.client.post("/onboarding/tax/", TAX_POST)
        self.client.post("/onboarding/workplace/", WORKPLACE_POST)
        # Back on the tax page, the already-filled Workplace step is "started".
        resp = self.client.get("/onboarding/tax/")
        self.assertContains(resp, "setup-step--started")


class PasswordValidatorTest(TestCase):
    def test_character_classes_required(self):
        v = CharacterClassesPasswordValidator()
        for bad in (
            "VQZ#8MTLP4",  # no lowercase
            "vqz#8mtlp4",  # no uppercase
            "Vqz#mtLpx",   # no number
            "Vqz8mtLp4",   # no symbol
        ):
            with self.assertRaises(ValidationError):
                v.validate(bad)
        v.validate(VALID_PW)  # has all four → ok

    def test_no_repeated_or_sequential_runs(self):
        v = NoSequencesPasswordValidator()
        for bad in ("Xaaa#9mt", "Xabc#9mt", "Xqz#123p"):
            with self.assertRaises(ValidationError):
                v.validate(bad)
        v.validate(VALID_PW)  # clean → no raise


class DkSlugifyTest(TestCase):
    def test_danish_letters_transliterated(self):
        self.assertEqual(dk_slugify("Jåd Kå Æf"), "jaad-kaa-aef")
        self.assertEqual(dk_slugify("Rødgrød med fløde"), "roedgroed-med-floede")
        self.assertEqual(dk_slugify(""), "")
