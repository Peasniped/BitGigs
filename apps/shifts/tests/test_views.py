from datetime import date, time
from decimal import Decimal

from django.urls import reverse

from core.testing import LoggedInTestCase
from shifts.models import Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


class OverviewViewTests(LoggedInTestCase):
    """The overview pages render. The daily one reversed a mis-cased URL name
    (``shifts:Shift-create``), which is a NoReverseMatch — i.e. a 500 — and only
    shows up when the template is actually rendered."""

    def setUp(self):
        super().setUp()
        self.wp = Workplace.objects.create(name="Test Corp")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2000, 1, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"),
            weekly_hours_fixed=Decimal("37.00"),
        )
        Shift.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(8, 0),
            end_time=time(16, 0),
            break_minutes=30,
        )

    def test_daily_overview_renders(self):
        url = reverse("shifts:daily-overview", args=[2026, 3, 2])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("shifts:shift-create"))

    def test_daily_overview_renders_with_no_shifts(self):
        url = reverse("shifts:daily-overview", args=[2026, 3, 3])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_monthly_overview_renders(self):
        url = reverse("shifts:monthly-overview", args=[2026, 3])
        self.assertEqual(self.client.get(url).status_code, 200)
