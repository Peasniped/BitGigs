/* Approve-shifts page: select-all toggle + the shared pencil-edit modal
   (see edit_shift_modal.js), whose saved shift is written back into the table. */
(function() {
  // Select All
  document.getElementById('selectAll').addEventListener('change', function() {
    document.querySelectorAll('.shift-check').forEach(function(cb) {
      cb.checked = document.getElementById('selectAll').checked;
    });
  });

  var editShift = initEditShiftModal({
    onSaved: function(s) {
      // Update the table row in-place
      var row = document.querySelector('tr[data-shift-id="' + s.id + '"]');
      if (!row) return;
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
    },
    onDeleted: function(shiftId) {
      var row = document.querySelector('tr[data-shift-id="' + shiftId + '"]');
      if (row) row.remove();
      // With the last shift gone the page has nothing left to approve.
      if (!document.querySelector('tr[data-shift-id]')) window.location.reload();
    },
  });

  // Pencil edit buttons
  document.querySelectorAll('.edit-shift-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      editShift.open(parseInt(btn.dataset.shiftId));
    });
  });
})();
