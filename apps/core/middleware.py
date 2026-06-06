from django.shortcuts import redirect
from django.urls import reverse


def _is_setup_flow_url(path):
    """True for URLs that are part of the onboarding flow or infrastructure."""
    if path.startswith((
        "/setup/",
        "/workplaces/new/",
        "/admin/",
        "/static/",
        "/media/",
        "/favicon",
        "/accounts/",
    )):
        return True
    # /workplaces/<slug>/contracts/add/
    parts = path.strip("/").split("/")
    if (len(parts) == 4
            and parts[0] == "workplaces"
            and parts[2] == "contracts"
            and parts[3] == "add"):
        return True
    # /workplaces/<slug>/contracts/<cpk>/terms/add/
    if (len(parts) == 6
            and parts[0] == "workplaces"
            and parts[2] == "contracts"
            and parts[4] == "terms"
            and parts[5] == "add"):
        return True
    return False


class SetupRequiredMiddleware:
    """Redirect any page to the appropriate setup step if onboarding is incomplete."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _is_setup_flow_url(request.path):
            return self.get_response(request)

        if request.session.get("setup_complete"):
            return self.get_response(request)

        from core.models import TaxProfile
        from workplaces.models import Workplace, WorkplaceContract, ContractTermSet

        if not TaxProfile.objects.exists():
            return redirect(reverse("core:setup"))

        if not Workplace.objects.exists():
            return redirect("/workplaces/new/?setup=1")

        if not WorkplaceContract.objects.exists():
            wp = Workplace.objects.first()
            return redirect(f"/workplaces/{wp.slug}/contracts/add/?setup=1")

        if not ContractTermSet.objects.exists():
            wp = Workplace.objects.first()
            contract = WorkplaceContract.objects.filter(workplace=wp).first()
            if contract:
                return redirect(f"/workplaces/{wp.slug}/contracts/{contract.pk}/terms/add/?setup=1")

        request.session["setup_complete"] = True
        return self.get_response(request)
