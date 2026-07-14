/* Live password requirement checklist. Drives any form carrying data-pw1-id /
   data-pw2-id: the onboarding account step, and the set/change password modal on
   the settings page. Flips each <li data-check> in the form's checklist between
   pass/fail as the user types. Client-side hints only — Django's password
   validators remain authoritative on submit.

   The similarity check needs the account's email. On onboarding that's a field on
   the form (data-email-id); on the settings page the account already exists, so
   the address is passed as a literal (data-email). */
document.querySelectorAll('form[data-pw1-id]').forEach(function (form) {
  var list = form.querySelector('[data-pw-checklist]');
  if (!list) return;

  var email = form.dataset.emailId ? document.getElementById(form.dataset.emailId) : null;
  var knownEmail = form.dataset.email || '';
  var emailHint = form.querySelector('[data-email-hint]');
  var pw1 = document.getElementById(form.dataset.pw1Id);
  var pw2 = document.getElementById(form.dataset.pw2Id);
  if (!pw1 || !pw2) return;

  // Debounced email format check: validate a short moment after the user stops
  // typing, so it doesn't flag a half-typed address. Server-side validation on
  // submit stays authoritative.
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  var emailTimer = null;

  function validateEmail() {
    if (!email) return;
    var value = email.value.trim();
    var valid = EMAIL_RE.test(value);
    email.classList.toggle('is-invalid', value.length > 0 && !valid);
    email.classList.toggle('is-valid', valid);
    if (emailHint) emailHint.classList.toggle('d-none', valid || value.length === 0);
  }

  if (email) {
    email.addEventListener('input', function () {
      // Clear feedback while typing; re-check ~700ms after the last keystroke.
      email.classList.remove('is-invalid', 'is-valid');
      if (emailHint) emailHint.classList.add('d-none');
      clearTimeout(emailTimer);
      emailTimer = setTimeout(validateEmail, 700);
    });
    email.addEventListener('blur', function () {
      clearTimeout(emailTimer);
      validateEmail();
    });
  }

  var items = {};
  list.querySelectorAll('li[data-check]').forEach(function (li) {
    items[li.dataset.check] = li;
  });

  function setState(li, ok, active) {
    if (!li) return;
    var icon = li.querySelector('i');
    li.classList.toggle('is-pass', ok && active);
    li.classList.toggle('is-fail', !ok && active);
    if (icon) {
      icon.className = 'bi me-1 ' + (!active ? 'bi-circle' : (ok ? 'bi-check-circle-fill' : 'bi-x-circle'));
    }
  }

  // Mirror of core.validators.CharacterClassesPasswordValidator: a symbol is any
  // char that is neither alphanumeric nor whitespace.
  function hasSymbol(pw) {
    return /[^A-Za-z0-9\s]/.test(pw);
  }

  // Mirror of core.validators.NoSequencesPasswordValidator: reject 3+ identical
  // chars in a row, or a 3+ ascending/descending alphanumeric run.
  function hasBadRun(pw) {
    var s = pw.toLowerCase();
    for (var i = 0; i + 2 < s.length; i++) {
      var a = s.charCodeAt(i), b = s.charCodeAt(i + 1), c = s.charCodeAt(i + 2);
      if (a === b && b === c) return true;
      var alnum = /[a-z0-9]/.test(s[i]) && /[a-z0-9]/.test(s[i + 1]) && /[a-z0-9]/.test(s[i + 2]);
      if (alnum && (b - a) === (c - b) && Math.abs(b - a) === 1) return true;
    }
    return false;
  }

  // Rough mirror of Django's UserAttributeSimilarityValidator: fail when the
  // password contains (or is contained by) the email or its local-part.
  function tooSimilar(pw, mail) {
    if (!pw || !mail) return false;
    var p = pw.toLowerCase();
    var candidates = [mail.toLowerCase(), mail.split('@')[0].toLowerCase()];
    return candidates.some(function (c) {
      if (c.length < 3) return false;
      return p.indexOf(c) !== -1 || c.indexOf(p) !== -1;
    });
  }

  function update() {
    var p1 = pw1.value;
    var p2 = pw2.value;
    var mail = email ? email.value : knownEmail;
    var typed = p1.length > 0;

    setState(items.length, p1.length >= 8, typed);
    setState(items.lowercase, /[a-z]/.test(p1), typed);
    setState(items.uppercase, /[A-Z]/.test(p1), typed);
    setState(items.number, /[0-9]/.test(p1), typed);
    setState(items.symbol, hasSymbol(p1), typed);
    setState(items.nosequence, !hasBadRun(p1), typed);
    setState(items.notsimilar, !tooSimilar(p1, mail), typed && !!mail);

    // Both password fields turn green (matching the email field) once they're
    // equal, and red once the repeat is filled but doesn't match.
    var match = typed && p1 === p2;
    var mismatch = p2.length > 0 && p1 !== p2;
    setState(items.match, p1 === p2, typed && p2.length > 0);
    [pw1, pw2].forEach(function (el) {
      el.classList.toggle('is-valid', match);
      el.classList.toggle('is-invalid', mismatch);
    });
  }

  [pw1, pw2, email].forEach(function (el) {
    if (el) el.addEventListener('input', update);
  });
  update();
});
