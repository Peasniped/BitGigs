# BitGigs: Contracts & Employment Terms History
## Status (as of 2026-06-02 session)

### Done
- `workplaces/models.py` — `Workplace` stripped to appearance, `WorkplaceContract` + `ContractTermSet` added, `PayRate` removed
- `shifts/models.py` — `Shift.terms` FK added, `PlannedShift.approve()` auto-resolves termset
- `workplaces/migrations/0004_workplacecontract_contracttermset.py` — creates tables, migrates data, drops PayRate
- `shifts/migrations/0002_shift_terms.py` — adds terms FK, assigns to existing shifts
- `workplaces/forms.py` — `WorkplaceForm` (appearance only), `WorkplaceContractForm`, `ContractTermSetForm`
- `workplaces/views.py` + `urls.py` — contract/termset CRUD views added, PayRate views removed
- `workplaces/services.py` — `workplaces_active_in_period()` helper added
- `analytics/services.py` — contract-aware, PayRate removed
- `payroll/services.py` — all settings resolved via `active_termset_on()`
- `payroll/views.py` — `TaxPullDayUpdateView` + `PayrollPeriodDetailView` updated
- `calendar_view/views.py` + `services.py` — termset-aware, default shift from termset
- `workplaces/admin.py` — updated for new models
- `data_io/services.py` — export/import updated (contracts/termsets, no PayRate)
- `python manage.py check` passes ✓

### Still to do (next session)
1. Fix `core/dashboard_service.py` — lines 90 and 136 access `wp.employment_type` directly (should use `wp.active_termset_on(date)`)
2. Fix `shifts/tests/test_services.py` + `payroll/tests/test_services.py` — create Workplaces with contracts/termsets instead of direct fields
3. Create templates:
   - `workplaces/templates/workplaces/contract_form.html`
   - `workplaces/templates/workplaces/termset_form.html`
   - `workplaces/templates/workplaces/contract_confirm_delete.html`
   - `workplaces/templates/workplaces/termset_confirm_delete.html`
   - Update `workplace_detail.html` to show contract timeline section
   - Update `_form_fields.html` (employment section now via ContractTermSetForm)
4. Run `python manage.py migrate` and smoke-test the app
5. Update `analytics/views.py` — check if `Workplace.EmploymentType` still referenced
6. Check `core/views.py` and `core/dashboard_service.py` for remaining Workplace field references

### Key command to resume
```powershell
cd c:\Git\BitGigs
.venv\Scripts\python.exe manage.py check --settings=bitgigs.settings.local
```

---


## Context
All employment settings currently live directly on `Workplace`. There is no way to have multiple distinct employment arrangements at one workplace (e.g., different labs at AAU), and changing any setting silently overwrites old values — breaking historical accuracy of shifts, payroll, and projections.

The new design has three layers:
1. **Workplace** — appearance only (name, icon, colors)
2. **WorkplaceContract** — an employment arrangement with a date range (e.g., "Physics Lab 2022–2024")
3. **ContractTermSet** — a versioned snapshot of all employment settings within a contract (effective from a given date)

`Shift` references `ContractTermSet` directly, so it always knows exactly which pay rate, hours, pension etc. applied at the time. `PlannedShift` is temporary — it does NOT store terms; on approval it resolves the correct `ContractTermSet` for the shift date and creates the `Shift`.

---

## Data model

### `Workplace` — appearance only
**Keep:** `name`, `slug`, `is_active`, `icon`, `custom_icon`, `color`, `accent_color`, `created_at`, `updated_at`
**Remove:** all employment/payroll/pension/hours/default-shift/hour-goal fields and `contract_start_date` / `contract_end_date`

**Add helpers:**
```python
def active_contract_on(self, d: date) -> "WorkplaceContract | None"
def contracts_in_period(self, start: date, end: date) -> QuerySet
```

---

### `WorkplaceContract` — employment period
```
workplace       FK(Workplace, related_name="contracts")
name            CharField(blank=True)       # optional label, e.g. "Physics Lab"
start_date      DateField()                 # required
end_date        DateField(null=True)        # null = still active
created_at, updated_at
```

**Helpers:**
```python
def active_termset_on(self, d: date) -> "ContractTermSet | None"
    # latest ContractTermSet with effective_from <= d
def is_active_on(self, d: date) -> bool
```

**Validation (clean):**
- `start_date <= end_date` if both set
- No overlap with another contract on the same workplace

---

### `ContractTermSet` — versioned employment settings (replaces `PayRate`)
```
contract        FK(WorkplaceContract, related_name="term_sets")
effective_from  DateField()                 # required; terms apply from this date

# All settings currently on Workplace:
employment_type
hourly_rate, monthly_salary
weekly_hours_fixed, weekly_hours_min, weekly_hours_max
payroll_period_start_day
tax_card_type, tax_pull_day
vacation_type
pension_employee_percent, pension_employer_percent
fritvalgskonto_enabled, fritvalgskonto_percent, fritvalgskonto_payout_type
ferietillaeg_enabled, ferietillaeg_percent, ferietillaeg_payout_months
default_shift_start_time, default_shift_end_time, default_shift_break_minutes, default_shift_type
hour_goal_type, hour_goal_min, hour_goal_max

created_at
```

**Move from `Workplace` to `ContractTermSet`:** all computed properties (`base_hourly_rate`, `effective_hourly_rate`, `total_hourly_rate`, `expected_weekly_hours`, `beskæftigelsesprocent`, `ferietillaeg_payout_month_list`, `get_rate_as_of` logic).

**Meta:** `unique_together = [["contract", "effective_from"]]`, `ordering = ["-effective_from"]`

---

### `PayRate` — removed
Absorbed into `ContractTermSet`. The existing `PayRate` records are migrated as additional `ContractTermSet` entries.

---

### `Shift` — add terms FK
```python
terms = ForeignKey(ContractTermSet, null=True, blank=True, on_delete=SET_NULL)
```
Nullable for migration safety; auto-set on creation.

### `PlannedShift` — no terms FK
Planned shifts are temporary. They keep the existing `workplace` FK. On `approve()`, the shift is created with `terms = workplace.active_contract_on(shift.date).active_termset_on(shift.date)`.

---

## TermSet UX

### Creating a new TermSet
`ContractTermSetCreateView` presents a full settings form **with an `effective_from` date field** (pre-filled to today, editable). The user sets the date from which the new terms apply.

### Editing an existing TermSet
When the user opens `ContractTermSetUpdateView`, they choose:

| Button | Behaviour |
|---|---|
| **"Update these terms"** | Overwrites the record in-place. Shows a warning: "This affects N existing shifts." Appropriate for correcting a data entry error. |
| **"New terms from [date]"** | Pre-fills a new TermSet form with the current values and an `effective_from` date field. User adjusts what changed and picks the effective date. Old shifts are unaffected; new shifts from that date forward use the new terms. |

The contract detail/history page lists all `ContractTermSet` entries chronologically, with create / edit / delete buttons per entry.

---

## Migration strategy

Single migration file with a `RunPython` data step:

1. Create `WorkplaceContract` and `ContractTermSet` tables (nullable fields initially).
2. **Data — one contract per workplace:** `start_date = contract_start_date or date(2000,1,1)`, `end_date = contract_end_date`.
3. **Data — one ContractTermSet per contract:** copy all employment fields from `Workplace`; `effective_from = start_date`.
4. **Data — migrate existing `PayRate` records:** for each `PayRate`, create a `ContractTermSet` on that workplace's contract with `effective_from = pay_rate.effective_from` and the new rate values (other fields copied from the base `ContractTermSet`).
5. **Data — assign terms to existing Shifts:** for each `Shift`, resolve `terms = contract.active_termset_on(shift.date)`.
6. Make `WorkplaceContract.start_date` and `ContractTermSet.effective_from` non-nullable via `AlterField`.
7. Remove employment fields from `Workplace`; drop `PayRate` table.

---

## Service layer — what to update

| File | Change |
|---|---|
| `workplaces/services.py` | `get_hourly/salaried_workplaces` → filter via `contracts__term_sets__employment_type`. Add `workplaces_active_in_period(start, end)`. |
| `analytics/services.py:245` | `wp.is_contract_active_in_month(y, m)` → `wp.contracts_in_period(month_start, month_end).exists()`. |
| `analytics/services.py` (project_period) | `wp.employment_type`, `wp.expected_weekly_hours` → `terms = contract.active_termset_on(midmonth)`, then `terms.employment_type` etc. |
| `analytics/services.py` (rate_history) | Iterate `ContractTermSet` objects instead of `PayRate`. |
| `payroll/services.py` | `workplace.payroll_period_start_day`, `.tax_pull_day`, `.tax_card_type`, `.employment_type` → resolve via `workplace.active_contract_on(period.start_date).active_termset_on(period.start_date)`. |
| `payroll/views.py:229` | `period.workplace.tax_pull_day = day; .save()` → update the active `ContractTermSet` record instead. |
| `shifts/models.py` (`PlannedShift.approve`) | After creating the `Shift`, set `shift.terms = shift.workplace.active_contract_on(shift.date).active_termset_on(shift.date)`. |

---

## New views & URLs (`workplaces/`)

| URL | View |
|---|---|
| `<slug>/contracts/add/` | `ContractCreateView` |
| `<slug>/contracts/<cpk>/edit/` | `ContractUpdateView` (dates + name only) |
| `<slug>/contracts/<cpk>/delete/` | `ContractDeleteView` (blocked if shifts reference terms under this contract) |
| `<slug>/contracts/<cpk>/terms/add/` | `ContractTermSetCreateView` |
| `<slug>/contracts/<cpk>/terms/<tpk>/edit/` | `ContractTermSetUpdateView` (overwrite or fork) |
| `<slug>/contracts/<cpk>/terms/<tpk>/delete/` | `ContractTermSetDeleteView` |

`WorkplaceCreateView` — after saving, redirects to `ContractCreateView`.
`WorkplaceDetailView` — add contract timeline section.
`WorkplaceUpdateView` — appearance fields only.

---

## Period-based workplace filtering

Replace all `Workplace.objects.filter(is_active=True)` (7 sites in analytics, calendar, payroll, data_io) with:

```python
# workplaces/services.py
def workplaces_active_in_period(start: date, end: date):
    return Workplace.objects.filter(is_active=True).filter(
        contracts__start_date__lte=end
    ).filter(
        Q(contracts__end_date__isnull=True) | Q(contracts__end_date__gte=start)
    ).distinct()
```

---

## Files to create / modify

**New files:**
- `workplaces/migrations/0004_workplacecontract_contracttermset.py`
- `workplaces/templates/workplaces/contract_form.html`
- `workplaces/templates/workplaces/contract_termset_form.html`
- `workplaces/templates/workplaces/contract_confirm_delete.html`
- `workplaces/templates/workplaces/contract_termset_confirm_delete.html`

**Modified files:**
- `workplaces/models.py` — major (strip Workplace, add WorkplaceContract + ContractTermSet, remove PayRate)
- `workplaces/forms.py` — add `WorkplaceContractForm`, `ContractTermSetForm`; update `WorkplaceForm` to appearance-only
- `workplaces/views.py` — add 6 new views; update existing
- `workplaces/urls.py` — 6 new URL patterns
- `workplaces/services.py` — add period-active helper; update type filters
- `workplaces/templates/workplaces/workplace_detail.html` — contract timeline section
- `workplaces/templates/workplaces/_form_fields.html` — replace employment fields
- `shifts/models.py` — add `terms` FK; update `approve()`
- `shifts/migrations/0002_shift_terms.py`
- `analytics/services.py`
- `payroll/services.py`
- `payroll/views.py`
- `calendar_view/services.py` + `views.py`

---

## Verification

```powershell
python manage.py check --settings=bitgigs.settings.local
python manage.py migrate --settings=bitgigs.settings.local
python manage.py test --settings=bitgigs.settings.local
```

**Manual flow checks:**
- Create workplace → redirected to add first contract → add initial terms → workplace detail shows contract + terms
- Add second non-overlapping contract → works; overlapping → validation error
- Edit terms → "Update these terms" shows affected shift count; "New terms from [date]" creates new record; old shifts unchanged
- Approve a planned shift → `shift.terms` is set correctly to terms active on shift date
- Analytics filter by period → workplaces with no active contract in that period are excluded
