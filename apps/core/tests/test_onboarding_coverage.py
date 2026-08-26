"""Setup coverage and the partial commit.

Coverage answers "what does this install still need?", where each piece may be
satisfied either by a row an import already wrote or by a valid wizard draft that
Finish will write. These are unit tests over that logic with no HTTP client — the
branching is what the Review screen and the commit both depend on.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from core import onboarding as ob
from core.models import OnboardingDraft
from tax.models import TaxProfile
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract

TAX_DRAFT = {
    "monthly_deduction": "4000",
    "tax_percent": "37",
    "am_bidrag_percent": "8",
    "effective_from": "2026-01-01",
}
WORKPLACE_DRAFT = {"name": "Jåd Kå Æf", "slug": "", "contract-name": ""}
TERMS_DRAFT = {
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


class CoverageTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.request = RequestFactory().get("/onboarding/review/")
        self.request.user = self.user
        self.request.session = {}

    def draft(self, **payloads):
        OnboardingDraft.objects.update_or_create(user=self.user, defaults={"data": payloads})

    def cov(self):
        return ob.coverage(self.request)

    # ── helpers that put real rows in the database, as an import would ──
    def make_tax(self):
        TaxProfile.objects.create(monthly_deduction=Decimal("4000"), tax_percent=Decimal("37"),
                                  am_bidrag_percent=Decimal("8"), effective_from=date(2026, 1, 1))

    def make_workplace(self, with_contract=True, with_terms=True):
        wp = Workplace.objects.create(name="Imported Inc")
        if not with_contract:
            return wp
        contract = WorkplaceContract.objects.create(workplace=wp, name="Main")
        if with_terms:
            ContractTermSet.objects.create(
                contract=contract, effective_from=date(2024, 1, 1),
                employment_type="hourly", hourly_rate=Decimal("180"),
                weekly_hours_fixed=Decimal("37"))
        return wp


class CoverageStateTest(CoverageTestCase):
    def test_empty_install_covers_nothing(self):
        cov = self.cov()
        self.assertFalse(cov.has_tax)
        self.assertFalse(cov.has_terms)
        self.assertFalse(cov.can_finish)
        self.assertEqual(cov.missing(), ["tax", "workplace"])

    def test_rows_in_the_database_count_as_covered(self):
        self.make_tax()
        self.make_workplace()
        cov = self.cov()
        self.assertTrue(cov.tax.in_db)
        self.assertFalse(cov.tax.from_draft)
        self.assertTrue(cov.can_finish)
        self.assertEqual(cov.missing(), [])

    def test_a_valid_draft_covers_a_piece_but_marks_it_unwritten(self):
        self.draft(tax=TAX_DRAFT)
        cov = self.cov()
        self.assertTrue(cov.tax.covered)
        self.assertTrue(cov.tax.from_draft)
        self.assertFalse(cov.tax.in_db)

    def test_an_invalid_draft_is_started_not_covered(self):
        self.draft(tax=dict(TAX_DRAFT, tax_percent=""))
        cov = self.cov()
        self.assertEqual(cov.tax.draft, "started")
        self.assertFalse(cov.tax.covered)

    def test_terms_draft_alone_does_not_cover_pay_terms(self):
        """Pay terms need a workplace to hang on — the interdependency."""
        self.draft(terms=TERMS_DRAFT)
        self.assertFalse(self.cov().has_terms)

    def test_terms_plus_workplace_drafts_cover_pay_terms(self):
        self.draft(workplace=WORKPLACE_DRAFT, terms=TERMS_DRAFT)
        self.assertTrue(self.cov().has_terms)

    def test_imported_workplace_without_contracts_is_not_covered(self):
        """An export may carry "contracts": [], creating a Workplace no term set
        can attach to. Treating that as covered would green-light a dead end."""
        self.make_workplace(with_contract=False)
        cov = self.cov()
        self.assertTrue(Workplace.objects.exists())
        self.assertFalse(cov.workplace.in_db)
        self.assertFalse(cov.has_terms)

    def test_shifts_are_counted_but_never_block(self):
        from shifts.models import Shift
        self.make_tax()
        wp = self.make_workplace()
        Shift.objects.create(workplace=wp, date=date(2026, 3, 2),
                             start_time="08:00", end_time="16:00",
                             break_minutes=0, shift_type="on_site")
        cov = self.cov()
        self.assertEqual(cov.shifts, 1)
        self.assertTrue(cov.can_finish)

    def test_no_shifts_still_finishes(self):
        self.make_tax()
        self.make_workplace()
        cov = self.cov()
        self.assertEqual(cov.shifts, 0)
        self.assertEqual(cov.planned, 0)
        self.assertTrue(cov.can_finish)


class CommitSetupTest(CoverageTestCase):
    def test_full_scratch_draft_writes_everything(self):
        self.draft(tax=TAX_DRAFT, workplace=WORKPLACE_DRAFT, terms=TERMS_DRAFT)
        self.assertIs(ob.commit_setup(self.request), True)
        self.assertEqual(TaxProfile.objects.count(), 1)
        self.assertEqual(Workplace.objects.count(), 1)
        self.assertEqual(WorkplaceContract.objects.count(), 1)
        self.assertEqual(ContractTermSet.objects.count(), 1)

    def test_gaps_are_reported_not_written(self):
        self.draft(tax=TAX_DRAFT)
        result = ob.commit_setup(self.request)
        self.assertEqual(result[0], "workplace")
        self.assertFalse(TaxProfile.objects.exists())   # nothing partial

    def test_tax_already_imported_is_not_written_twice(self):
        self.make_tax()
        self.draft(tax=TAX_DRAFT, workplace=WORKPLACE_DRAFT, terms=TERMS_DRAFT)
        self.assertIs(ob.commit_setup(self.request), True)
        self.assertEqual(TaxProfile.objects.count(), 1)

    def test_imported_workplace_and_terms_leave_the_drafts_unused(self):
        """Mixed mode: only the tax draft should be written."""
        self.make_workplace()
        self.draft(tax=TAX_DRAFT, workplace=WORKPLACE_DRAFT, terms=TERMS_DRAFT)
        self.assertIs(ob.commit_setup(self.request), True)
        self.assertEqual(Workplace.objects.count(), 1)
        self.assertEqual(Workplace.objects.get().name, "Imported Inc")
        self.assertEqual(TaxProfile.objects.count(), 1)

    def test_commits_with_no_workplace_draft_at_all(self):
        """The import path leaves those keys absent entirely."""
        self.make_workplace()
        self.draft(tax=TAX_DRAFT)
        self.assertIs(ob.commit_setup(self.request), True)
        self.assertEqual(TaxProfile.objects.count(), 1)

    def test_terms_attach_to_a_single_termless_imported_contract(self):
        self.make_workplace(with_terms=False)
        self.make_tax()
        self.draft(terms=TERMS_DRAFT)
        self.assertIs(ob.commit_setup(self.request), True)
        self.assertEqual(Workplace.objects.count(), 1)      # no second workplace
        self.assertEqual(ContractTermSet.objects.count(), 1)
        self.assertEqual(ContractTermSet.objects.get().contract.workplace.name, "Imported Inc")

    def test_ambiguous_termless_contracts_are_not_guessed(self):
        """Two candidates → don't silently pin pay terms to an arbitrary job."""
        wp = self.make_workplace(with_terms=False)
        WorkplaceContract.objects.create(workplace=wp, name="Second")
        self.assertIsNone(ob._terms_target_contract(self.cov()))

    def test_a_late_failure_rolls_back_everything_the_draft_wrote(self):
        """The atomic boundary.

        Tax is written first, the workplace second and the terms last, so a
        failure on the terms must undo the two rows already inserted in this
        request. Forced with a patch rather than bad input on purpose: the
        contract-bound validations (term-set succession, contract overlap) can
        only fire against sibling rows, and a freshly created contract has none —
        so no natural input reaches this branch. The transaction still has to be
        right if that ever changes."""
        from unittest.mock import patch
        from django.core.exceptions import ValidationError
        from workplaces.forms import ContractTermSetForm

        self.draft(tax=TAX_DRAFT, workplace=WORKPLACE_DRAFT, terms=TERMS_DRAFT)
        with patch.object(ContractTermSetForm, "save",
                          side_effect=ValidationError("terms")):
            result = ob.commit_setup(self.request)

        self.assertEqual(result[0], "terms")
        self.assertFalse(TaxProfile.objects.exists())
        self.assertFalse(Workplace.objects.exists())
        self.assertFalse(WorkplaceContract.objects.exists())
        self.assertFalse(ContractTermSet.objects.exists())


class PlaceholderTermsTest(CoverageTestCase):
    """A file whose shifts name a workplace it never defines.

    perform_import writes a zero-pay stub so the shifts have a contract active on
    their dates — without one they'd be rejected outright. That stub prices every
    imported shift at zero, so setup must not finish while it survives.
    """

    def make_placeholder(self, name="Ghost Co"):
        wp = Workplace.objects.create(name=name)
        contract = WorkplaceContract.objects.create(workplace=wp)
        return ContractTermSet.objects.create(
            contract=contract, effective_from=date(2000, 1, 1),
            employment_type="hourly", hourly_rate=Decimal("0"),
            weekly_hours_fixed=Decimal("37"))

    def test_a_zero_pay_termset_is_detected(self):
        self.make_placeholder()
        cov = self.cov()
        self.assertEqual(cov.placeholder_names, ["Ghost Co"])

    def test_real_terms_are_not_mistaken_for_a_placeholder(self):
        self.make_workplace()          # hourly_rate 180
        self.assertEqual(self.cov().placeholders, ())

    def test_a_salaried_termset_is_not_a_placeholder(self):
        wp = Workplace.objects.create(name="Salaried Inc")
        contract = WorkplaceContract.objects.create(workplace=wp)
        ContractTermSet.objects.create(
            contract=contract, effective_from=date(2024, 1, 1),
            employment_type="salaried", monthly_salary=Decimal("40000"),
            weekly_hours_fixed=Decimal("37"))
        self.assertEqual(self.cov().placeholders, ())

    def test_a_placeholder_blocks_finish_even_with_tax_and_other_terms(self):
        self.make_tax()
        self.make_workplace()          # a fully valid second workplace
        self.make_placeholder()
        cov = self.cov()
        self.assertTrue(cov.has_tax)
        self.assertTrue(cov.has_terms)
        self.assertFalse(cov.can_finish)    # ...but the stub still blocks
        self.assertEqual(cov.missing(), ["terms"])

    def test_commit_is_refused_while_a_placeholder_remains(self):
        self.make_tax()
        self.make_placeholder()
        result = ob.commit_setup(self.request)
        self.assertEqual(result[0], "terms")

    def test_finish_is_allowed_once_the_stub_carries_real_pay(self):
        self.make_tax()
        stub = self.make_placeholder()
        stub.hourly_rate = Decimal("195")
        stub.save()
        self.assertTrue(self.cov().can_finish)


class ResolveGotoTest(CoverageTestCase):
    """Where "Next" lands.

    The reported bug: restore a complete export, go back to fill in Tax, press
    Next — and the wizard stops on the Workplace step offering to create a
    *second* workplace beside the one the file brought in.
    """

    def post(self, path, data):
        request = RequestFactory().post(path, data)
        request.user = self.user
        request.session = {}
        return request

    def test_next_steps_to_the_following_step_on_a_fresh_install(self):
        request = self.post("/onboarding/tax/", {"onboarding_goto": "next"})
        self.assertEqual(ob.resolve_goto(request, "tax"), "/onboarding/workplace/")

    def test_next_skips_steps_an_import_already_wrote(self):
        self.make_workplace()          # workplace + contract + pay terms in the DB
        request = self.post("/onboarding/tax/", {"onboarding_goto": "next"})
        self.assertEqual(ob.resolve_goto(request, "tax"), "/onboarding/review/")

    def test_next_still_stops_on_terms_while_a_placeholder_survives(self):
        """Term sets exist, but they are the import's zero-pay stub — that step
        is the only place to fix it, so Next must not walk past it."""
        wp = Workplace.objects.create(name="Ghost Co")
        contract = WorkplaceContract.objects.create(workplace=wp)
        ContractTermSet.objects.create(
            contract=contract, effective_from=date(2000, 1, 1),
            employment_type="hourly", hourly_rate=Decimal("0"),
            weekly_hours_fixed=Decimal("37"))
        request = self.post("/onboarding/tax/", {"onboarding_goto": "next"})
        self.assertEqual(ob.resolve_goto(request, "tax"), "/onboarding/terms/")

    def test_a_draft_the_user_typed_is_not_skipped(self):
        """Only rows in the database are skipped. Re-showing a step the user
        filled in re-binds their own input, which is helpful, not confusing."""
        self.draft(workplace=WORKPLACE_DRAFT, terms=TERMS_DRAFT)
        request = self.post("/onboarding/tax/", {"onboarding_goto": "next"})
        self.assertEqual(ob.resolve_goto(request, "tax"), "/onboarding/workplace/")

    def test_an_explicit_jump_is_honoured_even_when_covered(self):
        self.make_workplace()
        request = self.post("/onboarding/tax/", {"onboarding_goto": "workplace"})
        self.assertEqual(ob.resolve_goto(request, "tax"), "/onboarding/workplace/")
