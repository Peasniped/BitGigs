"""Tests for contract-overlap detection and skipping during import."""
from datetime import date

from django.test import TestCase

from data_io import services
from workplaces.models import Workplace, WorkplaceContract


def _wp_dict(name, contracts):
    return {"name": name, "contracts": contracts}


def _data(*workplaces):
    return {"version": 1, "workplaces": list(workplaces), "shifts": [], "planned_shifts": []}


class DetectContractOverlapsTest(TestCase):
    def test_flags_overlapping_contracts(self):
        data = _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01", "end_date": "2024-12-31"},
            {"name": "B", "start_date": "2024-06-01", "end_date": None},
        ]))
        problems = services.detect_contract_overlaps(data)
        self.assertIn("Acme", problems)
        self.assertEqual(problems["Acme"], [("A", "B")])

    def test_adjacent_contracts_do_not_overlap(self):
        data = _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01", "end_date": "2024-06-30"},
            {"name": "B", "start_date": "2024-07-01", "end_date": None},
        ]))
        self.assertEqual(services.detect_contract_overlaps(data), {})

    def test_two_open_ended_contracts_overlap(self):
        data = _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01", "end_date": None},
            {"name": "B", "start_date": "2024-03-01", "end_date": None},
        ]))
        self.assertIn("Acme", services.detect_contract_overlaps(data))

    def test_single_contract_is_clean(self):
        data = _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01", "end_date": None},
        ]))
        self.assertEqual(services.detect_contract_overlaps(data), {})


class ImportSkipOverlapTest(TestCase):
    def test_skip_workplaces_prevents_creation(self):
        data = _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01", "end_date": None},
        ]))
        mapping = {"Acme": {"action": "create"}}
        services.perform_import(data, mapping, skip_workplaces={"Acme"})
        self.assertFalse(Workplace.objects.filter(name="Acme").exists())

    def test_create_without_skip_builds_workplace(self):
        data = _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01", "end_date": None,
             "term_sets": []},
        ]))
        mapping = {"Acme": {"action": "create"}}
        services.perform_import(data, mapping)
        self.assertTrue(Workplace.objects.filter(name="Acme").exists())

    def test_restores_contract_and_term_set_dates(self):
        """A restored contract has no date fields of its own; its span comes from
        the term sets, including the optional effective_until."""
        d = _wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01", "end_date": "2024-06-30",
             "term_sets": [{
                 "effective_from": "2024-01-01",
                 "effective_until": "2024-06-30",
                 "employment_type": "salaried",
                 "monthly_salary": "30000",
                 "weekly_hours_fixed": "37",
             }]},
        ])
        wp = services._create_workplace_from_dict(d)
        contract = WorkplaceContract.objects.get(workplace=wp)
        self.assertEqual(contract.start_date, date(2024, 1, 1))
        self.assertEqual(contract.end_date, date(2024, 6, 30))
