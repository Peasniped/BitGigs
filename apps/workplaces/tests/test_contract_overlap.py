"""Contracts have no dates of their own — activity and the non-overlap guard
are derived from their term sets. The guard now triggers when a term set is
saved (that is when dates enter the model)."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from workplaces.models import Workplace, WorkplaceContract, ContractTermSet


def make_terms(contract, effective_from, effective_until=None, **overrides):
    """Create a minimally-valid salaried term set for *contract*."""
    kwargs = dict(
        contract=contract,
        effective_from=effective_from,
        effective_until=effective_until,
        employment_type=ContractTermSet.EmploymentType.SALARIED,
        monthly_salary=Decimal("30000"),
        weekly_hours_fixed=Decimal("37"),
    )
    kwargs.update(overrides)
    return ContractTermSet.objects.create(**kwargs)


class ContractOverlapValidationTest(TestCase):
    def setUp(self):
        self.wp = Workplace.objects.create(name="Acme")
        self.first = WorkplaceContract.objects.create(workplace=self.wp, name="First")
        make_terms(self.first, date(2024, 1, 1))  # open-ended

    def test_overlapping_terms_fail_full_clean(self):
        second = WorkplaceContract.objects.create(workplace=self.wp, name="Second")
        clash = ContractTermSet(
            contract=second,
            effective_from=date(2024, 6, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000"),
            weekly_hours_fixed=Decimal("37"),
        )
        with self.assertRaises(ValidationError):
            clash.full_clean()

    def test_non_overlapping_terms_pass(self):
        # Close the first contract by expiring its terms, then start after.
        ts = self.first.term_sets.first()
        ts.effective_until = date(2024, 6, 30)
        ts.save()
        second = WorkplaceContract.objects.create(workplace=self.wp, name="Second")
        later = ContractTermSet(
            contract=second,
            effective_from=date(2024, 7, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000"),
            weekly_hours_fixed=Decimal("37"),
        )
        later.full_clean()  # should not raise

    def test_only_one_contract_active_on_a_date(self):
        ts = self.first.term_sets.first()
        ts.effective_until = date(2024, 6, 30)
        ts.save()
        second = WorkplaceContract.objects.create(workplace=self.wp, name="Second")
        make_terms(second, date(2024, 7, 1))
        self.assertEqual(self.wp.active_contract_on(date(2024, 3, 1)).name, "First")
        self.assertEqual(self.wp.active_contract_on(date(2024, 8, 1)).name, "Second")


class TermSetActiveWindowTest(TestCase):
    """The 'runs until next / expiry ends it' semantics."""

    def setUp(self):
        self.wp = Workplace.objects.create(name="Acme")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)

    def test_expiry_ends_the_contract(self):
        make_terms(self.contract, date(2024, 1, 1), effective_until=date(2024, 3, 31))
        self.assertTrue(self.contract.is_active_on(date(2024, 3, 31)))
        self.assertFalse(self.contract.is_active_on(date(2024, 4, 1)))
        self.assertIsNone(self.wp.active_termset_on(date(2024, 4, 1)))

    def test_later_termset_supersedes_earlier(self):
        a = make_terms(self.contract, date(2024, 1, 1))          # open
        b = make_terms(self.contract, date(2024, 6, 1))          # open
        self.assertEqual(self.contract.active_termset_on(date(2024, 2, 1)), a)
        self.assertEqual(self.contract.active_termset_on(date(2024, 7, 1)), b)

    def test_expired_tail_is_not_reopened_by_earlier_open_terms(self):
        make_terms(self.contract, date(2024, 1, 1))                      # open
        make_terms(self.contract, date(2024, 6, 1), date(2024, 12, 31))  # expires
        # After the last term set expires the contract is closed, even though an
        # earlier term set was open-ended.
        self.assertIsNone(self.contract.active_termset_on(date(2025, 1, 1)))

    def test_derived_span(self):
        make_terms(self.contract, date(2024, 1, 1))
        make_terms(self.contract, date(2024, 6, 1), date(2024, 12, 31))
        self.assertEqual(self.contract.start_date, date(2024, 1, 1))
        self.assertEqual(self.contract.end_date, date(2024, 12, 31))


class ContractCreateViewTest(TestCase):
    def setUp(self):
        self.wp = Workplace.objects.create(name="Acme", slug="acme")
        self.url = reverse("workplaces:contract-create", args=[self.wp.slug])

    def test_create_contract_is_name_only_and_redirects_to_terms(self):
        resp = self.client.post(self.url, {"name": "New"})
        self.assertEqual(resp.status_code, 302)  # redirects to add terms
        contract = self.wp.contracts.get(name="New")
        self.assertIn("/terms/add/", resp["Location"])
        # A brand-new contract has no span until it gets terms.
        self.assertIsNone(contract.start_date)
