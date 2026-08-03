"""First-time setup wizard: draft storage, step model and the commit.

The account is created immediately (step 1) — the whole site is behind a login,
so there must be a logged-in user for the remaining steps. The data steps are
then held in a durable per-user ``OnboardingDraft`` (a DB row, not the session,
so logging out mid-onboarding doesn't lose the data) and written to the real
tables together, atomically, only on the final "Finish". Each step's stored
payload is the raw POST of a form that already passed ``is_valid()``, so
re-binding it on a later visit re-shows the input with no validation errors —
that's what makes back-navigation keep its place.

The contract has no step of its own: its only editable field is an optional
label, so the Workplace step carries it as a prefixed "contract-name" field and
a single payload holds both forms.

This lives outside ``views.py`` (which is already ~1300 lines) and outside
``services.py`` (which is the tax engine), following the ``dashboard_service``
precedent. Views stay thin: they guard, build context, and delegate here.
"""
import calendar as _calendar
import json
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.urls import reverse

from .forms import TaxProfileForm

# The wizard in order. Everything numbered — the step indicator, navigation and
# resume — derives from this one list, so a step can't be numbered inconsistently
# in two places.
STEP_KEYS = ["account", "start", "tax", "workplace", "terms", "review"]
STEP_NUM = {key: i + 1 for i, key in enumerate(STEP_KEYS)}

# Steps whose input is held in the draft and written on Finish. Deliberately NOT
# the same list as STEP_KEYS: Account, Start and Review hold no draft payload of
# their own. Keeping these separate is what stops "navigable step", "draft key"
# and "thing the commit needs" from drifting into each other.
DRAFT_KEYS = ["tax", "workplace", "terms"]

# Steps the user can be sent to by `onboarding_goto` (Account is behind the setup
# key and Review is reached by finishing, not by jumping).
NAV_KEYS = ["start", "tax", "workplace", "terms", "review"]

URLS = {key: f"core:onboarding-{key}" for key in STEP_KEYS}

MONTH_CHOICES = [(str(i), _calendar.month_abbr[i]) for i in range(1, 13)]

STEP_LABELS = {
    "tax": "Tax details",
    "workplace": "Workplace",
    "terms": "Pay terms",
}


def is_setup_complete():
    """Does the database hold what setup needs — a tax profile and pay terms?

    A pure data check. It is *not* the same question as "has the owner finished
    the wizard" (see ``setup_finished``), because an import satisfies this the
    moment it lands, well before the user reaches Finish."""
    from core.models import TaxProfile
    from workplaces.models import ContractTermSet
    return TaxProfile.objects.exists() and ContractTermSet.objects.exists()


def setup_finished(request):
    """Has the owner actually come out the other side of first-time setup?

    This is what the app chrome and the funnel must key on. The data check alone
    is wrong during the import window: bringing in a complete file satisfies it
    while the user is still standing on Review, which used to hand them the full
    navigation (on pages exempt from the funnel, e.g. the help manual) before
    they had pressed Finish.

    A surviving ``OnboardingDraft`` is the durable marker of "still in the
    wizard" — every path into it stores a step, and ``mark_complete`` deletes the
    row on Finish. Durable rather than session-only, so it survives the logout
    the wizard explicitly supports."""
    from .models import OnboardingDraft

    session = getattr(request, "session", None)
    if session is not None and session.get("onboarding_complete"):
        return True
    if not is_setup_complete():
        return False
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated             and OnboardingDraft.objects.filter(user=user).exists():
        return False
    return True


# ─── Draft storage ───────────────────────────────────────────────────────────

def draft_data(request):
    """The current user's saved onboarding step payloads (empty dict if none)."""
    from .models import OnboardingDraft
    draft = OnboardingDraft.objects.filter(user=request.user).first()
    return draft.data if draft else {}


def store_step(request, key, post):
    from .models import OnboardingDraft
    payload = {k: v for k, v in post.items() if k != "csrfmiddlewaretoken"}
    draft, _ = OnboardingDraft.objects.get_or_create(user=request.user)
    draft.data[key] = payload
    draft.save(update_fields=["data", "updated_at"])


def clear_draft(request):
    from .models import OnboardingDraft
    OnboardingDraft.objects.filter(user=request.user).delete()
    request.session.pop("onboarding", None)  # clear any legacy session copy


# ─── Forms ───────────────────────────────────────────────────────────────────

def _build_step_form(key, payload):
    """The bound form for a stored step payload — used to check completeness and
    to commit. Terms is built without a contract (guards no-op until Finish)."""
    from workplaces.forms import WorkplaceForm, ContractTermSetForm
    if key == "tax":
        return TaxProfileForm(data=payload)
    if key == "workplace":
        return WorkplaceForm(data=payload)
    return ContractTermSetForm(data=payload, contract=None)


def _build_contract_form(payload=None):
    """The contract's optional label rides along on the Workplace step, prefixed
    so it can't collide with the workplace's own `name`."""
    from workplaces.forms import WorkplaceContractForm
    if payload is None:
        return WorkplaceContractForm(prefix="contract")
    return WorkplaceContractForm(data=payload, prefix="contract")


def _build_calendar_config_form(payload=None):
    """The per-contract invite config also rides along on the Workplace step, so a
    fresh install can opt in during setup. Field names are unprefixed — they don't
    collide with the workplace's or contract's own fields."""
    from calendar_sync.forms import ContractCalendarConfigForm
    from calendar_sync.models import ContractCalendarConfig
    instance = ContractCalendarConfig()
    if payload is None:
        return ContractCalendarConfigForm(instance=instance)
    return ContractCalendarConfigForm(data=payload, instance=instance)


def calendar_readiness():
    """Flags for the invite block's "won't send yet" notice — mirrors
    ``workplaces.views._calendar_readiness``."""
    from core.models import EmailSettings
    from calendar_sync.models import CalendarInviteSettings
    invite_settings = CalendarInviteSettings.load()
    return {
        "email_configured": EmailSettings.load().is_configured,
        "invites_master_on": invite_settings.enabled,
        "personal_invites_on": invite_settings.send_to_personal,
    }


def invites_opted_in(request):
    """Did the stored Workplace step switch calendar invites on? Reads the raw
    ``send_invites`` value the Yes/No toggle submitted."""
    wp = draft_data(request).get("workplace") or {}
    return str(wp.get("send_invites", "")).strip().lower() in ("true", "on", "1")


def wants_email_step(request):
    """Whether the hidden email step should be slotted in after the Workplace step:
    invites were opted into **and** no working mail server is configured yet (once
    it is, there's nothing to set up, so skip straight to Pay Terms)."""
    from core.models import EmailSettings
    return invites_opted_in(request) and not EmailSettings.load().is_configured


def apply_calendar_config(contract, payload):
    """Best-effort: create *contract*'s invite config from a stored Workplace-step
    payload. Writes a row only when invites were switched on **and** the form
    validates; when off (or on but incomplete) nothing is written, matching the
    "off by default" state. Never blocks Finish — invites are optional and remain
    editable on the contract page afterwards."""
    if not payload:
        return
    form = _build_calendar_config_form(payload)
    if form.is_valid() and form.cleaned_data.get("send_invites"):
        config = form.save(commit=False)
        config.contract = contract
        config.save()


# ─── Navigation and the step indicator ───────────────────────────────────────

STEP_TITLES = {
    "account": "Account",
    "start": "Start",
    "tax": "Tax Profile",
    "workplace": "Workplace",
    "terms": "Pay Terms",
    "review": "Review",
}


def _db_satisfied(cov, key):
    """Does the *database* already answer this step, so "Next" should walk past it?

    Only the imported case. A step the user filled in themselves is worth
    re-showing on the way past — it re-binds their own input. But an import has
    already created the workplace and its pay terms, and stopping there offers to
    create a *second* workplace beside the one in the file, which is what made
    Next unusable after restoring an export."""
    if key == "workplace":
        return cov.workplace.in_db
    if key == "terms":
        # Term sets exist but are the import's zero-pay stub: that step still has
        # real work, and it's the only place to do it.
        return cov.terms.in_db and not cov.placeholders
    return False


def resolve_goto(request, current):
    """Destination after saving `current`: the ``onboarding_goto`` field is
    ``next`` (the following step) or a step key (jump there). Guards against
    arbitrary values — note "finish" is deliberately not a target here; only the
    Review step commits.

    An explicit jump is honoured as-is; only "next" skips covered steps, since a
    jump names a step the user asked to see."""
    goto = request.POST.get("onboarding_goto", "next")
    if goto in NAV_KEYS:
        return reverse(URLS[goto])

    idx = min(NAV_KEYS.index(current) + 1, len(NAV_KEYS) - 1)
    cov = coverage(request)
    while idx < len(NAV_KEYS) - 1 and _db_satisfied(cov, NAV_KEYS[idx]):
        idx += 1
    return reverse(URLS[NAV_KEYS[idx]])


def progress(cov, data):
    """Per indicator-step status: 'covered' (already in the database, e.g. from an
    import), 'valid' (draft complete), 'started' (has data but not yet valid), or
    'empty'. Step 1 (Account) is always valid here."""
    def piece(p):
        if p.in_db:
            return "covered"
        return p.draft

    return {
        1: "valid",
        2: "valid" if "start" in data else "empty",
        3: piece(cov.tax),
        4: piece(cov.workplace),
        # Terms exist but are still the import's zero-pay stub: "started",
        # not "covered" — a green check would say this step is finished.
        5: "started" if cov.placeholders else (
            "covered" if cov.terms.in_db else cov.terms.draft),
        6: "valid" if cov.can_finish else ("started" if cov.method else "empty"),
    }


def steps(current, cov, data):
    """Step-indicator model for the given wizard page. A step is 'active' (the
    current page), 'done' (green check — filled and valid, or already satisfied by
    an import), 'started' (yellow number — filled but ahead of the current page
    because the user navigated back, or filled yet incomplete), or 'upcoming'
    (grey — not started). 'done' and 'started' are both clickable so the user can
    jump back and forth.

    A step the database already satisfies is 'done' regardless of position: after
    a full import the later steps read as finished rather than as work pending."""
    active_num = STEP_NUM[current]
    prog = progress(cov, data)
    out = []
    for key in STEP_KEYS:
        num = STEP_NUM[key]
        url = None if key == "account" else reverse(URLS[key])
        state = prog[num]
        if num == active_num:
            step_state, step_url = "active", None
        elif state == "covered":
            step_state, step_url = "done", url
        elif state == "empty":
            step_state, step_url = "upcoming", None
        elif state == "valid" and num < active_num:
            step_state, step_url = "done", url
        else:
            # Filled but ahead of the current page (the user navigated back), or
            # filled yet incomplete → yellow.
            step_state, step_url = "started", url
        out.append({"num": num, "label": STEP_TITLES[key],
                    "state": step_state, "url": step_url})
    return out


def steps_for(request, current):
    """`steps` for a request — the account step runs before login, so it has no
    draft and nothing in the database to read."""
    if not request.user.is_authenticated:
        empty = Piece(False, "empty")
        cov = Coverage(tax=empty, workplace=empty, terms=empty, shifts=0, planned=0,
                       method="", imported_anything=False)
        return steps(current, cov, {})
    return steps(current, coverage(request), draft_data(request))


# ─── Transient display objects ───────────────────────────────────────────────

def transient_workplace(request):
    """Unsaved Workplace built from the stored workplace step — for display only
    (name) on the later onboarding pages, since nothing is saved yet."""
    from workplaces.models import Workplace
    data = draft_data(request).get("workplace", {})
    return Workplace(name=data.get("name", ""), slug=data.get("slug", "") or "")


def transient_contract(request):
    from workplaces.models import WorkplaceContract
    data = draft_data(request).get("workplace", {})
    return WorkplaceContract(name=data.get("contract-name", ""))


def tax_profile_json(request):
    """Tax card JSON for the Terms page's live gross-pay estimate, built from the
    stored (not-yet-saved) tax step. Mirrors workplaces.views._tax_profile_json."""
    tax = draft_data(request).get("tax")
    if not tax:
        return ""
    form = TaxProfileForm(data=tax)
    if not form.is_valid():
        return ""
    cd = form.cleaned_data
    percent = cd["tax_percent"] + (cd.get("church_tax_percent") or Decimal("0"))
    return json.dumps({"deduction": str(cd["monthly_deduction"]), "percent": str(percent)})


# ─── Coverage ────────────────────────────────────────────────────────────────
# Setup can be satisfied two ways — an import wrote the rows already, or the
# wizard holds a valid draft that Finish will write. Coverage is the single
# answer to "what does this install still need?", read by the Review screen, the
# step indicator and the commit.


@dataclass(frozen=True)
class Piece:
    """One thing setup needs, and where it comes from."""
    in_db: bool           # already written (imported, or an earlier commit)
    draft: str            # "valid" | "started" | "empty"

    @property
    def covered(self):
        return self.in_db or self.draft == "valid"

    @property
    def from_draft(self):
        """Covered by the draft and not yet written — i.e. the commit must save it."""
        return not self.in_db and self.draft == "valid"


@dataclass(frozen=True)
class Coverage:
    tax: Piece
    workplace: Piece
    terms: Piece
    shifts: int           # informational only — never blocks Finish
    planned: int          # informational only — never blocks Finish
    method: str           # "import" | "scratch" | "" (the Start step's choice)
    imported_anything: bool
    # Every workplace that exists so far: {"name", "ready"} — Review lists these
    # so the user can see what an import actually brought in.
    workplaces: tuple = ()
    # Stub term sets that carry no actual pay, as ``(termset_id, workplace_name)``.
    # An import creates one when the file's shifts name a workplace it never
    # defines: the shifts need a contract active on their dates to be accepted at
    # all, so a placeholder is written to let them in. It prices every one of
    # those shifts at zero, so setup is not allowed to finish while one survives.
    placeholders: tuple = ()

    @property
    def has_tax(self):
        return self.tax.covered

    @property
    def has_terms(self):
        # Pay terms need something to hang on: either they already exist, or the
        # draft supplies both a workplace and the terms themselves.
        return self.terms.in_db or (self.workplace.covered and self.terms.draft == "valid")

    @property
    def can_finish(self):
        return self.has_tax and self.has_terms and not self.placeholders

    @property
    def placeholder_names(self):
        return [name for _, name in self.placeholders]

    def missing(self):
        """Step keys still blocking Finish, in wizard order."""
        gaps = []
        if not self.has_tax:
            gaps.append("tax")
        if not self.has_terms:
            gaps.append("workplace" if not self.workplace.covered else "terms")
        elif self.placeholders:
            # Terms exist but are the import's zero-pay stub — same step fixes it.
            gaps.append("terms")
        return gaps


def _workplace_review_info(wp, stub_names):
    """One Review "Workplaces" row: name + pay-terms-ready flag, plus the primary
    contract's pk and whether it still wants a label / calendar invites, so Review
    can offer an "Edit contract" button and a soft nudge."""
    contract = wp.contracts.all().first()
    return {
        "name": wp.name,
        "ready": wp.name not in stub_names and wp.contracts.filter(
            term_sets__isnull=False).exists(),
        "contract_pk": contract.pk if contract else None,
        "contract_named": bool(contract and contract.name),
        # getattr default works because a missing reverse one-to-one raises an
        # AttributeError subclass (same idiom as calendar_sync.invites._config).
        "invites_set": bool(contract and getattr(contract, "calendar_config", None)
                            and contract.calendar_config.send_invites),
    }


def coverage(request):
    from core.models import TaxProfile
    from shifts.models import PlannedShift, Shift
    from workplaces.models import ContractTermSet, Workplace

    data = draft_data(request) if request.user.is_authenticated else {}

    def draft_state(key):
        if key not in data:
            return "empty"
        return "valid" if _build_step_form(key, data[key]).is_valid() else "started"

    # A workplace only counts if it can actually hold pay terms. An export may
    # carry a workplace with "contracts": [], which creates a Workplace row that
    # no term set can attach to — treating that as covered would show step 4 green
    # while Finish has nowhere to write.
    workplace_in_db = Workplace.objects.filter(contracts__isnull=False).exists()

    placeholders = tuple(
        (ts.pk, ts.contract.workplace.name) for ts in placeholder_termsets()
    )
    stub_names = {name for _, name in placeholders}

    # What Review lists under "Workplaces": every one that exists so far, each
    # flagged with whether its pay is set up, plus its primary contract's pk and a
    # nudge flag so Review can offer "Edit contract" (label + calendar invites).
    workplaces = tuple(
        _workplace_review_info(wp, stub_names)
        for wp in Workplace.objects.order_by("name").prefetch_related(
            "contracts__term_sets", "contracts__calendar_config")
    )

    return Coverage(
        tax=Piece(TaxProfile.objects.exists(), draft_state("tax")),
        workplace=Piece(workplace_in_db, draft_state("workplace")),
        terms=Piece(ContractTermSet.objects.exists(), draft_state("terms")),
        shifts=Shift.objects.count(),
        planned=PlannedShift.objects.count(),
        method=data.get("start", {}).get("method", ""),
        imported_anything=Workplace.objects.exists() or TaxProfile.objects.exists(),
        workplaces=workplaces,
        placeholders=placeholders,
    )


def placeholder_termsets():
    """Term sets that specify no pay at all, oldest first.

    These are the stubs ``data_io.perform_import`` writes for a workplace the
    file mentions on a shift but never defines — a shift is rejected unless a
    contract is active on its date, so without one the shifts would be dropped.
    Detected by what they *are* (zero pay) rather than by tracking where they
    came from, so a zero-pay term set arriving any other way is caught too."""
    from django.db.models import Q
    from workplaces.models import ContractTermSet

    no_hourly = Q(hourly_rate__isnull=True) | Q(hourly_rate=0)
    no_salary = Q(monthly_salary__isnull=True) | Q(monthly_salary=0)
    return (
        ContractTermSet.objects
        .filter(no_hourly & no_salary)
        .select_related("contract__workplace")
        .order_by("pk")
    )


def _terms_target_contract(cov):
    """The existing contract a terms draft should attach to, or None (→ create the
    workplace and contract from the draft instead).

    Only when the answer is unambiguous: exactly one imported contract without
    term sets. With several, we refuse to guess — silently attaching pay terms to
    the wrong job is worse than sending the user to the workplaces UI."""
    from workplaces.models import WorkplaceContract

    if not cov.workplace.in_db:
        return None
    termless = WorkplaceContract.objects.filter(term_sets__isnull=True)
    return termless.first() if termless.count() == 1 else None


# ─── Commit ──────────────────────────────────────────────────────────────────

def mark_complete(request):
    """Record that setup is finished: cache the flag and drop the draft.

    Shared with the middleware, which flips the same flag the moment the database
    satisfies the completion signal — that can happen mid-wizard right after an
    import, so the draft must be cleaned up by whichever path notices first."""
    request.session["onboarding_complete"] = True
    if request.user.is_authenticated:
        clear_draft(request)


def commit_setup(request):
    """Write whatever setup still needs, atomically.

    Commits **only what the database lacks** — an import may already have supplied
    the workplace and pay terms, leaving just a hand-filled tax step to save (or
    the reverse). Returns True, or ``(step_key, message)`` naming the first gap.

    Placeholder term sets are not this function's problem: they are real rows
    already in the database, so the Pay Terms step edits them in place (see
    ``OnboardingTermsView``) and they simply have to be gone before Finish is
    offered at all.

    The transaction covers everything the *draft* contributes, so a failure part
    way leaves nothing behind. Rows an import wrote in an earlier request sit
    outside it and are never rolled back — the one place the wizard's "nothing is
    saved until Finish" rule legitimately doesn't hold."""
    from django.core.exceptions import ValidationError
    from workplaces.forms import ContractTermSetForm

    cov = coverage(request)
    if not cov.can_finish:
        key = cov.missing()[0]
        return (key, f"Please finish the {STEP_LABELS[key]} step before you can submit.")

    data = draft_data(request)
    try:
        with transaction.atomic():
            if cov.tax.from_draft:
                _build_step_form("tax", data["tax"]).save()

            if not cov.terms.in_db:
                contract = _terms_target_contract(cov)
                if contract is None:
                    wp_form = _build_step_form("workplace", data["workplace"])
                    wp_form.is_valid()          # already checked via coverage
                    workplace = wp_form.save()
                    contract_form = _build_contract_form(data["workplace"])
                    contract_form.is_valid()    # optional label — never fails
                    contract = contract_form.save(commit=False)
                    contract.workplace = workplace
                    contract.save()
                    # Opt-in calendar invites captured on the Workplace step ride in
                    # the same draft payload — best-effort, never blocks Finish.
                    apply_calendar_config(contract, data["workplace"])
                # Re-bind to the real contract so dates/overlap validate against it.
                terms_form = ContractTermSetForm(data=data["terms"], contract=contract)
                if not terms_form.is_valid():
                    raise ValidationError("terms")
                terms_form.save()
    except ValidationError:
        return ("terms", f"Please finish the {STEP_LABELS['terms']} step before you can submit.")
    return True
