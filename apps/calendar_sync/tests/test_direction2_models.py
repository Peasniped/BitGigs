"""Phase 2a — Direction 2 models: settings singleton, per-contract config,
address parsing, title/location templating (with global-default inheritance),
and invite_uid across approval."""
from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from calendar_sync.models import (
    CalendarInviteSettings,
    ContractCalendarConfig,
    parse_addresses,
)
from shifts.models import PlannedShift, Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


def _workplace(name="JKF"):
    """Return (workplace, contract) with an active hourly term set from 2026."""
    wp = Workplace.objects.create(name=name, slug=name.lower())
    contract = WorkplaceContract.objects.create(workplace=wp)
    ContractTermSet.objects.create(
        contract=contract,
        effective_from=date(2026, 1, 1),
        employment_type=ContractTermSet.EmploymentType.HOURLY,
        hourly_rate=Decimal("200"),
    )
    return wp, contract


class ParseAddressesTests(TestCase):
    def test_splits_on_comma_semicolon_newline_and_dedupes(self):
        text = "a@x.com, b@x.com; a@X.com\n c@x.com \n"
        self.assertEqual(parse_addresses(text), ["a@x.com", "b@x.com", "c@x.com"])

    def test_empty(self):
        self.assertEqual(parse_addresses(""), [])
        self.assertEqual(parse_addresses(None), [])


class InviteSettingsTests(TestCase):
    def test_singleton_load(self):
        a = CalendarInviteSettings.load()
        a.owner_address = "me@home.example"
        a.save()
        b = CalendarInviteSettings.load()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(b.owner_address, "me@home.example")
        self.assertEqual(CalendarInviteSettings.objects.count(), 1)


class ContractConfigTemplatingTests(TestCase):
    def setUp(self):
        self.wp, self.contract = _workplace()
        self.cfg = ContractCalendarConfig.objects.create(
            contract=self.contract,
            send_invites=True,
            recipient="boss@work.example",
        )

    def test_recipient_list(self):
        self.assertEqual(self.cfg.recipient_list(), ["boss@work.example"])

    def test_recipient_list_blank_when_empty(self):
        self.cfg.recipient = ""
        self.assertEqual(self.cfg.recipient_list(), [])

    def test_title_by_type_defaults(self):
        ctx = {"workplace": self.wp.name, "date": "2026-03-15", "start": "09:00", "end": "17:00"}
        self.assertEqual(self.cfg.title_for("on_site", ctx), "På arbejde hos JKF")
        self.assertEqual(self.cfg.title_for("remote", ctx), "Arbejder hjemme, JKF")

    def test_title_override(self):
        self.cfg.override_title_onsite = True
        self.cfg.title_onsite = "At {workplace} office"
        self.assertEqual(self.cfg.title_for("on_site", {"workplace": "JKF"}), "At JKF office")

    def test_title_bad_placeholder_falls_back_to_template(self):
        self.cfg.override_title_onsite = True
        self.cfg.title_onsite = "At {nope}"
        self.assertEqual(self.cfg.title_for("on_site", {"workplace": "JKF"}), "At {nope}")

    def test_location_by_type_with_fallbacks(self):
        settings = CalendarInviteSettings(default_remote_address="Home office")
        # on-site with no address → workplace name
        self.assertEqual(self.cfg.location_for("on_site", settings), "JKF")
        # remote with no override → global default
        self.assertEqual(self.cfg.location_for("remote", settings), "Home office")
        # explicit values win
        self.cfg.address_onsite = "Office St 1"
        self.cfg.override_address_remote = True
        self.cfg.address_remote = "My desk"
        self.assertEqual(self.cfg.location_for("on_site", settings), "Office St 1")
        self.assertEqual(self.cfg.location_for("remote", settings), "My desk")


class InviteUidAcrossApprovalTests(TestCase):
    def setUp(self):
        self.wp, self.contract = _workplace()

    def _planned(self, **kw):
        return PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 3, 15),
            start_time=time(9, 0), end_time=time(17, 0), **kw,
        )

    def test_approval_moves_invite_uid_to_shift(self):
        import uuid
        uid = uuid.uuid4()
        planned = self._planned(invite_uid=uid)

        shift = planned.approve()
        planned.refresh_from_db()

        self.assertEqual(shift.invite_uid, uid)          # carried onto the Shift
        self.assertIsNone(planned.invite_uid)            # cleared on the PlannedShift
        self.assertEqual(planned.status, PlannedShift.Status.APPROVED)

    def test_approval_without_invite_is_unaffected(self):
        planned = self._planned()
        shift = planned.approve()
        self.assertIsNone(shift.invite_uid)
        self.assertIsInstance(shift, Shift)
