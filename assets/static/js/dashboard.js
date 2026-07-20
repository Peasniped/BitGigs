/* Main dashboard client logic: goal-bar tooltip, today's-shift arrival-time
   queue, live shift countdown, and the bulk-approve modal. Endpoint URLs and
   the banner "multiple shifts" flag come from #dashboardConfig data-* attrs;
   shift data come from json_script blobs. Each section guards on its own DOM
   anchor so it no-ops when the server didn't render that part. Uses
   getCsrfToken() and toDanish() from app.js. */
(function () {
  var CFG = document.getElementById('dashboardConfig');
  var cfg = CFG ? CFG.dataset : {};

// ═══════ Shared shift modal + backdrop ═══════
// One instance of the shared edit-shift modal for the whole page (the approve
// modal's pencil buttons and the arrival banner both open it, passing their own
// callbacks to open()). It runs backdrop-less, as does the approve modal, and the
// dashboard keeps a single backdrop up while either is open — Bootstrap would
// otherwise tear its own down with each modal, flashing the undimmed page every
// time the approve modal steps aside for the edit modal.
var editShift = initEditShiftModal({ backdrop: false });
var backdrop = null;
var openModals = 0;

function raiseBackdrop() {
  if (backdrop) return;
  backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop fade';
  document.body.appendChild(backdrop);
  backdrop.offsetHeight;                                    // reflow, so the fade runs
  backdrop.classList.add('show');
  backdrop.addEventListener('click', function() {           // click-outside to close
    var top = document.querySelector('.modal.show');
    if (top) bootstrap.Modal.getInstance(top).hide();       // may prompt — see the guard
  });
}
function dropBackdrop() {
  if (!backdrop) return;
  var el = backdrop;
  backdrop = null;
  el.classList.remove('show');
  setTimeout(function() { el.remove(); }, 150);             // matches Bootstrap's fade
}
// Deferred, so a modal that hides only to hand over to another (approve -> edit)
// has re-opened by the time we count.
function trackModal(el) {
  if (!el) return;
  el.addEventListener('show.bs.modal', function() { openModals++; raiseBackdrop(); });
  el.addEventListener('hidden.bs.modal', function() {
    openModals--;
    setTimeout(function() { if (openModals <= 0) dropBackdrop(); }, 0);
  });
}
if (editShift) trackModal(editShift.el);
trackModal(document.getElementById('dashApproveModal'));

// â•â•â•â•â•â•â• Goal Tooltip â•â•â•â•â•â•â•
(function() {
  var tip = document.getElementById('goalTooltip');
  if (!tip) return;
  var dot = tip.querySelector('.goal-tooltip__dot');
  var txt = tip.querySelector('.goal-tooltip__text');

  document.querySelectorAll('.goal-bar__seg').forEach(function(seg) {
    seg.addEventListener('mouseenter', function(e) {
      dot.style.background = seg.dataset.goalColor;
      txt.textContent = seg.dataset.goalLabel;
      tip.style.background = 'var(--text)';
      tip.style.display = '';
      positionTip(e);
    });
    seg.addEventListener('mousemove', positionTip);
    seg.addEventListener('mouseleave', function() {
      tip.style.display = 'none';
    });
  });

  function positionTip(e) {
    tip.style.left = (e.clientX + 10) + 'px';
    tip.style.top = (e.clientY - 32) + 'px';
  }
})();

// â•â•â•â•â•â•â• Today's Shift . Arrival Queue â•â•â•â•â•â•â•
(function() {
  var queue = JSON.parse(document.getElementById('todaysShiftsData').textContent);
  var multiple = !!cfg.bannerMultiple;
  var wrap = document.getElementById('todayArrivalWrap');
  var input = document.getElementById('todayArrivalTime');
  var saveBtn = document.getElementById('todayArrivalSave');
  var label = document.getElementById('todayArrivalLabel');
  var errorWrap = document.getElementById('todayArrivalError');
  var errorText = document.getElementById('todayArrivalErrorText');
  var editBtn = document.getElementById('todayArrivalEditBtn');
  if (!wrap || !input || !saveBtn || !label) return;
  var idx = 0;
  var UPDATE_URL = cfg.updateUrl;
  var STATS_URL = cfg.statsUrl;

  // Format a number in Danish style (period thousands, no decimals)
  function dkFmt(n) {
    return Math.round(n).toLocaleString('da-DK', { maximumFractionDigits: 0 });
  }

  // Format hours with 2 decimal places in Danish style
  function dkFmtH(n) {
    return parseFloat(n).toLocaleString('da-DK', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function refreshStats() {
    var params = new URLSearchParams(window.location.search);
    var qs = params.toString() ? '?' + params.toString() : '';
    fetch(STATS_URL + qs)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (!d.ok) return;
        var el;
        if ((el = document.getElementById('stat-planned-gross'))) el.textContent = dkFmt(d.planned_gross);
        if ((el = document.getElementById('stat-planned-net'))) el.textContent = dkFmt(d.planned_net);
        if ((el = document.getElementById('stat-earned-gross'))) el.textContent = dkFmt(d.earned_gross);
        if ((el = document.getElementById('stat-earned-net'))) el.textContent = dkFmt(d.earned_net);
        if ((el = document.getElementById('stat-earned-shift-count'))) el.textContent = d.total_approved_shift_count;
        if ((el = document.getElementById('stat-combined-gross'))) el.textContent = dkFmt(d.combined_gross);
        if ((el = document.getElementById('stat-combined-net'))) el.textContent = dkFmt(d.combined_net);
        if (d.has_any_goal) {
          if ((el = document.getElementById('stat-planned-hours'))) el.textContent = dkFmtH(d.total_planned_hours);
          if ((el = document.getElementById('stat-approved-hours'))) el.textContent = dkFmtH(d.total_approved_hours);
          if ((el = document.getElementById('stat-goal-range'))) {
            el.textContent = dkFmt(d.total_goal_min) + (d.total_goal_max ? '\u2013' + dkFmt(d.total_goal_max) : '');
          }
          var approvedSeg = document.getElementById('goal-bar-approved');
          var plannedSeg = document.getElementById('goal-bar-planned');
          if (approvedSeg) {
            approvedSeg.style.width = d.goal_approved_pct + '%';
            approvedSeg.dataset.goalLabel = 'Approved: ' + dkFmtH(d.total_approved_hours) + 'h';
          }
          if (plannedSeg) {
            plannedSeg.style.width = d.goal_planned_pct + '%';
            plannedSeg.dataset.goalLabel = 'Planned: ' + dkFmtH(d.total_planned_hours) + 'h';
          }
        }
      })
      .catch(function() {});
  }

  function showCurrent() {
    if (idx >= queue.length) {
      wrap.style.transition = 'opacity .4s';
      wrap.style.opacity = '0';
      setTimeout(function() { window.location.reload(); }, 400);
      return;
    }
    var s = queue[idx];
    window.setTimeValue(input, s.start_time);
    if (multiple) {
      label.textContent = 'Did you arrive early for your ' + s.start_time + ' shift?';
    } else {
      label.textContent = 'Did you arrive early?';
    }
    saveBtn.innerHTML = '<i class="bi bi-check-lg"></i>';
    saveBtn.disabled = false;
    clearArrivalError();
  }

  function clearArrivalError() {
    input.classList.remove('is-invalid');
    saveBtn.disabled = false;
    saveBtn.classList.remove('btn-outline-danger');
    saveBtn.classList.add('btn-outline-primary');
    if (errorWrap) errorWrap.classList.add('d-none');
  }

  /* An arrival at or after the shift's end leaves no shift at all — the server
     rejects it. Say so, and offer to carry the time into the edit modal so the end
     time can be moved out to meet it. */
  function checkArrival() {
    var s = queue[idx];
    if (!s || !input.value) return true;
    if (input.value < s.end_time) { clearArrivalError(); return true; }
    input.classList.add('is-invalid');
    saveBtn.disabled = true;
    saveBtn.classList.remove('btn-outline-primary');
    saveBtn.classList.add('btn-outline-danger');
    if (errorWrap && errorText) {
      errorText.textContent = 'Your shift ends at ' + s.end_time + '.';
      errorWrap.classList.remove('d-none');
    }
    return false;
  }

  if (editBtn && editShift) {
    editBtn.addEventListener('click', function() {
      var s = queue[idx];
      if (!s) return;
      editShift.open(s.id, {
        prefill: { start_time: input.value },        // carried over; the end time needs fixing
        saveWith: { arrival_confirmed: true },       // else the banner keeps asking
        onSaved: function() { window.location.reload(); },
        onDeleted: function() { window.location.reload(); },
      });
    });
  }

  function reflectArrival() {
    var s = queue[idx];
    if (!s || !checkArrival()) return;
    if (input.value < s.start_time) {
      label.textContent = multiple ? 'Arrived early for ' + s.start_time + '!' : 'Arrived early!';
    } else if (input.value > s.start_time) {
      label.textContent = multiple ? 'Arrived late for ' + s.start_time + '?' : 'Arrived late?';
    } else {
      showCurrent();
    }
  }

  // React while typing, not just on blur — but settle first, so a half-typed hour
  // doesn't flash an error.
  var reflectTimer = null;
  input.addEventListener('input', function() {
    clearTimeout(reflectTimer);
    reflectTimer = setTimeout(reflectArrival, 300);
  });
  input.addEventListener('change', function() {
    clearTimeout(reflectTimer);
    reflectArrival();
  });

  saveBtn.addEventListener('click', function() {
    if (idx >= queue.length) return;
    if (!checkArrival()) return;
    var s = queue[idx];
    saveBtn.disabled = true;
    fetch(UPDATE_URL.replace('/0/', '/' + s.id + '/'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({ start_time: input.value, arrival_confirmed: true }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
        label.textContent = 'Saved!';
        saveBtn.innerHTML = '<i class="bi bi-check-lg"></i>';
        refreshStats();
        idx++;
        setTimeout(function() { showCurrent(); }, 1000);
      } else {
        saveBtn.disabled = false;
      }
    })
    .catch(function() { saveBtn.disabled = false; });
  });

  showCurrent();
})();

// â•â•â•â•â•â•â• Today's Shift . Live Countdown â•â•â•â•â•â•â•
(function() {
  var el = document.getElementById('todayShiftStatus');
  if (!el) return;
  var shifts = JSON.parse(document.getElementById('todaysBannerShiftsData').textContent);
  if (!shifts || shifts.length === 0) return;

  // Parse "HH:MM" to minutes since midnight
  function toMin(t) {
    var p = t.split(':');
    return parseInt(p[0]) * 60 + parseInt(p[1]);
  }

  function fmtDuration(totalMin) {
    var h = Math.floor(totalMin / 60);
    var m = totalMin % 60;
    if (h > 0 && m > 0) return h + 'h ' + m + 'min';
    if (h > 0) return h + 'h';
    return m + 'min';
  }

  // Original static text as fallback
  var staticText = el.innerHTML;

  function update() {
    var now = new Date();
    var nowMin = now.getHours() * 60 + now.getMinutes();
    var current = null;
    var next = null;

    // Find current and next shift
    for (var i = 0; i < shifts.length; i++) {
      var s = shifts[i];
      var sStart = toMin(s.start_time);
      var sEnd = toMin(s.end_time);
      if (nowMin >= sStart && nowMin < sEnd) {
        current = { shift: s, index: i, endMin: sEnd };
        if (i + 1 < shifts.length) next = shifts[i + 1];
        break;
      }
    }

    // If no current shift, find next upcoming
    if (!current) {
      for (var j = 0; j < shifts.length; j++) {
        if (nowMin < toMin(shifts[j].start_time)) {
          next = shifts[j];
          break;
        }
      }
    }

    if (current) {
      var remaining = current.endMin - nowMin;
      var wpName = shifts.length > 1 ? (' at ' + escapeHtml(current.shift.workplace_name)) : '';
      var html = '<i class="bi bi-clock me-1"></i>Your current shift' + wpName +
                 ' ends in <strong>' + fmtDuration(remaining) + '</strong>' +
                 ' <span style="font-size:0.78rem;opacity:0.7;">(' + current.shift.start_time + '–' + current.shift.end_time + ')</span>';
      if (next) {
        html += '<br><span style="font-size:0.82rem;">Then at <strong>' + next.start_time +
                '</strong> you have a' + (shifts.length > 1 ? ' ' + escapeHtml(next.workplace_name) : '') +
                ' shift until ' + next.end_time + '</span>';
      }
      el.innerHTML = html;
    } else if (next) {
      var untilStart = toMin(next.start_time) - nowMin;
      var wpName2 = shifts.length > 1 ? (escapeHtml(next.workplace_name) + ' ') : '';
      var html2 = '<i class="bi bi-hourglass-split me-1"></i>Your ' + wpName2 + 'shift starts in <strong>' +
                  fmtDuration(untilStart) + '</strong>' +
                  ' <span style="font-size:0.78rem;opacity:0.7;">(' + next.start_time + '–' + next.end_time + ')</span>';
      el.innerHTML = html2;
    } else {
      // All shifts ended . check if we're past the last shift
      var last = shifts[shifts.length - 1];
      if (nowMin >= toMin(last.end_time)) {
        var worked = 0;
        shifts.forEach(function(s) { worked += parseFloat(s.net_hours); });
        el.innerHTML = '<i class="bi bi-check-circle me-1"></i>That\'s a wrap — <strong>' +
                       toDanish(worked.toFixed(2)) + 'h</strong> across ' + shifts.length +
                       ' shift' + (shifts.length === 1 ? '' : 's') + '.';
        // The headline is written in the present tense for the rest of the day.
        var headline = document.getElementById('todayShiftHeadline');
        if (headline && headline.dataset.done) headline.textContent = headline.dataset.done;
        var banner = el.closest('.today-shift-banner');
        if (banner) banner.classList.add('today-shift-banner--done');
      } else {
        el.innerHTML = staticText;
      }
    }
  }

  update();
  setInterval(update, 30000); // update every 30s
})();

// â•â•â•â•â•â•â• Dashboard Approve Modal â•â•â•â•â•â•â•
(function() {
  var body = document.getElementById('dashApproveBody');
  if (!body) return;
  var SHIFTS = JSON.parse(document.getElementById('pendingShiftsData').textContent);
  var countSpan = document.getElementById('dashApproveSelectedCount');
  var APPROVE_URL = cfg.approveUrl;

  var approveModalEl = document.getElementById('dashApproveModal');
  // backdrop-less: the page keeps one of its own up (see trackModal above).
  var approveModal = bootstrap.Modal.getOrCreateInstance(approveModalEl, { backdrop: false });
  var dirty = false;          // inline edits made, not yet sent to the server
  var rendering = false;      // we are writing the fields ourselves, not the user
  var stepAside = false;      // parent is hiding to make way for the edit modal
  var confirmedClose = false; // the discard prompt has been answered

  // Recompute a row's Hours cell from its inline start/end/break inputs.
  function recalcRow(tr) {
    var startEl = tr.querySelector('[data-field="start_time"]');
    var endEl = tr.querySelector('[data-field="end_time"]');
    var breakEl = tr.querySelector('[data-field="break_minutes"]');
    var cell = tr.querySelector('[data-field="hours"]');
    if (!startEl || !endEl || !cell) return;
    var start = startEl.value, end = endEl.value;
    var sh = start.split(':').map(Number), eh = end.split(':').map(Number);
    // An end at or before the start is rejected by the server, so flag it here
    // and hold back the Approve button rather than failing silently on submit.
    var bad = Boolean(start && end) && (eh[0] * 60 + eh[1]) <= (sh[0] * 60 + sh[1]);
    startEl.classList.toggle('is-invalid', bad);
    endEl.classList.toggle('is-invalid', bad);
    if (!start || !end || bad) { cell.textContent = '–'; return; }
    var totalMin = (eh[0] * 60 + eh[1]) - (sh[0] * 60 + sh[1]);
    totalMin -= parseInt(breakEl ? breakEl.value : 0, 10) || 0;
    if (totalMin <= 0) { cell.textContent = '–'; return; }
    cell.textContent = toDanish((totalMin / 60).toFixed(2)) + 'h';
  }
  function onTimeEdit(e) {
    if (e.target.matches('[data-field="start_time"],[data-field="end_time"],[data-field="break_minutes"]')) {
      var tr = e.target.closest('tr');
      if (tr) recalcRow(tr);
      updateApproveState();
    }
  }

  // A lone shift needs no picking: it is approved as-is, with no checkboxes shown.
  function single() { return SHIFTS.length === 1; }

  // Approve is blocked while nothing is selected, or a selected row's times are
  // impossible (which the server would reject anyway).
  function updateApproveState() {
    var btn = document.getElementById('dashApproveConfirmBtn');
    var warn = document.getElementById('dashApproveWarning');
    var ids = selectedIds();
    var invalid = false;
    ids.forEach(function(id) {
      var tr = body.querySelector('tr[data-shift-id="' + id + '"]');
      if (tr && tr.querySelector('.is-invalid')) invalid = true;
    });
    if (btn) btn.disabled = invalid || ids.length === 0;
    if (warn) warn.classList.toggle('d-none', !invalid);
  }

  // Any touched shift field counts as an unsaved edit: the values only reach the
  // server on "Approve Selected", so closing the modal must not happen silently.
  // Our own writes don't count — setTimeValue/initTimePickers fire change events too,
  // which would otherwise mark the table dirty the moment it renders.
  function onFieldEdit(e) {
    if (rendering) return;
    if (e.target.dataset && e.target.dataset.field) dirty = true;
  }

  // Drop a deleted shift's row, taking the workplace group with it if that was the
  // group's last row. (Rebuilding the body instead would lose the other rows' edits.)
  function dropRow(shiftId) {
    var tr = body.querySelector('tr[data-shift-id="' + shiftId + '"]');
    if (!tr) return;
    var tbody = tr.parentNode;
    tr.remove();
    if (tbody.querySelector('tr')) return;
    var wrapper = tbody.closest('.table-responsive');
    if (!wrapper) return;
    var header = wrapper.previousElementSibling;
    if (header) header.remove();
    wrapper.remove();
  }

  // Refresh one row from a server-saved shift, leaving the other rows' unsaved
  // inline edits alone (a full renderBody() would throw them away).
  function updateRow(s) {
    var tr = body.querySelector('tr[data-shift-id="' + s.id + '"]');
    if (!tr) return;
    rendering = true;
    try { writeRow(tr, s); } finally { rendering = false; }
  }
  function writeRow(tr, s) {
    var dateCell = tr.querySelector('[data-field="date"]');
    if (dateCell) dateCell.textContent = s.date;
    window.setTimeValue(tr.querySelector('[data-field="start_time"]'), s.start_time);
    window.setTimeValue(tr.querySelector('[data-field="end_time"]'), s.end_time);
    var breakEl = tr.querySelector('[data-field="break_minutes"]');
    if (breakEl) breakEl.value = s.break_minutes || 0;
    var typeEl = tr.querySelector('[data-field="shift_type"]');
    if (typeEl) typeEl.value = s.shift_type;
    var cell = tr.querySelector('[data-field="hours"]');
    if (cell) cell.textContent = toDanish(s.net_hours) + 'h';
  }

  // Group shifts by workplace
  function groupByWorkplace(shifts) {
    var groups = {};
    var order = [];
    shifts.forEach(function(s) {
      if (!groups[s.workplace_id]) {
        groups[s.workplace_id] = { name: s.workplace_name, color: s.workplace_color, shifts: [] };
        order.push(s.workplace_id);
      }
      groups[s.workplace_id].shifts.push(s);
    });
    return { groups: groups, order: order };
  }

  function renderBody() {
    rendering = true;
    try { buildBody(); } finally { rendering = false; }
  }

  function buildBody() {
    body.innerHTML = '';
    var data = groupByWorkplace(SHIFTS);
    data.order.forEach(function(wpId) {
      var g = data.groups[wpId];
      // Workplace group header
      var header = document.createElement('div');
      header.className = 'px-3 pt-3 pb-1 d-flex align-items-center gap-2';
      header.innerHTML =
        '<span style="width:10px;height:10px;border-radius:50%;background:' + escapeHtml(g.color) + ';flex-shrink:0;"></span>' +
        '<span class="fw-semibold" style="font-size:0.9rem;">' + escapeHtml(g.name) + '</span>' +
        (single() ? '' :
        '<div class="form-check ms-auto mb-0">' +
          '<input class="form-check-input wp-select-all" type="checkbox" data-wp="' + wpId + '">' +
          '<label class="form-check-label small text-muted">Select all</label>' +
        '</div>');
      body.appendChild(header);

      // Table
      var wrapper = document.createElement('div');
      wrapper.className = 'table-responsive';
      var table = document.createElement('table');
      table.className = 'table table-sm table-hover mb-0 dash-approve-table';
      table.innerHTML =
        '<thead class="table-light"><tr>' +
          (single() ? '' : '<th style="width:36px;"></th>') +
          '<th class="small text-muted">Date</th>' +
          '<th class="small text-muted">Start</th>' +
          '<th class="small text-muted">End</th>' +
          '<th class="small text-muted">Break</th>' +
          '<th class="small text-muted">Type</th>' +
          '<th class="small text-muted text-end">Hours</th>' +
          '<th style="width:32px;"></th>' +
        '</tr></thead>';
      var tbody = document.createElement('tbody');
      tbody.className = 'dash-approve-tbody';

      g.shifts.forEach(function(s) {
        var tr = document.createElement('tr');
        tr.dataset.shiftId = s.id;
        tr.innerHTML = window.buildApproveRowHtml(s, {
          selectable: !single(),
          cbClass: 'dash-approve-cb',
          cbAttrs: 'data-wp="' + wpId + '"',
          editBtnClass: 'dash-edit-btn',
        });
        tbody.appendChild(tr);
      });

      table.appendChild(tbody);
      wrapper.appendChild(table);
      body.appendChild(wrapper);
    });

    // Apply the 12/24h time-picker enhancement to the freshly-built rows.
    if (window.initTimePickers) window.initTimePickers(body);

    // Bound once on the persistent body (rows are rebuilt on each render).
    if (!body.dataset.bound) {
      body.dataset.bound = '1';
      body.addEventListener('input', onTimeEdit);
      body.addEventListener('change', onTimeEdit);
      body.addEventListener('input', onFieldEdit);
      body.addEventListener('change', onFieldEdit);
      body.addEventListener('change', onSelectionChange);
      body.addEventListener('mousedown', onSelectMouseDown);
      body.addEventListener('mouseover', onSelectMouseOver);
      body.addEventListener('click', onRowClick);
    }

    // Pencil buttons
    body.querySelectorAll('.dash-edit-btn').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        openEditShift(parseInt(btn.dataset.shiftId));
      });
    });

    updateCount();
  }

  /* Clicking a row's dead space latches a shade on it, so you can keep your place
     while working down a long list. It is a marker, not a selection: it moves to
     whichever row was clicked last, and a second click on the same row drops it.
     Clicking a field or the pencil is the user editing that row, not marking it. */
  function onRowClick(e) {
    if (e.target.closest('.form-control, .form-select, .form-check-input, button, label, a')) return;
    var tr = e.target.closest('tr[data-shift-id]');
    if (!tr) return;
    var wasFocused = tr.classList.contains('row-focused');
    body.querySelectorAll('tr.row-focused').forEach(function(r) { r.classList.remove('row-focused'); });
    tr.classList.toggle('row-focused', !wasFocused);
  }

  // A workplace's "select all", or a row checkbox (which may un-tick its group's).
  function onSelectionChange(e) {
    if (e.target.classList.contains('wp-select-all')) {
      var wp = e.target.dataset.wp;
      body.querySelectorAll('.dash-approve-cb[data-wp="' + wp + '"]').forEach(function(c) {
        c.checked = e.target.checked;
      });
      updateCount();
    } else if (e.target.classList.contains('dash-approve-cb')) {
      syncGroupCheckbox(e.target.dataset.wp);
      updateCount();
    }
  }

  function syncGroupCheckbox(wpId) {
    var all = body.querySelectorAll('.dash-approve-cb[data-wp="' + wpId + '"]');
    var allChecked = all.length > 0;
    all.forEach(function(c) { if (!c.checked) allChecked = false; });
    var wpCb = body.querySelector('.wp-select-all[data-wp="' + wpId + '"]');
    if (wpCb) wpCb.checked = allChecked;
  }

  /* Drag across the checkbox column to select a run of shifts. The row the drag
     starts on is left to the checkbox's own click; every row dragged over after
     that copies the state it is heading for. */
  var dragging = false;
  var dragState = false;

  function onSelectMouseDown(e) {
    var cb = e.target.closest('.dash-approve-cb');
    if (!cb) return;
    dragging = true;
    dragState = !cb.checked;
    body.classList.add('approve-selecting');
  }

  function onSelectMouseOver(e) {
    if (!dragging) return;
    var tr = e.target.closest('tr[data-shift-id]');
    if (!tr) return;
    var cb = tr.querySelector('.dash-approve-cb');
    if (!cb || cb.checked === dragState) return;
    cb.checked = dragState;
    syncGroupCheckbox(cb.dataset.wp);
    updateCount();
  }

  document.addEventListener('mouseup', function() {
    if (!dragging) return;
    dragging = false;
    body.classList.remove('approve-selecting');
    updateCount();
  });

  function selectedIds() {
    // With a single shift there is nothing to choose between, so it has no checkbox.
    if (single()) return [SHIFTS[0].id];
    var ids = [];
    body.querySelectorAll('.dash-approve-cb:checked').forEach(function(cb) { ids.push(parseInt(cb.value)); });
    return ids;
  }

  function updateCount() {
    if (single()) {
      countSpan.textContent = '1 shift';
    } else {
      countSpan.textContent = selectedIds().length + ' of ' + SHIFTS.length + ' selected';
    }
    updateApproveState();
  }

  // Approve button
  document.getElementById('dashApproveConfirmBtn').addEventListener('click', function() {
    var btn = this;
    var ids = selectedIds();
    if (ids.length === 0) return;

    var edits = [];
    ids.forEach(function(id) {
      var edit = { id: id };
      var fields = body.querySelectorAll('[data-id="' + id + '"]');
      fields.forEach(function(f) { if (f.dataset.field) edit[f.dataset.field] = f.value; });
      edits.push(edit);
    });

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Approving…';

    fetch(APPROVE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({ shift_ids: ids, edits: edits }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
        dirty = false;   // the edits are in the DB now; don't warn on the reload
        leaving = true;
        window.location.reload();
      } else {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-check2-all me-1"></i>Approve Selected';
      }
    })
    .catch(function() {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-check2-all me-1"></i>Approve Selected';
    });
  });

  /* Closing with work pending (backdrop click, Esc, X, Cancel) is a click away from
     throwing away a whole review pass — ask first. Both the inline edits and the
     ticked checkboxes only reach the server on "Approve Selected", so both count.
     Saying yes really does discard them (the table is rebuilt from the server's
     copy), so nothing lingers to warn about later. */
  function anySelected() {
    // The lone-shift table has no checkboxes: there is nothing to pick, so nothing
    // to lose by closing.
    return !single() && body.querySelector('.dash-approve-cb:checked') !== null;
  }
  function discardMessage() {
    var lost = [];
    if (dirty) lost.push('unsaved shift edits');
    if (anySelected()) lost.push('shifts selected for approval');
    return 'You have ' + lost.join(' and ') + ' — they are only written when you ' +
      'click "Approve Selected".\n\nDiscard them and close?';
  }

  approveModalEl.addEventListener('hide.bs.modal', function(e) {
    if (stepAside || confirmedClose || (!dirty && !anySelected())) return;
    e.preventDefault();
    if (!window.confirm(discardMessage())) return;
    confirmedClose = true;
    dirty = false;
    renderBody();   // rebuilt from the server's copy: edits gone, checkboxes cleared
    setTimeout(function() { approveModal.hide(); confirmedClose = false; }, 0);
  });

  // Only while work is actually pending — the discard above clears it, and a reload
  // we asked for ourselves (approve, last shift deleted) is not the user leaving.
  var leaving = false;
  window.addEventListener('beforeunload', function(e) {
    if (leaving || (!dirty && !anySelected())) return;
    e.preventDefault();
    e.returnValue = '';
  });

  // Opening the shared edit modal from a pencil button. Bootstrap can't stack modals
  // — a second one opens behind the backdrop and locks the page — so the approve
  // modal steps aside while it is open and comes back afterwards.
  /* The row's fields as they stand right now — its inline edits are only in the DOM,
     so the modal has to be handed them, or opening it would quietly revert the row to
     the server's copy. Untouched fields simply hand back what the server sent. */
  function rowValues(shiftId) {
    var tr = body.querySelector('tr[data-shift-id="' + shiftId + '"]');
    if (!tr) return {};
    var vals = {};
    tr.querySelectorAll('[data-field]').forEach(function(f) {
      if (f.value !== undefined) vals[f.dataset.field] = f.value;   // the date/hours cells are td's
    });
    return vals;
  }

  function openEditShift(shiftId) {
    editShift.open(shiftId, {
      prefill: rowValues(shiftId),
      present: function(show) {
        stepAside = true;
        approveModalEl.addEventListener('hidden.bs.modal', function onHidden() {
          approveModalEl.removeEventListener('hidden.bs.modal', onHidden);
          stepAside = false;
          show();
        });
        approveModal.hide();
      },
      onHidden: function() { approveModal.show(); },
      onSaved: function(s) {
        for (var i = 0; i < SHIFTS.length; i++) {
          if (SHIFTS[i].id === s.id) {
            SHIFTS[i].date = s.date;
            SHIFTS[i].start_time = s.start_time;
            SHIFTS[i].end_time = s.end_time;
            SHIFTS[i].break_minutes = s.break_minutes;
            SHIFTS[i].shift_type = s.shift_type;
            SHIFTS[i].net_hours = s.net_hours;
            break;
          }
        }
        updateRow(s);
      },
      onDeleted: function(shiftId) {
        SHIFTS = SHIFTS.filter(function(s) { return s.id !== shiftId; });
        if (!SHIFTS.length) {   // nothing left to approve — the banner has to go
          dirty = false;
          leaving = true;
          window.location.reload();
          return;
        }
        dropRow(shiftId);
        updateCount();
      },
    });
  }

  renderBody();
})();
})();
