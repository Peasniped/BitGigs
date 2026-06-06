"""
Export/import services for BitGigs data.

Export format is JSON with sections:
- workplaces: list of workplace dicts (config only, no shifts)
- shifts: list of approved shift (Shift) dicts
- planned_shifts: list of PlannedShift dicts
- tax_profiles: list of TaxProfile dicts
"""
import json
from datetime import date, datetime
from decimal import Decimal

from shifts.models import Shift, PlannedShift
from workplaces.models import Workplace
from core.models import TaxProfile


class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def export_data(*, date_from=None, date_to=None, include_workplaces=True,
                include_shifts=True, include_planned=True, include_tax=True,
                workplace_ids=None):
    """
    Build a JSON-serializable dict of all selected data.
    date_from / date_to filter shifts and planned_shifts by date.
    workplace_ids (list of int or None) filters which workplaces to include.
    """
    data = {"version": 1, "exported_at": datetime.now().isoformat()}

    # Workplaces
    if include_workplaces:
        qs = Workplace.objects.all()
        if workplace_ids:
            qs = qs.filter(pk__in=workplace_ids)
        data["workplaces"] = [_wp_to_dict(wp) for wp in qs]
    else:
        data["workplaces"] = []

    # Approved shifts (Shifts)
    if include_shifts:
        qs = Shift.objects.select_related("workplace").all()
        if workplace_ids:
            qs = qs.filter(workplace_id__in=workplace_ids)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        data["shifts"] = [_shift_to_dict(s) for s in qs]
    else:
        data["shifts"] = []

    # Planned shifts
    if include_planned:
        qs = PlannedShift.objects.select_related("workplace").all()
        if workplace_ids:
            qs = qs.filter(workplace_id__in=workplace_ids)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        data["planned_shifts"] = [_planned_to_dict(s) for s in qs]
    else:
        data["planned_shifts"] = []

    # Tax profiles (not date-filtered)
    if include_tax:
        data["tax_profiles"] = [_tax_to_dict(t) for t in TaxProfile.objects.all()]
    else:
        data["tax_profiles"] = []

    return data


def export_json(**kwargs):
    """Return a JSON string of exported data."""
    return json.dumps(export_data(**kwargs), cls=_Encoder, indent=2, ensure_ascii=False)


def parse_import_file(file_content):
    """
    Parse uploaded JSON and return the data dict.
    Raises ValueError on bad format.
    """
    try:
        data = json.loads(file_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object at the top level.")
    if "version" not in data:
        raise ValueError("Missing 'version' key . not a valid BitGigs export file.")
    return data


def detect_workplace_conflicts(data):
    """
    Examine imported data and find workplace names that don't match existing ones.
    Returns a dict of: { imported_name: existing_workplace_or_None }
    """
    existing = {wp.name: wp for wp in Workplace.objects.all()}
    imported_names = set()

    for wp in data.get("workplaces", []):
        imported_names.add(wp["name"])
    for s in data.get("shifts", []):
        imported_names.add(s["workplace_name"])
    for s in data.get("planned_shifts", []):
        imported_names.add(s["workplace_name"])

    conflicts = {}
    for name in imported_names:
        if name not in existing:
            conflicts[name] = None  # No match
    return conflicts


def perform_import(data, workplace_mapping):
    """
    Import data into the database.

    workplace_mapping: dict mapping imported workplace_name -> action dict:
      {"action": "create"} . create new workplace from export data
      {"action": "map", "target_id": int} . map to existing workplace id
      {"action": "skip"} . skip shifts for this workplace

    Returns a summary dict with counts.
    """
    existing_by_name = {wp.name: wp for wp in Workplace.objects.all()}
    # Resolve mapping: build imported_name -> Workplace instance
    resolved = {}

    for name, action in workplace_mapping.items():
        if action["action"] == "skip":
            resolved[name] = None
        elif action["action"] == "map":
            resolved[name] = Workplace.objects.get(pk=action["target_id"])
        elif action["action"] == "create":
            # Find workplace data from the export
            wp_data = None
            for wp in data.get("workplaces", []):
                if wp["name"] == name:
                    wp_data = wp
                    break
            if wp_data:
                resolved[name] = _create_workplace_from_dict(wp_data)
            else:
                # Create minimal workplace with a placeholder contract/termset
                from datetime import date as _date
                from workplaces.models import WorkplaceContract, ContractTermSet
                minimal_wp = Workplace.objects.create(name=name)
                minimal_contract = WorkplaceContract.objects.create(
                    workplace=minimal_wp,
                    start_date=_date(2000, 1, 1),
                )
                ContractTermSet.objects.create(
                    contract=minimal_contract,
                    effective_from=_date(2000, 1, 1),
                    employment_type="hourly",
                    hourly_rate=Decimal("0"),
                    weekly_hours_fixed=Decimal("37"),
                )
                resolved[name] = minimal_wp

    # Also include already-matching workplaces
    for name in set(
        s.get("workplace_name", "") for s in data.get("shifts", [])
    ) | set(
        s.get("workplace_name", "") for s in data.get("planned_shifts", [])
    ):
        if name not in resolved and name in existing_by_name:
            resolved[name] = existing_by_name[name]

    counts = {"shifts_created": 0, "planned_created": 0, "tax_created": 0, "skipped": 0}

    # Import tax profiles
    for tp in data.get("tax_profiles", []):
        eff = date.fromisoformat(tp["effective_from"])
        if not TaxProfile.objects.filter(effective_from=eff).exists():
            TaxProfile.objects.create(
                monthly_deduction=Decimal(tp["monthly_deduction"]),
                tax_percent=Decimal(tp["tax_percent"]),
                church_tax_percent=Decimal(tp.get("church_tax_percent", "0")),
                am_bidrag_percent=Decimal(tp.get("am_bidrag_percent", "8")),
                effective_from=eff,
            )
            counts["tax_created"] += 1

    # Import shifts
    for s in data.get("shifts", []):
        wp = resolved.get(s["workplace_name"])
        if wp is None:
            counts["skipped"] += 1
            continue
        from datetime import time as _time
        shift_date = date.fromisoformat(s["date"])
        start = _time.fromisoformat(s["start_time"])
        end = _time.fromisoformat(s["end_time"])
        # Avoid duplicates
        if not Shift.objects.filter(
            workplace=wp, date=shift_date, start_time=start, end_time=end
        ).exists():
            Shift.objects.create(
                workplace=wp,
                date=shift_date,
                start_time=start,
                end_time=end,
                break_minutes=s.get("break_minutes", 0),
                shift_type=s.get("shift_type", "on_site"),
                notes=s.get("notes", ""),
            )
            counts["shifts_created"] += 1

    # Import planned shifts
    for s in data.get("planned_shifts", []):
        wp = resolved.get(s["workplace_name"])
        if wp is None:
            counts["skipped"] += 1
            continue
        from datetime import time as _time
        shift_date = date.fromisoformat(s["date"])
        start = _time.fromisoformat(s["start_time"])
        end = _time.fromisoformat(s["end_time"])
        if not PlannedShift.objects.filter(
            workplace=wp, date=shift_date, start_time=start, end_time=end
        ).exists():
            PlannedShift.objects.create(
                workplace=wp,
                date=shift_date,
                start_time=start,
                end_time=end,
                break_minutes=s.get("break_minutes", 0),
                shift_type=s.get("shift_type", "on_site"),
                notes=s.get("notes", ""),
                status=s.get("status", "planned"),
            )
            counts["planned_created"] += 1

    return counts


# â•â•â• Serialization helpers â•â•â•

def _termset_to_dict(ts):
    return {
        "effective_from": ts.effective_from.isoformat(),
        "employment_type": ts.employment_type,
        "hourly_rate": str(ts.hourly_rate) if ts.hourly_rate else None,
        "monthly_salary": str(ts.monthly_salary) if ts.monthly_salary else None,
        "weekly_hours_fixed": str(ts.weekly_hours_fixed) if ts.weekly_hours_fixed else None,
        "weekly_hours_min": str(ts.weekly_hours_min) if ts.weekly_hours_min else None,
        "weekly_hours_max": str(ts.weekly_hours_max) if ts.weekly_hours_max else None,
        "payroll_period_start_day": ts.payroll_period_start_day,
        "tax_card_type": ts.tax_card_type,
        "tax_pull_day": ts.tax_pull_day,
        "vacation_type": ts.vacation_type,
        "pension_employee_percent": str(ts.pension_employee_percent),
        "pension_employer_percent": str(ts.pension_employer_percent),
        "fritvalgskonto_enabled": ts.fritvalgskonto_enabled,
        "fritvalgskonto_percent": str(ts.fritvalgskonto_percent),
        "fritvalgskonto_payout_type": ts.fritvalgskonto_payout_type,
        "ferietillaeg_enabled": ts.ferietillaeg_enabled,
        "ferietillaeg_percent": str(ts.ferietillaeg_percent),
        "ferietillaeg_payout_months": ts.ferietillaeg_payout_months,
        "hour_goal_type": ts.hour_goal_type,
        "hour_goal_min": str(ts.hour_goal_min) if ts.hour_goal_min else None,
        "hour_goal_max": str(ts.hour_goal_max) if ts.hour_goal_max else None,
    }


def _wp_to_dict(wp):
    import base64
    custom_icon_data = None
    if wp.custom_icon:
        try:
            wp.custom_icon.open("rb")
            custom_icon_data = {
                "filename": wp.custom_icon.name.split("/")[-1],
                "data": base64.b64encode(wp.custom_icon.read()).decode("ascii"),
            }
            wp.custom_icon.close()
        except (FileNotFoundError, OSError):
            pass

    contracts = []
    for c in wp.contracts.prefetch_related("term_sets").order_by("start_date"):
        contracts.append({
            "name": c.name,
            "start_date": c.start_date.isoformat(),
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "term_sets": [_termset_to_dict(ts) for ts in c.term_sets.order_by("effective_from")],
        })

    return {
        "name": wp.name,
        "slug": wp.slug,
        "icon": wp.icon,
        "color": wp.color,
        "accent_color": wp.accent_color,
        "custom_icon": custom_icon_data,
        "default_shift_start_time": wp.default_shift_start_time.strftime("%H:%M") if wp.default_shift_start_time else None,
        "default_shift_end_time": wp.default_shift_end_time.strftime("%H:%M") if wp.default_shift_end_time else None,
        "default_shift_break_minutes": wp.default_shift_break_minutes,
        "default_shift_type": wp.default_shift_type,
        "contracts": contracts,
    }


def _shift_to_dict(s):
    return {
        "workplace_name": s.workplace.name,
        "date": s.date.isoformat(),
        "start_time": s.start_time.strftime("%H:%M"),
        "end_time": s.end_time.strftime("%H:%M"),
        "break_minutes": s.break_minutes,
        "shift_type": s.shift_type,
        "notes": s.notes,
    }


def _planned_to_dict(s):
    return {
        "workplace_name": s.workplace.name,
        "date": s.date.isoformat(),
        "start_time": s.start_time.strftime("%H:%M"),
        "end_time": s.end_time.strftime("%H:%M"),
        "break_minutes": s.break_minutes,
        "shift_type": s.shift_type,
        "notes": s.notes,
        "status": s.status,
    }


def _tax_to_dict(t):
    return {
        "monthly_deduction": str(t.monthly_deduction),
        "tax_percent": str(t.tax_percent),
        "church_tax_percent": str(t.church_tax_percent),
        "am_bidrag_percent": str(t.am_bidrag_percent),
        "effective_from": t.effective_from.isoformat(),
    }


def _create_workplace_from_dict(d):
    """Create a Workplace (and its contracts/termsets) from an exported dict."""
    from datetime import time as _time, date as _date
    from workplaces.models import WorkplaceContract, ContractTermSet

    from datetime import time as _time2
    wp = Workplace.objects.create(
        name=d["name"],
        slug=d.get("slug", ""),
        icon=d.get("icon", ""),
        color=d.get("color", ""),
        accent_color=d.get("accent_color", ""),
        default_shift_start_time=_time2.fromisoformat(d["default_shift_start_time"]) if d.get("default_shift_start_time") else None,
        default_shift_end_time=_time2.fromisoformat(d["default_shift_end_time"]) if d.get("default_shift_end_time") else None,
        default_shift_break_minutes=d.get("default_shift_break_minutes", 0) or 0,
        default_shift_type=d.get("default_shift_type", "on_site") or "on_site",
    )

    # Restore custom icon from base64 data
    custom_icon_data = d.get("custom_icon")
    if custom_icon_data and isinstance(custom_icon_data, dict):
        import base64
        from django.core.files.base import ContentFile
        file_bytes = base64.b64decode(custom_icon_data["data"])
        filename = custom_icon_data.get("filename", "icon.png")
        wp.custom_icon.save(filename, ContentFile(file_bytes), save=True)

    if d.get("contracts"):
        # New-format export: restore full contract/termset structure
        for c_data in d["contracts"]:
            contract = WorkplaceContract.objects.create(
                workplace=wp,
                name=c_data.get("name", ""),
                start_date=_date.fromisoformat(c_data["start_date"]),
                end_date=_date.fromisoformat(c_data["end_date"]) if c_data.get("end_date") else None,
            )
            for ts_data in c_data.get("term_sets", []):
                _create_termset_from_dict(contract, ts_data)
    else:
        # Legacy flat format: create one contract + one termset
        contract = WorkplaceContract.objects.create(
            workplace=wp,
            name="",
            start_date=_date(2000, 1, 1),
        )
        _create_termset_from_dict(contract, dict(d, effective_from="2000-01-01"))

    return wp


def _create_termset_from_dict(contract, d):
    from datetime import time as _time, date as _date
    from workplaces.models import ContractTermSet

    kwargs = {
        "contract": contract,
        "effective_from": _date.fromisoformat(d.get("effective_from", "2000-01-01")),
        "employment_type": d.get("employment_type", "hourly"),
        "payroll_period_start_day": d.get("payroll_period_start_day", 1),
        "tax_card_type": d.get("tax_card_type", "hoofdkort"),
        "tax_pull_day": d.get("tax_pull_day", 18),
        "vacation_type": d.get("vacation_type", "feriekonto"),
        "pension_employee_percent": Decimal(d.get("pension_employee_percent", "0")),
        "pension_employer_percent": Decimal(d.get("pension_employer_percent", "0")),
        "fritvalgskonto_enabled": d.get("fritvalgskonto_enabled", False),
        "fritvalgskonto_percent": Decimal(d.get("fritvalgskonto_percent", "0")),
        "fritvalgskonto_payout_type": d.get("fritvalgskonto_payout_type", "accrues"),
        "ferietillaeg_enabled": d.get("ferietillaeg_enabled", False),
        "ferietillaeg_percent": Decimal(d.get("ferietillaeg_percent", "1.00")),
        "ferietillaeg_payout_months": d.get("ferietillaeg_payout_months", "5,8"),
        "hour_goal_type": d.get("hour_goal_type", ""),
    }
    if d.get("hourly_rate"):
        kwargs["hourly_rate"] = Decimal(d["hourly_rate"])
    if d.get("monthly_salary"):
        kwargs["monthly_salary"] = Decimal(d["monthly_salary"])
    if d.get("weekly_hours_fixed"):
        kwargs["weekly_hours_fixed"] = Decimal(d["weekly_hours_fixed"])
    else:
        kwargs["weekly_hours_fixed"] = Decimal("37")
    if d.get("weekly_hours_min"):
        kwargs["weekly_hours_min"] = Decimal(d["weekly_hours_min"])
    if d.get("weekly_hours_max"):
        kwargs["weekly_hours_max"] = Decimal(d["weekly_hours_max"])
    if d.get("hour_goal_min"):
        kwargs["hour_goal_min"] = Decimal(d["hour_goal_min"])
    if d.get("hour_goal_max"):
        kwargs["hour_goal_max"] = Decimal(d["hour_goal_max"])

    return ContractTermSet.objects.create(**kwargs)

