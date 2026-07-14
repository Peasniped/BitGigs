# BitGigs — Agent Quick Reference

Django 6.0 app for tracking shifts and estimating Danish net pay across multiple workplaces. Bootstrap 5 + Bootstrap Icons UI, Cropper.js for icon cropping, Chart.js (CDN) for analytics charts. SQLite in dev, Postgres in prod.

## Run / verify

- Activate venv: `.venv\Scripts\Activate.ps1` (Windows PowerShell). Always use `--settings=bitgigs.settings.local` for dev.
- Smoke check after edits: `python manage.py check --settings=bitgigs.settings.local`
- Quick page render check (**must log in** — the whole site requires auth): `python manage.py shell --settings=bitgigs.settings.local -c "from django.contrib.auth.models import User; from django.test import Client; c = Client(); c.force_login(User.objects.first()); print(c.get('/PATH/').status_code)"`
- Tests: `python manage.py test apps --settings=bitgigs.settings.local` (the `apps` label is required — see layout note below). View tests need `self.client.force_login(...)` (see `LoggedInTestCase` in `apps/workplaces/tests/test_contract_overlap.py`).
- Optional `.env` at the repo root is loaded by `bitgigs/settings/base.py` (real env vars win; empty values ignored); `.env.example` documents the variables. `wsgi.py`/`asgi.py` default to **production** settings, and production refuses to boot without `DJANGO_SECRET_KEY`/`POSTGRES_PASSWORD`.

## Project layout

- Feature apps live under `apps/`. `apps/` is a plain directory placed on `sys.path` (via a one-line insert in `bitgigs/settings/base.py`), **not** a Python package — so import names and app labels stay bare (`core`, `workplaces`, …) and `INSTALLED_APPS` is unchanged. Never add `apps/__init__.py`.
- Because `apps/` isn't a package, `manage.py test` with no args discovers 0 tests — always pass the `apps` label (or specific app labels).
- `bitgigs/` (project config) stays at the repo root, so `BASE_DIR` and `DJANGO_SETTINGS_MODULE`/`wsgi`/`asgi` paths are unaffected.
- Project-level assets live under `assets/`: `assets/static/{css,js,graphics}` (the staticfiles root) and `assets/templates/` (project-level templates). `graphics/` holds bundled images like the logos (referenced as `{% static 'graphics/…' %}`); user-uploaded files stay in `media/`.

## Apps (each = `models.py`, `views.py`, `services.py`, `urls.py`, `templates/<app>/`, `tests/`; all under `apps/`)

| App | Purpose |
|---|---|
| `bitgigs/` | Project config (at repo root, not under `apps/`); settings split into `base.py` / `local.py` / `production.py`; root `urls.py` |
| `core/` | `UserSettings` (singleton), `TaxProfile` (date-versioned), `ATPConfiguration`/`ATPBracket`, dashboard, settings page, `templatetags/dk_filters.py` (`dk` number filter) |
| `workplaces/` | `Workplace`, `WorkplaceContract` (a named container with **no date fields**), `ContractTermSet` (date-versioned employment terms: `effective_from` + optional `effective_until`). A contract's active span is **derived** from its term sets — read-only `start_date`/`end_date` properties = earliest `effective_from` → last term set's `effective_until`. Detail page hosts the customize-appearance modal (icon upload + Cropper.js + SVG recolor modal) |
| `shifts/` | `Shift` (approved + planned). Daily/monthly overviews. Forms in `forms.py`. |
| `payroll/` | Payroll periods, payslip lines, vacation/feriekonto/fritvalg/pension, commuting summary |
| `calendar_view/` | Cross-workplace month grid; planning + approve flow |
| `analytics/` | Income projection (`analytics.html`) and rate history (`rate_history.html`). Shared filter helpers `_resolve_workplace_filter` and `_resolve_period` in `views.py` |
| `data_io/` | Import/export |
| `assets/templates/` | Project-level `base.html`, `dashboard.html`, `_period_filter_notice.html` |
| `assets/static/` | `css/style.css`, `css/planning.css`, `js/app.js` (+ per-page JS), `graphics/` (logos) |

## Conventions

- **Auth**: the whole site sits behind Django's `LoginRequiredMiddleware` (added in `base.py`); mark genuinely public views with `@login_not_required`. First-time setup is an **onboarding wizard** (`core.views`, URLs under `/onboarding/`, names `core:onboarding-*`). Step 1 creates the single admin account **immediately** (needed for the logged-in steps) and is only reachable while no user exists. It is **three pages**, all subclassing `_AccountStepView`: `/onboarding/account/` (the **setup key** — see below), then `/onboarding/account/method/` (Authentik vs email+password, shown only when `SSO_ENABLED`), then `/onboarding/account/email/` (the `OnboardingUserCreationForm`) or `/onboarding/account/sso/` (hand-off to the IdP). **Only `_AccountStepView` may define `dispatch()`** — `login_not_required` is attached to the dispatch *method*, so an overriding subclass drops the marker and `LoginRequiredMiddleware` starts bouncing anonymous visitors out of the logged-out pages; vary behaviour via its `requires_key` / `requires_sso` class attributes instead.
- **Setup key** (`core/setup_key.py`, `manage.py setup_key [--regenerate]`): a fresh install has no owner, so *whoever reaches the account step first* would claim it. The key (256-bit, `secrets.token_urlsafe`) is printed to the server log and written to `settings.SETUP_KEY_PATH` (`instance/setup_key.txt`) on first visit; the account step verifies it once, records `setup_key.SESSION_FLAG` in the session, and every later page — **including the SSO bootstrap in `core.adapters`** — refuses to act without that flag. Deleted once an owner exists. Tests must point `SETUP_KEY_PATH` at a temp file (see `SetupKeyMixin` in `apps/core/tests/test_auth.py`) or they clobber the real key. Steps Tax → Workplace → Terms are **deferred**: each step's raw POST is held in a durable per-user **`OnboardingDraft`** (`core.models`, a `OneToOne(User)` + `data` JSONField — not the session, so logging out mid-onboarding via the top-left "Log out" doesn't lose it; the `_onboarding_*`/`_store_onboarding`/`_clear_onboarding` helpers in `core.views` manage it), each payload having already passed `is_valid()` so re-binding it on revisit re-shows the input with no errors → back-navigation keeps its place. Everything is written to the DB together, atomically, only on the Terms step's **Finish** (`_commit_onboarding`), which then deletes the draft. The wizard reuses the real `WorkplaceForm`/`WorkplaceContractForm`/`ContractTermSetForm` and their templates via an `onboarding=True` context flag (transient unsaved Workplace/Contract objects supply display names). **The contract has no step of its own**: its only editable field is an optional label, so the Workplace step renders `WorkplaceContractForm(prefix="contract")` alongside `WorkplaceForm` (built by `_build_contract_form`) — one raw-POST payload under the `workplace` draft key holds both, and a small script in `workplace_form.html` reveals the label field once the workplace is named. The step indicator (`_onboarding_steps`) is 4 circles (Account / Tax Profile / Workplace / Pay Terms) and marks a step `done`/`active`/`started` (filled but ahead because the user went back → yellow, clickable)/`upcoming`. `OnboardingRequiredMiddleware` funnels anonymous fresh installs to the account step and logged-in-but-unfinished users to `/onboarding/`; completion signal = a `TaxProfile` **and** a `ContractTermSet` exist (cached in `session["onboarding_complete"]`, also exposed to templates by `core.context_processors.onboarding_status` so `base.html` hides the nav until done and the login page shows a "finish setting up" hint). The single account is the **owner/admin**; its username **is** the email (`OnboardingUserCreationForm`, validated + copied to `User.email`). Password policy adds `core.validators.EmailSimilarityValidator` (reworded similarity), `CharacterClassesPasswordValidator` (one lowercase + uppercase + number + symbol — this subsumes Django's `NumericPasswordValidator`, which is therefore not enabled), and `NoSequencesPasswordValidator` (no `aaa`/`abc` runs); the account page's live checklist (`onboarding_password.js`) mirrors these. View tests that hit normal pages must mark onboarding complete (see `LoggedInTestCase`).
- **Optional SSO (Authentik / any OIDC provider)**: `django-allauth` is **always installed** (one migration state for every deploy), but the OIDC provider is only registered when `AUTHENTIK_SERVER_URL`/`_CLIENT_ID`/`_CLIENT_SECRET` are all set — `settings.SSO_ENABLED`. **BitGigs must stay feature-complete standalone**: with those unset it is exactly as before (native password login, no SSO button, no IdP required). Django's auth URLs are included **before** `allauth.urls` in `bitgigs/urls.py` so the native `/accounts/login/` and `/accounts/logout/` keep winning; allauth only supplies `/accounts/oidc/…`. Because the app is **single-tenant** (`Workplace`/`TaxProfile`/`UserSettings` have no user FK, so every `User` sees the same data), SSO **must never create a User** — `core.adapters.OwnerOnlySocialAccountAdapter` links an incoming identity to the single existing owner only when the email matches, and refuses everything else; `NoSignupAccountAdapter` closes allauth's own signup route. The one exception is the **fresh-install bootstrap**: with no owner yet, an identity coming through the account step's Authentik button becomes the owner (no password set) — but only behind the setup-key session flag. Authentik's own branding lives in `assets/static/graphics/authentik_icon.svg` (their asset) + `.btn-authentik` (`#fd4b2d`, their colour). Two auth backends are now configured, so any manual `auth.login()` call **must name its backend** (see `OnboardingAccountEmailView`).
- **SSO flows**: an identity from the IdP never lands silently — it is parked in the session and shown on a **confirm page** (name / email / uid, read via `core.adapters.claim` from the raw claims, *not* `sociallogin.user`: allauth drops an invalid email and splits `name` on a space, which doubles authentik's surname). That applies to the fresh-install bootstrap (`OnboardingAccountConfirmView`) **and** to linking from the settings page (`SSOLinkConfirmView`, `process=connect`) — with a live IdP session the round-trip is instant, so you would otherwise bind whichever account it happened to hold. A plain login is deliberately *not* interrupted. `/sso/launch/` is meant to be the **Launch URL of the Authentik application**: opening BitGigs from the IdP dashboard signs you in, or offers to link when you're signed in locally but unlinked. "Not you?" (`/sso/idp-logout/`) is RP-initiated logout to the IdP's `end_session_endpoint` — no `post_logout_redirect_uri`, so nothing needs registering; authentik's own signed-out page takes it from there. (`prompt=login` would be tidier but authentik ignores it on repeat attempts.) The hand-off pages render with `minimal_chrome` (see `base.html`): centred logo, nothing clickable, so a stray nav click can't strand the round-trip.
- **Sign-in management** (settings page, `PasswordSignInView`): set/change the password (a modal reusing the account step's `password-box` + live checklist — `password_checklist.js` drives any form with `data-pw1-id`), turn password sign-in off (`set_unusable_password`), or unlink the IdP. One invariant runs through all of it — **at least one way in must survive**: the password can only be turned off while an identity is linked, and the identity can only be unlinked while a usable password exists. Always `update_session_auth_hash` after any password change, or it logs the owner out of their own session. `BitGigsLoginView` hides the password box entirely when password sign-in is off (a form that cannot succeed is a trap) — but never when `SSO_ENABLED` is false, which would lock a standalone owner out. There is no email backend, so account recovery is `manage.py changepassword`; the login page's "Forgot your password?" / "Can't access Authentik?" modal says so.
- Money: `Decimal` everywhere; never float.
- Number formatting is "en-DK": English UI, Danish numbers. Decimal comma is **automatic** via Django L10N (`FORMAT_MODULE_PATH = "bitgigs.formats"`, en override) — bare `{{ value }}` already renders `1234,56`. Use `|dk:N` (or `|floatformat:"Ng"`) only when you also want **thousands grouping** (`1.234,56`); `dk` now delegates to Django's `floatformat` + Unicode minus. Parse locale input with `core.utils.parse_danish_decimal` (uses `get_format` separators). **Never enable `USE_THOUSAND_SEPARATOR`** — grouping is magnitude-based and would corrupt years/IDs (`2026 → "2.026"`, breaking JS `parseInt`).
- Time pickers: native `<input type="time">` can't be forced to 24-hour (it follows the browser locale), so `app.js` `initTimePickers()` converts each one into a custom **always-24h** segmented text input (type the hour pair → auto-advance to minutes; Up/Down/Left/Right adjust/move) with a clock glyph. Templates keep `type="time"`; the JS does the conversion, so dynamically-created inputs must be initialised via `window.initTimePickers(container)`. The value stays `HH:MM`, so server parsing and JS reads are unchanged — but **write** a time input via `window.setTimeValue(el, "HH:MM")` (not `el.value = …`) so the buffer/formatting reset correctly.
- Tax profiles and term sets are **date-versioned**: pick the row whose `effective_from <= date`. Never mutate historical rows.
- **Contract activity is derived from term-set dates only** (contracts have no dates). `active_termset_on(d)` = the latest term set with `effective_from <= d`; if *that* term set's `effective_until` is earlier than `d`, the contract has ended → inactive. So a term set "runs until the next one starts," and only an `effective_until` on the tail closes the contract. Contracts for one workplace **must not overlap** — the guard lives in `ContractTermSet.clean()` (runs on term-set save, since that's when dates enter), not on the contract.
- Services pattern: heavy logic lives in `<app>/services.py`; views stay thin.
- Filter forms use a hidden `wp_set=1` marker + multiple `workplace=<slug>` (or `workplace=all`) values; `_resolve_workplace_filter` decodes them.
- Period filter uses `period_mode=year|range` + `year=` or `start=`/`end=`; decoded by `_resolve_period`.
- Analytics filter bar (period card + workplace cards in `picker-row`) is shared verbatim between `analytics.html` and `rate_history.html`.
- Bootstrap modals stacked over the customize-appearance modal must hide the parent first (see SVG recolor flow in `apps/workplaces/templates/workplaces/workplace_detail.html`).
- Some templates contain mojibake bytes (`â•Ð…`) in section comments. `replace_string_in_file` may fail to match those lines — use a small Python script with explicit `\u00e2\u2022\u0090` escapes when needed.
- Multi-line `{# … #}` Django comments don't exist; use `{% comment %}…{% endcomment %}`.

## Code style & hardening

How new code / changes should be written:

- Match the surrounding code's style; don't restyle or re-comment code you didn't change.
- Keep views thin — heavy logic goes in `<app>/services.py`.
- Money is `Decimal` (never float), shown via en-DK L10N / the `dk` filter (see Conventions).
- Date-versioned data (tax profiles, pay rates): pick the effective row with `core.utils.active_dated_row`; never mutate historical rows.
- Ship new logic with a test under `apps/<app>/tests/` (run with the `apps` label).
- No new dependencies without a real need.
- Parse user input via helpers, don't hand-roll — `core.utils.parse_danish_decimal` for locale numbers; `parse_int_param` / `parse_iso_date_param` / `parse_iso_time_param` for request params (return `None`/default instead of raising → views answer 400, not 500).
- Dates: use `timezone.localdate()` / `timezone.localtime()`, never `date.today()` / `datetime.now()` (`USE_TZ=True`; the server may not run in Danish time).
- Payroll month bounds: use `PayrollPeriodService.resolve_period_bounds(workplace, year, month)` → `(termset, start, end)`; don't re-derive the term-set/full-month fallback inline. Date-span overlap checks: `core.utils.date_spans_overlap`.
- Sanitize uploads: SVGs go through `core.utils.sanitize_svg` — an XML **allowlist** parser that returns `None` for unparseable input (reject the upload). Both the customize view and data_io import enforce the shared icon constraints in `workplaces/services.py` (`ALLOWED_ICON_EXTS`, `MAX_ICON_SIZE`).
- CDN `<script>`/`<link>` tags are version-pinned **with SRI** (`integrity` + `crossorigin`) — keep the hash in sync when bumping a version (Google Fonts CSS is per-browser and can't have SRI).
- `data_io.perform_import` is `@transaction.atomic` and `full_clean`s imported rows (invalid shifts are skipped and counted; invalid term sets abort the import).
- Redirect only to same-origin URLs — follow the `_safe_next` pattern in `apps/core/views.py`.
- Use the ORM / Django forms (no raw SQL); rely on template auto-escaping — never `|safe` untrusted data.
- Keep secrets/config in env vars (see `bitgigs/settings/production.py`); never commit secrets. Don't weaken the production hardening there (HTTPS/HSTS/secure cookies, gated by `DJANGO_ENABLE_HTTPS`).

## Frontend bits

- Charts: Chart.js v4 from CDN; category x-axis with ISO date labels; stepped lines for rate history; segment dash for projected tail.
- Workplace icons: 256×256 PNG produced by Cropper.js; SVG uploads first go through `svgRecolorModal` (per-color or single-tint remap, hex + color-picker inputs, live preview) before being passed to the cropper.
- Auto-dismissing notices: add `data-dismiss-after="<ms>"` to any Bootstrap `.alert` and `initDismissibleNotices` (`app.js`) swaps the close button for a draining **countdown ring** (`.notice-timer`, CSS in `style.css`) that dismisses on empty; hovering pauses it and reveals a click-to-close X. `base.html` opts success messages in.

## Don'ts

- Don't add new docstrings/comments/type hints to code you didn't change.
- Don't run destructive git/db commands without confirmation.
- Don't bypass `--settings=bitgigs.settings.local` in dev.
- Don't introduce new dependencies without need.

## Do's

- Whenever I send a prompt, ask youself if what I am asking makes sense if not, ask. I am not the smartest person in the world, and may make mistakes or ask for things that does not make sense (:
- Always DO ask me if you are ever uncertain about something
- DO make sure to keep CLAUDE.md up to date if making changes that contradict or add to something written in here.
- When you are done implementing a feature before git commit, DO let me know what to test in order to asses the implementation (user steps)
- Do write Git commits at a regular interval when it makes sense
- You must DO show a preview of git commits in text to the user for their confirmation before any tools are called.
- (!!! Ignore this for now, will be important once the system is actively running.) DO ask the user if they want to create a new feature branch, or change to an existing branch(search and see what there is) if it makes sense, each session before editing files.
- DO make a copy of the database when creating a new branch