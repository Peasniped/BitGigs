# BitGigs — Agent Quick Reference

Django 5.1 app for tracking shifts and estimating Danish net pay across multiple workplaces. Bootstrap 5 + Bootstrap Icons UI, Cropper.js for icon cropping, Chart.js (CDN) for analytics charts. SQLite in dev, Postgres in prod.

## Run / verify

- Activate venv: `.venv\Scripts\Activate.ps1` (Windows PowerShell). Always use `--settings=bitgigs.settings.local` for dev.
- Smoke check after edits: `python manage.py check --settings=bitgigs.settings.local`
- Quick page render check: `python manage.py shell --settings=bitgigs.settings.local -c "from django.test import Client; print(Client().get('/PATH/').status_code)"`
- Tests: `python manage.py test --settings=bitgigs.settings.local`

## Apps (each = `models.py`, `views.py`, `services.py`, `urls.py`, `templates/<app>/`, `tests/`)

| App | Purpose |
|---|---|
| `bitgigs/` | Project config; settings split into `base.py` / `local.py` / `production.py`; root `urls.py` |
| `core/` | `UserSettings` (singleton), `TaxProfile` (date-versioned), `ATPConfiguration`/`ATPBracket`, dashboard, settings page, `templatetags/dk_filters.py` (`dk` number filter) |
| `workplaces/` | `Workplace`, `WorkplacePayRate` (date-versioned hourly/salary). Detail page hosts the customize-appearance modal (icon upload + Cropper.js + SVG recolor modal) |
| `shifts/` | `Shift` (approved + planned). Daily/monthly overviews. Forms in `forms.py`. |
| `payroll/` | Payroll periods, payslip lines, vacation/feriekonto/fritvalg/pension, commuting summary |
| `calendar_view/` | Cross-workplace month grid; planning + approve flow |
| `analytics/` | Income projection (`analytics.html`) and rate history (`rate_history.html`). Shared filter helpers `_resolve_workplace_filter` and `_resolve_period` in `views.py` |
| `data_io/` | Import/export |
| `templates/` | Project-level `base.html`, `dashboard.html` |
| `static/` | `css/style.css`, `js/app.js` |

## Conventions

- Money: `Decimal` everywhere; never float. Use `core.templatetags.dk_filters.dk` for display (Danish formatting).
- Tax profiles and pay rates are **date-versioned**: pick the row whose `effective_from <= date`. Never mutate historical rows.
- Services pattern: heavy logic lives in `<app>/services.py`; views stay thin.
- Filter forms use a hidden `wp_set=1` marker + multiple `workplace=<slug>` (or `workplace=all`) values; `_resolve_workplace_filter` decodes them.
- Period filter uses `period_mode=year|range` + `year=` or `start=`/`end=`; decoded by `_resolve_period`.
- Analytics filter bar (period card + workplace cards in `picker-row`) is shared verbatim between `analytics.html` and `rate_history.html`.
- Bootstrap modals stacked over the customize-appearance modal must hide the parent first (see SVG recolor flow in `workplaces/templates/workplaces/workplace_detail.html`).
- Some templates contain mojibake bytes (`â•Ð…`) in section comments. `replace_string_in_file` may fail to match those lines — use a small Python script with explicit `\u00e2\u2022\u0090` escapes when needed.
- Multi-line `{# … #}` Django comments don't exist; use `{% comment %}…{% endcomment %}`.

## Frontend bits

- Charts: Chart.js v4 from CDN; category x-axis with ISO date labels; stepped lines for rate history; segment dash for projected tail.
- Workplace icons: 256×256 PNG produced by Cropper.js; SVG uploads first go through `svgRecolorModal` (per-color or single-tint remap, hex + color-picker inputs, live preview) before being passed to the cropper.

## Don't

- Don't add new docstrings/comments/type hints to code you didn't change.
- Don't run destructive git/db commands without confirmation.
- Don't bypass `--settings=bitgigs.settings.local` in dev.
- Don't introduce new dependencies without need.
