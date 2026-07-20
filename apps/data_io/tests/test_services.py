"""Round-trip and edge-case tests for the data_io export/import pipeline."""
import shutil
import tempfile
from datetime import date, time
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import TaxProfile
from data_io import services
from shifts.models import PlannedShift, Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


def _populate():
    """Create one fully-populated workplace plus a shift, planned shift and tax profile."""
    wp = Workplace.objects.create(
        name="Yoyo Inc", slug="yoyo", icon="bi-briefcase",
        color="#112233", accent_color="#445566",
    )
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
        break_minutes=30, shift_type="on_site", notes="morning",
    )
    PlannedShift.objects.create(
        workplace=wp, date=date(2026, 3, 5),
        start_time=time(9, 0), end_time=time(15, 0),
        break_minutes=0, shift_type="remote", status="approved",
    )
    TaxProfile.objects.create(
        monthly_deduction=Decimal("4900.00"),
        tax_percent=Decimal("37.00"),
        effective_from=date(2026, 1, 1),
    )
    return wp


def _wipe():
    Shift.objects.all().delete()
    PlannedShift.objects.all().delete()
    TaxProfile.objects.all().delete()
    Workplace.objects.all().delete()


class ExportTest(TestCase):
    def test_export_data_sections(self):
        _populate()
        data = services.export_data()
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["workplaces"]), 1)
        self.assertEqual(len(data["shifts"]), 1)
        self.assertEqual(len(data["planned_shifts"]), 1)
        self.assertEqual(len(data["tax_profiles"]), 1)
        wp = data["workplaces"][0]
        self.assertEqual(wp["name"], "Yoyo Inc")
        self.assertEqual(len(wp["contracts"]), 1)
        self.assertEqual(len(wp["contracts"][0]["term_sets"]), 1)

    def test_export_flags_and_filters(self):
        _populate()
        data = services.export_data(include_planned=False, include_tax=False)
        self.assertEqual(data["planned_shifts"], [])
        self.assertEqual(data["tax_profiles"], [])
        self.assertEqual(len(data["shifts"]), 1)
        # Date filter excludes the March shift
        early = services.export_data(date_to=date(2026, 1, 1))
        self.assertEqual(early["shifts"], [])

    def test_export_json_is_parseable(self):
        _populate()
        text = services.export_json()
        parsed = services.parse_import_file(text)
        self.assertEqual(parsed["version"], 1)
        self.assertIn("workplaces", parsed)


class ParseImportTest(TestCase):
    def test_valid(self):
        data = services.parse_import_file('{"version": 1, "workplaces": []}')
        self.assertEqual(data["version"], 1)

    def test_bad_json_raises(self):
        with self.assertRaises(ValueError):
            services.parse_import_file("{not valid json")

    def test_non_object_raises(self):
        with self.assertRaises(ValueError):
            services.parse_import_file("[1, 2, 3]")

    def test_missing_version_raises(self):
        with self.assertRaises(ValueError):
            services.parse_import_file('{"workplaces": []}')


class ConflictDetectionTest(TestCase):
    def test_flags_unknown_workplace(self):
        data = {"version": 1, "shifts": [{"workplace_name": "Ghost Co"}]}
        conflicts = services.detect_workplace_conflicts(data)
        self.assertIn("Ghost Co", conflicts)
        self.assertIsNone(conflicts["Ghost Co"])

    def test_ignores_existing_workplace(self):
        Workplace.objects.create(name="Real Co")
        data = {"version": 1, "workplaces": [{"name": "Real Co"}]}
        self.assertEqual(services.detect_workplace_conflicts(data), {})


class RoundTripImportTest(TestCase):
    def test_create_round_trip(self):
        _populate()
        data = services.export_data()
        _wipe()
        self.assertEqual(Workplace.objects.count(), 0)

        counts = services.perform_import(data, {"Yoyo Inc": {"action": "create"}})
        self.assertEqual(counts["shifts_created"], 1)
        self.assertEqual(counts["planned_created"], 1)
        self.assertEqual(counts["tax_created"], 1)

        wp = Workplace.objects.get(name="Yoyo Inc")
        self.assertEqual(wp.slug, "yoyo")
        self.assertEqual(wp.color, "#112233")
        self.assertEqual(wp.accent_color, "#445566")

        ts = wp.contracts.get().term_sets.get()
        self.assertEqual(ts.employment_type, "hourly")
        self.assertEqual(ts.hourly_rate, Decimal("185.50"))
        self.assertEqual(ts.weekly_hours_fixed, Decimal("37.00"))

        shift = Shift.objects.get()
        self.assertEqual(shift.date, date(2026, 3, 2))
        self.assertEqual(shift.start_time, time(8, 0))
        self.assertEqual(shift.end_time, time(16, 0))
        self.assertEqual(shift.break_minutes, 30)
        self.assertEqual(shift.shift_type, "on_site")
        self.assertEqual(shift.notes, "morning")

        planned = PlannedShift.objects.get()
        self.assertEqual(planned.status, "approved")
        self.assertEqual(planned.shift_type, "remote")

        tp = TaxProfile.objects.get()
        self.assertEqual(tp.monthly_deduction, Decimal("4900.00"))
        self.assertEqual(tp.tax_percent, Decimal("37.00"))

    def test_import_is_idempotent(self):
        _populate()
        data = services.export_data()
        _wipe()
        services.perform_import(data, {"Yoyo Inc": {"action": "create"}})
        # Re-import: workplace now matches by name, so nothing should duplicate.
        counts = services.perform_import(data, {})
        self.assertEqual(counts["shifts_created"], 0)
        self.assertEqual(counts["planned_created"], 0)
        self.assertEqual(counts["tax_created"], 0)
        self.assertEqual(Shift.objects.count(), 1)
        self.assertEqual(PlannedShift.objects.count(), 1)
        self.assertEqual(Workplace.objects.count(), 1)


class ImportMappingTest(TestCase):
    def test_map_to_existing_workplace(self):
        _populate()
        data = services.export_data()
        _wipe()
        target = Workplace.objects.create(name="Target Co")
        # Imported shifts are validated like any other shift: the target needs
        # a contract covering their dates, otherwise they are skipped.
        contract = WorkplaceContract.objects.create(workplace=target, name="Main")
        ContractTermSet.objects.create(
            contract=contract, effective_from=date(2024, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("100.00"), weekly_hours_fixed=Decimal("37.00"),
        )
        counts = services.perform_import(
            data, {"Yoyo Inc": {"action": "map", "target_id": target.id}}
        )
        self.assertEqual(counts["shifts_created"], 1)
        self.assertEqual(Shift.objects.filter(workplace=target).count(), 1)

    def test_map_to_missing_workplace_fails_cleanly(self):
        _populate()
        data = services.export_data()
        _wipe()
        with self.assertRaises(ValueError):
            services.perform_import(
                data, {"Yoyo Inc": {"action": "map", "target_id": 99999}}
            )
        # atomic: nothing half-imported
        self.assertEqual(Shift.objects.count(), 0)

    def test_skip_workplace(self):
        _populate()
        data = services.export_data()
        _wipe()
        counts = services.perform_import(data, {"Yoyo Inc": {"action": "skip"}})
        self.assertEqual(counts["shifts_created"], 0)
        self.assertGreaterEqual(counts["skipped"], 1)
        self.assertEqual(Shift.objects.count(), 0)


class TermSetDefaultsTest(TestCase):
    def test_missing_tax_card_type_defaults_to_valid_hovedkort(self):
        """Regression: the default was the invalid 'hoofdkort', silently taxing
        imported term sets as bikort."""
        wp = Workplace.objects.create(name="Defaults Co")
        contract = WorkplaceContract.objects.create(workplace=wp, name="Main")
        ts = services._create_termset_from_dict(
            contract, {"effective_from": "2024-01-01", "hourly_rate": "150.00"}
        )
        self.assertEqual(ts.tax_card_type, "hovedkort")
        ts.full_clean()  # must be a valid model choice


class IconRoundTripTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self.tmp)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_imported_svg_icon_is_sanitized(self):
        import base64
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><rect width="1" height="1"/></svg>'
        data = {
            "version": 1,
            "workplaces": [{
                "name": "Evil Co",
                "contracts": [{"name": "Main", "term_sets": [{"effective_from": "2024-01-01", "hourly_rate": "100"}]}],
                "custom_icon": {"filename": "evil.svg",
                                "data": base64.b64encode(svg).decode()},
            }],
        }
        services.perform_import(data, {"Evil Co": {"action": "create"}})
        wp = Workplace.objects.get(name="Evil Co")
        self.assertTrue(wp.custom_icon)
        wp.custom_icon.open("rb")
        stored = wp.custom_icon.read()
        wp.custom_icon.close()
        self.assertNotIn(b"script", stored)
        self.assertNotIn(b"alert", stored)

    def test_imported_icon_with_bad_extension_or_size_is_skipped(self):
        import base64
        big = base64.b64encode(b"x" * (600 * 1024)).decode()
        data = {
            "version": 1,
            "workplaces": [
                {"name": "ExeCo", "contracts": [{"name": "Main", "term_sets": [{"effective_from": "2024-01-01", "hourly_rate": "100"}]}],
                 "custom_icon": {"filename": "a.exe",
                                 "data": base64.b64encode(b"MZ").decode()}},
                {"name": "BigCo", "contracts": [{"name": "Main", "term_sets": [{"effective_from": "2024-01-01", "hourly_rate": "100"}]}],
                 "custom_icon": {"filename": "b.png", "data": big}},
            ],
        }
        services.perform_import(
            data, {"ExeCo": {"action": "create"}, "BigCo": {"action": "create"}}
        )
        self.assertFalse(Workplace.objects.get(name="ExeCo").custom_icon)
        self.assertFalse(Workplace.objects.get(name="BigCo").custom_icon)

    def test_custom_icon_round_trip(self):
        wp = Workplace.objects.create(name="Iconic", slug="iconic")
        wp.custom_icon.save("iconic_icon.png", ContentFile(b"\x89PNGfakebytes"), save=True)

        data = services.export_data()
        self.assertIsNotNone(data["workplaces"][0]["custom_icon"])

        # Remove the on-disk file too (model.delete() leaves it), so the re-import
        # lands the clean deterministic name like a fresh-machine import would.
        wp.custom_icon.delete(save=False)
        Workplace.objects.all().delete()
        services.perform_import(data, {"Iconic": {"action": "create"}})

        wp2 = Workplace.objects.get(name="Iconic")
        self.assertTrue(wp2.custom_icon)
        self.assertTrue(wp2.custom_icon.name.endswith("iconic_icon.png"))
        wp2.custom_icon.open("rb")
        self.assertEqual(wp2.custom_icon.read(), b"\x89PNGfakebytes")
        wp2.custom_icon.close()


class ImportConfirmLayoutTest(TestCase):
    """Outside the wizard the same page is a normal full-width settings page."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_no_wizard_column_or_step_bar(self):
        _populate()
        payload = services.export_json()
        response = self.client.post("/data/import/", {
            "import_file": SimpleUploadedFile("e.json", payload.encode("utf-8"),
                                              content_type="application/json"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "setup-steps-track")
        self.assertNotContains(response, "col-12 col-md-10 col-lg-8")
