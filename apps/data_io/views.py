import json

from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views import View
from django.utils import timezone

from core.utils import parse_int_param, parse_iso_date_param
from workplaces.models import Workplace
from . import services

# A malformed import file must answer with a message, not a 500. Beyond bad JSON
# (ValueError) and invalid rows (ValidationError), hand-edited files can miss
# keys (KeyError), carry non-numeric decimals (InvalidOperation, an
# ArithmeticError) or wrong-shaped structures (TypeError/AttributeError).
IMPORT_ERRORS = (ValueError, KeyError, TypeError, AttributeError, ArithmeticError)

# Uploads land in the session between the two import steps, so cap them well
# before they could bloat it (a real export is a few hundred KB at most).
MAX_IMPORT_SIZE = 10 * 1024 * 1024  # 10 MB


class DataIOPageView(View):
    """Main page with export form and import upload."""

    def get(self, request):
        workplaces = Workplace.objects.all()
        return render(request, "data_io/main.html", {"workplaces": workplaces})


class ExportView(View):
    """Handle export form submission — return JSON file download."""

    def post(self, request):
        # Parse options — bad values fall back to "no filter" rather than 500.
        date_from = parse_iso_date_param(request.POST.get("date_from"))
        date_to = parse_iso_date_param(request.POST.get("date_to"))

        include_workplaces = request.POST.get("include_workplaces") == "on"
        include_shifts = request.POST.get("include_shifts") == "on"
        include_planned = request.POST.get("include_planned") == "on"
        include_tax = request.POST.get("include_tax") == "on"

        raw_ids = request.POST.getlist("workplace_ids")
        workplace_ids = [
            wid for wid in (parse_int_param(x) for x in raw_ids) if wid is not None
        ] or None

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
        from django.contrib import messages

        uploaded = request.FILES.get("import_file")
        if not uploaded:
            return redirect("data_io:main")
        if uploaded.size > MAX_IMPORT_SIZE:
            messages.error(request, "Import failed: the file is larger than 10 MB.")
            return redirect("data_io:main")

        try:
            content = uploaded.read().decode("utf-8")
            data = services.parse_import_file(content)

            conflicts = services.detect_workplace_conflicts(data)

            # Overlapping contracts only matter for workplaces that will be created
            # (unmatched names); mapped/matched workplaces don't import contracts.
            contract_overlaps = {
                name: clashes
                for name, clashes in services.detect_contract_overlaps(data).items()
                if name in conflicts
            }

            summary = services.import_summary(data)
        except (UnicodeDecodeError, *IMPORT_ERRORS) as e:
            messages.error(request, f"Import failed: {e}")
            return redirect("data_io:main")

        existing_workplaces = Workplace.objects.all()

        # Store data in session for step 2
        request.session["import_data"] = content

        return render(request, "data_io/import_confirm.html", {
            "conflicts": conflicts,
            "conflict_rows": services.describe_conflicts(data, conflicts),
            "existing_workplaces": existing_workplaces,
            "contract_overlaps": contract_overlaps,
            "summary": summary,
            "data": data,
            # The onboarding wizard reuses this template with its own endpoints.
            "confirm_url": reverse("data_io:import-confirm"),
            "cancel_url": reverse("data_io:main"),
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
            conflicts = services.detect_workplace_conflicts(data)
        except IMPORT_ERRORS as e:
            del request.session["import_data"]
            messages.error(request, f"Import failed: {e}")
            return redirect("data_io:main")

        workplace_mapping = services.build_workplace_mapping(request.POST, conflicts)

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
        except (ValidationError, *IMPORT_ERRORS) as e:
            # perform_import is atomic — nothing was written.
            del request.session["import_data"]
            messages.error(request, f"Import failed, nothing was imported: {e}")
            return redirect("data_io:main")

        # Clean up session
        del request.session["import_data"]

        messages.success(request, services.describe_import(counts))
        if skip_workplaces:
            messages.warning(
                request,
                "Skipped {} workplace(s) with overlapping contracts: {}.".format(
                    len(skip_workplaces), ", ".join(sorted(skip_workplaces))
                ),
            )
        return redirect("data_io:main")
