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
});


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

