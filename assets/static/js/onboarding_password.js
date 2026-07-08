/* Onboarding account step: live password requirement checklist. Reads the field
   ids from #accountForm data-* attributes and flips each <li data-check> in
   #pwChecklist between pass/fail as the user types. These are client-side hints
   only — Django's password validators remain authoritative on submit. */
(function () {
  var form = document.getElementById('accountForm');
  var list = document.getElementById('pwChecklist');
  if (!form || !list) return;

  var email = document.getElementById(form.dataset.emailId);
  var emailHint = document.getElementById('emailHint');
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
    var mail = email ? email.value : '';
    var typed = p1.length > 0;

    setState(items.length, p1.length >= 8, typed);
    setState(items.notnumeric, !/^\d+$/.test(p1), typed);
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
})();
