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

  // ----- Session form: live hour calculation -----
  initSessionCalc();

  // ----- Work session modal (AJAX) -----
  initSessionModal();
});


/* ===========================================================================
 *  DANISH NUMBER FORMAT
 * =========================================================================*/

/**
 * Convert a value (standard "15000.50" or Danish "15.000,50") → display Danish "15.000,50".
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
 * Convert Danish "15.000,50" → standard "15000.50" for form submission.
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
 *  WORKPLACE FORM — conditional sections, calculations
 * =========================================================================*/

function initWorkplaceForm(formEl) {
  var empRadios = formEl.querySelectorAll('[data-emp-type]');
  var salariedSection = formEl.querySelector('[data-section="salaried"]');
  var hourlySection = formEl.querySelector('[data-section="hourly"]');

  // ---- Employment type toggle ----
  function toggleEmploymentSections() {
    var checked = formEl.querySelector('[data-emp-type]:checked');
    var isSalaried = checked && checked.value === 'salaried';
    if (salariedSection) salariedSection.style.display = isSalaried ? '' : 'none';
    if (hourlySection) hourlySection.style.display = isSalaried ? 'none' : '';

    // Hidden payroll start: only included for salaried (value=1), hourly uses visible field
    var hiddenStart = formEl.querySelector('[data-hidden-payroll-start]');
    if (hiddenStart) hiddenStart.disabled = !isSalaried;

    // Disable the visible payroll start if salaried
    var visibleStart = hourlySection ? hourlySection.querySelector('input[type="number"]') : null;
    if (visibleStart) visibleStart.disabled = isSalaried;
  }
  empRadios.forEach(function (r) { r.addEventListener('change', toggleEmploymentSections); });
  toggleEmploymentSections();

  // ---- Work time type toggle (salaried: fuldtid / deltid) ----
  var wttRadios = formEl.querySelectorAll('[data-wtt]');
  var deltidSection = formEl.querySelector('[data-subsection="deltid-hours"]');

  function toggleWorkTime() {
    var checked = formEl.querySelector('[data-wtt]:checked');
    var isDeltid = checked && checked.value === 'deltid';
    if (deltidSection) deltidSection.style.display = isDeltid ? '' : 'none';
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

  // ---- Hourly rate calculation (salaried: grundløn / monthly hours) ----
  var salaryInput = salariedSection ? salariedSection.querySelector('[data-calc-trigger="hourly-rate"]') : null;
  var deltidHoursInput = deltidSection ? deltidSection.querySelector('.dk-number') : null;
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
      var weeklyHours = deltidHoursInput ? parseDanish(deltidHoursInput.value) : 0;
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
  if (deltidHoursInput) {
    deltidHoursInput.addEventListener('input', calcHourlyRate);
    deltidHoursInput.addEventListener('change', calcHourlyRate);
  }
  calcHourlyRate();

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

  // ---- Ferietillæg toggle: show/hide percent input ----
  var ferietillaegToggle = formEl.querySelector('[data-ferietillaeg-toggle]');
  var ferietillaegFields = formEl.querySelector('[data-ferietillaeg-fields]');
  function toggleFerietillaeg() {
    if (!ferietillaegToggle || !ferietillaegFields) return;
    ferietillaegFields.style.display = ferietillaegToggle.checked ? '' : 'none';
  }
  if (ferietillaegToggle) {
    ferietillaegToggle.addEventListener('change', toggleFerietillaeg);
    toggleFerietillaeg();
  }

  // ---- Vacation type: show/hide feriekonto note ----
  var vacationSelect = formEl.querySelector('select[name$="vacation_type"]');
  var feriekontoNote = formEl.querySelector('[data-vacation-note="feriekonto"]');
  var accruedNote = formEl.querySelector('[data-vacation-note="accrued"]');
  function toggleVacationNotes() {
    if (!vacationSelect) return;
    var isFerie = vacationSelect.value === 'feriekonto';
    if (feriekontoNote) feriekontoNote.style.display = isFerie ? '' : 'none';
    if (accruedNote) accruedNote.style.display = isFerie ? 'none' : '';
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
        taxCardDesc.textContent = 'Primary tax card — monthly deduction (fradrag) is applied.';
      }
    } else {
      if (pct !== null) {
        taxCardDesc.textContent = 'Income is taxed with ' + toDanish(pct) + '% A-skat with no tax deduction used.';
      } else {
        taxCardDesc.textContent = 'Secondary tax card — no deduction applied.';
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

  // ---- Icon picker (kept for backward compat — now mainly in customize modal) ----
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
 *  TAX PROFILE FORM — folkekirken toggle helper
 * =========================================================================*/

function findToggleTarget(trigger, name) {
  // Search for the matching target within the same form container
  var container = trigger.closest('[data-form]') || trigger.closest('form') || document;
  return container.querySelector('[data-toggle-target="' + name + '"]');
}


/* ===========================================================================
 *  CALENDAR MODAL — auto-open (no-op; logic is in page-specific script)
 * =========================================================================*/

function initCalendarModal() {
  // Calendar modal initialization is handled by inline <script> in workplace_detail.html
}


/* ===========================================================================
 *  SESSION MODAL — AJAX create (no-op; logic is in page-specific script)
 * =========================================================================*/

function initSessionModal() {
  // Session modal initialization is handled by inline <script> in workplace_detail.html
}


/* ===========================================================================
 *  SESSION FORM — live hour/minute calculation
 * =========================================================================*/

function initSessionCalc() {
  var display = document.getElementById('session-total');
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
    display.textContent = hours + 'h ' + mins + 'm (' + dec + 'h)';
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
