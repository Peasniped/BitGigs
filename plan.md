# Codebase audit — status & remaining work

Full audit (security / correctness / dead+duplicated code) ran 2026-07-08.
Baseline: all tests green, `manage.py check` clean. This file tracks the
remediation; delete it when everything below is done.

## Done (committed)

- **WP1 — `hoofdkort` typo bug**: fixed in `payroll/services.py` and
  `data_io/services.py` (was silently taxing fallback/imported term sets as
  bikort). Regression tests added.
- **WP2 — Security hardening**:
  - Site-wide login (`LoginRequiredMiddleware`), login page, navbar logout.
  - Onboarding step 0: first-run account creation at `/setup/user/` (fresh
    install funnels there; page disappears once a user exists).
  - Fail-closed settings: production refuses to boot without
    `DJANGO_SECRET_KEY` / `POSTGRES_PASSWORD`; `wsgi.py`/`asgi.py` default to
    production settings; `.env` loader + `.env.example`.
  - `sanitize_svg` rewritten as XML allowlist parser (+11 bypass tests).
  - data_io icon import guarded (extension/size/sanitize, shared constants in
    `workplaces/services.py`).
  - SRI hashes on all pinned CDN tags; Google Fonts noted as not SRI-able.
  - `requirements.txt` Django pin corrected to `>=6.0,<6.1`.
- **WP3 — Robustness**:
  - Timezone sweep: `timezone.localdate()`/`localtime()` everywhere.
  - Shared `parse_int_param`/`parse_iso_date_param`/`parse_iso_time_param` in
    `core/utils.py`; JSON APIs return 400 on bad input; GET filters fall back
    to defaults; analytics' private `_parse_int` folded in.
  - `perform_import` atomic + `full_clean` on imported term sets (aborts) and
    shifts (skips row, counted); missing map target → clean error; empty
    `"contracts": []` no longer falls into the legacy import branch.
  - Workplace list N+1 fixed (`prefetch_related("contracts__term_sets")`;
    `active_termset_on` now walks prefetched rows instead of re-querying).

## Remaining

### WP4 — Dead code removal (all grep-verified unreferenced; re-verify before deleting)
- `apps/payroll/forms.py` — delete whole file (nothing imports it).
- `apps/shifts/forms.py` — delete `ShiftFilterForm`.
- `apps/workplaces/services.py` — delete `WorkplaceService.get_active_workplaces`,
  `.get_hourly_workplaces`, `.get_salaried_workplaces`.
- `apps/workplaces/models.py` — delete `has_active_contract_in_month`,
  `WorkplaceContract.get_rate_as_of`, `beskæftigelsesprocent`,
  `ferietillaeg_payout_month_names`, `vacation_days_per_month` (move the
  `2.08` constant to `payroll/services.py` as `VACATION_DAYS_PER_MONTH`,
  replacing the hardcoded literal there).
- `apps/shifts/models.py` — delete `Shift.is_commuting_day`.
- `apps/core/dashboard_service.py` — delete `period_boundaries` field + the
  block populating it; drop redundant local `import calendar` (2×).
- `apps/analytics/services.py` — drop unused `Q` import.
- `apps/core/views.py` — delete `LogoView` + its `core/urls.py` route (keep
  the `BitGigs_Logo.png` asset).
- Delete `apps/shifts/templates/shifts/shift_list.html` (no view renders it).
- `apps/data_io/services.py` — fix `"Missing 'version' key ."` message typo and
  mojibake section comments (use a Python script; Edit can't match the bytes).
- KEEP the orphaned calendar pages (month / payroll-period views + templates)
  — decision deferred, ToDo note pending (WP6).

### WP5 — De-duplication
- Shared period-bounds helper `PayrollPeriodService.resolve_period_bounds(wp, year, month)`
  replacing ~6 repeated blocks: `core/dashboard_service.py` (2×),
  `calendar_view/services.py:~229`, `calendar_view/views.py:~127`,
  `payroll/services.py:~96`, `workplaces/views.py:~102`.
- Merge `_spans_overlap` (`workplaces/models.py`) and `_intervals_overlap`
  (`data_io/services.py`) into one `core/utils.py` helper.
- `shifts/views.py` MonthlyOverviewView: use `core.utils.prev_next_month`
  instead of hand-rolled month arithmetic.
- Merge `_shift_to_dict` / `_approved_shift_to_dict` in `calendar_view/views.py`.
- (Optional) unify `active_intervals` vs `_termset_active_range` only if
  semantics are identical on inspection.

### WP6 — Docs
- CLAUDE.md: site-wide auth (test clients must log in; page-render snippet
  needs a login), new sanitizer behavior, wsgi/asgi default to production,
  `.env` support, onboarding step 0.
- ToDo: mark audit item done; add "decide fate of orphaned calendar pages";
  add the back-to-back-contracts-in-one-month gap (earlier contract's salaried
  pay dropped by `active_termset_in_month`) under the multi-rate item.

### Final verification
- Full suite (`manage.py test apps`), logged-in render check of the main
  pages, then user test steps (login flow, SVG icon upload incl. recolor,
  export→import round trip, salaried month numbers unchanged, `?year=abc`
  returns a sane page).

## Known/deferred findings (NOT fixed on purpose — tracked in ToDo)
- Double personfradrag when a month spans multiple term sets.
- `build_payslip` re-taxes an already-net running total (payslip editor path).
- Back-to-back contracts within one month: earlier contract's pay omitted.
