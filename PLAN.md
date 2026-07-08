# Onboarding — remaining work (save-as-you-go + partial-fill)

Full design is in `~/.claude/plans/sprightly-fluttering-scroll.md` (approved).
This file tracks what's DONE vs LEFT so the next session can finish + commit.

## Status of the working tree (NOT yet committed)

Two batches of uncommitted changes are in the tree:

1. **Round 2 — COMPLETE + previously tested (149 passing before round 3):**
   durable `OnboardingDraft` model (+ migration `0002`), symbol +
   no-sequence password validators, owner/admin wording, top-right "Logged in
   as … · Log out", login "finish setup" hint, yellow "started" step, reusable
   countdown-ring dismissible notice (`data-dismiss-after`).

2. **Round 3 — BACKEND DONE, frontend + tests LEFT (this file).**

## Round 3 — DONE (backend, `apps/core/views.py`)

- Deferred-step `post` handlers (tax/workplace/contract) now **save the raw POST
  to the draft without validating**, then `redirect(_resolve_goto(request, key))`.
  Forward "Continue" (no `onboarding_goto`) defaults to `next` and works today.
- `OnboardingTermsView.post`: saves terms, then if `onboarding_goto` is
  `next`/`finish` runs `_commit_onboarding`, else navigates (back/jump).
- `_resolve_goto(request, current)` — maps `onboarding_goto` (`next` or a step
  key) to a URL, guarded.
- Step indicator is now **validity-driven**: `_onboarding_progress(data)` +
  `_build_step_form(key, payload)`; `_onboarding_steps` → `done` (valid, green),
  `started` (has data but invalid, yellow), `active`, `upcoming`. Both `done` and
  `started` are clickable.
- `_commit_onboarding` re-validates every step; messages now name the step
  ("Please finish the Tax details step before you can submit.") and it redirects
  to the first incomplete step.
- `_STEP_LABELS` added. `manage.py check` passes.

## Round 3 — LEFT TO DO

### A. Templates — wire navigation so back/jump SAVES current input
The core bug (typing then going Back/step-number discards input) is still live,
because Back and the step numbers are plain `<a href>` GET links. Fix:

- Each onboarding form gets `data-onboarding-form` and class `onboarding-fields`
  (only in `{% if onboarding %}`): `onboarding_tax.html`, and workplaces
  `workplace_form.html`, `contract_form.html`, `termset_form.html`.
- Convert **Continue** and **Back** (currently `<a>`) to named submit buttons:
  `<button type="submit" name="onboarding_goto" value="next">Continue</button>`
  and `... value="<prev-step-key>">Back</button>`. Terms "Finish setup" →
  `value="finish"`, its Back → `value="contract"`. Prev keys: tax(none),
  workplace→`tax`, contract→`workplace`, terms→`contract`.
- Step-number links in `core/_onboarding_steps.html`: keep `<a href>` but add
  `data-onboarding-goto="{{ step.key }}"` (need to add a `key` to each step dict
  in `_onboarding_steps`, e.g. tax/workplace/contract for indicator steps 2/3/4).

### B. JS — `assets/static/js/app.js`
Add `initOnboardingNav(document)` (call it from `DOMContentLoaded`): on click of
`[data-onboarding-goto]`, find `form[data-onboarding-form]`, inject a hidden
`<input name="onboarding_goto" value="<key>">`, `preventDefault`, `form.submit()`
(so the current input is saved before navigating). `termset_form.js` has no
submit handler, so `.submit()` is safe.

### C. CSS — `assets/static/css/style.css`
Recolor Bootstrap red validation to **amber** inside `.onboarding-fields` so a
revisited partial step highlights unfilled required fields in yellow, not red:
`.onboarding-fields .is-invalid { border-color:#f59e0b; background-image:none; }`
`.onboarding-fields .invalid-feedback { color:#b45309; }`
(Account step keeps red — it's a different template.)

### D. termset required inputs
Confirm the conditionally-required inputs in `termset_form.html`
(`employment_type`, `hourly_rate`, `monthly_salary`, `weekly_hours_*`) render
`{% if form.X.errors %}is-invalid{% endif %}` so the amber highlight lands on
them; add where missing.

### E. Tests — `apps/core/tests/test_auth.py`
- **WILL FAIL NOW:** `test_earlier_navigation_marks_ahead_step_started` posts
  *valid* tax+workplace, so workplace is now `done` (green), not `started`.
  Rewrite it to post a **partial** step and assert `setup-step--started`
  (e.g. POST workplace with an empty name, or POST tax missing `tax_percent`).
- Add: partial input saved on back-nav (POST workplace `onboarding_goto=tax`
  with partial payload → draft has workplace data, 302 to tax); Continue
  advances with an incomplete step (no block); Finish with an incomplete step →
  redirect to it + "finish … before you can submit" message, no real rows.
- Re-run `python manage.py test apps --settings=bitgigs.settings.local`.

### F. Docs + commit
- Update the CLAUDE.md Auth note: onboarding saves every step on navigation (no
  per-step validation), validates only at Finish, step indicator + field
  highlights are validity-driven.
- Then present ONE combined commit for round 2 + round 3 (see prior proposed
  messages) and delete this PLAN.md.

## Quick verify after finishing
`python manage.py check` → `test apps` → manual: type in Workplace, click the Tax
step number → input preserved, Workplace dot yellow; leave a required field
blank, Finish → bounced to that step with an amber-highlighted field + message.
