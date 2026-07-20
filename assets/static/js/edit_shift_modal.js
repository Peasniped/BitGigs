/* Drives the shared shift modal (assets/templates/_edit_shift_modal.html) for the
   approve flows — the dashboard (Review & Approve + the arrival banner), the
   workplace page and the Approve Shifts page. (The planning calendar drives the
   same markup itself, in planning.js.)

   Loads a planned shift from the update API, validates end > start as it is typed,
   and saves or deletes it. Relies on getCsrfToken() / toDanish() from app.js.

   initEditShiftModal(opts) -> { open: function(shiftId, opts) {}, el, modal }
   (null if the modal isn't on the page). One instance per page — a page with
   several flows passes its per-flow callbacks to open() instead of init().

   opts (all optional, and overridable per open()):
     onSaved: function(shift) {},     // shift as returned by the API
     onDeleted: function(shiftId) {},
     present: function(show) {},      // how to bring the modal up — the approve
                                      // modals hide themselves first, since
                                      // Bootstrap can't stack modals
     prefill: { start_time: "HH:MM", … },  // applied over the loaded shift, e.g. the
                                           // arrival time carried into the modal
     saveWith: { arrival_confirmed: true },  // extra fields sent with the save — the
                                             // arrival hand-off confirms the arrival,
                                             // or the banner would keep asking
     backdrop: true,                  // false = the caller supplies the backdrop
                                      // (init only — it is a Bootstrap config)
     onHidden: function() {} */
/* One approve-table row's inner HTML — shared by the dashboard's Review &
   Approve modal (dashboard.js) and the workplace page's approve modal
   (workplace_detail.js), which used to keep identical copies of this markup.
   Element IDs/classes are part of the contract with those scripts.

   o: { selectable: bool,        // render the leading checkbox cell
        cbClass: 'approve-cb',   // checkbox class the caller listens on
        cbAttrs: '',             // extra checkbox attributes (e.g. data-wp="3")
        editBtnClass: 'edit-approve-btn' } */
window.buildApproveRowHtml = function (s, o) {
  function typeOption(value, label) {
    return '<option value="' + value + '"' + (s.shift_type === value ? ' selected' : '') + '>' + label + '</option>';
  }
  return (
    (o.selectable ?
    '<td class="select-cell"><input type="checkbox" class="form-check-input ' + o.cbClass + '" value="' + s.id + '"' +
      (o.cbAttrs ? ' ' + o.cbAttrs : '') + '></td>' : '') +
    '<td class="small" data-field="date">' + s.date + '</td>' +
    '<td><input type="time" class="form-control form-control-sm py-0" value="' + s.start_time + '" data-field="start_time" data-id="' + s.id + '" style="width:5.5rem;"></td>' +
    '<td><input type="time" class="form-control form-control-sm py-0" value="' + s.end_time + '" data-field="end_time" data-id="' + s.id + '" style="width:5.5rem;"></td>' +
    '<td><div class="input-group input-group-sm" style="width:5rem;">' +
      '<input type="number" class="form-control form-control-sm py-0" min="0" step="5" value="' + (s.break_minutes || 0) + '" data-field="break_minutes" data-id="' + s.id + '" title="Break (minutes)">' +
      '<span class="input-group-text px-1 small text-muted">m</span>' +
    '</div></td>' +
    '<td><select class="form-select form-select-sm py-0" data-field="shift_type" data-id="' + s.id + '" style="width:7rem;">' +
      typeOption('on_site', 'On-site') +
      typeOption('remote', 'Remote') +
      typeOption('sick_leave', 'Sick leave') +
      typeOption('paid_absence', 'Paid absence') +
      typeOption('vacation', 'Vacation') +
    '</select></td>' +
    '<td class="small text-end" data-field="hours">' + toDanish(s.net_hours) + 'h</td>' +
    '<td class="text-center"><button type="button" class="btn btn-sm btn-outline-primary py-0 px-1 ' + o.editBtnClass + '" data-shift-id="' + s.id + '" title="Edit shift"><i class="bi bi-pencil" style="font-size:0.65rem;"></i></button></td>'
  );
};

function initEditShiftModal(opts) {
  var el = document.getElementById('shiftModal');
  if (!el) return null;

  opts = opts || {};
  var active = opts;   // opts for the opening currently on screen
  // backdrop:false lets a caller supply its own (the dashboard keeps one backdrop
  // up across the whole approve session, so the dimming never flickers).
  var modal = bootstrap.Modal.getOrCreateInstance(el, opts.backdrop === false ? { backdrop: false } : {});
  var URL_TEMPLATE = el.dataset.updateUrlTemplate;
  var TIME_ORDER_MSG = 'End time must be after start time.';

  var form = document.getElementById('shiftForm');
  var idEl = document.getElementById('shiftId');
  var dateEl = document.getElementById('shiftDate');
  var startEl = document.getElementById('shiftStart');
  var endEl = document.getElementById('shiftEnd');
  var breakEl = document.getElementById('shiftBreak');
  var typeEl = document.getElementById('shiftType');
  var notesEl = document.getElementById('shiftNotes');
  var durationEl = document.getElementById('shiftDuration');
  var grossRow = document.getElementById('shiftDurationGrossRow');
  var grossLabel = document.getElementById('shiftDurationGrossLabel');
  var grossEl = document.getElementById('shiftDurationGross');
  var errorsEl = document.getElementById('shiftModalErrors');
  var deleteBtn = document.getElementById('shiftDeleteBtn');
  var saveBtn = form.querySelector('button[type="submit"]');

  function urlFor(shiftId) { return URL_TEMPLATE.replace('/0/', '/' + shiftId + '/'); }

  function showError(msg) {
    errorsEl.textContent = msg;
    errorsEl.classList.remove('d-none');
  }

  function renderBanner(s) {
    var avatar = document.getElementById('shiftModalAvatar');
    avatar.style.background = s.workplace_color || 'var(--primary)';
    if (s.workplace_custom_icon_url) {
      avatar.innerHTML = '<img src="' + escapeHtml(s.workplace_custom_icon_url) + '" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">';
    } else if (s.workplace_icon) {
      avatar.innerHTML = '<i class="bi ' + escapeHtml(s.workplace_icon) + '" style="font-size:0.7rem;"></i>';
    } else {
      avatar.textContent = s.workplace_initials || '';
    }
    document.getElementById('shiftModalWorkplace').textContent = s.workplace_name;
  }

  /* End at or before start is rejected by the server, so flag it while typing
     rather than only on save. */
  function validateTimes() {
    var start = startEl.value, end = endEl.value;
    var bad = false;
    if (start && end) {
      var sp = start.split(':').map(Number), ep = end.split(':').map(Number);
      bad = (ep[0] * 60 + ep[1]) <= (sp[0] * 60 + sp[1]);
    }
    startEl.classList.toggle('is-invalid', bad);
    endEl.classList.toggle('is-invalid', bad);
    saveBtn.disabled = bad;
    if (bad) showError(TIME_ORDER_MSG);
    else if (errorsEl.textContent === TIME_ORDER_MSG) errorsEl.classList.add('d-none');
    return !bad;
  }

  function fmtSpan(min) {
    return Math.floor(min / 60) + 'h ' + (min % 60) + 'm (' + toDanish((min / 60).toFixed(2)) + 'h)';
  }

  function calcDuration() {
    var ok = validateTimes();
    var start = startEl.value, end = endEl.value;
    var brk = parseInt(breakEl.value, 10) || 0;
    grossRow.classList.add('d-none');
    if (!ok || !start || !end) { durationEl.textContent = '–'; return; }
    var sp = start.split(':').map(Number), ep = end.split(':').map(Number);
    var grossMin = (ep[0] * 60 + ep[1]) - (sp[0] * 60 + sp[1]);
    var netMin = grossMin - brk;
    if (netMin <= 0) { durationEl.textContent = '–'; return; }
    durationEl.textContent = fmtSpan(netMin);
    // Only worth a line of its own when a break actually splits the two.
    if (brk > 0) {
      grossLabel.textContent = 'Before ' + brk + ' min break';
      grossEl.textContent = fmtSpan(grossMin);
      grossRow.classList.remove('d-none');
    }
  }

  [startEl, endEl, breakEl].forEach(function(f) {
    f.addEventListener('input', calcDuration);
    f.addEventListener('change', calcDuration);
  });

  el.addEventListener('hidden.bs.modal', function() {
    if (active.onHidden) active.onHidden();
  });
  // Opened on an impossible span (the arrival hand-off does exactly that): put the
  // cursor where the fix has to be made.
  el.addEventListener('shown.bs.modal', function() {
    if (endEl.classList.contains('is-invalid')) endEl.focus();
  });

  function open(shiftId, openOpts) {
    active = openOpts ? Object.assign({}, opts, openOpts) : opts;
    fetch(urlFor(shiftId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({}),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) return;
      var s = Object.assign({}, data.shift, active.prefill || {});
      idEl.value = s.id;
      renderBanner(s);
      window.setDateValue(dateEl, s.date);
      window.setTimeValue(startEl, s.start_time);
      window.setTimeValue(endEl, s.end_time);
      breakEl.value = s.break_minutes;
      typeEl.value = s.shift_type;
      notesEl.value = s.notes;
      errorsEl.classList.add('d-none');
      deleteBtn.classList.remove('d-none');
      calcDuration();
      if (active.present) active.present(function() { modal.show(); });
      else modal.show();
    });
  }

  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var shiftId = idEl.value;
    if (!shiftId || !validateTimes()) return;
    var payload = Object.assign({
      date: dateEl.value,
      start_time: startEl.value,
      end_time: endEl.value,
      break_minutes: parseInt(breakEl.value, 10) || 0,
      shift_type: typeEl.value,
      notes: notesEl.value,
    }, active.saveWith || {});
    fetch(urlFor(shiftId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) { showError(data.error || 'Error saving.'); return; }
      if (active.onSaved) active.onSaved(data.shift);
      modal.hide();
    });
  });

  deleteBtn.addEventListener('click', function() {
    var shiftId = idEl.value;
    if (!shiftId || !confirm('Delete this planned shift?')) return;
    fetch(urlFor(shiftId), {
      method: 'DELETE',
      headers: { 'X-CSRFToken': getCsrfToken() },
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) { showError('Error deleting.'); return; }
      if (active.onDeleted) active.onDeleted(parseInt(shiftId, 10));
      modal.hide();
    });
  });

  return { open: open, el: el, modal: modal };
}
window.initEditShiftModal = initEditShiftModal;
