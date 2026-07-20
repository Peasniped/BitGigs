"""Tests for contract-overlap detection and skipping during import."""
from datetime import date

from django.test import TestCase

from data_io import services
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


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
        wp, termsets = services._create_workplace_from_dict(d)
        self.assertEqual(termsets, 1)
        contract = WorkplaceContract.objects.get(workplace=wp)
        self.assertEqual(contract.start_date, date(2024, 1, 1))
        self.assertEqual(contract.end_date, date(2024, 6, 30))


class ImportCountsTest(TestCase):
    """perform_import must count what it creates, or a workplaces-only file
    reports "nothing to import" while visibly creating a workplace."""

    def test_counts_workplaces_and_term_sets(self):
        data = _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01",
             "term_sets": [
                 {"effective_from": "2024-01-01", "employment_type": "hourly",
                  "hourly_rate": "180", "weekly_hours_fixed": "37"},
                 {"effective_from": "2025-01-01", "employment_type": "hourly",
                  "hourly_rate": "200", "weekly_hours_fixed": "37"},
             ]},
        ]))
        counts = services.perform_import(data, {"Acme": {"action": "create"}})
        self.assertEqual(counts["workplaces_created"], 1)
        self.assertEqual(counts["termsets_created"], 2)

    def test_describe_import_mentions_a_workplaces_only_file(self):
        data = _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01",
             "term_sets": [{"effective_from": "2024-01-01", "employment_type": "hourly",
                            "hourly_rate": "180", "weekly_hours_fixed": "37"}]},
        ]))
        counts = services.perform_import(data, {"Acme": {"action": "create"}})
        described = services.describe_import(counts)
        self.assertIn("1 workplace(s)", described)
        self.assertNotIn("nothing to import", described)

    def test_mapping_to_an_existing_workplace_creates_nothing(self):
        Workplace.objects.create(name="Acme")
        wp = Workplace.objects.get(name="Acme")
        data = _data()
        counts = services.perform_import(data, {"Acme": {"action": "map", "target_id": wp.pk}})
        self.assertEqual(counts["workplaces_created"], 0)
        self.assertEqual(counts["termsets_created"], 0)

    def test_workplace_with_no_contracts_creates_no_term_sets(self):
        """A legitimate export shape — and the reason coverage can't infer pay
        terms from the presence of a workplace."""
        counts = services.perform_import(_data(_wp_dict("Acme", [])),
                                         {"Acme": {"action": "create"}})
        self.assertEqual(counts["workplaces_created"], 1)
        self.assertEqual(counts["termsets_created"], 0)


class DescribeConflictsTest(TestCase):
    """"Create" means two different things, so the review page has to say which."""

    def test_a_defined_workplace_is_flagged_as_described(self):
        data = _data(_wp_dict("Acme", []))
        rows = services.describe_conflicts(data, {"Acme": None})
        self.assertEqual(rows, [{"name": "Acme", "defined": True}])

    def test_a_name_only_seen_on_shifts_is_not(self):
        data = {"version": 1, "workplaces": [],
                "shifts": [{"workplace_name": "Ghost Co"}], "planned_shifts": []}
        rows = services.describe_conflicts(data, {"Ghost Co": None})
        self.assertEqual(rows, [{"name": "Ghost Co", "defined": False}])

    def test_rows_are_sorted_so_the_table_is_stable(self):
        data = _data(_wp_dict("Beta", []))
        rows = services.describe_conflicts(data, {"Beta": None, "Alpha": None})
        self.assertEqual([r["name"] for r in rows], ["Alpha", "Beta"])
        self.assertEqual([r["defined"] for r in rows], [False, True])


class CreateBlankTest(TestCase):
    """"Create blank" takes the shifts but not the file's settings."""

    def _defined(self):
        return _data(_wp_dict("Acme", [
            {"name": "A", "start_date": "2024-01-01",
             "term_sets": [{"effective_from": "2024-01-01", "employment_type": "hourly",
                            "hourly_rate": "180", "weekly_hours_fixed": "37"}]},
        ]))

    def test_ignores_the_files_settings(self):
        services.perform_import(self._defined(), {"Acme": {"action": "create_blank"}})
        wp = Workplace.objects.get(name="Acme")
        contract = wp.contracts.get()
        self.assertEqual(contract.name, "")               # not the file's "A"
        self.assertEqual(contract.term_sets.get().hourly_rate, 0)

    def test_create_still_takes_them(self):
        services.perform_import(self._defined(), {"Acme": {"action": "create"}})
        contract = Workplace.objects.get(name="Acme").contracts.get()
        self.assertEqual(contract.name, "A")
        self.assertEqual(contract.term_sets.get().hourly_rate, 180)

    def test_blank_creation_is_counted(self):
        counts = services.perform_import(self._defined(), {"Acme": {"action": "create_blank"}})
        self.assertEqual(counts["workplaces_created"], 1)

    def test_the_form_accepts_the_new_action(self):
        mapping = services.build_workplace_mapping({"action_Acme": "create_blank"}, {"Acme": None})
        self.assertEqual(mapping, {"Acme": {"action": "create_blank"}})

    def test_an_unknown_action_still_falls_back_to_skip(self):
        mapping = services.build_workplace_mapping({"action_Acme": "create_evil"}, {"Acme": None})
        self.assertEqual(mapping, {"Acme": {"action": "skip"}})
