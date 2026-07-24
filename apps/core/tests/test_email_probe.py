"""The live host/port probe behind the Email settings modal (core:email-probe)
and the resolve_host / check_port helpers it shares with the staged test."""
import socket
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core import mail as core_mail


class ProbeHelperTests(TestCase):
    def test_resolve_host_reports_the_addresses(self):
        with mock.patch(
            "core.mail.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.1", 587))],
        ):
            probe = core_mail.resolve_host("smtp.example.com", 587)
        self.assertTrue(probe.ok)
        self.assertEqual(probe.addresses, ["10.0.0.1"])
        self.assertIn("10.0.0.1", probe.detail)

    def test_resolve_host_names_the_typo_hint_on_failure(self):
        with mock.patch(
            "core.mail.socket.getaddrinfo", side_effect=socket.gaierror("nope")
        ):
            probe = core_mail.resolve_host("smtp.zink.nu")
        self.assertFalse(probe.ok)
        self.assertIn("could not be resolved", probe.detail)
        self.assertIn("typos", probe.hint)

    def test_check_port_refused_suggests_the_right_ports(self):
        with mock.patch(
            "core.mail.socket.create_connection", side_effect=ConnectionRefusedError()
        ):
            probe = core_mail.check_port("smtp.example.com", 587, 5)
        self.assertFalse(probe.ok)
        self.assertIn("587", probe.hint)

    def test_check_port_open(self):
        with mock.patch("core.mail.socket.create_connection"):
            probe = core_mail.check_port("smtp.example.com", 465, 5)
        self.assertTrue(probe.ok)


class EmailProbeViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()
        self.url = reverse("core:email-probe")

    def test_blank_host_checks_nothing(self):
        data = self.client.post(self.url, {"host": "  "}).json()
        self.assertIsNone(data["host"])
        self.assertIsNone(data["port"])

    def test_unresolvable_host_is_reported(self):
        with mock.patch(
            "core.mail.socket.getaddrinfo", side_effect=socket.gaierror("nope")
        ):
            data = self.client.post(self.url, {"host": "smtp.zink.nu"}).json()
        self.assertEqual(data["host"]["status"], "failed")
        # DNS failed → the port check is never attempted.
        self.assertIsNone(data["port"])

    def test_host_and_port_both_checked_when_reachable(self):
        with mock.patch(
            "core.mail.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.1", 465))],
        ), mock.patch("core.mail.socket.create_connection"):
            data = self.client.post(
                self.url, {"host": "smtp.example.com", "port": "465"}
            ).json()
        self.assertEqual(data["host"]["status"], "ok")
        self.assertEqual(data["port"]["status"], "ok")
        self.assertEqual(data["port"]["port"], 465)

    def test_out_of_range_port_is_ignored(self):
        with mock.patch(
            "core.mail.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.1", 465))],
        ), mock.patch("core.mail.socket.create_connection") as connect:
            data = self.client.post(
                self.url, {"host": "smtp.example.com", "port": "70000"}
            ).json()
        self.assertEqual(data["host"]["status"], "ok")
        self.assertIsNone(data["port"])
        connect.assert_not_called()

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url, {"host": "smtp.example.com"})
        self.assertEqual(response.status_code, 302)
