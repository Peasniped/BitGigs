/* Main dashboard client logic: goal-bar tooltip, today's-shift arrival-time
   queue, live shift countdown, and the bulk-approve modal. Endpoint URLs and
   the banner "multiple shifts" flag come from #dashboardConfig data-* attrs;
   shift data come from json_script blobs. Each section guards on its own DOM
   anchor so it no-ops when the server didn't render that part. Uses
   getCsrfToken() and toDanish() from app.js. */
(function () {
  var CFG = document.getElementById('dashboardConfig');
  var cfg = CFG ? CFG.dataset : {};

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
  }

  input.addEventListener('change', function() {
    var s = queue[idx];
    if (input.value < s.start_time) {
      label.textContent = multiple ? 'Arrived early for ' + s.start_time + '!' : 'Arrived early!';
    } else if (input.value > s.start_time) {
      label.textContent = multiple ? 'Arrived late for ' + s.start_time + '?' : 'Arrived late?';
    } else {
      showCurrent();
    }
  });

  saveBtn.addEventListener('click', function() {
    if (idx >= queue.length) return;
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
      var wpName = shifts.length > 1 ? (' at ' + current.shift.workplace_name) : '';
      var html = '<i class="bi bi-clock me-1"></i>Your current shift' + wpName +
                 ' ends in <strong>' + fmtDuration(remaining) + '</strong>' +
                 ' <span style="font-size:0.78rem;opacity:0.7;">(' + current.shift.start_time + '–' + current.shift.end_time + ')</span>';
      if (next) {
        html += '<br><span style="font-size:0.82rem;">Then at <strong>' + next.start_time +
                '</strong> you have a' + (shifts.length > 1 ? ' ' + next.workplace_name : '') +
                ' shift until ' + next.end_time + '</span>';
      }
      el.innerHTML = html;
    } else if (next) {
      var untilStart = toMin(next.start_time) - nowMin;
      var wpName2 = shifts.length > 1 ? (next.workplace_name + ' ') : '';
      var html2 = '<i class="bi bi-hourglass-split me-1"></i>Your ' + wpName2 + 'shift starts in <strong>' +
                  fmtDuration(untilStart) + '</strong>' +
                  ' <span style="font-size:0.78rem;opacity:0.7;">(' + next.start_time + '–' + next.end_time + ')</span>';
      el.innerHTML = html2;
    } else {
      // All shifts ended . check if we're past the last shift
      var last = shifts[shifts.length - 1];
      if (nowMin >= toMin(last.end_time)) {
        el.innerHTML = '<i class="bi bi-check-circle me-1"></i>All shifts for today are done!';
        var banner = el.closest('.today-shift-banner');
        if (banner) {
          banner.style.background = 'linear-gradient(135deg, #dcfce7 0%, #f0fdf4 100%)';
          banner.style.borderColor = '#86efac';
        }
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
  var UPDATE_URL = cfg.updateUrl;
  var APPROVE_URL = cfg.approveUrl;

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
    body.innerHTML = '';
    var data = groupByWorkplace(SHIFTS);
    data.order.forEach(function(wpId) {
      var g = data.groups[wpId];
      // Workplace group header
      var header = document.createElement('div');
      header.className = 'px-3 pt-3 pb-1 d-flex align-items-center gap-2';
      header.innerHTML =
        '<span style="width:10px;height:10px;border-radius:50%;background:' + g.color + ';flex-shrink:0;"></span>' +
        '<span class="fw-semibold" style="font-size:0.9rem;">' + g.name + '</span>' +
        '<div class="form-check ms-auto mb-0">' +
          '<input class="form-check-input wp-select-all" type="checkbox" data-wp="' + wpId + '" checked>' +
          '<label class="form-check-label small text-muted">Select all</label>' +
        '</div>';
      body.appendChild(header);

      // Table
      var wrapper = document.createElement('div');
      wrapper.className = 'table-responsive';
      var table = document.createElement('table');
      table.className = 'table table-sm table-hover mb-0';
      table.innerHTML =
        '<thead class="table-light"><tr>' +
          '<th style="width:36px;"></th>' +
          '<th class="small text-muted">Date</th>' +
          '<th class="small text-muted">Start</th>' +
          '<th class="small text-muted">End</th>' +
          '<th class="small text-muted">Type</th>' +
          '<th class="small text-muted text-end">Hours</th>' +
          '<th style="width:32px;"></th>' +
        '</tr></thead>';
      var tbody = document.createElement('tbody');
      tbody.className = 'dash-approve-tbody';

      g.shifts.forEach(function(s) {
        var tr = document.createElement('tr');
        tr.innerHTML =
          '<td><input type="checkbox" class="form-check-input dash-approve-cb" value="' + s.id + '" data-wp="' + wpId + '" checked></td>' +
          '<td class="small">' + s.date + '</td>' +
          '<td><input type="time" class="form-control form-control-sm py-0" value="' + s.start_time + '" data-field="start_time" data-id="' + s.id + '" style="width:5.5rem;"></td>' +
          '<td><input type="time" class="form-control form-control-sm py-0" value="' + s.end_time + '" data-field="end_time" data-id="' + s.id + '" style="width:5.5rem;"></td>' +
          '<td><select class="form-select form-select-sm py-0" data-field="shift_type" data-id="' + s.id + '" style="width:7rem;">' +
            '<option value="on_site"' + (s.shift_type==='on_site'?' selected':'') + '>On-site</option>' +
            '<option value="remote"' + (s.shift_type==='remote'?' selected':'') + '>Remote</option>' +
            '<option value="sick_leave"' + (s.shift_type==='sick_leave'?' selected':'') + '>Sick leave</option>' +
            '<option value="paid_absence"' + (s.shift_type==='paid_absence'?' selected':'') + '>Paid absence</option>' +
            '<option value="vacation"' + (s.shift_type==='vacation'?' selected':'') + '>Vacation</option>' +
          '</select></td>' +
          '<td class="small text-end">' + toDanish(s.net_hours) + 'h</td>' +
          '<td class="text-center"><button type="button" class="btn btn-sm btn-outline-primary py-0 px-1 dash-edit-btn" data-shift-id="' + s.id + '" title="Edit shift"><i class="bi bi-pencil" style="font-size:0.65rem;"></i></button></td>';
        tbody.appendChild(tr);
      });

      table.appendChild(tbody);
      wrapper.appendChild(table);
      body.appendChild(wrapper);
    });

    // Apply the 12/24h time-picker enhancement to the freshly-built rows.
    if (window.initTimePickers) window.initTimePickers(body);

    // Attach per-workplace select all
    body.querySelectorAll('.wp-select-all').forEach(function(cb) {
      cb.addEventListener('change', function() {
        var wpId = cb.dataset.wp;
        body.querySelectorAll('.dash-approve-cb[data-wp="' + wpId + '"]').forEach(function(c) { c.checked = cb.checked; });
        updateCount();
      });
    });

    // Individual checkbox changes
    body.addEventListener('change', function(e) {
      if (e.target.classList.contains('dash-approve-cb')) {
        var wpId = e.target.dataset.wp;
        var allWp = body.querySelectorAll('.dash-approve-cb[data-wp="' + wpId + '"]');
        var allChecked = true;
        allWp.forEach(function(c) { if (!c.checked) allChecked = false; });
        var wpCb = body.querySelector('.wp-select-all[data-wp="' + wpId + '"]');
        if (wpCb) wpCb.checked = allChecked;
        updateCount();
      }
    });

    // Pencil buttons
    body.querySelectorAll('.dash-edit-btn').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        openEditModal(parseInt(btn.dataset.shiftId));
      });
    });

    updateCount();
  }

  function updateCount() {
    var checked = body.querySelectorAll('.dash-approve-cb:checked').length;
    countSpan.textContent = checked + ' of ' + SHIFTS.length + ' selected';
  }

  // Approve button
  document.getElementById('dashApproveConfirmBtn').addEventListener('click', function() {
    var btn = this;
    var ids = [];
    body.querySelectorAll('.dash-approve-cb:checked').forEach(function(cb) { ids.push(parseInt(cb.value)); });
    if (ids.length === 0) return;

    var edits = [];
    ids.forEach(function(id) {
      var edit = { id: id };
      var fields = body.querySelectorAll('[data-id="' + id + '"]');
      fields.forEach(function(f) { if (f.dataset.field) edit[f.dataset.field] = f.value; });
      edits.push(edit);
    });

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Approvingâ€¦';

    fetch(APPROVE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({ shift_ids: ids, edits: edits }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
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

  // Edit modal
  var editModal = new bootstrap.Modal(document.getElementById('dashEditApproveModal'));

  function openEditModal(shiftId) {
    var url = UPDATE_URL.replace('/0/', '/' + shiftId + '/');
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({}),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) return;
      var s = data.shift;
      document.getElementById('dashEditShiftId').value = s.id;
      window.setDateValue(document.getElementById('dashEditDate'), s.date);
      window.setTimeValue(document.getElementById('dashEditStart'), s.start_time);
      window.setTimeValue(document.getElementById('dashEditEnd'), s.end_time);
      document.getElementById('dashEditBreak').value = s.break_minutes;
      document.getElementById('dashEditType').value = s.shift_type;
      document.getElementById('dashEditNotes').value = s.notes;
      document.getElementById('dashEditErrors').classList.add('d-none');
      editModal.show();
    });
  }

  document.getElementById('dashEditSaveBtn').addEventListener('click', function() {
    var shiftId = document.getElementById('dashEditShiftId').value;
    if (!shiftId) return;
    var url = UPDATE_URL.replace('/0/', '/' + shiftId + '/');
    var payload = {
      date: document.getElementById('dashEditDate').value,
      start_time: document.getElementById('dashEditStart').value,
      end_time: document.getElementById('dashEditEnd').value,
      break_minutes: parseInt(document.getElementById('dashEditBreak').value) || 0,
      shift_type: document.getElementById('dashEditType').value,
      notes: document.getElementById('dashEditNotes').value,
    };
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) {
        document.getElementById('dashEditErrors').textContent = data.error || 'Error saving.';
        document.getElementById('dashEditErrors').classList.remove('d-none');
        return;
      }
      var s = data.shift;
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
      editModal.hide();
      renderBody();
    });
  });

  renderBody();
})();
})();
