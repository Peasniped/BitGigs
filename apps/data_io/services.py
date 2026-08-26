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

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from shifts.models import Shift, PlannedShift
from workplaces.models import Workplace
from tax.models import TaxProfile
from core.utils import date_spans_overlap


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
    data = {"version": 1, "exported_at": timezone.localtime().isoformat()}

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
        raise ValueError("Missing 'version' key -- not a valid BitGigs export file.")
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


def detect_contract_overlaps(data):
    """Find imported workplaces whose own contracts overlap in time.

    Clean exports never contain overlaps (the source data is validated), so this
    only catches hand-edited/corrupt files. Returns a dict of
    ``{workplace_name: [(contract_label_a, contract_label_b), ...]}`` for every
    workplace with at least one clashing pair.
    """
    problems = {}
    for wp in data.get("workplaces", []):
        parsed = []
        for c in wp.get("contracts", []):
            try:
                start = date.fromisoformat(c["start_date"])
            except (KeyError, TypeError, ValueError):
                continue
            end = None
            if c.get("end_date"):
                try:
                    end = date.fromisoformat(c["end_date"])
                except (TypeError, ValueError):
                    end = None
            label = c.get("name") or f"contract from {start}"
            parsed.append((label, start, end))

        clashes = []
        for i in range(len(parsed)):
            for j in range(i + 1, len(parsed)):
                if date_spans_overlap(parsed[i][1], parsed[i][2], parsed[j][1], parsed[j][2]):
                    clashes.append((parsed[i][0], parsed[j][0]))
        if clashes:
            problems[wp["name"]] = clashes
    return problems


OVERLAP_DISCARD_MESSAGE = (
    "Import cancelled — the file contains workplaces with "
    "overlapping contracts. Nothing was imported."
)


def overlapping_created_workplaces(data, workplace_mapping) -> set[str]:
    """Names whose contracts overlap **and** which this run would create.

    An overlap only bites a workplace being created from the file — one mapped
    onto an existing workplace, or skipped, never has those contracts written.
    Shared by both import flows (Settings → Import and the onboarding wizard) so
    they can't disagree about what the file's overlaps affect.
    """
    overlaps = detect_contract_overlaps(data)
    return {
        name for name in overlaps
        if workplace_mapping.get(name, {}).get("action") == "create"
    }


def import_summary(data):
    """Row counts for the review page, per export section."""
    return {
        "workplaces": len(data.get("workplaces", [])),
        "shifts": len(data.get("shifts", [])),
        "planned_shifts": len(data.get("planned_shifts", [])),
        "tax_profiles": len(data.get("tax_profiles", [])),
    }


def describe_conflicts(data, conflicts):
    """Review-page rows for unmatched names: ``{"name", "defined"}``, sorted.

    ``defined`` separates the two very different things "create" can mean. A file
    that *defines* the workplace restores its settings, contracts and pay terms;
    a file that only *mentions* it on a shift yields a bare workplace with a stub
    contract that still needs its pay terms entered. Same word, same button —
    which is why the option text has to say which one you're getting."""
    defined = {wp.get("name") for wp in data.get("workplaces", [])}
    return [{"name": name, "defined": name in defined} for name in sorted(conflicts)]


def build_workplace_mapping(post, conflicts):
    """Decode the review page's per-workplace ``action_<name>`` selects into the
    mapping ``perform_import`` expects. Anything unrecognised (including a
    non-numeric target id) falls back to "skip", so a tampered form can only ever
    import less, never something unintended."""
    from core.utils import parse_int_param

    mapping = {}
    for name in conflicts:
        action = post.get(f"action_{name}", "skip")
        if action in ("create", "create_blank"):
            mapping[name] = {"action": action}
        elif action.startswith("map_"):
            target_id = parse_int_param(action.removeprefix("map_"))
            mapping[name] = ({"action": "skip"} if target_id is None
                             else {"action": "map", "target_id": target_id})
        else:
            mapping[name] = {"action": "skip"}
    return mapping


def describe_import(counts):
    """Human summary of a completed import ("Import complete: 3 shift(s), …")."""
    parts = []
    if counts.get("workplaces_created"):
        parts.append(f"{counts['workplaces_created']} workplace(s)")
    if counts.get("termsets_created"):
        parts.append(f"{counts['termsets_created']} pay term set(s)")
    if counts["shifts_created"]:
        parts.append(f"{counts['shifts_created']} shift(s)")
    if counts["planned_created"]:
        parts.append(f"{counts['planned_created']} planned shift(s)")
    if counts["tax_created"]:
        parts.append(f"{counts['tax_created']} tax profile(s)")
    if counts["skipped"]:
        parts.append(f"{counts['skipped']} skipped")
    return "Import complete: " + (", ".join(parts) if parts else "nothing to import.")


@transaction.atomic
def perform_import(data, workplace_mapping, skip_workplaces=None):
    """
    Import data into the database. Runs in a single transaction — a failure
    midway (bad dates, invalid rows) rolls the whole import back.

    workplace_mapping: dict mapping imported workplace_name -> action dict:
      {"action": "create"} . create new workplace from export data
      {"action": "map", "target_id": int} . map to existing workplace id
      {"action": "skip"} . skip shifts for this workplace

    skip_workplaces: set of imported workplace names to treat as "skip"
      regardless of their mapping (used to drop workplaces with overlapping
      contracts).

    Returns a summary dict with counts.
    """
    skip_workplaces = skip_workplaces or set()
    existing_by_name = {wp.name: wp for wp in Workplace.objects.all()}
    # Initialised before the resolution loop below, which creates workplaces.
    counts = {"workplaces_created": 0, "termsets_created": 0,
              "shifts_created": 0, "planned_created": 0, "tax_created": 0, "skipped": 0}
    # Resolve mapping: build imported_name -> Workplace instance
    resolved = {}

    for name, action in workplace_mapping.items():
        if name in skip_workplaces or action["action"] == "skip":
            resolved[name] = None
        elif action["action"] == "map":
            try:
                resolved[name] = Workplace.objects.get(pk=action["target_id"])
            except Workplace.DoesNotExist:
                raise ValueError(
                    f"The workplace selected for '{name}' no longer exists."
                )
        elif action["action"] == "create_blank":
            # The file describes this workplace, but the user chose to start it
            # clean rather than take its settings.
            resolved[name] = _create_blank_workplace(name)
            counts["workplaces_created"] += 1
            counts["termsets_created"] += 1
        elif action["action"] == "create":
            # Find workplace data from the export
            wp_data = None
            for wp in data.get("workplaces", []):
                if wp["name"] == name:
                    wp_data = wp
                    break
            if wp_data:
                created_wp, n_termsets = _create_workplace_from_dict(wp_data)
                resolved[name] = created_wp
                counts["workplaces_created"] += 1
                counts["termsets_created"] += n_termsets
            else:
                # The file names this workplace but never describes it.
                resolved[name] = _create_blank_workplace(name)
                counts["workplaces_created"] += 1
                counts["termsets_created"] += 1

    # Also include already-matching workplaces
    for name in set(
        s.get("workplace_name", "") for s in data.get("shifts", [])
    ) | set(
        s.get("workplace_name", "") for s in data.get("planned_shifts", [])
    ):
        if name not in resolved and name in existing_by_name:
            resolved[name] = existing_by_name[name]

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
            shift = Shift(
                workplace=wp,
                date=shift_date,
                start_time=start,
                end_time=end,
                break_minutes=s.get("break_minutes", 0),
                shift_type=s.get("shift_type", "on_site"),
                notes=s.get("notes", ""),
            )
            try:
                shift.full_clean()
            except ValidationError:
                # e.g. a date no contract covers — skip the row, keep the import
                counts["skipped"] += 1
                continue
            shift.save()
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
            planned = PlannedShift(
                workplace=wp,
                date=shift_date,
                start_time=start,
                end_time=end,
                break_minutes=s.get("break_minutes", 0),
                shift_type=s.get("shift_type", "on_site"),
                notes=s.get("notes", ""),
                status=s.get("status", "planned"),
            )
            try:
                planned.full_clean()
            except ValidationError:
                counts["skipped"] += 1
                continue
            planned.save()
            counts["planned_created"] += 1

    return counts


# --- Serialization helpers ---

def _termset_to_dict(ts):
    return {
        "effective_from": ts.effective_from.isoformat(),
        "effective_until": ts.effective_until.isoformat() if ts.effective_until else None,
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
    from django.db.models import Min
    ordered = (
        wp.contracts.prefetch_related("term_sets")
        .annotate(_start=Min("term_sets__effective_from"))
        .order_by("_start")
    )
    for c in ordered:
        # start_date/end_date are derived from the term sets (kept in the export
        # for the overlap detector and human readability).
        contracts.append({
            "name": c.name,
            "start_date": c.start_date.isoformat() if c.start_date else None,
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


def _restore_custom_icon(wp, icon_data):
    """Restore a base64 icon with the same guards as the upload view: extension
    allowlist, size cap, and SVG sanitisation. Invalid icons are skipped (the
    icon is cosmetic; the import itself proceeds)."""
    import base64
    import binascii
    import os

    from django.core.files.base import ContentFile

    from core.utils import sanitize_svg
    from workplaces.services import ALLOWED_ICON_EXTS, MAX_ICON_SIZE

    try:
        file_bytes = base64.b64decode(icon_data["data"])
    except (KeyError, TypeError, binascii.Error):
        return
    filename = icon_data.get("filename", "icon.png")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_ICON_EXTS or len(file_bytes) > MAX_ICON_SIZE:
        return
    if ext == ".svg":
        file_bytes = sanitize_svg(file_bytes)
        if file_bytes is None:
            return
    wp.custom_icon.save(filename, ContentFile(file_bytes), save=True)


def _create_blank_workplace(name):
    """A workplace with nothing but a name, plus the stub contract its shifts need.

    Used when the file doesn't describe the workplace, and when the user asks for
    a clean one instead of the file's settings. The term set is a placeholder — a
    Shift is refused unless a contract is active on its date, so the shifts would
    be dropped without it. Callers surface it for correction; see
    ``core.onboarding.placeholder_termsets``."""
    from datetime import date as _date
    from workplaces.models import WorkplaceContract, ContractTermSet

    wp = Workplace.objects.create(name=name)
    contract = WorkplaceContract.objects.create(workplace=wp)
    ContractTermSet.objects.create(
        contract=contract,
        effective_from=_date(2000, 1, 1),
        employment_type="hourly",
        hourly_rate=Decimal("0"),
        weekly_hours_fixed=Decimal("37"),
    )
    return wp


def _create_workplace_from_dict(d):
    """Create a Workplace (and its contracts/termsets) from an exported dict.

    Returns ``(workplace, termsets_created)`` — the caller counts term sets so a
    coverage report can tell "imported a workplace" from "imported pay terms".
    An export may legitimately carry a workplace with ``contracts: []``, which
    yields zero term sets."""
    from datetime import time as _time
    from workplaces.models import WorkplaceContract
    from workplaces.services import valid_hex_color, valid_icon_class

    # Appearance fields from the file are untrusted (a hand-edited export could
    # smuggle markup into style/class contexts) — drop anything malformed, the
    # same shapes the customize view enforces. The icon is cosmetic; the import
    # itself proceeds.
    icon = d.get("icon", "") or ""
    color = d.get("color", "") or ""
    accent_color = d.get("accent_color", "") or ""

    # A slug already in use would IntegrityError mid-transaction; blank it and
    # let Workplace.save() derive a unique one from the name instead.
    slug = d.get("slug", "") or ""
    if slug and Workplace.objects.filter(slug=slug).exists():
        slug = ""

    wp = Workplace.objects.create(
        name=d["name"],
        slug=slug,
        icon=icon if valid_icon_class(icon) else "",
        color=color if valid_hex_color(color) else "",
        accent_color=accent_color if valid_hex_color(accent_color) else "",
        default_shift_start_time=_time.fromisoformat(d["default_shift_start_time"]) if d.get("default_shift_start_time") else None,
        default_shift_end_time=_time.fromisoformat(d["default_shift_end_time"]) if d.get("default_shift_end_time") else None,
        default_shift_break_minutes=d.get("default_shift_break_minutes", 0) or 0,
        default_shift_type=d.get("default_shift_type", "on_site") or "on_site",
    )

    custom_icon_data = d.get("custom_icon")
    if custom_icon_data and isinstance(custom_icon_data, dict):
        _restore_custom_icon(wp, custom_icon_data)

    termsets = 0
    if "contracts" in d:
        # New-format export: restore full contract/termset structure (an empty
        # list is valid — a workplace with no contracts yet). A contract has no
        # dates of its own — its span is derived from the term sets.
        # Overlapping workplaces are already filtered upstream by
        # detect_contract_overlaps before import.
        for c_data in d["contracts"]:
            contract = WorkplaceContract.objects.create(
                workplace=wp,
                name=c_data.get("name", ""),
            )
            for ts_data in c_data.get("term_sets", []):
                _create_termset_from_dict(contract, ts_data)
                termsets += 1
    else:
        # Legacy flat format: create one contract + one termset
        contract = WorkplaceContract.objects.create(workplace=wp, name="")
        _create_termset_from_dict(contract, dict(d, effective_from="2000-01-01"))
        termsets = 1

    return wp, termsets


def _create_termset_from_dict(contract, d):
    from datetime import time as _time, date as _date
    from workplaces.models import ContractTermSet

    kwargs = {
        "contract": contract,
        "effective_from": _date.fromisoformat(d.get("effective_from", "2000-01-01")),
        "effective_until": _date.fromisoformat(d["effective_until"]) if d.get("effective_until") else None,
        "employment_type": d.get("employment_type", "hourly"),
        "payroll_period_start_day": d.get("payroll_period_start_day", 1),
        "tax_card_type": d.get("tax_card_type", "hovedkort"),
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

    ts = ContractTermSet(**kwargs)
    # Enforce the model invariants (incl. the contract-overlap guard) on
    # imported data too; a ValidationError aborts and rolls back the import.
    ts.full_clean()
    ts.save()
    return ts

