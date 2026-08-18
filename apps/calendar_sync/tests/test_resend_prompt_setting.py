"""Direction 2 — "stop asking me to re-send".

The post-edit prompt is a client-side dialog, so the owner's answer to *whether
they want asking at all* has to travel with the shift (``invite_ask``) as well as
being stored. Switching it off is a **quiet** mode, not a silent-send one: the
shift keeps its out-of-date marker and the month's sweep still offers the update,
so nothing leaves without a press either way — which is what makes the switch
safe to offer from inside the dialog itself.
"""
from datetime import date, time
from decimal import Decimal

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from calendar_sync import invites
from calendar_sync.models import CalendarInviteSettings, ContractCalendarConfig
from core.models import EmailSettings, MailConnection
from core.testing import LoggedInTestCase
from shifts.models import PlannedShift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,
)
class ResendPromptSettingTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        mail.outbox = []

        MailConnection.objects.create(name="Default", host="smtp.zink.nu",
                                      from_email="robot@zink.nu", is_default=True)
        es = EmailSettings.load()
        es.enabled = True
        es.save()
        s = CalendarInviteSettings.load()
        s.enabled = True
        s.save()

        self.wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract, effective_from=date(2026, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("200"),
        )
        ContractCalendarConfig.objects.create(
            contract=contract, send_invites=True, recipient="boss@work.example",
        )

    def _planned(self):
        return PlannedShift.objects.create(
            workplace=self.wp, date=date(2035, 3, 15),
            start_time=time(9, 0), end_time=time(17, 0),
        )

    def _payload(self, shift):
        """The shift dict the modal is driven from (an empty POST = a read)."""
        resp = self.client.post(
            reverse("calendar_view:planned-shift-update-api", args=[shift.pk]),
            data="{}", content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["shift"]

    def test_asking_is_on_by_default(self):
        self.assertTrue(CalendarInviteSettings.load().ask_before_resend)
        self.assertTrue(self._payload(self._planned())["invite_ask"])

    def test_the_switch_travels_with_the_shift(self):
        s = CalendarInviteSettings.load()
        s.ask_before_resend = False
        s.save()
        self.assertFalse(self._payload(self._planned())["invite_ask"])

    def test_the_dialog_can_turn_it_off_through_the_settings_endpoint(self):
        """"No, and stop asking me" posts the same field the Calendar tab's
        "Offer to re-send an invite when a shift changes" switch does — and an
        unchecked switch posts no value at all."""
        resp = self.client.post(
            reverse("core:settings-field"),
            {"scope": "calendar", "field": "ask_before_resend"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(CalendarInviteSettings.load().ask_before_resend)

        # …and back on, without disturbing anything else on the singleton.
        self.client.post(
            reverse("core:settings-field"),
            {"scope": "calendar", "field": "ask_before_resend",
             "ask_before_resend": "on"},
        )
        settings = CalendarInviteSettings.load()
        self.assertTrue(settings.ask_before_resend)
        self.assertTrue(settings.enabled)

    def test_silence_still_marks_the_shift_and_keeps_it_in_the_sweep(self):
        """The whole reason the switch is safe: a shift nobody was asked about is
        still out of date, and Send invites still offers the update."""
        s = CalendarInviteSettings.load()
        s.ask_before_resend = False
        s.save()

        shift = self._planned()
        invites.activate(shift)
        shift.refresh_from_db()
        shift.end_time = time(18, 0)
        shift.save()

        self.assertTrue(invites.is_stale(shift))
        self.assertTrue(invites.needs_send(shift))
        groups = invites.month_sweep(2035, 3)
        self.assertEqual([len(g.updates) for g in groups], [1])

    def test_the_calendar_tab_renders_the_switch(self):
        html = self.client.get("/settings/?tab=calendar").content.decode()
        self.assertIn('id="id_ask_before_resend"', html)
        self.assertIn('data-autosave="calendar"', html)
