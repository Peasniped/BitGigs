# Onboarding — full plan + remaining work (self-contained)

Everything needed to finish the onboarding "save-as-you-go + partial-fill"
work. Self-contained (the approved plan file lived outside the repo). Delete
this file once the work is finished and committed.

---

## Context / goal

The onboarding wizard (account → Tax → Workplace → Contract → Terms) previously
only saved a step when submitted **valid**, which caused two problems:

1. **Bug:** navigating back via the step number or Back button is a plain GET
   link, so typed-but-unsubmitted input is discarded and the step reverts to
   grey/unclickable (no draft data). E.g. type "asdf" in Workplace, go back to
   Tax → Workplace entry lost, its dot grey.
2. **Desired UX:** fill steps **partially**, move on freely, and only be stopped
   at **Finish** with "you need to finish step X before submitting". When
   returning to a partial step, **unfilled required fields highlight in yellow**.

**Fix:** change from "validate-and-block per step" to **save-on-every-navigation
(no per-step gate) + validate-only-at-Finish**, with a validity-driven step
indicator (green = complete, yellow = started/incomplete) and yellow field
highlights on revisit. Builds on the durable `OnboardingDraft` (already in DB).

Key files: `apps/core/views.py`, `apps/core/templates/core/_onboarding_steps.html`,
`apps/core/templates/core/onboarding_tax.html`,
`apps/workplaces/templates/workplaces/{workplace_form,contract_form,termset_form}.html`,
`assets/static/js/app.js`, `assets/static/css/style.css`,
`apps/core/tests/test_auth.py`, `CLAUDE.md`.

---

## DONE (backend — `apps/core/views.py`, `manage.py check` passes)

- Deferred-step `post` (tax/workplace/contract) **save raw POST to the draft
  without validating**, then `redirect(_resolve_goto(request, key))`. Forward
  "Continue" (no `onboarding_goto`) defaults to `next` and works today.
- `OnboardingTermsView.post`: save terms; if `onboarding_goto` is `next`/`finish`
  run `_commit_onboarding`, else navigate (back/jump).
- `_resolve_goto(request, current)`: `onboarding_goto` = `next` (following step)
  or a step key (jump there); guarded against arbitrary values.
- Validity-driven indicator: `_build_step_form(key, payload)` +
  `_onboarding_progress(data)` (per indicator-step: valid/started/empty) +
  `_onboarding_steps` → states `done`(valid,green) / `started`(has data but
  invalid,yellow) / `active` / `upcoming`. `done` and `started` both clickable.
- `_commit_onboarding` re-validates every step; messages name the step
  ("Please finish the Tax details step before you can submit.") and redirect to
  the first incomplete step. `_STEP_LABELS` added.

---

## LEFT TO DO

### A. Templates — make Back/step-jump SAVE current input (fixes the core bug)
The bug is still live because Back and the step numbers are plain `<a href>` GET
links. In each onboarding form (only under `{% if onboarding %}`):

- Add `data-onboarding-form` and class `onboarding-fields` to the `<form>`:
  `onboarding_tax.html` + `workplace_form.html` + `contract_form.html` +
  `termset_form.html`.
- Convert **Continue** and **Back** (Back is currently `<a>`) to named submit
  buttons: `<button type="submit" name="onboarding_goto" value="next">Continue</button>`
  and `... value="<prev-key>">Back</button>`. Terms "Finish setup" →
  `value="finish"`; terms Back → `value="contract"`.
  Prev keys: tax → (no Back), workplace → `tax`, contract → `workplace`,
  terms → `contract`.
- Step-number links in `core/_onboarding_steps.html`: keep `<a href>`, add
  `data-onboarding-goto="{{ step.key }}"`. Requires adding a `key` to each step
  dict in `_onboarding_steps` (indicator steps 2/3/4 → `tax`/`workplace`/
  `contract`; step 1 account → none).

### B. JS — `assets/static/js/app.js`
Add `initOnboardingNav(document)` (call from `DOMContentLoaded`): on click of
`[data-onboarding-goto]`, find `form[data-onboarding-form]`, inject a hidden
`<input name="onboarding_goto" value="<key>">`, `preventDefault`, `form.submit()`
(saves current input before navigating). `termset_form.js` has no submit
handler, so `.submit()` is safe. Falls back to the plain link if JS is off.

### C. CSS — `assets/static/css/style.css`
Recolor Bootstrap red validation to amber inside `.onboarding-fields` so a
revisited partial step highlights unfilled required fields yellow, not red:
```
.onboarding-fields .is-invalid { border-color:#f59e0b; background-image:none; }
.onboarding-fields .invalid-feedback { color:#b45309; }
```
(The account step keeps red — different template, not `.onboarding-fields`.)
Field highlights already appear because each step `get` binds the form with the
stored data when the step has draft data (`Form(data=stored)`), producing
`.is-invalid`; this only recolors them.

### D. termset required inputs — `termset_form.html`
Confirm the conditionally-required inputs (`employment_type`, `hourly_rate`,
`monthly_salary`, `weekly_hours_fixed`/`_min`/`_max`) render
`{% if form.X.errors %}is-invalid{% endif %}` on the `<input>` so the amber
highlight lands on them; add where missing.

### E. Tests — `apps/core/tests/test_auth.py`
- **WILL FAIL NOW — must rewrite:** `test_earlier_navigation_marks_ahead_step_started`
  posts *valid* tax+workplace, so Workplace is now `done` (green), not `started`.
  Change it to post a **partial** step (e.g. POST workplace with empty name, or
  POST tax missing `tax_percent`) and assert `setup-step--started`.
- Add: partial input saved on back-nav (POST workplace with
  `onboarding_goto=tax` + partial payload → draft has workplace data, 302 to
  tax); Continue advances an incomplete step without blocking; Finish with an
  incomplete step → redirect to it + a "finish … before you can submit" message,
  no real rows created.
- Run `python manage.py test apps --settings=bitgigs.settings.local`.

### F. Docs + commit
- Update the CLAUDE.md **Auth** bullet: onboarding saves every step on
  navigation (no per-step validation), validates only at Finish, and the step
  indicator + field highlights are validity-driven.
- Commit, then delete this PLAN.md.

---

## Verify when finished
`manage.py check` → `test apps` → manual (incomplete DB): type into Workplace,
click the Tax step number → input preserved + Workplace dot yellow/clickable;
leave Tax's rate blank, Continue through to Terms, Finish → bounced to Tax with
a "finish the Tax details" message and the empty required field highlighted
yellow; fill it, Finish → dashboard with the auto-dismissing welcome toast.

---

## Also in this branch (already committed in d5debab, for context)
Round 2, complete: durable `OnboardingDraft` (+migration 0002); `SymbolPassword`
+ `NoSequences` password validators (`core/validators.py`) with live checklist
(`onboarding_password.js`); owner/admin account wording; top-right "Logged in as
… · Log out" during onboarding; login "finish setup" hint; reusable
countdown-ring dismissible notice (`data-dismiss-after`, `initDismissibleNotices`
in `app.js`, `.notice-timer` CSS).
