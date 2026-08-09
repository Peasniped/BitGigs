"""Editing a contract from Settings → Calendar returns to that tab.

The tab links here to fix a contract's invites; redirecting to the workplace
page afterwards left the owner to navigate back to the tab themselves. Both Save
and Cancel honour a same-origin ``next`` — and nothing else."""
from django.urls import reverse

from core.testing import LoggedInTestCase
from workplaces.models import Workplace, WorkplaceContract


class ContractEditReturnsToNextTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.wp = Workplace.objects.create(name="JKF", slug="jkf")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp, name="Lab")
        self.url = reverse("workplaces:contract-update",
                           args=[self.wp.slug, self.contract.pk])
        self.back = "/settings/?tab=calendar"

    def test_get_carries_next_into_the_form_and_cancel(self):
        resp = self.client.get(self.url, {"next": self.back})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('name="next" value="/settings/?tab=calendar"', html)
        # Cancel goes back there too, not to the workplace page.
        self.assertIn('href="/settings/?tab=calendar"', html)

    def test_save_redirects_to_next(self):
        resp = self.client.post(self.url, {"name": "Lab", "next": self.back})
        self.assertRedirects(resp, self.back, fetch_redirect_response=False)

    def test_without_next_it_still_returns_to_the_workplace(self):
        resp = self.client.post(self.url, {"name": "Lab"})
        self.assertRedirects(
            resp, reverse("workplaces:workplace-detail", args=[self.wp.slug]),
            fetch_redirect_response=False)

    def test_offsite_next_is_refused(self):
        evil = "https://evil.example.com/"
        resp = self.client.post(self.url, {"name": "Lab", "next": evil})
        self.assertRedirects(
            resp, reverse("workplaces:workplace-detail", args=[self.wp.slug]),
            fetch_redirect_response=False)

    def test_offsite_next_is_not_reflected_into_the_form(self):
        resp = self.client.get(self.url, {"next": "https://evil.example.com/"})
        self.assertNotIn('name="next" value="https://evil.example.com/"',
                         resp.content.decode())


class CalendarTabLinksBackTests(LoggedInTestCase):
    def test_contract_edit_links_carry_the_return_url(self):
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        WorkplaceContract.objects.create(workplace=wp, name="Lab")
        resp = self.client.get("/settings/?tab=calendar")
        self.assertContains(resp, "next=%2Fsettings%2F%3Ftab%3Dcalendar")
