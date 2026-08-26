"""Generator for the demo dataset (see ``manage.py seed_demo_data``).

Builds a synthetic but plausible two-year working life: six workplaces, a
mixture of hourly and salaried, contracts that start, end and hand over, mid-
contract raises, an offset payroll period, and shifts running from ~19 months
ago to the end of next month.

**Everything is anchored on today**, expressed as month offsets from
``history_start`` rather than as literal dates — a fixture pinned to 2025-2026
reads as ancient history the moment the year turns, and the whole point of the
data is that "now" sits in the middle of it with real months behind and planned
months ahead.

Three rules keep it readable as one person's life rather than as noise:

* **at most three jobs at once** — a permanent pair (Netto hourly, AAU salaried)
  plus a third slot that changes hands;
* **no two shifts overlap in time** — the weekly pattern windows are disjoint,
  and a candidate that jitter pushes onto an already-placed shift is dropped
  rather than nudged, which would only move the collision;
* **leave belongs to the day, not to one job** — a holiday or a sick day books
  at every job that would have been worked and nothing else. You do not take a
  holiday from one employer and turn up at another the same afternoon.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

D = Decimal

DEFAULT_SEED = 20260813
DEFAULT_EMAIL = "demo@bitgigs.dk"
DEFAULT_PASSWORD = "Screenshot2026!"
DEFAULT_NAME = "Mikkel"

# How far back the history runs, in whole months before the current one. The
# handover offsets below are positions inside this window.
HISTORY_MONTHS = 19

# Fixed-date Danish public holidays. Enough to make the calendar look plausible
# without pulling in an easter algorithm.
SKIP_DAYS = {(1, 1), (12, 24), (12, 25), (12, 26), (12, 31), (6, 5)}

# (month offset from history_start, first day, last day, shift type)
LEAVE_BLOCKS = [
    (6, 7, 18, "vacation"),
    (9, 13, 17, "vacation"),
    (10, 19, 21, "sick_leave"),
    (13, 16, 20, "vacation"),
    (14, 9, 11, "sick_leave"),
    (18, 13, 31, "vacation"),
]


@dataclass
class DemoResult:
    workplaces: int = 0
    contracts: int = 0
    term_sets: int = 0
    approved: int = 0
    pending: int = 0
    planned: int = 0
    periods: int = 0
    first_day: date | None = None
    last_day: date | None = None


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    """(year, month) *delta* months from (y, m). Negative goes back."""
    total = y * 12 + (m - 1) + delta
    return total // 12, total % 12 + 1


def _month_day(anchor: tuple[int, int], offset: int, day: int) -> date:
    """The *day*-th of the month *offset* months after *anchor*, clamped to the
    month's length so a "31st" in a short month still resolves."""
    from calendar import monthrange

    y, m = _shift_month(anchor[0], anchor[1], offset)
    return date(y, m, min(day, monthrange(y, m)[1]))


def _month_end(anchor: tuple[int, int], offset: int) -> date:
    from calendar import monthrange

    y, m = _shift_month(anchor[0], anchor[1], offset)
    return date(y, m, monthrange(y, m)[1])


def _build_spec(anchor: tuple[int, int]):
    """The six workplaces, with every date derived from *anchor* (the first
    month of history). The third-slot handovers sit at these offsets:

        0-6    Café Kaffeklubben        (ends — the "contract finished" case)
        7      nothing                  (a month between jobs)
        8-11   Fitness World, vikar
        12-14  Fitness World, fast      (same workplace, second contract)
        15-18  Nordjysk Webbureau
        19-    Aalborg Kongres          (starts this month — no closed period yet)
    """
    from workplaces.models import ContractTermSet

    HOURLY = ContractTermSet.EmploymentType.HOURLY
    SALARIED = ContractTermSet.EmploymentType.SALARIED
    HOVED = ContractTermSet.TaxCardType.HOVEDKORT
    BI = ContractTermSet.TaxCardType.BIKORT
    FERIEKONTO = ContractTermSet.VacationType.FERIEKONTO
    ACCRUED = ContractTermSet.VacationType.ACCRUED

    at = lambda off, day=1: _month_day(anchor, off, day)  # noqa: E731
    end_of = lambda off: _month_end(anchor, off)          # noqa: E731

    return {
        "netto": dict(
            name="Netto Nørrebro", icon="bi-cart-fill",
            color="#fef08a", accent="#eab308",
            default=(time(16, 0), time(21, 30), 30, "on_site"),
            contracts=[("Butiksassistent", [
                # Started five months before the window opens, so the main job
                # is already established when the history begins.
                dict(effective_from=at(-5), employment_type=HOURLY,
                     hourly_rate=D("138.50"),
                     weekly_hours_min=D("12"), weekly_hours_max=D("25"),
                     payroll_period_start_day=1, tax_card_type=HOVED,
                     tax_pull_day=18, vacation_type=FERIEKONTO,
                     fritvalgskonto_enabled=True, fritvalgskonto_percent=D("4.00"),
                     hour_goal_type="weekly", hour_goal_min=D("12"),
                     hour_goal_max=D("25")),
                dict(effective_from=at(6), hourly_rate=D("145.20")),
                dict(effective_from=at(15), hourly_rate=D("152.00"),
                     fritvalgskonto_percent=D("5.00")),
            ])],
            pattern=[(0, time(16, 0), time(21, 30), 30, 0.9),
                     (2, time(16, 0), time(21, 30), 30, 0.85),
                     (5, time(13, 0), time(18, 0), 30, 0.8)],
        ),
        "aau": dict(
            name="Aalborg Universitet", icon="bi-mortarboard-fill",
            color="#bfdbfe", accent="#3b82f6",
            default=(time(9, 0), time(15, 30), 30, "on_site"),
            contracts=[("Studentermedhjælper, Institut for Datalogi", [
                # Salaried, and paid on an offset 20th→19th period — the awkward
                # case most of the payroll code exists to get right.
                dict(effective_from=at(0), employment_type=SALARIED,
                     monthly_salary=D("9850.00"), weekly_hours_fixed=D("15"),
                     payroll_period_start_day=20, tax_card_type=BI,
                     tax_pull_day=17, vacation_type=ACCRUED,
                     pension_employee_percent=D("4.00"),
                     pension_employer_percent=D("8.00"),
                     ferietillaeg_enabled=True, ferietillaeg_percent=D("1.00"),
                     ferietillaeg_payout_months="5,8"),
                dict(effective_from=at(12), monthly_salary=D("10400.00")),
            ])],
            pattern=[(1, time(9, 0), time(15, 30), 30, 0.9),
                     (2, time(9, 0), time(13, 0), 0, 0.45),
                     (3, time(9, 0), time(15, 30), 30, 0.9)],
        ),
        "cafe": dict(
            name="Café Kaffeklubben", icon="bi-cup-hot-fill",
            color="#fed7aa", accent="#f97316",
            default=(time(6, 30), time(12, 0), 30, "on_site"),
            contracts=[("Barista", [
                dict(effective_from=at(0), effective_until=end_of(6),
                     employment_type=HOURLY, hourly_rate=D("132.00"),
                     weekly_hours_min=D("6"), weekly_hours_max=D("14"),
                     payroll_period_start_day=1, tax_card_type=BI,
                     tax_pull_day=18, vacation_type=FERIEKONTO),
            ])],
            pattern=[(4, time(6, 30), time(12, 0), 30, 0.85),
                     (6, time(8, 0), time(14, 0), 30, 0.8)],
        ),
        "fitness": dict(
            name="Fitness World Hasseris", icon="bi-heart-pulse-fill",
            color="#bbf7d0", accent="#22c55e",
            default=(time(17, 30), time(20, 30), 0, "on_site"),
            contracts=[
                ("Vikar", [
                    dict(effective_from=at(8), effective_until=end_of(11),
                         employment_type=HOURLY, hourly_rate=D("141.00"),
                         weekly_hours_min=D("3"), weekly_hours_max=D("10"),
                         payroll_period_start_day=1, tax_card_type=BI,
                         tax_pull_day=18, vacation_type=FERIEKONTO),
                ]),
                ("Fast holdinstruktør", [
                    dict(effective_from=at(12), effective_until=end_of(14),
                         employment_type=HOURLY, hourly_rate=D("168.00"),
                         weekly_hours_min=D("4"), weekly_hours_max=D("10"),
                         payroll_period_start_day=1, tax_card_type=BI,
                         tax_pull_day=18, vacation_type=FERIEKONTO,
                         fritvalgskonto_enabled=True,
                         fritvalgskonto_percent=D("4.00"),
                         fritvalgskonto_payout_type="paid_monthly"),
                ]),
            ],
            pattern=[(1, time(17, 30), time(20, 30), 0, 0.85),
                     (5, time(9, 0), time(12, 0), 0, 0.7)],
        ),
        "web": dict(
            name="Nordjysk Webbureau", icon="bi-laptop-fill",
            color="#99f6e4", accent="#14b8a6",
            default=(time(18, 30), time(21, 30), 0, "remote"),
            contracts=[("Freelance frontend", [
                dict(effective_from=at(15), employment_type=HOURLY,
                     hourly_rate=D("275.00"), weekly_hours_min=D("2"),
                     weekly_hours_max=D("10"), payroll_period_start_day=1,
                     tax_card_type=BI, tax_pull_day=15,
                     vacation_type=FERIEKONTO),
                dict(effective_from=at(17), effective_until=end_of(18),
                     hourly_rate=D("295.00")),
            ])],
            pattern=[(3, time(18, 30), time(21, 30), 0, 0.7),
                     (6, time(16, 0), time(19, 30), 0, 0.6)],
        ),
        "akkc": dict(
            name="Aalborg Kongres & Kultur Center", icon="bi-music-note-beamed",
            color="#ddd6fe", accent="#8b5cf6",
            default=(time(17, 0), time(23, 0), 30, "on_site"),
            contracts=[("Eventmedarbejder", [
                dict(effective_from=at(19), employment_type=HOURLY,
                     hourly_rate=D("165.00"), weekly_hours_min=D("0"),
                     weekly_hours_max=D("12"), payroll_period_start_day=1,
                     tax_card_type=BI, tax_pull_day=20,
                     vacation_type=FERIEKONTO),
            ])],
            pattern=[(4, time(17, 0), time(23, 0), 30, 0.6),
                     (5, time(19, 0), time(23, 30), 45, 0.6)],
        ),
    }


def _leave_windows(anchor: tuple[int, int]) -> list[tuple[date, date, str]]:
    return [
        (_month_day(anchor, off, first), _month_day(anchor, off, last), kind)
        for (off, first, last, kind) in LEAVE_BLOCKS
    ]


@transaction.atomic
def build_demo_data(
    *, today: date | None = None, seed: int = DEFAULT_SEED,
    email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD,
    name: str = DEFAULT_NAME, with_payroll: bool = True,
) -> DemoResult:
    """Wipe the working data and write the demo dataset in its place.

    Destructive by design — the command that calls this is what asks for
    confirmation. Runs in one transaction so a failure leaves nothing behind.
    """
    from django.contrib.auth.models import User

    from core.models import UserSettings
    from tax.models import ATPBracket, ATPConfiguration, TaxProfile
    from payroll.models import (
        CommutingRecord, PayrollPeriod, PayslipLine, VacationBalance,
    )
    from shifts.models import PlannedShift, Shift
    from workplaces.models import ContractTermSet, Workplace, WorkplaceContract

    today = today or timezone.localdate()
    rng = random.Random(seed)
    result = DemoResult()

    anchor = _shift_month(today.year, today.month, -HISTORY_MONTHS)
    history_start = date(anchor[0], anchor[1], 1)
    plan_until = _month_end((today.year, today.month), 1)
    pending_from = today - timedelta(days=3)
    leave_windows = _leave_windows(anchor)

    # ── account, tax, ATP ────────────────────────────────────────────────────
    User.objects.all().delete()
    owner = User.objects.create_superuser(
        username=email, email=email, password=password,
    )
    owner.first_name = name
    owner.save(update_fields=["first_name"])

    TaxProfile.objects.all().delete()
    TaxProfile.objects.create(
        effective_from=history_start, monthly_deduction=D("4300.00"),
        tax_percent=D("37.00"), church_tax_percent=D("0.87"),
        am_bidrag_percent=D("8.00"),
    )
    TaxProfile.objects.create(
        effective_from=_month_day(anchor, 12, 1), monthly_deduction=D("4520.00"),
        tax_percent=D("37.10"), church_tax_percent=D("0.87"),
        am_bidrag_percent=D("8.00"),
    )

    ATPConfiguration.objects.all().delete()
    atp = ATPConfiguration.objects.create(
        effective_from=date(history_start.year - 1, 1, 1),
    )
    for lo, hi, emp, empl in [
        (0, 38, "0.00", "0.00"), (39, 77, "33.00", "66.00"),
        (78, 116, "66.00", "132.00"), (117, None, "99.00", "198.00"),
    ]:
        ATPBracket.objects.create(
            configuration=atp, hours_min=D(lo),
            hours_max=None if hi is None else D(hi),
            employee_amount=D(emp), employer_amount=D(empl),
        )

    settings_row = UserSettings.load()
    settings_row.theme = "light"
    settings_row.week_start = 0
    settings_row.projection_method = "ema"
    settings_row.projection_trailing_months = 6
    settings_row.use_planned_shifts = True
    settings_row.mask_money = False
    settings_row.save()

    # ── workplaces / contracts / term sets ───────────────────────────────────
    Workplace.objects.all().delete()
    spec_by_key = _build_spec(anchor)
    workplaces = {}
    for key, spec in spec_by_key.items():
        wp = Workplace.objects.create(
            name=spec["name"], icon=spec["icon"], color=spec["color"],
            accent_color=spec["accent"],
            default_shift_start_time=spec["default"][0],
            default_shift_end_time=spec["default"][1],
            default_shift_break_minutes=spec["default"][2],
            default_shift_type=spec["default"][3],
        )
        workplaces[key] = wp
        for label, term_sets in spec["contracts"]:
            contract = WorkplaceContract.objects.create(workplace=wp, name=label)
            carried: dict = {}
            for fields in term_sets:
                carried = {**carried, **fields}       # a raise inherits the rest
                if "effective_until" not in fields:   # …but never the old end date
                    carried.pop("effective_until", None)
                ts = ContractTermSet(contract=contract, **carried)
                ts.full_clean()
                ts.save()

    result.workplaces = Workplace.objects.count()
    result.contracts = WorkplaceContract.objects.count()
    result.term_sets = ContractTermSet.objects.count()

    # ── shifts ───────────────────────────────────────────────────────────────
    Shift.objects.all().delete()
    PlannedShift.objects.all().delete()

    def leave_on(day: date) -> str | None:
        for start, end, kind in leave_windows:
            if start <= day <= end:
                return kind
        return None

    def jitter(t: time, minutes: int) -> time:
        steps = minutes // 15
        delta = rng.randint(-steps, steps) * 15
        total = min(max(t.hour * 60 + t.minute + delta, 0), 23 * 60 + 45)
        return time(total // 60, total % 60)

    contracts_by_key = {
        key: list(workplaces[key].contracts.prefetch_related("term_sets"))
        for key in spec_by_key
    }
    approved, pending, planned = [], [], []

    day = history_start
    while day <= plan_until:
        if (day.month, day.day) in SKIP_DAYS:
            day += timedelta(days=1)
            continue

        kind = leave_on(day)
        placed: list[tuple[time, time]] = []
        for key, spec in spec_by_key.items():
            wp = workplaces[key]

            termset = None
            for contract in contracts_by_key[key]:
                termset = contract.active_termset_on(day)
                if termset:
                    break
            if termset is None:
                continue

            for weekday, start, end, brk, chance in spec["pattern"]:
                if day.weekday() != weekday or rng.random() > chance:
                    continue

                if kind:
                    # Leave is logged against the hours that job would have had,
                    # so an evening job books an evening — not a blanket 8 h.
                    shift_type, brk = kind, 0
                else:
                    shift_type = spec["default"][3]
                    start = jitter(start, 30)
                    end = jitter(end, 45)
                if start >= end:
                    continue
                if any(start < p_end and p_start < end for p_start, p_end in placed):
                    continue
                placed.append((start, end))

                common = dict(
                    workplace=wp, date=day, start_time=start, end_time=end,
                    break_minutes=brk, shift_type=shift_type,
                )
                if day < pending_from:
                    approved.append(Shift(terms=termset, **common))
                elif day <= today:
                    # A few days left unapproved, so the dashboard has something
                    # in its Review & Approve queue.
                    pending.append(
                        PlannedShift(status=PlannedShift.Status.PLANNED, **common)
                    )
                else:
                    planned.append(
                        PlannedShift(status=PlannedShift.Status.PLANNED, **common)
                    )
        day += timedelta(days=1)

    Shift.objects.bulk_create(approved, batch_size=500)
    PlannedShift.objects.bulk_create(pending + planned, batch_size=500)
    result.approved, result.pending, result.planned = (
        len(approved), len(pending), len(planned)
    )
    result.first_day, result.last_day = history_start, plan_until

    # ── payroll periods, vacation, commuting ─────────────────────────────────
    PayrollPeriod.objects.all().delete()
    PayslipLine.objects.all().delete()
    VacationBalance.objects.all().delete()
    CommutingRecord.objects.all().delete()

    if with_payroll:
        from payroll.services import (
            CommutingService, PayrollPeriodService, PayslipService, VacationService,
        )

        month_start = date(today.year, today.month, 1)
        y, m = anchor
        while (y, m) <= (today.year, today.month):
            for wp in workplaces.values():
                if wp.active_termset_in_month(y, m) is None:
                    continue
                period, _ = PayrollPeriodService.get_or_create_period(wp, y, m)
                PayslipService.populate_standard_lines(period)
                # A period that closed before this month is settled, so lock it.
                if period.end_date < month_start:
                    period.is_locked = True
                    period.save(update_fields=["is_locked"])
                VacationService.update_balance(wp, y, m)
                CommutingService.update_commuting(wp, y, m)
                result.periods += 1
            y, m = _shift_month(y, m, 1)

    return result
