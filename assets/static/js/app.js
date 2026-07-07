/**
 * BitGigs client-side JavaScript.
 */

document.addEventListener('DOMContentLoaded', function () {
  // ----- Payslip line drag-and-drop reordering -----
  var payslipTable = document.getElementById('payslip-lines');
  if (payslipTable) {
    initPayslipDragDrop(payslipTable);
  }

  // ----- Danish number formatting -----
  initDanishNumbers();

  // ----- Workplace form dynamic behaviour -----
  document.querySelectorAll('[data-form="workplace"]').forEach(initWorkplaceForm);

  // ----- Tax profile form: folkekirken toggle -----
  document.querySelectorAll('[data-toggle-trigger="folkekirken"]').forEach(function (cb) {
    cb.addEventListener('change', function () {
      var target = findToggleTarget(this, 'folkekirken');
      if (target) target.style.display = this.checked ? '' : 'none';
    });
  });

  // ----- Calendar day modal auto-open -----
  initCalendarModal();

  // ----- Shift form: live hour calculation -----
  initShiftCalc();

  // ----- Work Shift modal (AJAX) -----
  initShiftModal();

  // ----- Time pickers (custom 24-hour segmented input) -----
  initTimePickers(document);

  // ----- Date pickers (dd/mm/yyyy display, ISO submit) -----
  initDatePickers(document);

  // ----- "Today" quick-fill buttons on effective-from date fields -----
  initTodayButtons(document);
});


/* ===========================================================================
 *  TIME PICKERS — custom, always 24-hour, segmented like the native control
 *
 *  Native <input type="time"> can't be forced to 24h (it follows the browser
 *  locale), so we convert each one to a plain text input and drive the editing
 *  ourselves: focus selects the hour pair, typing auto-advances to the minutes,
 *  and Up/Down/Left/Right adjust or move between segments. The value stays a
 *  24-hour "HH:MM" string, so server parsing and other JS are unaffected.
 * =========================================================================*/

var TIME_PLACEHOLDER = '--:--';

function pad2(n) { return ('0' + n).slice(-2); }

/**
 * Convert every <input type="time"> within `root` into a segmented 24h input.
 * Exposed on window so dynamically-inserted inputs can be initialised too.
 */
function initTimePickers(root) {
  (root || document).querySelectorAll('input[type="time"]').forEach(function (el) {
    if (el.dataset.time24) return;
    el.dataset.time24 = '1';
    el.type = 'text';
    el.classList.add('time-24-input');           // clock glyph via CSS
    el.setAttribute('inputmode', 'numeric');
    el.setAttribute('autocomplete', 'off');
    el.maxLength = 5;
    if (!el.getAttribute('placeholder')) el.setAttribute('placeholder', TIME_PLACEHOLDER);
    if (el.value) normalizeTimeInput(el);
    updateClockIcon(el);

    el.addEventListener('focus', function () {
      if (!el.value) el.value = TIME_PLACEHOLDER;
      selectTimeSegment(el, 0);
    });
    el.addEventListener('mouseup', function () {
      setTimeout(function () { selectTimeSegment(el, caretSegment(el)); }, 0);
    });
    el.addEventListener('keydown', function (e) { onTimeKeydown(el, e); });
    el.addEventListener('blur', function () { normalizeTimeInput(el); });
  });
}
window.initTimePickers = initTimePickers;

/** Set a time value programmatically (val = "HH:MM" 24h, or empty to clear). */
function setTimeValue(el, val) {
  if (!el) return;
  el.dataset.buf = '';
  el.value = val || '';
  if (el.value && el.dataset.time24) normalizeTimeInput(el);
  else if (el.dataset.time24) updateClockIcon(el);
}
window.setTimeValue = setTimeValue;

function timeSegs(el) {
  var v = el.value || TIME_PLACEHOLDER;
  var i = v.indexOf(':');
  return i === -1 ? [v.slice(0, 2), '--'] : [v.slice(0, i), v.slice(i + 1)];
}

function renderTime(el, hh, mm) { el.value = hh + ':' + mm; updateClockIcon(el); }

/** Build the clock-face background image for the given hand angles (deg from 12). */
function clockBg(hAngle, mAngle) {
  function hand(angle, len, w) {
    var a = angle * Math.PI / 180;
    return "<line x1='8' y1='8' x2='" + (8 + len * Math.sin(a)).toFixed(2) +
           "' y2='" + (8 - len * Math.cos(a)).toFixed(2) +
           "' stroke='#6c757d' stroke-width='" + w + "' stroke-linecap='round'/>";
  }
  var svg =
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>" +
    "<circle cx='8' cy='8' r='7.2' fill='none' stroke='#6c757d' stroke-width='1'/>" +
    hand(hAngle, 3.0, 1.3) + hand(mAngle, 4.6, 1) +
    "<circle cx='8' cy='8' r='0.7' fill='#6c757d'/></svg>";
  return 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")';
}

function shortestAngle(from, to) { return ((to - from + 540) % 360) - 180; }

/** Point the clock glyph at the input's current time, sweeping the hands there. */
function updateClockIcon(el) {
  var p = timeSegs(el);
  var h = parseInt(p[0], 10); if (isNaN(h)) h = 0;   // empty -> 12:00
  var m = parseInt(p[1], 10); if (isNaN(m)) m = 0;
  var targetH = (h % 12) * 30 + m * 0.5;
  var targetM = m * 6;
  var fromH = (el._clockH == null) ? targetH : el._clockH;   // no sweep on first paint
  var fromM = (el._clockM == null) ? targetM : el._clockM;
  var dH = shortestAngle(fromH, targetH);
  var dM = shortestAngle(fromM, targetM);
  if (el._clockRAF) cancelAnimationFrame(el._clockRAF);
  if (Math.abs(dH) < 0.1 && Math.abs(dM) < 0.1) {
    el._clockH = targetH; el._clockM = targetM;
    el.style.backgroundImage = clockBg(targetH, targetM);
    return;
  }
  var dur = 220, start = null;
  function frame(ts) {
    if (start == null) start = ts;
    var k = Math.min((ts - start) / dur, 1);
    var e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;   // easeInOutQuad
    var curH = fromH + dH * e, curM = fromM + dM * e;
    el._clockH = curH; el._clockM = curM;                            // track for smooth chaining
    el.style.backgroundImage = clockBg(curH, curM);
    if (k < 1) { el._clockRAF = requestAnimationFrame(frame); }
    else { el._clockH = targetH; el._clockM = targetM; el._clockRAF = null; }
  }
  el._clockRAF = requestAnimationFrame(frame);
}

function caretSegment(el) {
  var i = el.value.indexOf(':');
  return (i === -1 || el.selectionStart <= i) ? 0 : 1;
}

/** Highlight a segment; resets the typing buffer (fresh entry into the segment). */
function selectTimeSegment(el, seg) {
  el.dataset.seg = String(seg);
  el.dataset.buf = '';
  selectTimeRange(el, seg);
}

/** Highlight a segment without touching the typing buffer. */
function selectTimeRange(el, seg) {
  var i = el.value.indexOf(':');
  if (i === -1) { renderTime(el, timeSegs(el)[0] || '--', '--'); i = 2; }
  if (seg === 0) el.setSelectionRange(0, i);
  else el.setSelectionRange(i + 1, el.value.length);
}

function onTimeKeydown(el, e) {
  var seg = parseInt(el.dataset.seg || '0', 10);
  if (/^[0-9]$/.test(e.key)) {
    e.preventDefault();
    typeTimeDigit(el, seg, parseInt(e.key, 10));
  } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    e.preventDefault();
    stepTimeSegment(el, seg, e.key === 'ArrowUp' ? 1 : -1);
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault();
    selectTimeSegment(el, 0);
  } else if (e.key === 'ArrowRight' || e.key === ':') {
    e.preventDefault();
    selectTimeSegment(el, 1);
  } else if (e.key === 'Backspace' || e.key === 'Delete') {
    e.preventDefault();
    var parts = timeSegs(el);
    parts[seg] = '--';
    renderTime(el, parts[0], parts[1]);
    selectTimeSegment(el, seg);
  }
  // Tab / Enter and modifier combos fall through to default behaviour.
}

function typeTimeDigit(el, seg, d) {
  var parts = timeSegs(el);
  var buf = el.dataset.buf || '';
  if (seg === 0) {
    if (buf === '') {
      parts[0] = '0' + d;
      renderTime(el, parts[0], parts[1]);
      if (d >= 3) { selectTimeSegment(el, 1); }          // 3-9 can't lead a 2-digit hour
      else { el.dataset.buf = String(d); selectTimeRange(el, 0); }
    } else {
      var h = parseInt(buf, 10) * 10 + d;
      if (h <= 23) { parts[0] = pad2(h); renderTime(el, parts[0], parts[1]); selectTimeSegment(el, 1); }
      else {                                             // e.g. "2" then "5" -> hour 02, 5 starts minutes
        parts[0] = '0' + buf; renderTime(el, parts[0], parts[1]);
        selectTimeSegment(el, 1);
        typeTimeDigit(el, 1, d);
        return;
      }
    }
  } else {
    if (buf === '') {
      parts[1] = '0' + d;
      renderTime(el, parts[0], parts[1]);
      if (d >= 6) { selectTimeRange(el, 1); }            // 6-9 can't lead a 2-digit minute
      else { el.dataset.buf = String(d); selectTimeRange(el, 1); }
    } else {
      parts[1] = pad2(parseInt(buf, 10) * 10 + d);       // buf <= 5 -> always <= 59
      renderTime(el, parts[0], parts[1]);
      el.dataset.buf = '';
      selectTimeRange(el, 1);
    }
  }
  fireTimeInput(el);
}

function stepTimeSegment(el, seg, delta) {
  var parts = timeSegs(el);
  var h = parseInt(parts[0], 10) || 0;
  var m = parseInt(parts[1], 10) || 0;
  if (seg === 0) h = (h + delta + 24) % 24;
  else m = (m + delta + 60) % 60;
  renderTime(el, pad2(h), pad2(m));
  el.dataset.buf = '';
  selectTimeRange(el, seg);
  fireTimeInput(el);
}

/** Pad/clamp to a valid "HH:MM" (or empty) and notify listeners. */
function normalizeTimeInput(el) {
  var parts = timeSegs(el);
  var hd = parts[0].replace(/\D/g, '');
  var md = parts[1].replace(/\D/g, '');
  if (hd === '' && md === '') { el.value = ''; }
  else {
    var h = Math.min(23, parseInt(hd || '0', 10));
    var m = Math.min(59, parseInt(md || '0', 10));
    el.value = pad2(h) + ':' + pad2(m);
  }
  updateClockIcon(el);
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function fireTimeInput(el) {
  if (/^\d\d:\d\d$/.test(el.value)) el.dispatchEvent(new Event('input', { bubbles: true }));
}


/* ===========================================================================
 *  DATE PICKERS — Air Datepicker calendar, dd/mm/yyyy display, ISO value
 *
 *  Native <input type="date"> renders in the browser locale (US -> mm/dd/yyyy)
 *  and can't be forced to dd/mm/yyyy. Each date input is demoted to a hidden
 *  ISO (yyyy-mm-dd) carrier that keeps its name + id — so form submits and JS
 *  reads still see ISO — and a sibling text input gets the Air Datepicker
 *  calendar showing dd/mm/yyyy. JS writes go through setDateValue.
 *  (Air Datepicker defaults to Russian, hence the explicit English locale.)
 * =========================================================================*/

var ADP_EN_LOCALE = {
  days: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
  daysShort: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
  daysMin: ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'],
  months: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
  monthsShort: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
  today: 'Today', clear: 'Clear', dateFormat: 'dd/MM/yyyy', timeFormat: 'HH:mm', firstDay: 1
};

function dateFromIso(iso) {
  var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}
function isoFromDate(d) {
  return d ? d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2) : '';
}

/** Parse a typed dd/mm/yyyy (also d/m/yyyy, '.', '-' separators) to ISO, or ''. */
function isoFromDisplay(s) {
  var m = /^\s*(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{4})\s*$/.exec(s || '');
  if (!m) return '';
  var dd = parseInt(m[1], 10), mm = parseInt(m[2], 10), yy = parseInt(m[3], 10);
  var d = new Date(yy, mm - 1, dd);
  // Reject impossible dates (e.g. 31/02/2025 rolling over).
  if (d.getFullYear() !== yy || d.getMonth() !== mm - 1 || d.getDate() !== dd) return '';
  return isoFromDate(d);
}

function initDatePickers(root) {
  if (typeof AirDatepicker === 'undefined') return;
  (root || document).querySelectorAll('input[type="date"]').forEach(function (el) {
    if (el.dataset.adpInit) return;
    el.dataset.adpInit = '1';

    var iso = /^\d{4}-\d{2}-\d{2}$/.test(el.value) ? el.value : '';

    // Visible display input (dd/mm/yyyy); original becomes a hidden ISO carrier.
    var disp = document.createElement('input');
    disp.type = 'text';
    disp.className = el.className;
    disp.setAttribute('placeholder', 'dd/mm/yyyy');
    disp.setAttribute('inputmode', 'numeric');
    disp.setAttribute('autocomplete', 'off');
    if (el.getAttribute('style')) disp.setAttribute('style', el.getAttribute('style'));
    if (el.required) { disp.required = true; el.required = false; }
    el.type = 'hidden';
    el.value = iso;
    el.parentNode.insertBefore(disp, el.nextSibling);

    el._adp = new AirDatepicker(disp, {
      locale: ADP_EN_LOCALE,
      dateFormat: 'dd/MM/yyyy',
      autoClose: true,
      selectedDates: iso ? [dateFromIso(iso)] : [],
      onSelect: function (o) {
        var d = Array.isArray(o.date) ? o.date[0] : o.date;
        el.value = isoFromDate(d);
        el.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    el._adpDisplay = disp;

    // Air Datepicker's onSelect only fires for calendar clicks, so a *typed*
    // dd/mm/yyyy edit would never reach the hidden ISO carrier and the form
    // would submit the stale value. Sync typed input on change (fires on blur).
    disp.addEventListener('change', function () {
      var typed = disp.value.trim();
      if (typed === '') {
        if (el.value !== '') {
          el.value = '';
          el._adp.clear();
          el.dispatchEvent(new Event('change', { bubbles: true }));
        }
        return;
      }
      var iso2 = isoFromDisplay(typed);
      if (iso2) {
        if (iso2 !== el.value) {
          el.value = iso2;
          el._adp.selectDate(dateFromIso(iso2), { silent: true });
          el.dispatchEvent(new Event('change', { bubbles: true }));
        }
      } else if (el.value) {
        // Unparseable text — restore the display to the last valid value.
        el._adp.selectDate(dateFromIso(el.value), { silent: true });
      }
    });

    // Keep clicks inside the calendar (date select, month/year nav — which
    // re-render and detach nodes mid-click) from bubbling to Bootstrap's
    // dropdown "auto-close outside" handler, which would close a host popup
    // (e.g. the analytics period dropdown).
    if (el._adp.$datepicker) {
      el._adp.$datepicker.addEventListener('mousedown', function (e) { e.stopPropagation(); });
      el._adp.$datepicker.addEventListener('click', function (e) { e.stopPropagation(); });
    }
  });
}
window.initDatePickers = initDatePickers;

/** Set a date input's value (iso = "yyyy-mm-dd" or empty), updating the picker. */
function setDateValue(el, iso) {
  if (!el) return;
  el.value = iso || '';
  if (el._adp) {
    var d = dateFromIso(iso);
    if (d) el._adp.selectDate(d, { silent: true });
    else el._adp.clear();
  }
  el.dispatchEvent(new Event('change', { bubbles: true }));
}
window.setDateValue = setDateValue;

/**
 * Wire every [data-today-btn] to set its paired [data-effective-from] date input
 * to today's date. The input is located by walking up from the button, so the
 * two just need to share a wrapper (see _taxprofile_form_fields / termset_form).
 */
function initTodayButtons(root) {
  (root || document).querySelectorAll('[data-today-btn]').forEach(function (btn) {
    if (btn.dataset.todayBound) return;
    btn.dataset.todayBound = '1';
    btn.addEventListener('click', function () {
      var input = null, node = btn;
      while (node && !input) {
        input = node.querySelector('[data-effective-from]');
        node = node.parentElement;
      }
      if (!input) return;
      var iso = new Date().toLocaleDateString('sv');  // yyyy-mm-dd
      if (window.setDateValue) window.setDateValue(input, iso);
      else input.value = iso;
      input.dispatchEvent(new Event('input'));
    });
  });
}
window.initTodayButtons = initTodayButtons;


/* ===========================================================================
 *  DANISH NUMBER FORMAT
 * =========================================================================*/

/**
 * Convert a value (standard "15000.50" or Danish "15.000,50") -> display Danish "15.000,50".
 */
function toDanish(value) {
  var str = String(value).trim();
  if (!str) return '';

  var hasComma = str.indexOf(',') >= 0;
  var dots = (str.match(/\./g) || []).length;
  var num, decSource;

  if (hasComma) {
    // Danish input: dots = thousands, comma = decimal
    num = parseFloat(str.replace(/\./g, '').replace(',', '.'));
    decSource = str.split(',')[1] || '';
  } else if (dots === 1) {
    var afterDot = str.split('.')[1] || '';
    if (afterDot.length === 3 && /^\d{3}$/.test(afterDot)) {
      // Looks like a thousands separator (e.g. "1.500" = 1500)
      num = parseFloat(str.replace('.', ''));
      decSource = '';
    } else {
      // Standard decimal (e.g. "15000.50")
      num = parseFloat(str);
      decSource = afterDot;
    }
  } else if (dots > 1) {
    // Multiple dots are thousands separators
    num = parseFloat(str.replace(/\./g, ''));
    decSource = '';
  } else {
    num = parseFloat(str);
    decSource = '';
  }

  if (isNaN(num)) return str;

  var decPlaces = Math.min(decSource.length, 2);
  var fixed = decPlaces > 0 ? num.toFixed(decPlaces) : Math.round(num).toString();
  var parts = fixed.split('.');

  // Add thousands separator dots
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');

  if (parts.length > 1) {
    // Trim trailing zeros
    var dec = parts[1].replace(/0+$/, '');
    if (dec) return parts[0] + ',' + dec;
  }
  return parts[0];
}

/**
 * Convert Danish "15.000,50" -> standard "15000.50" for form submission.
 */
function toStandard(value) {
  var str = String(value).trim();
  if (!str) return '';
  return str.replace(/\./g, '').replace(',', '.');
}

/**
 * Parse a possibly-Danish-formatted string into a float. Returns NaN on failure.
 */
function parseDanish(value) {
  return parseFloat(toStandard(value)) || 0;
}

function initDanishNumbers() {
  document.querySelectorAll('.dk-number').forEach(function (input) {
    // Convert initial Django-rendered value to Danish display
    if (input.value) {
      input.value = toDanish(input.value);
    }

    input.addEventListener('focus', function () {
      // Remove thousands dots for easier editing (keep comma decimal)
      this.value = this.value.replace(/\./g, '');
    });

    input.addEventListener('blur', function () {
      if (!this.value.trim()) return;
      this.value = toDanish(this.value);
    });
  });

  // Before form submit: convert all dk-number fields to standard format
  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function () {
      this.querySelectorAll('.dk-number').forEach(function (input) {
        input.value = toStandard(input.value);
      });
    });
  });
}


/* ===========================================================================
 *  WORKPLACE FORM - conditional sections, calculations
 * =========================================================================*/

function initWorkplaceForm(formEl) {
  var empRadios = formEl.querySelectorAll('[data-emp-type]');
  var salariedSection = formEl.querySelector('[data-section="salaried"]');
  var hourlySection = formEl.querySelector('[data-section="hourly"]');

  // ---- Helpers to disable/enable all inputs in a section ----
  function disableSectionInputs(section) {
    if (!section) return;
    section.querySelectorAll('input, select, textarea').forEach(function (el) {
      el.disabled = true;
    });
  }
  function enableSectionInputs(section) {
    if (!section) return;
    section.querySelectorAll('input, select, textarea').forEach(function (el) {
      el.disabled = false;
    });
  }

  // ---- Employment type toggle ----
  function toggleEmploymentSections() {
    var checked = formEl.querySelector('[data-emp-type]:checked');
    var isSalaried = checked && checked.value === 'salaried';
    if (salariedSection) {
      salariedSection.style.display = isSalaried ? '' : 'none';
      if (isSalaried) enableSectionInputs(salariedSection); else disableSectionInputs(salariedSection);
    }
    if (hourlySection) {
      hourlySection.style.display = isSalaried ? 'none' : '';
      if (isSalaried) disableSectionInputs(hourlySection); else enableSectionInputs(hourlySection);
    }

    // Hidden payroll start: only included for salaried (value=1), hourly uses visible field
    var hiddenStart = formEl.querySelector('[data-hidden-payroll-start]');
    if (hiddenStart) hiddenStart.disabled = !isSalaried;
  }
  empRadios.forEach(function (r) { r.addEventListener('change', toggleEmploymentSections); });
  toggleEmploymentSections();

  // ---- Work time type toggle (salaried: full-time / part-time) ----
  var wttRadios = formEl.querySelectorAll('[data-wtt]');
  var partTimeSection = formEl.querySelector('[data-subsection="deltid-hours"]');

  function toggleWorkTime() {
    var checked = formEl.querySelector('[data-wtt]:checked');
    var isPartTime = checked && checked.value === 'deltid';
    if (partTimeSection) partTimeSection.style.display = isPartTime ? '' : 'none';
    calcHourlyRate();
  }
  wttRadios.forEach(function (r) { r.addEventListener('change', toggleWorkTime); });
  toggleWorkTime();

  // ---- Hours type toggle (hourly: fixed / variable) ----
  var htRadios = formEl.querySelectorAll('[data-ht]');
  var fixedSection = formEl.querySelector('[data-subsection="fixed-hours"]');
  var variableSection = formEl.querySelector('[data-subsection="variable-hours"]');

  function toggleHoursType() {
    var checked = formEl.querySelector('[data-ht]:checked');
    var isVariable = checked && checked.value === 'variable';
    if (fixedSection) fixedSection.style.display = isVariable ? 'none' : '';
    if (variableSection) variableSection.style.display = isVariable ? '' : 'none';
  }
  htRadios.forEach(function (r) { r.addEventListener('change', toggleHoursType); });
  toggleHoursType();

  // ---- Hourly rate calculation (salaried: base salary / monthly hours) ----
  var salaryInput = salariedSection ? salariedSection.querySelector('[data-calc-trigger="hourly-rate"]') : null;
  var partTimeHoursInput = partTimeSection ? partTimeSection.querySelector('.dk-number') : null;
  var rateDisplay = formEl.querySelector('[data-display="hourly-rate"]');

  function calcHourlyRate() {
    if (!rateDisplay) return;
    var salary = salaryInput ? parseDanish(salaryInput.value) : 0;
    var wttChecked = formEl.querySelector('[data-wtt]:checked');
    var wtt = wttChecked ? wttChecked.value : 'fuldtid';
    var monthlyHours;

    if (wtt === 'fuldtid') {
      monthlyHours = 160.33;
    } else {
      var weeklyHours = partTimeHoursInput ? parseDanish(partTimeHoursInput.value) : 0;
      monthlyHours = weeklyHours * 52 / 12;
    }

    if (salary && monthlyHours) {
      var rate = salary / monthlyHours;
      rateDisplay.textContent = toDanish(rate.toFixed(2)) + ' DKK/h';
    } else {
      rateDisplay.textContent = '\u2013';
    }
  }

  if (salaryInput) {
    salaryInput.addEventListener('input', calcHourlyRate);
    salaryInput.addEventListener('change', calcHourlyRate);
  }
  if (partTimeHoursInput) {
    partTimeHoursInput.addEventListener('input', calcHourlyRate);
    partTimeHoursInput.addEventListener('change', calcHourlyRate);
  }
  calcHourlyRate();

  // ---- Estimated gross pay calculation (hourly: rate * hours * 52/12) ----
  var grossPayDisplay = formEl.querySelector('[data-display="gross-pay"]');
  var grossPayGoalDisplay = formEl.querySelector('[data-display="gross-pay-goal"]');
  var hourlyRateInput = hourlySection ? hourlySection.querySelector('input[name$="hourly_rate"]') : null;
  var fixedHoursInput = formEl.querySelector('[data-subsection="fixed-hours"] .dk-number');
  var varMinInput = formEl.querySelector('[data-subsection="variable-hours"] input[name$="weekly_hours_min"]');
  var varMaxInput = formEl.querySelector('[data-subsection="variable-hours"] input[name$="weekly_hours_max"]');
  var goalMinInput = formEl.querySelector('input[name$="hour_goal_min"]');
  var goalMaxInput = formEl.querySelector('input[name$="hour_goal_max"]');

  function calcGrossPay() {
    if (!grossPayDisplay) return;
    var rate = hourlyRateInput ? parseDanish(hourlyRateInput.value) : 0;
    if (!rate) {
      grossPayDisplay.textContent = '\u2013';
      if (grossPayGoalDisplay) grossPayGoalDisplay.style.display = 'none';
      return;
    }

    var htChecked = formEl.querySelector('[data-ht]:checked');
    var isVariable = htChecked && htChecked.value === 'variable';
    var monthlyText = '';

    if (isVariable) {
      var minH = varMinInput ? parseDanish(varMinInput.value) : 0;
      var maxH = varMaxInput ? parseDanish(varMaxInput.value) : 0;
      if (minH && maxH) {
        var minPay = rate * minH * 52 / 12;
        var maxPay = rate * maxH * 52 / 12;
        monthlyText = toDanish(minPay.toFixed(0)) + ' \u2013 ' + toDanish(maxPay.toFixed(0)) + ' DKK/mo';
      } else if (minH) {
        monthlyText = '~' + toDanish((rate * minH * 52 / 12).toFixed(0)) + ' DKK/mo';
      }
    } else {
      var fixedH = fixedHoursInput ? parseDanish(fixedHoursInput.value) : 0;
      if (fixedH) {
        monthlyText = '~' + toDanish((rate * fixedH * 52 / 12).toFixed(0)) + ' DKK/mo';
      }
    }

    grossPayDisplay.textContent = monthlyText || '\u2013';

    // Hour goal-based estimate
    if (grossPayGoalDisplay) {
      var goalType = formEl.querySelector('input[name$="hour_goal_type"]:checked');
      var gMin = goalMinInput ? parseDanish(goalMinInput.value) : 0;
      var gMax = goalMaxInput ? parseDanish(goalMaxInput.value) : 0;
      if (goalType && gMin) {
        var multiplier = goalType.value === 'weekly' ? 52 / 12 : 1;
        var goalText = '';
        if (gMax) {
          var goalMinPay = rate * gMin * multiplier;
          var goalMaxPay = rate * gMax * multiplier;
          goalText = 'With hour goal: ' + toDanish(goalMinPay.toFixed(0)) + ' \u2013 ' + toDanish(goalMaxPay.toFixed(0)) + ' DKK/mo';
        } else {
          var goalPay = rate * gMin * multiplier;
          goalText = 'With hour goal: ~' + toDanish(goalPay.toFixed(0)) + ' DKK/mo';
        }
        grossPayGoalDisplay.textContent = goalText;
        grossPayGoalDisplay.style.display = '';
      } else {
        grossPayGoalDisplay.style.display = 'none';
      }
    }
  }

  [hourlyRateInput, fixedHoursInput, varMinInput, varMaxInput, goalMinInput, goalMaxInput].forEach(function(inp) {
    if (inp) {
      inp.addEventListener('input', calcGrossPay);
      inp.addEventListener('change', calcGrossPay);
    }
  });
  // Also recalculate when hours type or goal type changes
  htRadios.forEach(function(r) { r.addEventListener('change', calcGrossPay); });
  formEl.querySelectorAll('input[name$="hour_goal_type"]').forEach(function(r) {
    r.addEventListener('change', calcGrossPay);
  });
  formEl.querySelectorAll('input[name="goalMode"]').forEach(function(r) {
    r.addEventListener('change', calcGrossPay);
  });
  calcGrossPay();

  // ---- Pension total calculation ----
  var pensionEmployee = formEl.querySelector('[data-pension-field="employee"]');
  var pensionEmployer = formEl.querySelector('[data-pension-field="employer"]');
  var pensionTotal = formEl.querySelector('[data-display="pension-total"]');

  function calcPensionTotal() {
    if (!pensionTotal) return;
    var emp = pensionEmployee ? parseDanish(pensionEmployee.value) : 0;
    var er = pensionEmployer ? parseDanish(pensionEmployer.value) : 0;
    var total = emp + er;
    pensionTotal.textContent = toDanish(total.toFixed(2)) + ' %';
  }

  if (pensionEmployee) {
    pensionEmployee.addEventListener('input', calcPensionTotal);
    pensionEmployee.addEventListener('change', calcPensionTotal);
  }
  if (pensionEmployer) {
    pensionEmployer.addEventListener('input', calcPensionTotal);
    pensionEmployer.addEventListener('change', calcPensionTotal);
  }
  calcPensionTotal();

  // ---- Employment percentage calculation (hours per week / 37 * 100) ----
  var empPctInput = formEl.querySelector('[data-calc-trigger="employment-pct"]');
  var empPctDisplay = formEl.querySelector('[data-display="employment-pct"]');

  function calcEmploymentPct() {
    if (!empPctDisplay) return;
    var hours = empPctInput ? parseDanish(empPctInput.value) : 0;
    if (hours) {
      var percent = (hours / 37) * 100;
      empPctDisplay.textContent = toDanish(percent.toFixed(1)) + ' %';
    } else {
      empPctDisplay.textContent = '-';
    }
  }

  if (empPctInput) {
    empPctInput.addEventListener('input', calcEmploymentPct);
    empPctInput.addEventListener('change', calcEmploymentPct);
  }
  calcEmploymentPct();

  // ---- Holiday supplement toggle: show/hide percent input ----
  var holidaySupplToggle = formEl.querySelector('[data-ferietillaeg-toggle]');
  var holidaySupplFields = formEl.querySelector('[data-ferietillaeg-fields]');
  function toggleHolidaySuppl() {
    if (!holidaySupplToggle || !holidaySupplFields) return;
    holidaySupplFields.style.display = holidaySupplToggle.checked ? '' : 'none';
  }
  if (holidaySupplToggle) {
    holidaySupplToggle.addEventListener('change', toggleHolidaySuppl);
    toggleHolidaySuppl();
  }

  // ---- Holiday supplement payout month pill buttons ----
  var payoutHidden = formEl.querySelector('[data-ft-payout-hidden]');
  var monthBtns = formEl.querySelectorAll('[data-ft-month]');
  function syncPayoutMonths() {
    var selected = [];
    monthBtns.forEach(function(btn) {
      if (btn.dataset.ftSelected === '1') {
        selected.push(btn.dataset.ftMonth);
        btn.classList.remove('btn-outline-secondary');
        btn.classList.add('btn-primary');
      } else {
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-outline-secondary');
      }
    });
    if (payoutHidden) payoutHidden.value = selected.join(',');
  }
  // Initialise selected state from hidden field
  if (payoutHidden && payoutHidden.value) {
    var initMonths = payoutHidden.value.split(',');
    monthBtns.forEach(function(btn) {
      if (initMonths.indexOf(btn.dataset.ftMonth) !== -1) {
        btn.dataset.ftSelected = '1';
      }
    });
    syncPayoutMonths();
  }
  monthBtns.forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      btn.dataset.ftSelected = btn.dataset.ftSelected === '1' ? '0' : '1';
      syncPayoutMonths();
    });
  });

  // ---- Flex account toggle: show/hide percent input ----
  var flexAcctToggle = formEl.querySelector('[data-fritvalgskonto-toggle]');
  var flexAcctFields = formEl.querySelector('[data-fritvalgskonto-fields]');
  function toggleFlexAcct() {
    if (!flexAcctToggle || !flexAcctFields) return;
    flexAcctFields.style.display = flexAcctToggle.checked ? '' : 'none';
  }
  if (flexAcctToggle) {
    flexAcctToggle.addEventListener('change', toggleFlexAcct);
    toggleFlexAcct();
  }

  // ---- Vacation type: show/hide feriekonto note ----
  var vacationSelect = formEl.querySelector('select[name$="vacation_type"]');
  var holidayAcctNote = formEl.querySelector('[data-vacation-note="feriekonto"]');
  var accruedNote = formEl.querySelector('[data-vacation-note="accrued"]');
  function toggleVacationNotes() {
    if (!vacationSelect) return;
    var isHolidayAcct = vacationSelect.value === 'feriekonto';
    if (holidayAcctNote) holidayAcctNote.style.display = isHolidayAcct ? '' : 'none';
    if (accruedNote) accruedNote.style.display = isHolidayAcct ? 'none' : '';
  }
  if (vacationSelect) {
    vacationSelect.addEventListener('change', toggleVacationNotes);
    toggleVacationNotes();
  }

  // ---- Tax card: dynamic description based on live inputs or DB profile ----
  var taxCardSelect = formEl.querySelector('[data-tax-card-select]');
  var taxCardDesc = formEl.querySelector('[data-tax-card-desc]');

  // Find tax-profile inputs on the page (setup wizard uses "tax-" prefix, standalone uses no prefix)
  var deductionInput = document.querySelector('input[name="tax-monthly_deduction"]')
                    || document.querySelector('input[name="monthly_deduction"]');
  var taxPctInput = document.querySelector('input[name="tax-tax_percent"]')
                 || document.querySelector('input[name="tax_percent"]');
  var churchPctInput = document.querySelector('input[name="tax-church_tax_percent"]')
                    || document.querySelector('input[name="church_tax_percent"]');

  function parseDkNum(v) {
    if (!v) return null;
    var n = parseFloat(String(v).replace(/\./g, '').replace(',', '.'));
    return isNaN(n) ? null : n;
  }

  function getTaxValues() {
    // First try live input fields on the page
    if (deductionInput && taxPctInput) {
      var ded = parseDkNum(deductionInput.value);
      var tp = parseDkNum(taxPctInput.value);
      var cp = churchPctInput ? (parseDkNum(churchPctInput.value) || 0) : 0;
      if (ded !== null && tp !== null) {
        return { deduction: ded, percent: tp + cp };
      }
    }
    // Fall back to data attribute (from DB, for standalone workplace form)
    if (formEl.dataset.taxProfile) {
      var d = JSON.parse(formEl.dataset.taxProfile);
      return { deduction: parseFloat(d.deduction), percent: parseFloat(d.percent) };
    }
    return null;
  }

  function updateTaxCardDesc() {
    if (!taxCardSelect || !taxCardDesc) return;
    var vals = getTaxValues();
    var deduction = vals ? vals.deduction : null;
    var pct = vals ? vals.percent : null;
    if (taxCardSelect.value === 'hovedkort') {
      if (deduction !== null && pct !== null) {
        taxCardDesc.textContent = 'Income is taxed with 0% A-skat for the first ' + toDanish(deduction) + ' DKK, and the rest is taxed with ' + toDanish(pct) + '%.';
      } else {
        taxCardDesc.textContent = 'Primary tax card - monthly deduction (fradrag) is applied.';
      }
    } else {
      if (pct !== null) {
        taxCardDesc.textContent = 'Income is taxed with ' + toDanish(pct) + '% A-skat with no tax deduction used.';
      } else {
        taxCardDesc.textContent = 'Secondary tax card - no deduction applied.';
      }
    }
  }
  if (taxCardSelect) {
    taxCardSelect.addEventListener('change', updateTaxCardDesc);
    updateTaxCardDesc();
  }
  // Also update when tax profile inputs change (live on the same page)
  [deductionInput, taxPctInput, churchPctInput].forEach(function(inp) {
    if (inp) inp.addEventListener('input', updateTaxCardDesc);
  });

  // ---- Payroll period: dynamic period description ----
  var payrollStartInput = formEl.querySelector('[data-payroll-start]');
  var payrollPeriodMsg = formEl.querySelector('[data-payroll-period-msg]');
  function updatePayrollPeriodMsg() {
    if (!payrollStartInput || !payrollPeriodMsg) return;
    var startDay = parseInt(payrollStartInput.value) || 1;
    if (startDay < 1) startDay = 1;
    if (startDay > 31) startDay = 31;
    function ordinal(n) {
      var s = ['th','st','nd','rd'];
      var v = n % 100;
      return n + (s[(v-20)%10] || s[v] || s[0]);
    }
    if (startDay === 1) {
      payrollPeriodMsg.textContent = 'The payroll period runs from the 1st to the end of the month.';
    } else {
      var endDay = startDay - 1;
      payrollPeriodMsg.textContent = 'The payroll period runs from the ' + ordinal(startDay) + ' to the ' + ordinal(endDay) + '.';
    }
  }
  if (payrollStartInput) {
    payrollStartInput.addEventListener('input', updatePayrollPeriodMsg);
    payrollStartInput.addEventListener('change', updatePayrollPeriodMsg);
    updatePayrollPeriodMsg();
  }

  // ---- Icon picker (kept for backward compat - now mainly in customize modal) ----
  var iconPicker = formEl.querySelector('[data-icon-picker]');
  var iconInput = formEl.querySelector('[data-icon-input]');
  if (iconPicker && iconInput) {
    iconPicker.querySelectorAll('[data-icon-option]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        iconInput.value = btn.dataset.iconOption;
        iconPicker.querySelectorAll('[data-icon-option]').forEach(function(b) {
          b.className = b.className.replace('btn-primary', 'btn-outline-secondary');
        });
        btn.className = btn.className.replace('btn-outline-secondary', 'btn-primary');
      });
    });
  }
}


/* ===========================================================================
 *  TAX PROFILE FORM - folkekirken toggle helper
 * =========================================================================*/

function findToggleTarget(trigger, name) {
  // Search for the matching target within the same form container
  var container = trigger.closest('[data-form]') || trigger.closest('form') || document;
  return container.querySelector('[data-toggle-target="' + name + '"]');
}


/* ===========================================================================
 *  CALENDAR MODAL - auto-open (no-op; logic is in page-specific script)
 * =========================================================================*/

function initCalendarModal() {
  // Calendar modal initialization is handled by inline <script> in workplace_detail.html
}


/* ===========================================================================
 *  Shift MODAL - AJAX create (no-op; logic is in page-specific script)
 * =========================================================================*/

function initShiftModal() {
  // Shift modal initialization is handled by inline <script> in workplace_detail.html
}


/* ===========================================================================
 *  Shift FORM - live hour/minute calculation
 * =========================================================================*/

function initShiftCalc() {
  var display = document.getElementById('Shift-total');
  if (!display) return;

  function calc() {
    var startEl = document.getElementById('id_start_time');
    var endEl = document.getElementById('id_end_time');
    var breakEl = document.getElementById('id_break_minutes');

    if (!startEl || !endEl) { display.textContent = '\u2013'; return; }

    var start = startEl.value;
    var end = endEl.value;
    if (!start || !end) { display.textContent = '\u2013'; return; }

    var sh = start.split(':').map(Number);
    var eh = end.split(':').map(Number);
    var totalMin = (eh[0] * 60 + eh[1]) - (sh[0] * 60 + sh[1]);
    totalMin -= parseInt(breakEl ? breakEl.value : 0) || 0;

    if (totalMin <= 0) { display.textContent = '\u2013'; return; }

    var hours = Math.floor(totalMin / 60);
    var mins = totalMin % 60;
    var dec = (totalMin / 60).toFixed(2);
    display.textContent = hours + 'h ' + mins + 'm (' + toDanish(dec) + 'h)';
  }

  ['id_start_time', 'id_end_time', 'id_break_minutes'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', calc);
      el.addEventListener('change', calc);
    }
  });
  calc();
}


/* ===========================================================================
 *  PAYSLIP DRAG & DROP (unchanged)
 * =========================================================================*/


function initPayslipDragDrop(table) {
    const tbody = table.querySelector('tbody');
    if (!tbody) return;

    let dragEl = null;

    tbody.querySelectorAll('tr').forEach(function(row) {
        row.draggable = true;

        row.addEventListener('dragstart', function() {
            dragEl = row;
            row.classList.add('table-active');
        });

        row.addEventListener('dragend', function() {
            if (dragEl) dragEl.classList.remove('table-active');
            dragEl = null;
        });

        row.addEventListener('dragover', function(e) {
            e.preventDefault();
        });

        row.addEventListener('drop', function(e) {
            e.preventDefault();
            if (dragEl && dragEl !== row) {
                const rect = row.getBoundingClientRect();
                const midY = rect.top + rect.height / 2;
                if (e.clientY < midY) {
                    tbody.insertBefore(dragEl, row);
                } else {
                    tbody.insertBefore(dragEl, row.nextSibling);
                }
                savePayslipOrder(tbody);
            }
        });
    });
}


function savePayslipOrder(tbody) {
    const rows = tbody.querySelectorAll('tr');
    const order = [];
    rows.forEach(function(row) {
        const id = row.dataset.id;
        if (id) order.push(id);
    });

    // Get period PK from the URL or a data attribute
    const reorderUrl = tbody.closest('table').dataset.reorderUrl;
    if (reorderUrl) {
        fetch(reorderUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ order: order }),
        });
    }
}


function getCsrfToken() {
    const cookie = document.cookie.split(';')
        .find(c => c.trim().startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
}

