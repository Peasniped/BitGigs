/* Pay-terms form: Today button, fork-date label, hour-goal toggle +
   auto-populate from contracted hours. Django form field ids/names are read
   from #termsetForm data-* attributes. Uses toDanish() from app.js. */
(function() {
  var FORM = document.getElementById('termsetForm');
  var cfg = FORM ? FORM.dataset : {};

  // (The "Today" button is wired globally by initTodayButtons() in app.js.)

  // "Ends on" prompts. Depending on the surrounding term sets, the end date
  // means different things, so instead of a bare field we show one of:
  //   * next-prompt  — a LATER term set exists, so these terms are capped by it:
  //                    run until then (blank) or end earlier (a deliberate gap).
  //   * carry-over   — these terms start on/before a PREVIOUS term set's end
  //                    date: keep that end date, go open-ended, or set another.
  //   * plain field  — neither applies (last/only terms): optional end date.
  // Only active where the sibling dates are provided (data-existing-terms).
  (function() {
    var existing;
    try { existing = JSON.parse(cfg.existingTerms || '[]'); }
    catch (e) { existing = []; }
    if (!existing.length) return;

    var effInput = document.querySelector('[data-effective-from]');
    var untilInput = document.querySelector('[data-effective-until]');
    var carry = document.querySelector('[data-supersede-prompt]');
    var nextP = document.querySelector('[data-next-prompt]');
    var plain = document.querySelector('[data-plain-until]');
    if (!effInput || !untilInput || !carry || !nextP || !plain) return;
    var carryDateEls = carry.querySelectorAll('[data-supersede-date]');
    var nextDateEls = nextP.querySelectorAll('[data-next-date]');
    var boxSlot = carry.querySelector('[data-until-slot="box"]');
    var gapSlot = nextP.querySelector('[data-until-slot="gap"]');
    var plainSlot = plain.querySelector('[data-until-slot="plain"]');
    var initialUntil = untilInput.value;   // existing end date (if editing)
    var nextSeeded = false;

    // Relocate the (single) end-date field between the slots. Air Datepicker
    // turns the input into a hidden ISO carrier plus a visible display input
    // (el._adpDisplay); move both.
    function moveFieldTo(slot) {
      slot.appendChild(untilInput);
      if (untilInput._adpDisplay) slot.appendChild(untilInput._adpDisplay);
    }

    function dmy(iso) {
      var p = (iso || '').split('-');
      return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : iso;
    }
    function isoAddDays(iso, n) {
      var p = iso.split('-');
      var d = new Date(+p[0], +p[1] - 1, +p[2]);
      d.setDate(d.getDate() + n);
      return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) +
             '-' + ('0' + d.getDate()).slice(-2);
    }
    function setUntil(iso) {
      if (window.setDateValue) window.setDateValue(untilInput, iso);
      else untilInput.value = iso;
    }

    // Start date of the earliest term set that begins after effVal (the one
    // that caps these terms), or null when these are the last terms.
    function nextTermStart(effVal) {
      if (!effVal) return null;
      var best = null;
      existing.forEach(function(t) {
        if (t.from > effVal && (!best || t.from < best)) best = t.from;
      });
      return best;
    }

    // End date inherited from the term set this one supersedes: the latest prior
    // term set with an end date on/after the new start.
    function supersededExpiry(effVal) {
      if (!effVal) return null;
      var best = null;
      existing.forEach(function(t) {
        if (t.from < effVal && (!best || t.from > best.from)) best = t;
      });
      if (best && best.until && best.until >= effVal) return best.until;
      return null;
    }

    // ---- carry-over prompt (previous terms' end date) ----
    function applyCarry() {
      var sel = carry.querySelector('[data-until-choice]:checked');
      var val = sel ? sel.value : 'keep';
      var expiry = carry.dataset.expiry || '';
      if (val === 'custom') {
        moveFieldTo(boxSlot);
        boxSlot.style.display = '';
        if (!untilInput.value) setUntil(expiry);
      } else {
        boxSlot.style.display = 'none';
        moveFieldTo(plainSlot);
        setUntil(val === 'keep' ? expiry : '');
      }
    }

    // ---- next-term-set prompt (later terms cap these) ----
    // A gap date is only kept when it actually ends earlier than the day before
    // the next terms; the boundary day (redundant) or anything later just falls
    // back to "run until then" (blank).
    function validateGap() {
      var nextStart = nextP.dataset.nextStart || '';
      var from = effInput.value;
      var v = untilInput.value;
      if (!nextStart || !v) return;
      var lastGapDay = isoAddDays(nextStart, -2);   // latest date that leaves a gap
      if (v > lastGapDay || (from && v < from)) {
        setUntil('');
        var untilRadio = nextP.querySelector('[data-next-choice][value="until_next"]');
        if (untilRadio) untilRadio.checked = true;
        gapSlot.style.display = 'none';
      }
    }
    function applyNext() {
      var sel = nextP.querySelector('[data-next-choice]:checked');
      var val = sel ? sel.value : 'until_next';
      if (val === 'gap') {
        moveFieldTo(gapSlot);
        gapSlot.style.display = '';
        validateGap();   // normalise a redundant/invalid seeded value
      } else {
        gapSlot.style.display = 'none';
        moveFieldTo(gapSlot);
        setUntil('');
      }
    }

    function showOnly(which) {
      carry.style.display = which === 'carry' ? '' : 'none';
      nextP.style.display = which === 'next' ? '' : 'none';
      plain.style.display = which === 'plain' ? '' : 'none';
      if (which !== 'carry') boxSlot.style.display = 'none';
      if (which !== 'next') gapSlot.style.display = 'none';
    }

    function update() {
      var effVal = effInput.value;
      var laterStart = nextTermStart(effVal);
      var expiry = supersededExpiry(effVal);
      if (laterStart) {
        nextP.dataset.nextStart = laterStart;
        nextDateEls.forEach(function(el) { el.textContent = dmy(laterStart); });
        // First time we enter this mode, keep an existing end date as a gap
        // rather than defaulting to "run until then" and wiping it.
        if (!nextSeeded) {
          nextSeeded = true;
          var gapRadio = nextP.querySelector('[data-next-choice][value="gap"]');
          if (initialUntil && gapRadio) gapRadio.checked = true;
        }
        showOnly('next');
        applyNext();
      } else if (expiry) {
        carry.dataset.expiry = expiry;
        carryDateEls.forEach(function(el) { el.textContent = dmy(expiry); });
        showOnly('carry');
        applyCarry();
      } else {
        showOnly('plain');
        moveFieldTo(plainSlot);
      }
    }

    carry.querySelectorAll('[data-until-choice]').forEach(function(r) {
      r.addEventListener('change', applyCarry);
    });
    nextP.querySelectorAll('[data-next-choice]').forEach(function(r) {
      r.addEventListener('change', applyNext);
    });
    untilInput.addEventListener('change', function() {
      if (nextP.style.display !== 'none') validateGap();
    });
    effInput.addEventListener('change', update);
    effInput.addEventListener('input', update);
    update();
  })();

  // Update fork button label with the effective_from date
  (function() {
    var dateInput = document.getElementById(cfg.fieldEffectiveFrom);
    var label = document.getElementById('forkDateLabel');
    if (!dateInput || !label) return;
    function updateLabel() {
      label.textContent = dateInput.value || '…';
    }
    dateInput.addEventListener('input', updateLabel);
    dateInput.addEventListener('change', updateLabel);
    updateLabel();
  })();

  // Hour goal toggle
  document.getElementById('hourGoalToggle').addEventListener('change', function() {
    document.getElementById('hourGoalFields').style.display = this.checked ? '' : 'none';
    if (!this.checked) {
      document.querySelectorAll('input[name="' + cfg.nameGoalType + '"]').forEach(function(r) { r.checked = false; });
      document.querySelector('[name="' + cfg.nameGoalMin + '"]').value = '';
      document.querySelector('[name="' + cfg.nameGoalMax + '"]').value = '';
      document.getElementById('goalRangeWarning').style.display = 'none';
    } else {
      var any = document.querySelector('input[name="' + cfg.nameGoalType + '"]:checked');
      if (!any) document.getElementById('goalPeriodWeekly').checked = true;
      autoPopulateGoal();
    }
  });
  document.querySelectorAll('input[name="goalMode"]').forEach(function(radio) {
    radio.addEventListener('change', function() {
      var isRange = this.value === 'range';
      document.getElementById('goalMaxWrapper').style.display = isRange ? '' : 'none';
      document.getElementById('goalToLabel').style.display = isRange ? '' : 'none';
      if (!isRange) document.querySelector('[name="' + cfg.nameGoalMax + '"]').value = '';
    });
  });

  // ── Auto-populate hour goal from contracted hours ─────────────────────────
  function _parseDk(v) {
    if (!v) return NaN;
    return parseFloat(String(v).replace(/\./g, '').replace(',', '.'));
  }

  function getSuggestedGoal() {
    var empChecked = document.querySelector('[data-emp-type]:checked');
    if (!empChecked) return null;

    if (empChecked.value === 'salaried') {
      var wttChecked = document.querySelector('[data-wtt]:checked');
      var isFuldtid = !wttChecked || wttChecked.value === 'fuldtid';
      if (isFuldtid) {
        // Fuldtid shows no weekly-hours field — default to contracted monthly hours.
        return { hours: Math.round(37 * 52 / 12 * 100) / 100, period: 'monthly' };
      }
      // Deltid: the "Hours per week" field is visible — default to that weekly value.
      var weeklyHours = _parseDk(document.getElementById(cfg.fieldWeeklyFixed).value);
      if (isNaN(weeklyHours) || weeklyHours <= 0) return null;
      return { hours: weeklyHours, period: 'weekly' };

    } else {
      // hourly
      var htChecked = document.querySelector('[data-ht]:checked');
      var isFixed = !htChecked || htChecked.value === 'fixed';
      var weeklyHours;
      if (isFixed) {
        weeklyHours = _parseDk(
          document.getElementById(cfg.fieldWeeklyFixed + '_hourly').value
        );
      } else {
        var min = _parseDk(document.getElementById(cfg.fieldWeeklyMin).value);
        var max = _parseDk(document.getElementById(cfg.fieldWeeklyMax).value);
        if (!isNaN(min) && !isNaN(max) && min > 0 && max > 0) {
          weeklyHours = (min + max) / 2;
        } else if (!isNaN(min) && min > 0) {
          weeklyHours = min;
        }
      }
      if (isNaN(weeklyHours) || weeklyHours <= 0) return null;
      return { hours: weeklyHours, period: 'weekly' };
    }
  }

  function autoPopulateGoal() {
    if (!document.getElementById('hourGoalToggle').checked) return;
    var s = getSuggestedGoal();
    if (!s) return;

    // Set period radio
    var periodEl = document.getElementById(s.period === 'monthly' ? 'goalPeriodMonthly' : 'goalPeriodWeekly');
    if (periodEl) periodEl.checked = true;

    // Populate goal min
    var goalMinEl = document.querySelector('[name="' + cfg.nameGoalMin + '"]');
    if (goalMinEl) goalMinEl.value = toDanish(s.hours.toFixed(2));
  }

  // Wire up triggers that should refresh the goal suggestion
  ['[data-emp-type]', '[data-wtt]', '[data-ht]'].forEach(function(sel) {
    document.querySelectorAll(sel).forEach(function(el) {
      el.addEventListener('change', autoPopulateGoal);
    });
  });
  [
    cfg.fieldWeeklyFixed,
    cfg.fieldWeeklyFixed + '_hourly',
    cfg.fieldWeeklyMin,
    cfg.fieldWeeklyMax,
  ].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('input', autoPopulateGoal);
  });
})();
