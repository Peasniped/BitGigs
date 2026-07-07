/* Pay-terms form: Today button, fork-date label, hour-goal toggle +
   auto-populate from contracted hours. Django form field ids/names are read
   from #termsetForm data-* attributes. Uses toDanish() from app.js. */
(function() {
  var FORM = document.getElementById('termsetForm');
  var cfg = FORM ? FORM.dataset : {};

  // Today button: set today's date on the effective-from field
  (function() {
    var btn = document.querySelector('[data-today-btn]');
    var input = document.querySelector('[data-effective-from]');
    if (!btn || !input) return;
    btn.addEventListener('click', function() {
      var iso = new Date().toLocaleDateString('sv');  // yyyy-mm-dd
      if (window.setDateValue) window.setDateValue(input, iso);
      else input.value = iso;
      input.dispatchEvent(new Event('input'));
    });
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
      var weeklyHours;
      if (isFuldtid) {
        weeklyHours = 37;
      } else {
        weeklyHours = _parseDk(
          document.getElementById(cfg.fieldWeeklyFixed).value
        );
      }
      if (isNaN(weeklyHours) || weeklyHours <= 0) return null;
      return { hours: Math.round(weeklyHours * 52 / 12 * 100) / 100, period: 'monthly' };

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
