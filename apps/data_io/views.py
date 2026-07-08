import json
from datetime import date

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.views import View
from django.utils import timezone

from workplaces.models import Workplace
from . import services


class DataIOPageView(View):
    """Main page with export form and import upload."""

    def get(self, request):
        workplaces = Workplace.objects.all()
        return render(request, "data_io/main.html", {"workplaces": workplaces})


class ExportView(View):
    """Handle export form submission — return JSON file download."""

    def post(self, request):
        # Parse options
        date_from = request.POST.get("date_from") or None
        date_to = request.POST.get("date_to") or None
        if date_from:
            date_from = date.fromisoformat(date_from)
        if date_to:
            date_to = date.fromisoformat(date_to)

        include_workplaces = request.POST.get("include_workplaces") == "on"
        include_shifts = request.POST.get("include_shifts") == "on"
        include_planned = request.POST.get("include_planned") == "on"
        include_tax = request.POST.get("include_tax") == "on"

        workplace_ids = request.POST.getlist("workplace_ids")
        workplace_ids = [int(x) for x in workplace_ids] if workplace_ids else None

        data = services.export_data(
            date_from=date_from,
            date_to=date_to,
            include_workplaces=include_workplaces,
            include_shifts=include_shifts,
            include_planned=include_planned,
            include_tax=include_tax,
            workplace_ids=workplace_ids,
        )

        content = json.dumps(data, cls=services._Encoder, indent=2, ensure_ascii=False)
        response = HttpResponse(content, content_type="application/json")
        filename = f"bitgigs_export_{timezone.localdate().isoformat()}.json"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ImportUploadView(View):
    """Step 1: Upload file, detect conflicts, show mapping form."""

    def post(self, request):
        uploaded = request.FILES.get("import_file")
        if not uploaded:
            return redirect("data_io:main")

        try:
            content = uploaded.read().decode("utf-8")
            data = services.parse_import_file(content)
        except (ValueError, UnicodeDecodeError) as e:
            from django.contrib import messages
            messages.error(request, f"Import failed: {e}")
            return redirect("data_io:main")

        conflicts = services.detect_workplace_conflicts(data)
        existing_workplaces = Workplace.objects.all()

        # Overlapping contracts only matter for workplaces that will be created
        # (unmatched names); mapped/matched workplaces don't import contracts.
        contract_overlaps = {
            name: clashes
            for name, clashes in services.detect_contract_overlaps(data).items()
            if name in conflicts
        }

        # Summary counts
        summary = {
            "workplaces": len(data.get("workplaces", [])),
            "shifts": len(data.get("shifts", [])),
            "planned_shifts": len(data.get("planned_shifts", [])),
            "tax_profiles": len(data.get("tax_profiles", [])),
        }

        # Store data in session for step 2
        request.session["import_data"] = content

        return render(request, "data_io/import_confirm.html", {
            "conflicts": conflicts,
            "existing_workplaces": existing_workplaces,
            "contract_overlaps": contract_overlaps,
            "summary": summary,
            "data": data,
        })


class ImportConfirmView(View):
    """Step 2: Process the confirmed mapping and import data."""

    def post(self, request):
        from django.contrib import messages

        content = request.session.get("import_data")
        if not content:
            messages.error(request, "No import data found. Please upload again.")
            return redirect("data_io:main")

        try:
            data = services.parse_import_file(content)
        except ValueError as e:
            del request.session["import_data"]
            messages.error(request, f"Import failed: {e}")
            return redirect("data_io:main")
        conflicts = services.detect_workplace_conflicts(data)

        # Build workplace_mapping from form
        workplace_mapping = {}
        for name in conflicts:
            action = request.POST.get(f"action_{name}", "skip")
            if action == "create":
                workplace_mapping[name] = {"action": "create"}
            elif action.startswith("map_"):
                target_id = int(action.replace("map_", ""))
                workplace_mapping[name] = {"action": "map", "target_id": target_id}
            else:
                workplace_mapping[name] = {"action": "skip"}

        # Overlapping contracts only bite workplaces actually being created.
        overlaps = services.detect_contract_overlaps(data)
        overlapping_created = {
            name for name in overlaps
            if workplace_mapping.get(name, {}).get("action") == "create"
        }
        skip_workplaces = set()
        if overlapping_created:
            if request.POST.get("overlap_action") == "discard_all":
                del request.session["import_data"]
                messages.error(
                    request,
                    "Import cancelled — the file contains workplaces with "
                    "overlapping contracts. Nothing was imported.",
                )
                return redirect("data_io:main")
            # Default: skip just the overlapping workplace(s)
            skip_workplaces = overlapping_created

        from django.core.exceptions import ValidationError
        try:
            counts = services.perform_import(
                data, workplace_mapping, skip_workplaces=skip_workplaces
            )
        except (ValueError, ValidationError) as e:
            # perform_import is atomic — nothing was written.
            del request.session["import_data"]
            messages.error(request, f"Import failed, nothing was imported: {e}")
            return redirect("data_io:main")

        # Clean up session
        del request.session["import_data"]

        parts = []
        if counts["shifts_created"]:
            parts.append(f"{counts['shifts_created']} shift(s)")
        if counts["planned_created"]:
            parts.append(f"{counts['planned_created']} planned shift(s)")
        if counts["tax_created"]:
            parts.append(f"{counts['tax_created']} tax profile(s)")
        if counts["skipped"]:
            parts.append(f"{counts['skipped']} skipped")

        msg = "Import complete: " + (", ".join(parts) if parts else "nothing to import.")
        messages.success(request, msg)
        if skip_workplaces:
            messages.warning(
                request,
                "Skipped {} workplace(s) with overlapping contracts: {}.".format(
                    len(skip_workplaces), ", ".join(sorted(skip_workplaces))
                ),
            )
        return redirect("data_io:main")
