/* Approve-shifts page: select-all toggle + pencil-edit modal that fetches and
   saves a planned shift via the update API. The API URL template (with a pk=0
   placeholder) is read from #editShiftModal's data-update-url-template.
   Relies on getCsrfToken() from app.js. */
(function() {
  // Select All
  document.getElementById('selectAll').addEventListener('change', function() {
    document.querySelectorAll('.shift-check').forEach(function(cb) {
      cb.checked = document.getElementById('selectAll').checked;
    });
  });

  var CSRF = getCsrfToken();
  var modalEl = document.getElementById('editShiftModal');
  var editModal = new bootstrap.Modal(modalEl);
  var UPDATE_URL_TEMPLATE = modalEl.dataset.updateUrlTemplate;

  // Live "Total working time" display, recomputed as start/end/break change.
  var totalEl = document.getElementById('editTotal');
  function calcTotal() {
    if (!totalEl) return;
    var start = document.getElementById('editStart').value;
    var end = document.getElementById('editEnd').value;
    if (!start || !end) { totalEl.textContent = '–'; return; }
    var sh = start.split(':').map(Number);
    var eh = end.split(':').map(Number);
    var totalMin = (eh[0] * 60 + eh[1]) - (sh[0] * 60 + sh[1]);
    totalMin -= parseInt(document.getElementById('editBreak').value, 10) || 0;
    if (totalMin <= 0) { totalEl.textContent = '–'; return; }
    var hours = Math.floor(totalMin / 60);
    var mins = totalMin % 60;
    totalEl.textContent = hours + 'h ' + mins + 'm (' + toDanish((totalMin / 60).toFixed(2)) + 'h)';
  }
  ['editStart', 'editEnd', 'editBreak'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) { el.addEventListener('input', calcTotal); el.addEventListener('change', calcTotal); }
  });

  // Pencil edit buttons
  document.querySelectorAll('.edit-shift-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      var shiftId = parseInt(btn.dataset.shiftId);
      var url = UPDATE_URL_TEMPLATE.replace('/0/', '/' + shiftId + '/');

      // Fetch current shift data
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
        body: JSON.stringify({}),
      }).then(function(r) { return r.json(); }).then(function(data) {
        if (!data.ok) return;
        var s = data.shift;
        document.getElementById('editShiftId').value = s.id;
        window.setDateValue(document.getElementById('editDate'), s.date);
        window.setTimeValue(document.getElementById('editStart'), s.start_time);
        window.setTimeValue(document.getElementById('editEnd'), s.end_time);
        document.getElementById('editBreak').value = s.break_minutes;
        document.getElementById('editType').value = s.shift_type;
        document.getElementById('editNotes').value = s.notes;
        document.getElementById('editErrors').classList.add('d-none');
        calcTotal();
        editModal.show();
      });
    });
  });

  // Save edits
  document.getElementById('editSaveBtn').addEventListener('click', function() {
    var shiftId = document.getElementById('editShiftId').value;
    if (!shiftId) return;
    var url = UPDATE_URL_TEMPLATE.replace('/0/', '/' + shiftId + '/');
    var body = {
      date: document.getElementById('editDate').value,
      start_time: document.getElementById('editStart').value,
      end_time: document.getElementById('editEnd').value,
      break_minutes: parseInt(document.getElementById('editBreak').value) || 0,
      shift_type: document.getElementById('editType').value,
      notes: document.getElementById('editNotes').value,
    };

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify(body),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) {
        document.getElementById('editErrors').textContent = data.error || 'Error saving.';
        document.getElementById('editErrors').classList.remove('d-none');
        return;
      }
      // Update the table row in-place
      var s = data.shift;
      var row = document.querySelector('tr[data-shift-id="' + s.id + '"]');
      if (row) {
        var dateObj = new Date(s.date + 'T00:00:00');
        var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
        var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        row.querySelector('[data-field="date"]').textContent = days[dateObj.getDay()] + ', ' + months[dateObj.getMonth()] + ' ' + String(dateObj.getDate()).padStart(2,'0');
        row.querySelector('[data-field="time"]').textContent = s.start_time + ' . ' + s.end_time;
        row.querySelector('[data-field="hours"]').textContent = s.net_hours.replace('.',',') + 'h';
        var breakEl = row.querySelector('[data-field="break"]');
        if (breakEl) {
          breakEl.textContent = s.break_minutes ? '(' + s.break_minutes + 'min break)' : '';
        }
        row.querySelector('[data-field="type"]').textContent = s.shift_type_display;
        row.querySelector('[data-field="notes"]').textContent = s.notes ? s.notes.substring(0, 40) : '';
      }
      editModal.hide();
    });
  });
})();
