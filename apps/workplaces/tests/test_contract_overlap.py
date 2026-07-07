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

    def test_timeline_flags_a_gap_between_term_sets(self):
        make_terms(self.contract, date(2024, 1, 1), date(2024, 3, 31))  # older, ends Mar 31
        make_terms(self.contract, date(2024, 6, 1))                     # newer, from Jun 1
        tl = self.contract.timeline
        self.assertEqual(tl[0].effective_from, date(2024, 6, 1))        # newest first
        self.assertEqual(tl[0].gap_after, (date(2024, 4, 1), date(2024, 5, 31)))
        self.assertIsNone(tl[1].gap_after)

    def test_timeline_no_gap_when_contiguous_or_open_ended(self):
        make_terms(self.contract, date(2024, 1, 1), date(2024, 5, 31))  # ends the day before
        make_terms(self.contract, date(2024, 6, 1))
        self.assertIsNone(self.contract.timeline[0].gap_after)

        other = WorkplaceContract.objects.create(workplace=self.wp, name="Open")
        make_terms(other, date(2024, 1, 1))   # open-ended older term set
        make_terms(other, date(2024, 6, 1))   # auto-capped, no explicit gap
        self.assertIsNone(other.timeline[0].gap_after)

    def test_active_intervals_exclude_gaps(self):
        make_terms(self.contract, date(2026, 7, 13), date(2026, 7, 15))  # ends 15th
        make_terms(self.contract, date(2026, 7, 17))                     # open, capped by next
        make_terms(self.contract, date(2026, 7, 24), date(2026, 8, 1))
        self.assertEqual(self.contract.active_intervals(), [
            (date(2026, 7, 13), date(2026, 7, 15)),   # gap on the 16th
            (date(2026, 7, 17), date(2026, 7, 23)),   # capped the day before the next
            (date(2026, 7, 24), date(2026, 8, 1)),
        ])

    def test_end_date_cannot_reach_into_a_later_termset(self):
        # A newer term set (Jul 17) takes over, so an earlier term set's end date
        # must not reach it — otherwise both claim the same days with no warning.
        a = make_terms(self.contract, date(2024, 7, 15))
        make_terms(self.contract, date(2024, 7, 17))
        a.effective_until = date(2024, 8, 1)
        with self.assertRaises(ValidationError):
            a.full_clean()
        a.effective_until = date(2024, 7, 17)  # same day the next begins → still invalid
        with self.assertRaises(ValidationError):
            a.full_clean()
        a.effective_until = date(2024, 7, 16)  # strictly before the next → allowed
        a.full_clean()

    def test_overreaching_end_date_is_cleared_on_rerender(self):
        from workplaces.forms import ContractTermSetForm
        a = make_terms(self.contract, date(2024, 7, 15))
        make_terms(self.contract, date(2024, 7, 17))
        post = {
            "effective_from": "2024-07-15", "effective_until": "2024-08-01",
            "employment_type": "salaried", "monthly_salary": "8000",
            "work_time_type": "fuldtid", "hours_type": "fixed",
            "weekly_hours_fixed": "37", "payroll_period_start_day": "1",
            "tax_card_type": "hovedkort", "vacation_type": "feriekonto",
        }
        form = ContractTermSetForm(post, instance=a, contract=self.contract)
        self.assertFalse(form.is_valid())
        self.assertIn("effective_until", form.errors)
        # With a later term set present, the correction is "runs until then"
        # (blank), not a redundant day-before date.
        self.assertEqual(form.data.get("effective_until"), "")


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


class TermSetSupersedeExpiryTest(TestCase):
    """Adding a term set that starts on or before the current terms' end date
    moves the contract-end date to the new terms (carry over) or drops it
    (open-ended), and clears the now-superseded end date on the old terms."""

    def setUp(self):
        self.wp = Workplace.objects.create(name="Acme", slug="acme")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp, name="C")
        self.a = make_terms(self.contract, date(2026, 1, 1), date(2026, 12, 31))
        self.url = reverse(
            "workplaces:termset-create", args=[self.wp.slug, self.contract.pk]
        )

    def _post(self, effective_from, effective_until=""):
        return self.client.post(self.url, {
            "effective_from": effective_from,
            "effective_until": effective_until,
            "employment_type": "salaried",
            "monthly_salary": "40000",
            "work_time_type": "fuldtid",
            "hours_type": "fixed",
            "weekly_hours_fixed": "37",
            "payroll_period_start_day": "1",
            "tax_card_type": "hovedkort",
            "vacation_type": "feriekonto",
            "action": "overwrite",
        })

    def test_carry_over_moves_end_date_to_new_terms(self):
        resp = self._post("2026-06-01", effective_until="2026-12-31")
        self.assertEqual(resp.status_code, 302)
        self.a.refresh_from_db()
        b = self.contract.term_sets.get(effective_from=date(2026, 6, 1))
        self.assertIsNone(self.a.effective_until)          # old terms freed
        self.assertEqual(b.effective_until, date(2026, 12, 31))  # baton passed
        self.assertEqual(self.contract.end_date, date(2026, 12, 31))

    def test_open_ended_clears_end_date(self):
        resp = self._post("2026-06-01", effective_until="")
        self.assertEqual(resp.status_code, 302)
        self.a.refresh_from_db()
        b = self.contract.term_sets.get(effective_from=date(2026, 6, 1))
        self.assertIsNone(self.a.effective_until)
        self.assertIsNone(b.effective_until)
        self.assertIsNone(self.contract.end_date)          # contract now open

    def test_start_after_expiry_keeps_the_gap(self):
        # Old terms end Mar 31; new terms start Jun 1 (a deliberate gap) — the
        # old end date is meaningful and must be left intact.
        self.a.effective_until = date(2026, 3, 31)
        self.a.save()
        resp = self._post("2026-06-01", effective_until="")
        self.assertEqual(resp.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.effective_until, date(2026, 3, 31))

    def test_add_form_omits_prefilled_end_date(self):
        # The new-terms form no longer silently pre-fills the end date.
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["form"].initial.get("effective_until"))
        self.assertIn("existing_terms_json", resp.context)


class HourGoalPersistenceTest(TestCase):
    """A term set saved without an hour goal must not persist a stray period
    type — the hidden weekly radio posts hour_goal_type=weekly even when the
    goal toggle was never enabled, so clean() nulls it when no min/max exists."""

    def setUp(self):
        self.wp = Workplace.objects.create(name="Acme", slug="acme")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp, name="C")

    def _post(self, **extra):
        post = {
            "effective_from": "2026-01-01", "effective_until": "",
            "employment_type": "salaried", "monthly_salary": "40000",
            "work_time_type": "fuldtid", "hours_type": "fixed",
            "weekly_hours_fixed": "37", "payroll_period_start_day": "1",
            "tax_card_type": "hovedkort", "vacation_type": "feriekonto",
        }
        post.update(extra)
        return post

    def test_no_goal_clears_stray_period_type(self):
        from workplaces.forms import ContractTermSetForm
        form = ContractTermSetForm(self._post(hour_goal_type="weekly"), contract=self.contract)
        self.assertTrue(form.is_valid(), form.errors)
        ts = form.save()
        self.assertEqual(ts.hour_goal_type, "")
        self.assertIsNone(ts.hour_goal_min)

    def test_real_goal_is_kept(self):
        from workplaces.forms import ContractTermSetForm
        form = ContractTermSetForm(
            self._post(hour_goal_type="weekly", hour_goal_min="15", goalMode="target"),
            contract=self.contract,
        )
        self.assertTrue(form.is_valid(), form.errors)
        ts = form.save()
        self.assertEqual(ts.hour_goal_type, "weekly")
        self.assertEqual(ts.hour_goal_min, Decimal("15"))
