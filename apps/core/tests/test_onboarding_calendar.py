"""Phase 2 — calendar-invite opt-in captured on the onboarding Workplace step and
written to the fresh contract at Finish. Best-effort: only a complete "Yes" writes
a config row; "No" or an incomplete "Yes" writes nothing and never blocks Finish."""
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from calendar_sync.models import ContractCalendarConfig
from core import onboarding as ob
from core.models import OnboardingDraft
from workplaces.models import Workplace, WorkplaceContract

from .test_onboarding_coverage import TAX_DRAFT, TERMS_DRAFT


def workplace_draft(**invite):
    base = {"name": "Jåd Kå Æf", "slug": "", "contract-name": ""}
    base.update(invite)
    return base


class OnboardingCalendarCommitTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.request = RequestFactory().get("/onboarding/review/")
        self.request.user = self.user
        self.request.session = {}

    def draft(self, wp):
        OnboardingDraft.objects.update_or_create(
            user=self.user,
            defaults={"data": {"tax": TAX_DRAFT, "workplace": wp, "terms": TERMS_DRAFT}},
        )

    def test_yes_with_details_writes_config(self):
        self.draft(workplace_draft(
            send_invites="true",
            recipient="boss@work.example",
            address_onsite="Main St 1",
        ))
        self.assertIs(ob.commit_setup(self.request), True)
        contract = WorkplaceContract.objects.get()
        cfg = contract.calendar_config
        self.assertTrue(cfg.send_invites)
        self.assertEqual(cfg.recipient, "boss@work.example")

    def test_no_writes_no_config(self):
        self.draft(workplace_draft(send_invites=""))
        self.assertIs(ob.commit_setup(self.request), True)
        self.assertEqual(Workplace.objects.count(), 1)
        self.assertFalse(ContractCalendarConfig.objects.exists())

    def test_incomplete_yes_is_skipped_but_finish_still_succeeds(self):
        # Yes but no recipient/on-site: the config form is invalid, so no row is
        # written — but the rest of setup must still commit.
        self.draft(workplace_draft(send_invites="true"))
        self.assertIs(ob.commit_setup(self.request), True)
        self.assertEqual(WorkplaceContract.objects.count(), 1)
        self.assertFalse(ContractCalendarConfig.objects.exists())


class OnboardingWorkplaceRenderTest(TestCase):
    """The invite block renders on the Workplace step, and its SMTP notice is the
    informational (no link-out) variant while e-mail is unconfigured."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)

    def test_step_shows_invite_toggle_and_informational_notice(self):
        resp = self.client.get("/onboarding/workplace/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="id_send_invites_yes"', html)
        # Informational onboarding copy (points at the email step), not the
        # contract page's new-tab "Set it up under Settings → Email" link.
        self.assertIn("email step", html)
        self.assertNotIn('target="_blank"', html)
