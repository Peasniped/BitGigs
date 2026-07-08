# Codebase audit — status

Full audit (security / correctness / dead+duplicated code) ran 2026-07-08.
**All remediation work packages are complete.** This file can be deleted once
the final commit is verified.

## Done

- **WP1 — `hoofdkort` typo bug** (silent bikort taxation on fallback/import
  paths) + regression tests.
- **WP2 — Security**: site-wide login + first-run account-creation onboarding
  step; fail-closed production settings; `.env`/`.env.example`; allowlist SVG
  sanitizer (+11 bypass tests); guarded icon import; SRI on CDN assets;
  Django pin corrected to 6.0.
- **WP3 — Robustness**: timezone sweep; 400-not-500 request parsing via shared
  `core.utils` helpers; atomic + validated import; workplace list N+1 fixed.
- **WP4 — Dead code removed**: `payroll/forms.py`, `ShiftFilterForm`, three
  `WorkplaceService` getters, `has_active_contract_in_month`,
  `WorkplaceContract.get_rate_as_of`, `beskæftigelsesprocent`,
  `ferietillaeg_payout_month_names`, `vacation_days_per_month` (constant now
  `VACATION_DAYS_PER_MONTH` in payroll/services.py), `Shift.is_commuting_day`,
  `DashboardData.period_boundaries`, `LogoView`+route, `shift_list.html`,
  unused imports, data_io typo/mojibake. Orphaned calendar pages KEPT
  (decision item added to ToDo).
- **WP5 — De-duplication**: `PayrollPeriodService.resolve_period_bounds`
  replaces the repeated period-bounds block (dashboard ×2, calendar service,
  planning view, get_or_create_period); `core.utils.date_spans_overlap`
  replaces the two overlap helpers; `prev_next_month` reused in shifts monthly
  view; the two identical shift serializers merged.
- **WP6 — Docs**: CLAUDE.md (auth, .env, sanitizer, parse helpers,
  resolve_period_bounds, SRI, import validation, timezone rule); ToDo
  (audit follow-ups added under SENERE).

## Known/deferred findings (tracked in ToDo, deliberately not fixed)

- Double personfradrag when a month spans multiple term sets.
- `build_payslip` re-taxes an already-net running total (payslip editor path).
- Back-to-back contracts within one month: earlier contract's pay omitted.
- Orphaned calendar month / payroll-period pages: keep or delete.
