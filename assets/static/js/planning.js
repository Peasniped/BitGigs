/* Cross-workplace planning calendar: drag-to-create shifts, power-edit
   (copy/delete/delete-all/fast-create), shift + session modals, overlap
   checks, and per-workplace default-shift config. Endpoint URLs and the
   current year/month come from #planningConfig data-* attrs; workplace and
   month-name data come from json_script blobs. Uses getCsrfToken() and
   toDanish() from app.js. */
(function() {
  var _cfgEl = document.getElementById('planningConfig');
  var cfg = _cfgEl ? _cfgEl.dataset : {};
  const WORKPLACES = JSON.parse(document.getElementById('workplaceData').textContent);
  const CSRF = getCsrfToken();
  const API_BASE = cfg.apiBase;
  const MONTH_NAMES = JSON.parse(document.getElementById('monthNamesData').textContent);
  const CURRENT_YEAR = parseInt(cfg.currentYear, 10);
  const CURRENT_MONTH = parseInt(cfg.currentMonth, 10);
  const SHOW_TYPE_COLORS = cfg.showTypeColors === '1';

  const wpMap = {};
  WORKPLACES.forEach(function(wp) { wpMap[wp.id] = wp; });

  // Show monthly hours + goal on cards
  WORKPLACES.forEach(function(wp) {
    var el = document.querySelector('[data-wp-hours="' + wp.id + '"]');
    if (!el) return;
    var h = parseFloat(wp.total_hours.replace(',','.')) || 0;
    var hStr = toDanish(h.toFixed(2)) + 'h';

    // Compute monthly goal for display (convert weekly â†’ monthly with Ã—4.33)
    var goalMin = wp.hour_goal_min ? parseFloat(wp.hour_goal_min) : 0;
    var goalMax = wp.hour_goal_max ? parseFloat(wp.hour_goal_max) : 0;
    if (wp.hour_goal_type === 'weekly') {
      goalMin = goalMin * 4.33;
      goalMax = goalMax ? goalMax * 4.33 : 0;
    }

    if (goalMin > 0) {
      var goalStr;
      if (goalMax > 0) {
        goalStr = toDanish(goalMin.toFixed(0)) + '.' + toDanish(goalMax.toFixed(0)) + 'h';
      } else {
        goalStr = toDanish(goalMin.toFixed(0)) + 'h';
      }
      el.textContent = hStr + ' / ' + goalStr;

      // Color: green if in range, amber if below, red if over max
      var target = goalMax > 0 ? goalMax : goalMin;
      if (h >= goalMin && (goalMax <= 0 || h <= goalMax)) {
        el.style.color = 'var(--success)';
      } else if (h < goalMin) {
        el.style.color = 'var(--text-subtle)';
      } else {
        el.style.color = 'var(--danger)';
      }

      // Progress bar
      var barEl = document.querySelector('[data-wp-progress="' + wp.id + '"]');
      if (barEl) {
        barEl.style.display = '';
        var fill = barEl.querySelector('.wp-card__progress-fill');
        var barMax = goalMax > 0 ? goalMax : goalMin;
        var pct = Math.min((h / barMax) * 100, 100);
        fill.style.width = pct + '%';
        // Blue if under target/lower, green if at/over lower limit
        fill.style.background = h >= goalMin ? 'var(--success)' : 'var(--info)';
      }
    } else {
      el.textContent = hStr + ' this period';
    }
  });

  // Track which workplace is being dragged
  var draggedWorkplaceId = null;

  // ----- Power Edit modes -----
  var fastCreateMode = false;
  var copyMode = false;
  var deleteMode = false;
  var copiedShift = null;
  var powerToolbar = document.getElementById('powerToolbar');
  var powerEditToggle = document.getElementById('powerEditToggle');
  var peCreateBtn = document.getElementById('peCreateBtn');
  var peCreateLabel = document.getElementById('peCreateLabel');
  var peCopyBtn = document.getElementById('peCopyBtn');
  var peDeleteBtn = document.getElementById('peDeleteBtn');
  var peDeleteAllBtn = document.getElementById('peDeleteAllBtn');
  var peHint = document.getElementById('peHint');
  var peCloseBtn = document.getElementById('peCloseBtn');
  var deleteAllMode = false;
  var fastCreateWpId = null;
  var BULK_DELETE_URL = cfg.bulkDeleteUrl;

  function exitAllModes() {
    copyMode = false;
    deleteMode = false;
    deleteAllMode = false;
    fastCreateMode = false;
    copiedShift = null;
    fastCreateWpId = null;
    document.body.classList.remove('copy-mode', 'delete-mode', 'delete-all-mode', 'fast-create-stamp');
    peCopyBtn.classList.remove('active');
    peCreateBtn.classList.remove('active');
    peCreateLabel.textContent = 'Fast Create';
    peDeleteBtn.classList.remove('active');
    peDeleteAllBtn.classList.remove('active');
    peDeleteAllBtn.style.display = 'none';
    peHint.textContent = '';
    document.querySelectorAll('.shift-chip--copied').forEach(function(el) {
      el.classList.remove('shift-chip--copied');
    });
    // Remove wp-card selected highlights
    document.querySelectorAll('.wp-card--selected').forEach(function(el) {
      el.classList.remove('wp-card--selected');
    });
    clearPeriodHighlights();
  }

  powerEditToggle.addEventListener('click', function() {
    var isOpen = powerToolbar.classList.contains('show');
    if (isOpen) {
      exitAllModes();
      fastCreateMode = false;
      peCreateBtn.classList.remove('active');
      peCreateLabel.textContent = 'Fast Create';
      powerToolbar.classList.remove('show');
      powerEditToggle.classList.remove('btn-primary');
      powerEditToggle.classList.add('btn-outline-primary');
    } else {
      powerToolbar.classList.add('show');
      powerEditToggle.classList.remove('btn-outline-primary');
      powerEditToggle.classList.add('btn-primary');
    }
  });

  // Close button on toolbar
  peCloseBtn.addEventListener('click', function() {
    powerEditToggle.click();
  });

  // Flash red border + tooltip on a workplace card with no defaults
  function showNoDefaultsFlash(card) {
    card.classList.add('wp-card--no-defaults');
    var tip = document.createElement('span');
    tip.className = 'wp-card__no-defaults-tip';
    tip.textContent = 'No default shift set!';
    // Append to body with fixed coords so overflow:hidden on the card doesn't clip it
    var rect = card.getBoundingClientRect();
    tip.style.left = (rect.left + rect.width / 2) + 'px';
    tip.style.top = (rect.top - 36) + 'px';
    document.body.appendChild(tip);
    setTimeout(function() {
      card.classList.remove('wp-card--no-defaults');
      tip.remove();
    }, 2000);
  }

  // Create mode toggle
  peCreateBtn.addEventListener('click', function() {
    // Check before exitAllModes(), which clears fastCreateMode itself — reading
    // it afterwards always saw false, so the flag could only ever be turned on.
    if (fastCreateMode) {
      exitAllModes();
      return;
    }
    exitAllModes();
    fastCreateMode = true;
    peCreateBtn.classList.add('active');
    peHint.textContent = 'Click or drag a workplace card, then click days to stamp shifts';
  });

  // Copy mode toggle
  peCopyBtn.addEventListener('click', function() {
    if (copyMode) {
      exitAllModes();
      return;
    }
    exitAllModes();
    copyMode = true;
    document.body.classList.add('copy-mode');
    peCopyBtn.classList.add('active');
    peHint.textContent = 'Click a shift to copy it';
  });

  // Delete mode toggle
  peDeleteBtn.addEventListener('click', function() {
    if (deleteMode) {
      exitAllModes();
      return;
    }
    exitAllModes();
    deleteMode = true;
    document.body.classList.add('delete-mode');
    peDeleteBtn.classList.add('active');
    peDeleteAllBtn.style.display = '';
    peHint.textContent = 'Click a shift to delete it';
  });

  // Delete All mode toggle
  peDeleteAllBtn.addEventListener('click', function() {
    if (deleteAllMode) {
      // Go back to normal delete mode
      deleteAllMode = false;
      document.body.classList.remove('delete-all-mode');
      document.body.classList.add('delete-mode');
      deleteMode = true;
      peDeleteAllBtn.classList.remove('active');
      peHint.textContent = 'Click a shift to delete it';
      return;
    }
    // Enter delete-all mode
    deleteMode = false;
    deleteAllMode = true;
    document.body.classList.remove('delete-mode');
    document.body.classList.add('delete-all-mode');
    peDeleteAllBtn.classList.add('active');
    peHint.textContent = 'Click a workplace card to delete ALL its shifts, or click a calendar day to delete all shifts on that day';
  });

  function deleteAllForWorkplace(wpId) {
    var wp = wpMap[wpId];
    if (!wp || !wp.period_start || !wp.period_end) return;
    // Count shifts in the period for the confirmation prompt
    var count = 0;
    document.querySelectorAll('.shift-chip--planned[data-workplace-id="' + wpId + '"]').forEach(function(chip) {
      var td = chip.closest('td[data-date]');
      if (!td) return;
      var d = td.dataset.date;
      if (d >= wp.period_start && d <= wp.period_end) count++;
    });
    if (count === 0) return;
    if (!confirm('Delete all ' + count + ' planned shift(s) for ' + wp.name + '?')) return;
    fetch(BULK_DELETE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify({
        workplace_id: wpId,
        period_start: wp.period_start,
        period_end: wp.period_end,
      }),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) {
        // Remove only chips within the deleted period
        document.querySelectorAll('.shift-chip--planned[data-workplace-id="' + wpId + '"]').forEach(function(chip) {
          var td = chip.closest('td[data-date]');
          if (!td) return;
          var d = td.dataset.date;
          if (d >= wp.period_start && d <= wp.period_end) {
            chip.remove();
            updateDayHourBadge(td);
          }
        });
        updateWpCardProgress(wpId);
        recheckOverlaps();
        exitAllModes();
        peHint.textContent = 'Deleted ' + data.deleted + ' shift(s) for ' + (wp ? wp.name : 'workplace');
      }
    });
  }

  function deleteAllForDay(dateStr) {
    var chips = document.querySelectorAll('.planning-calendar td[data-date="' + dateStr + '"] .shift-chip--planned');
    var count = chips.length;
    if (count === 0) return;
    var parts = dateStr.split('-');
    var label = parts[2] + '/' + parts[1] + '/' + parts[0];
    if (!confirm('Delete all ' + count + ' planned shift(s) on ' + label + '?')) return;
    fetch(BULK_DELETE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify({ date: dateStr }),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) {
        var td = document.querySelector('.planning-calendar td[data-date="' + dateStr + '"]');
        if (td) {
          td.querySelectorAll('.shift-chip--planned').forEach(function(chip) {
            var wpId = parseInt(chip.dataset.workplaceId);
            chip.remove();
            if (wpId) updateWpCardProgress(wpId);
          });
          updateDayHourBadge(td);
        }
        recheckOverlaps();
        exitAllModes();
        peHint.textContent = 'Deleted ' + data.deleted + ' shift(s) on ' + label;
      }
    });
  }

  function selectShiftForCopy(chip) {
    var shiftId = parseInt(chip.dataset.shiftId);
    var url = cfg.shiftUpdateUrl.replace('/0/', '/' + shiftId + '/');
    fetch(url, {
      method: 'GET',
      headers: { 'X-CSRFToken': CSRF },
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) return;
      var s = data.shift;
      copiedShift = {
        workplace_id: s.workplace_id,
        start_time: s.start_time,
        end_time: s.end_time,
        break_minutes: s.break_minutes,
        shift_type: s.shift_type,
        notes: s.notes || '',
      };
      document.querySelectorAll('.shift-chip--copied').forEach(function(el) {
        el.classList.remove('shift-chip--copied');
      });
      chip.classList.add('shift-chip--copied');
      var wp = wpMap[copiedShift.workplace_id];
      peHint.textContent = 'Copied ' + (wp ? wp.name : '') + ' ' + s.start_time + '.' + s.end_time + ' . click days to paste';
      clearPeriodHighlights();
      highlightPeriodDays(copiedShift.workplace_id);
    });
  }

  function pasteShiftToDate(dateStr) {
    if (!copiedShift) return;
    if (!isInPeriod(copiedShift.workplace_id, dateStr)) {
      showPeriodWarning(copiedShift.workplace_id, dateStr);
      return;
    }
    if (!isInContract(copiedShift.workplace_id, dateStr)) {
      showContractWarning(copiedShift.workplace_id, dateStr);
      return;
    }
    var body = {
      workplace_id: copiedShift.workplace_id,
      date: dateStr,
      start_time: copiedShift.start_time,
      end_time: copiedShift.end_time,
      break_minutes: copiedShift.break_minutes,
      shift_type: copiedShift.shift_type,
      notes: copiedShift.notes,
    };
    fetch(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify(body),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) {
        var td = document.querySelector('.planning-calendar td[data-date="' + dateStr + '"]');
        if (td) {
          var container = td.querySelector('.planned-shifts-container');
          if (container) {
            var wp = wpMap[copiedShift.workplace_id];
            var chip = buildShiftChip(data.shift, wp);
            insertChipSorted(container, chip);
            updateDayHourBadge(td);
            recheckOverlaps();
          }
        }
      }
    });
  }

  function deleteShiftImmediate(chip) {
    var shiftId = parseInt(chip.dataset.shiftId);
    var wpId = parseInt(chip.dataset.workplaceId);
    if (!shiftId) return;
    var url = cfg.shiftUpdateUrl.replace('/0/', '/' + shiftId + '/');
    fetch(url, {
      method: 'DELETE',
      headers: { 'X-CSRFToken': CSRF },
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) {
        var td = chip.closest('td[data-date]');
        chip.style.transition = 'opacity 0.2s, transform 0.2s';
        chip.style.opacity = '0';
        chip.style.transform = 'scale(0.8)';
        setTimeout(function() {
          chip.remove();
          if (td) updateDayHourBadge(td);
          updateWpCardProgress(wpId);
          recheckOverlaps();
        }, 200);
      }
    });
  }

  // Build a shift chip element from API response data
  function buildShiftChip(s, wp) {
    var div = document.createElement('div');
    div.className = 'shift-chip shift-chip--planned';
    if (SHOW_TYPE_COLORS && s.shift_type) {
      div.classList.add('shift-chip--type-' + s.shift_type);
    }
    if (wp && (wp.accent_color || wp.color)) {
      div.style.borderColor = wp.accent_color || wp.color;
    }
    div.setAttribute('draggable', 'true');
    div.dataset.shiftId = s.id;
    div.dataset.workplaceId = s.workplace_id;
    div.title = '[Planned] ' + s.workplace_name + ': ' + s.start_time + '-' + s.end_time + ' (' + toDanish(s.net_hours) + 'h)';

    var avatarHtml = '';
    if (wp && wp.custom_icon_url) {
      avatarHtml = '<img src="' + wp.custom_icon_url + '" alt="">';
    } else if (wp && wp.icon) {
      avatarHtml = '<i class="bi ' + wp.icon + '"></i>';
    } else {
      avatarHtml = escapeHtml(wp ? (wp.initials ? wp.initials.charAt(0) : wp.name.charAt(0)) : '?');
    }
    var breakHtml = s.break_minutes ? '<i class="bi bi-cup-hot shift-chip__break" title="Includes a break"></i>' : '';
    var typeHtml = '';
    if (SHOW_TYPE_COLORS) {
      var symInner = '';
      if (s.shift_type === 'sick_leave') symInner = '<span class="shift-chip__sym shift-chip__sym--sick"></span>';
      else if (s.shift_type === 'vacation') symInner = '<span class="shift-chip__sym shift-chip__sym--vacation"></span>';
      typeHtml = '<span class="shift-chip__type" title="' + (s.shift_type_display || '') + '">' + symInner + '</span>';
    }
    div.innerHTML =
      '<span class="shift-chip__avatar" style="background:' + (wp && wp.color ? escapeHtml(wp.color) : 'var(--primary)') + ';">' + avatarHtml + '</span>' +
      '<small class="shift-chip__time">' + s.start_time + '-' + s.end_time + '</small>' +
      '<small class="shift-chip__hours">(' + toDanish(s.net_hours) + 'h)</small>' +
      breakHtml + typeHtml +
      '<i class="bi bi-pencil shift-chip__edit"></i>';

    wireShiftChip(div, s.workplace_id);
    return div;
  }

  // Attach drag, click, and hover handlers to a dynamically created or page-loaded chip.
  function wireShiftChip(chip, wpId) {
    var td = chip.closest('td[data-date]');
    var dateStr = td ? td.dataset.date : '';

    if (wpId && dateStr && !isInPeriod(wpId, dateStr)) {
      chip.classList.add('shift-chip--prior-period');
      // Stays draggable so a drag *attempt* can be answered with the
      // wrong-period warning instead of silently doing nothing.
      chip.addEventListener('dragstart', function(e) {
        e.preventDefault();
        showChipPeriodWarning(wpId, dateStr);
      });
      return;
    }

    chip.addEventListener('dragstart', function(e) {
      e.stopPropagation();
      draggedWorkplaceId = wpId;
      e.dataTransfer.setData('text/plain', JSON.stringify({
        type: 'move-shift',
        shift_id: parseInt(chip.dataset.shiftId),
        workplace_id: wpId,
      }));
      e.dataTransfer.effectAllowed = 'move';
      highlightPeriodDays(wpId);
    });
    chip.addEventListener('dragend', function() {
      draggedWorkplaceId = null;
      clearPeriodHighlights();
    });
    chip.addEventListener('click', function(e) {
      e.stopPropagation();
      if (copyMode) { selectShiftForCopy(chip); return; }
      if (deleteMode) { deleteShiftImmediate(chip); return; }
      if (deleteAllMode) { deleteAllForWorkplace(wpId); return; }
      openEditShiftModal(parseInt(chip.dataset.shiftId));
    });
    chip.addEventListener('mouseenter', function() {
      var parent = chip.closest('.calendar-day');
      if (parent) parent.classList.add('chip-hover');
    });
    chip.addEventListener('mouseleave', function() {
      var parent = chip.closest('.calendar-day');
      if (parent) parent.classList.remove('chip-hover');
    });
  }

  // Parse "HH:MM" into minutes-since-midnight.
  function toMinutes(hhmm) {
    var p = String(hhmm).trim().split(':');
    return parseInt(p[0]) * 60 + parseInt(p[1]);
  }

  // Insert a chip into a day container keeping chips ordered by start time.
  function insertChipSorted(container, chip) {
    var el = chip.querySelector('.shift-chip__time');
    var startMin = el ? toMinutes(el.textContent.trim().split('-')[0]) : 0;
    var ref = Array.from(container.children).find(function(c) {
      var e = c.querySelector('.shift-chip__time');
      return e && toMinutes(e.textContent.trim().split('-')[0]) > startMin;
    });
    container.insertBefore(chip, ref || null);
  }

  // Which overlapping pair warrants the amber warning. Two real shifts always
  // do (this matches the server's annotate_overlaps). A busy (external calendar)
  // chip only clashes with a shift that belongs to the *selected* month — a
  // faded prior-period shift shown only for context, or another busy block, is
  // ignored, so the overlay never warns about a shift managed in another month.
  function flagsOverlap(a, b) {
    if (a.busy && b.busy) return false;
    if (a.busy || b.busy) {
      var shift = a.busy ? b : a;
      return !shift.prior;
    }
    return true;
  }

  // Re-detect overlaps client-side and update chip styling + banner visibility.
  // Counts every chip on a day (including faded prior-period and approved
  // chips) so the warning matches the server's annotate_overlaps.
  function recheckOverlaps() {
    // Clear existing overlap styling
    document.querySelectorAll('.planning-calendar .shift-chip--overlap').forEach(function(c) {
      c.classList.remove('shift-chip--overlap');
      c.title = c.title.replace(/^⚠ Overlapping shift — /, '');
    });

    var hasAny = false;
    document.querySelectorAll('.planning-calendar td[data-date]').forEach(function(td) {
      var chips = Array.from(td.querySelectorAll('.shift-chip'));
      if (chips.length < 2) return;
      var items = chips.map(function(c) {
        var el = c.querySelector('.shift-chip__time');
        if (!el) return null;
        var parts = el.textContent.trim().split('-');
        if (parts.length !== 2) return null;
        return {
          el: c,
          start: toMinutes(parts[0]),
          end: toMinutes(parts[1]),
          busy: c.classList.contains('busy-chip'),
          prior: c.classList.contains('shift-chip--prior-period'),
        };
      }).filter(Boolean);

      var overlapping = new Set();
      for (var i = 0; i < items.length; i++) {
        for (var j = i + 1; j < items.length; j++) {
          if (items[i].start < items[j].end && items[j].start < items[i].end &&
              flagsOverlap(items[i], items[j])) {
            overlapping.add(i);
            overlapping.add(j);
          }
        }
      }
      overlapping.forEach(function(idx) {
        var chip = items[idx].el;
        chip.classList.add('shift-chip--overlap');
        if (!chip.title.startsWith('⚠')) chip.title = '⚠ Overlapping shift — ' + chip.title;
        hasAny = true;
      });
    });

    var banner = document.getElementById('overlapBanner');
    if (banner) {
      if (hasAny) {
        banner.style.display = 'flex';
      } else {
        banner.style.display = 'none';
      }
    }
  }

  // Recalculate and update the hour badge for a day cell
  function updateDayHourBadge(td) {
    var chips = td.querySelectorAll('.shift-chip');
    var totalMinutes = 0;
    chips.forEach(function(c) {
      var m = c.querySelector('.shift-chip__hours');
      if (m) {
        // Parse Danish formatted hours like "(7,50h)" or "(3h)"
        var text = m.textContent.replace(/[()h]/g, '').replace('.', ',');
        var val = parseFloat(text.replace(',', '.')) || 0;
        totalMinutes += Math.round(val * 60);
      }
    });
    var badge = td.querySelector('.calendar-day__hours');
    if (totalMinutes > 0) {
      var hours = (totalMinutes / 60).toFixed(2);
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'badge bg-primary bg-opacity-75 calendar-day__hours';
        var header = td.querySelector('.d-flex');
        if (header) header.appendChild(badge);
      }
      badge.textContent = toDanish(hours) + 'h';
    } else if (badge) {
      badge.remove();
    }
  }

  // Update the wp-card progress bar and hours text after adding/removing shifts
  function updateWpCardProgress(wpId) {
    var wp = wpMap[wpId];
    if (!wp) return;
    var totalMinutes = 0;
    document.querySelectorAll('.shift-chip[data-workplace-id="' + wpId + '"]').forEach(function(chip) {
      var td = chip.closest('td[data-date]');
      if (!td) return;
      if (!isInPeriod(wpId, td.dataset.date)) return;
      var m = chip.querySelector('.shift-chip__hours');
      if (m) {
        var val = parseFloat(m.textContent.replace(/[()h]/g, '').replace(',', '.')) || 0;
        totalMinutes += Math.round(val * 60);
      }
    });
    var h = totalMinutes / 60;
    var hoursEl = document.querySelector('[data-wp-hours="' + wpId + '"]');
    if (!hoursEl) return;
    var hStr = toDanish(h.toFixed(2)) + 'h';
    var goalMin = wp.hour_goal_min ? parseFloat(wp.hour_goal_min) : 0;
    var goalMax = wp.hour_goal_max ? parseFloat(wp.hour_goal_max) : 0;
    if (wp.hour_goal_type === 'weekly') { goalMin = goalMin * 4.33; goalMax = goalMax ? goalMax * 4.33 : 0; }
    if (goalMin > 0) {
      var goalStr = goalMax > 0
        ? toDanish(goalMin.toFixed(0)) + '\u2013' + toDanish(goalMax.toFixed(0)) + 'h'
        : toDanish(goalMin.toFixed(0)) + 'h';
      hoursEl.textContent = hStr + ' / ' + goalStr;
      hoursEl.style.color = (h >= goalMin && (goalMax <= 0 || h <= goalMax)) ? 'var(--success)' : (h < goalMin ? 'var(--text-subtle)' : 'var(--danger)');
      var barEl = document.querySelector('[data-wp-progress="' + wpId + '"]');
      if (barEl) {
        barEl.style.display = '';
        var fill = barEl.querySelector('.wp-card__progress-fill');
        var barMax = goalMax > 0 ? goalMax : goalMin;
        fill.style.width = Math.min((h / barMax) * 100, 100) + '%';
        fill.style.background = h >= goalMin ? 'var(--success)' : 'var(--info)';
      }
    } else {
      hoursEl.textContent = hStr + ' this period';
    }
  }

  function fastCreateShift(workplaceId, dateStr) {
    // Block fast-create outside the payroll period or contract bounds
    if (!isInPeriod(workplaceId, dateStr)) { showPeriodWarning(workplaceId, dateStr); return; }
    if (!isInContract(workplaceId, dateStr)) { showContractWarning(workplaceId, dateStr); return; }
    var wp = wpMap[workplaceId];
    if (!wp || !wp.default_start || !wp.default_end) {
      // No defaults configured . show yellow warning inside modal
      openNewShiftModal(workplaceId, dateStr, true);
      return;
    }
    var body = {
      workplace_id: workplaceId,
      date: dateStr,
      start_time: wp.default_start,
      end_time: wp.default_end,
      break_minutes: wp.default_break || 0,
      shift_type: wp.default_type || 'on_site',
      notes: '',
    };
    fetch(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify(body),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) {
        var td = document.querySelector('.planning-calendar td[data-date="' + dateStr + '"]');
        if (td) {
          var container = td.querySelector('.planned-shifts-container');
          if (container) {
            var chip = buildShiftChip(data.shift, wp);
            insertChipSorted(container, chip);
            updateDayHourBadge(td);
            updateWpCardProgress(workplaceId);
            recheckOverlaps();
          }
        }
      }
    });
  }

  // Escape key exits active modes. fastCreateMode is checked alongside
  // fastCreateWpId: the latter is only set once a workplace card is picked, so
  // on its own it left an armed-but-unpicked Fast Create with no way out.
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && (copyMode || deleteMode || deleteAllMode || fastCreateMode || fastCreateWpId)) exitAllModes();
  });

  // Click outside calendar exits copy/delete/delete-all/fast-create-stamp mode
  document.addEventListener('click', function(e) {
    if ((copyMode || deleteMode || deleteAllMode || fastCreateMode || fastCreateWpId) && !e.target.closest('.planning-calendar') && !e.target.closest('.power-toolbar') && !e.target.closest('#powerEditToggle') && !e.target.closest('.wp-card')) {
      exitAllModes();
    }
  });

  // ----- Drag from workplace cards -----
  document.querySelectorAll('.wp-card[draggable]').forEach(function(card) {
    var wpId = parseInt(card.dataset.workplaceId);
    card.addEventListener('dragstart', function(e) {
      draggedWorkplaceId = wpId;
      e.dataTransfer.setData('text/plain', JSON.stringify({
        type: 'new-shift',
        workplace_id: wpId,
      }));
      e.dataTransfer.effectAllowed = 'move';
      highlightPeriodDays(wpId);
      // Warn on drag if fast create is on but no defaults
      if (fastCreateMode) {
        var wp = wpMap[wpId];
        if (!wp || !wp.default_start || !wp.default_end) {
          showNoDefaultsFlash(card);
        }
      }
    });
    card.addEventListener('dragend', function() {
      draggedWorkplaceId = null;
      clearPeriodHighlights();
    });
    card.addEventListener('mouseenter', function() {
      if (!draggedWorkplaceId) highlightPeriodDays(wpId);
    });
    card.addEventListener('mouseleave', function() {
      if (!draggedWorkplaceId && fastCreateWpId !== wpId) clearPeriodHighlights();
    });
    card.addEventListener('click', function(e) {
      if (deleteAllMode) {
        e.preventDefault();
        deleteAllForWorkplace(wpId);
        return;
      }
      if (fastCreateMode) {
        e.preventDefault();
        var wp = wpMap[wpId];
        // If already selected, deselect
        if (fastCreateWpId === wpId) {
          fastCreateWpId = null;
          document.body.classList.remove('fast-create-stamp');
          card.classList.remove('wp-card--selected');
          clearPeriodHighlights();
          peHint.textContent = 'Click or drag a workplace card, then click days to stamp shifts';
          return;
        }
        // Select this workplace for stamping
        document.querySelectorAll('.wp-card--selected').forEach(function(el) { el.classList.remove('wp-card--selected'); });
        fastCreateWpId = wpId;
        card.classList.add('wp-card--selected');
        document.body.classList.add('fast-create-stamp');
        clearPeriodHighlights();
        highlightPeriodDays(wpId);
        if (!wp || !wp.default_start || !wp.default_end) {
          showNoDefaultsFlash(card);
          peHint.textContent = '\u26a0 ' + (wp ? wp.name : 'Workplace') + ' has no default shift . click days to open form';
        } else {
          peHint.textContent = wp.name + ' selected . click days to stamp ' + wp.default_start + '.' + wp.default_end;
        }
        return;
      }
    });
  });

  // ----- Gear icon â†’ default shift modal -----
  document.querySelectorAll('[data-wp-gear]').forEach(function(icon) {
    icon.addEventListener('click', function(e) {
      e.stopPropagation();
      openDefaultShiftModal(parseInt(icon.dataset.wpGear));
    });
  });

  // ----- Mark prior-period chips & set up drag/click for current-period chips -----
  document.querySelectorAll('.shift-chip--planned[draggable]').forEach(function(chip) {
    wireShiftChip(chip, parseInt(chip.dataset.workplaceId));
  });

  // ----- Click approved sessions to edit -----
  document.querySelectorAll('.shift-chip--editable-shift[data-session-id]').forEach(function(chip) {
    chip.addEventListener('click', function(e) {
      e.stopPropagation();
      openEditApprovedShiftModal(parseInt(chip.dataset.sessionId));
    });
  });

  // ----- Mark out-of-period days + add day indicators -----
  document.querySelectorAll('.planning-calendar .calendar-day[data-date]').forEach(function(td) {
    var dateStr = td.dataset.date;
    var validWps = WORKPLACES.filter(function(wp) { return isInPeriod(wp.id, dateStr); });
    if (validWps.length === 0) {
      td.classList.add('planning-day--no-create');
      return;
    }

    // Add frosted overlay with centered "+"
    var overlay = document.createElement('div');
    overlay.className = 'day-hover-overlay';
    overlay.innerHTML = '<span class="day-hover-plus">+</span>';
    td.appendChild(overlay);

    // Add bottom-right indicator
    if (validWps.length === 1) {
      var wp = validWps[0];
      var ind = document.createElement('span');
      ind.className = 'day-wp-indicator';
      ind.style.background = wp.color || 'var(--primary)';
      if (wp.custom_icon_url) {
        ind.innerHTML = '<img src="' + escapeHtml(wp.custom_icon_url) + '" alt="">';
      } else if (wp.icon) {
        ind.innerHTML = '<i class="bi ' + escapeHtml(wp.icon) + '" style="font-size:0.5rem;"></i>';
      } else {
        ind.textContent = wp.initials;
      }
      td.appendChild(ind);
    } else {
      var ind = document.createElement('span');
      ind.className = 'day-wp-indicator day-wp-indicator--multi';
      ind.textContent = '\u2026';
      td.appendChild(ind);
    }
  });

  // ----- Toggle chip-hover class so overlay hides when hovering a chip -----
  document.querySelectorAll('.planning-calendar .shift-chip').forEach(function(chip) {
    chip.addEventListener('mouseenter', function() {
      var td = chip.closest('.calendar-day');
      if (td) td.classList.add('chip-hover');
    });
    chip.addEventListener('mouseleave', function() {
      var td = chip.closest('.calendar-day');
      if (td) td.classList.remove('chip-hover');
    });
  });

  // ----- Period highlight helpers -----
  function highlightPeriodDays(wpId) {
    var wp = wpMap[wpId];
    if (!wp || !wp.period_start || !wp.period_end) return;
    var accentRgb = wp.accent_color ? hexToRgb(wp.accent_color) : null;
    document.querySelectorAll('.planning-calendar .calendar-day[data-date]').forEach(function(td) {
      var d = td.dataset.date;
      if (d >= wp.period_start && d <= wp.period_end && isInContract(wpId, d)) {
        td.classList.add('in-period-highlight');
        if (accentRgb) td.style.setProperty('--wp-accent-rgb', accentRgb);
      }
    });
  }

  function clearPeriodHighlights() {
    document.querySelectorAll('.in-period-highlight').forEach(function(td) {
      td.classList.remove('in-period-highlight');
      td.style.removeProperty('--wp-accent-rgb');
    });
  }

  function isInPeriod(wpId, dateStr) {
    var wp = wpMap[wpId];
    if (!wp || !wp.period_start || !wp.period_end) return true;
    return dateStr >= wp.period_start && dateStr <= wp.period_end;
  }

  // True when the date falls within one of the workplace's contracts
  function isInContract(wpId, dateStr) {
    var wp = wpMap[wpId];
    if (!wp || !wp.contract_intervals || !wp.contract_intervals.length) return true;
    return wp.contract_intervals.some(function(iv) {
      if (dateStr < iv.start) return false;
      if (iv.end && dateStr > iv.end) return false;
      return true;
    });
  }

  // A date is a valid drop target only if it's in the payroll period AND in contract
  function isValidDrop(wpId, dateStr) {
    return isInPeriod(wpId, dateStr) && isInContract(wpId, dateStr);
  }

  /**
   * For a date outside the current months payroll period, figure out which
   * payroll month it actually belongs to and return a user-friendly message.
   */
  function ordinalSuffix(n) {
    var s = ['th','st','nd','rd'];
    var v = n % 100;
    return n + (s[(v-20)%10] || s[v] || s[0]);
  }

  function outOfPeriodMessage(wpId, dateStr) {
    var wp = wpMap[wpId];
    var parts = dateStr.split('-');
    var day = parseInt(parts[2]);
    var dateMonth = parseInt(parts[1]);
    var dateYear = parseInt(parts[0]);

    var targetMonth, targetYear;
    if (dateStr > wp.period_end) {
      targetMonth = CURRENT_MONTH + 1;
      targetYear = CURRENT_YEAR;
      if (targetMonth > 12) { targetMonth = 1; targetYear++; }
    } else {
      targetMonth = CURRENT_MONTH - 1;
      targetYear = CURRENT_YEAR;
      if (targetMonth < 1) { targetMonth = 12; targetYear--; }
    }
    var targetName = MONTH_NAMES[String(targetMonth)];

    return {
      text: 'You are trying to plan a shift at ' + wp.name + ' for the ' + ordinalSuffix(day) + ' ' + MONTH_NAMES[String(dateMonth)] +
        ', which belongs to the ' + targetName + ' payroll.',
      hint: 'Please change the calendar to ' + targetName + ' to plan this shift.',
      targetMonth: targetMonth,
      targetYear: targetYear,
      targetName: targetName,
    };
  }

  function hexToRgb(hex) {
    var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return m ? parseInt(m[1],16)+','+parseInt(m[2],16)+','+parseInt(m[3],16) : null;
  }

  // ----- Warning modal helpers -----
  function showPeriodWarning(wpId, dateStr) {
    var info = outOfPeriodMessage(wpId, dateStr);
    document.getElementById('periodWarningTitle').textContent = 'Wrong payroll period';
    document.getElementById('periodWarningText').textContent = info.text;
    document.getElementById('periodWarningHint').textContent = info.hint;
    var go = document.getElementById('periodWarningGoBtn');
    document.getElementById('periodWarningGoBtnLabel').textContent = 'Go to ' + info.targetName;
    go.href = '?year=' + info.targetYear + '&month=' + info.targetMonth;
    go.style.display = '';
    new bootstrap.Modal(document.getElementById('periodWarningModal')).show();
  }

  // Variant for dragging an existing chip that belongs to another payroll
  // period — same modal, but worded for moving rather than planning.
  function showChipPeriodWarning(wpId, dateStr) {
    var info = outOfPeriodMessage(wpId, dateStr);
    document.getElementById('periodWarningTitle').textContent = 'Wrong payroll period';
    document.getElementById('periodWarningText').textContent =
      'This shift belongs to the ' + info.targetName + ' payroll period, so it can’t be moved from here.';
    document.getElementById('periodWarningHint').textContent =
      'Switch the calendar to ' + info.targetName + ' to move or edit it.';
    var go = document.getElementById('periodWarningGoBtn');
    document.getElementById('periodWarningGoBtnLabel').textContent = 'Go to ' + info.targetName;
    go.href = '?year=' + info.targetYear + '&month=' + info.targetMonth;
    go.style.display = '';
    new bootstrap.Modal(document.getElementById('periodWarningModal')).show();
  }

  function showContractWarning(wpId, dateStr) {
    var wp = wpMap[wpId];
    document.getElementById('periodWarningTitle').textContent = 'Outside contract dates';
    document.getElementById('periodWarningText').textContent =
      wp.name + ' has no active contract on ' + dateStr + '.';
    document.getElementById('periodWarningHint').textContent =
      'Adjust the contract dates (or add a contract) to cover this date before planning a shift.';
    // No month to jump to — hide the navigation button
    document.getElementById('periodWarningGoBtn').style.display = 'none';
    new bootstrap.Modal(document.getElementById('periodWarningModal')).show();
  }

  // ----- Drop targets (calendar days) -----
  document.querySelectorAll('.planning-calendar .calendar-day[data-date]').forEach(function(td) {
    td.addEventListener('dragover', function(e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (draggedWorkplaceId) {
        if (isValidDrop(draggedWorkplaceId, td.dataset.date)) {
          td.classList.add('drag-over');
        } else {
          td.classList.add('drag-over-invalid');
        }
      }
    });
    td.addEventListener('dragleave', function() {
      td.classList.remove('drag-over', 'drag-over-invalid');
    });
    td.addEventListener('drop', function(e) {
      e.preventDefault();
      td.classList.remove('drag-over', 'drag-over-invalid');
      var raw = e.dataTransfer.getData('text/plain');
      if (!raw) return;
      try { var data = JSON.parse(raw); } catch(_) { return; }
      var targetDate = td.dataset.date;

      if (data.type === 'new-shift') {
        // Block drops outside the payroll period or contract bounds
        if (!isInPeriod(data.workplace_id, targetDate)) {
          showPeriodWarning(data.workplace_id, targetDate);
          return;
        }
        if (!isInContract(data.workplace_id, targetDate)) {
          showContractWarning(data.workplace_id, targetDate);
          return;
        }
        if (fastCreateMode) {
          fastCreateShift(data.workplace_id, targetDate);
        } else {
          openNewShiftModal(data.workplace_id, targetDate);
        }
      } else if (data.type === 'move-shift') {
        // Block moves outside the shift's workplace period or contract
        var moveWpId = data.workplace_id;
        if (moveWpId && !isInPeriod(moveWpId, targetDate)) {
          showPeriodWarning(moveWpId, targetDate);
          return;
        }
        if (moveWpId && !isInContract(moveWpId, targetDate)) {
          showContractWarning(moveWpId, targetDate);
          return;
        }
        moveShift(data.shift_id, targetDate);
      }
    });

    // Click on empty day
    td.addEventListener('click', function(e) {
      if (e.target.closest('.shift-chip--planned') || e.target.closest('.shift-chip--approved') || e.target.closest('.wp-picker')) return;
      hideWpPicker();
      var dateStr = td.dataset.date;

      // In delete-all mode, delete all planned shifts for this day
      if (deleteAllMode) {
        deleteAllForDay(dateStr);
        return;
      }

      // In fast-create-stamp mode, stamp shift immediately (fastCreateShift gates bounds)
      if (fastCreateMode && fastCreateWpId) {
        fastCreateShift(fastCreateWpId, dateStr);
        return;
      }

      // In copy mode with a copied shift, paste immediately
      if (copyMode && copiedShift) {
        pasteShiftToDate(dateStr);
        return;
      }

      // Workplaces in payroll period, then those also within contract bounds
      var inPeriodWps = WORKPLACES.filter(function(wp) { return isInPeriod(wp.id, dateStr); });
      var validWps = inPeriodWps.filter(function(wp) { return isInContract(wp.id, dateStr); });

      if (validWps.length === 1) {
        openNewShiftModal(validWps[0].id, dateStr);
        return;
      }
      if (validWps.length > 1) {
        showWpPicker(td, dateStr, validWps);
        return;
      }
      // Nothing valid: explain why
      if (inPeriodWps.length === 0) {
        if (WORKPLACES.length > 0) showPeriodWarning(WORKPLACES[0].id, dateStr);
      } else {
        // In payroll period but no contract covers this date
        showContractWarning(inPeriodWps[0].id, dateStr);
      }
    });
  });

  // ----- Workplace picker popup -----
  var wpPickerEl = document.getElementById('wpPicker');

  function showWpPicker(td, dateStr, validWps) {
    wpPickerEl.innerHTML = '';
    validWps.forEach(function(wp) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'wp-picker__item';
      var accent = wp.accent_color || wp.color;
      var rgb = accent && hexToRgb(accent);
      btn.style.background = rgb ? 'rgba(' + rgb + ',0.15)' : 'rgba(var(--primary-rgb),0.15)';

      var avatarBg = wp.color ? escapeHtml(wp.color) : 'var(--primary)';
      var avatarHtml;
      if (wp.custom_icon_url) {
        avatarHtml = '<span class="wp-picker__avatar" style="background:' + avatarBg + ';"><img src="' + escapeHtml(wp.custom_icon_url) + '" alt=""></span>';
      } else if (wp.icon) {
        avatarHtml = '<span class="wp-picker__avatar" style="background:' + avatarBg + ';"><i class="bi ' + escapeHtml(wp.icon) + '" style="font-size:0.55rem;"></i></span>';
      } else {
        avatarHtml = '<span class="wp-picker__avatar" style="background:' + avatarBg + ';">' + escapeHtml(wp.initials) + '</span>';
      }
      btn.innerHTML = avatarHtml + '<span>' + escapeHtml(wp.name) + '</span>';
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        hideWpPicker();
        openNewShiftModal(wp.id, dateStr);
      });
      wpPickerEl.appendChild(btn);
    });

    // Position near the clicked cell
    var rect = td.getBoundingClientRect();
    wpPickerEl.style.position = 'fixed';
    wpPickerEl.style.left = rect.left + 'px';
    wpPickerEl.style.top = (rect.bottom + 4) + 'px';
    wpPickerEl.classList.add('show');
  }

  function hideWpPicker() {
    wpPickerEl.classList.remove('show');
  }

  // Close picker when clicking outside
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.wp-picker') && !e.target.closest('.calendar-day')) {
      hideWpPicker();
    }
  });

  // ----- Modal logic -----
  var shiftModal = new bootstrap.Modal(document.getElementById('shiftModal'));

  // Auto-focus start time hour position when modal opens
  document.getElementById('shiftModal').addEventListener('shown.bs.modal', function() {
    var startEl = document.getElementById('shiftStart');
    startEl.focus();
    startEl.setSelectionRange(0, 2);
  });

  // ----- Per-shift calendar-invite control (planned shifts only) -----
  // Invites are sent once and re-sent only on request; this is that request.
  var INVITE_URL = cfg.shiftInviteUrl || '';
  var inviteBlock = document.getElementById('shiftInviteBlock');
  var inviteBtn = document.getElementById('shiftInviteBtn');
  var inviteStatus = document.getElementById('shiftInviteStatus');
  var inviteLabel = document.getElementById('shiftInviteBtnLabel');
  var inviteShiftId = null;
  var inviteReloadOnClose = false;

  function hideInviteBlock() {
    if (inviteBlock) inviteBlock.classList.add('d-none');
    inviteShiftId = null;
  }

  // Reveal + label from the shift's invite state (only for planned shifts).
  function setupInviteBlock(shift) {
    if (!inviteBlock || !INVITE_URL) return;
    if (shift.invite_past) { hideInviteBlock(); return; }  // past → out of scope
    inviteShiftId = shift.id;
    inviteBtn.disabled = false;
    if (shift.has_active_invite) {
      inviteBlock.classList.remove('d-none');
      inviteStatus.innerHTML = '<i class="bi bi-envelope-check me-1" style="color:var(--info);"></i>Calendar invite sent';
      inviteLabel.textContent = 'Re-send invite';
    } else if (shift.invite_eligible) {
      inviteBlock.classList.remove('d-none');
      inviteStatus.textContent = 'No invite sent yet';
      inviteLabel.textContent = 'Send invite';
    } else {
      hideInviteBlock();
    }
  }

  if (inviteBtn) {
    inviteBtn.addEventListener('click', function () {
      if (!inviteShiftId || !INVITE_URL) return;
      var url = INVITE_URL.replace('/0/', '/' + inviteShiftId + '/');
      var orig = inviteLabel.textContent;
      inviteBtn.disabled = true;
      inviteLabel.textContent = 'Sending…';
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
        body: JSON.stringify({}),
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (!data.ok) {
          inviteStatus.textContent = data.error || 'Could not send invite.';
          inviteBtn.disabled = false;
          inviteLabel.textContent = orig;
          return;
        }
        inviteReloadOnClose = true;  // refresh chips on close to show the marker
        inviteStatus.innerHTML = '<i class="bi bi-check-circle-fill me-1" style="color:var(--success);"></i>' + (data.message || 'Invite sent.');
        inviteLabel.textContent = 'Re-send invite';
        inviteBtn.disabled = false;
      }).catch(function () {
        inviteStatus.textContent = 'Could not send invite.';
        inviteBtn.disabled = false;
        inviteLabel.textContent = orig;
      });
    });
  }

  document.getElementById('shiftModal').addEventListener('hidden.bs.modal', function () {
    if (inviteReloadOnClose) { inviteReloadOnClose = false; location.reload(); }
  });

  function openNewShiftModal(workplaceId, dateStr, showFastCreateWarn) {
    var wp = wpMap[workplaceId];
    if (!wp) return;
    // Never open the create modal outside the payroll period or contract bounds
    if (!isInPeriod(workplaceId, dateStr)) { showPeriodWarning(workplaceId, dateStr); return; }
    if (!isInContract(workplaceId, dateStr)) { showContractWarning(workplaceId, dateStr); return; }
    document.getElementById('shiftModalTitle').textContent = 'Plan Shift';
    document.getElementById('shiftSaveLabel').textContent = 'Save Shift';
    document.getElementById('shiftDeleteBtn').classList.add('d-none');
    document.getElementById('shiftId').value = '';
    document.getElementById('shiftIsSession').value = '';
    document.getElementById('shiftWorkplaceId').value = workplaceId;
    window.setDateValue(document.getElementById('shiftDate'), dateStr);
    window.setTimeValue(document.getElementById('shiftStart'), wp.default_start || '');
    window.setTimeValue(document.getElementById('shiftEnd'), wp.default_end || '');
    document.getElementById('shiftBreak').value = wp.default_break ?? 0;
    document.getElementById('shiftType').value = wp.default_type || 'on_site';
    document.getElementById('shiftNotes').value = '';
    document.getElementById('shiftModalErrors').classList.add('d-none');
    document.getElementById('shiftModalOverlap').classList.add('d-none');
    document.getElementById('shiftApprovedBanner').classList.add('d-none');
    document.getElementById('shiftTimeRow').style.outline = '';
    var fcWarn = document.getElementById('shiftModalFastCreateWarn');
    if (showFastCreateWarn) { fcWarn.classList.remove('d-none'); } else { fcWarn.classList.add('d-none'); }
    hideInviteBlock();
    updateModalBanner(wp);
    calcShiftDuration();
    checkOverlapsLive();
    shiftModal.show();
  }

  function openEditShiftModal(shiftId) {
    var chip = document.querySelector('[data-shift-id="' + shiftId + '"]');
    if (!chip) return;
    var url = cfg.shiftUpdateUrl.replace('/0/', '/' + shiftId + '/');
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify({}),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) return;
      var s = data.shift;
      var wp = wpMap[s.workplace_id];
      document.getElementById('shiftModalTitle').textContent = 'Edit Planned Shift';
      document.getElementById('shiftSaveLabel').textContent = 'Update Shift';
      document.getElementById('shiftDeleteBtn').classList.remove('d-none');
      document.getElementById('shiftId').value = s.id;
      document.getElementById('shiftIsSession').value = '';
      document.getElementById('shiftWorkplaceId').value = s.workplace_id;
      window.setDateValue(document.getElementById('shiftDate'), s.date);
      window.setTimeValue(document.getElementById('shiftStart'), s.start_time);
      window.setTimeValue(document.getElementById('shiftEnd'), s.end_time);
      document.getElementById('shiftBreak').value = s.break_minutes;
      document.getElementById('shiftType').value = s.shift_type;
      document.getElementById('shiftNotes').value = s.notes;
      document.getElementById('shiftModalErrors').classList.add('d-none');
      document.getElementById('shiftModalOverlap').classList.add('d-none');
      document.getElementById('shiftApprovedBanner').classList.add('d-none');
      document.getElementById('shiftTimeRow').style.outline = '';
      setupInviteBlock(s);
      if (wp) updateModalBanner(wp);
      calcShiftDuration();
      checkOverlapsLive();
      shiftModal.show();
    });
  }

  function openEditApprovedShiftModal(sessionId) {
    var url = cfg.sessionUpdateUrl.replace('/0/', '/' + sessionId + '/');
    fetch(url).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) return;
      var s = data.shift;
      var wp = wpMap[s.workplace_id];
      document.getElementById('shiftModalTitle').textContent = 'Edit Approved Shift';
      document.getElementById('shiftSaveLabel').textContent = 'Update Shift';
      document.getElementById('shiftDeleteBtn').classList.remove('d-none');
      document.getElementById('shiftId').value = '';
      document.getElementById('shiftIsSession').value = s.id;
      document.getElementById('shiftWorkplaceId').value = s.workplace_id;
      window.setDateValue(document.getElementById('shiftDate'), s.date);
      window.setTimeValue(document.getElementById('shiftStart'), s.start_time);
      window.setTimeValue(document.getElementById('shiftEnd'), s.end_time);
      document.getElementById('shiftBreak').value = s.break_minutes;
      document.getElementById('shiftType').value = s.shift_type;
      document.getElementById('shiftNotes').value = s.notes;
      document.getElementById('shiftModalErrors').classList.add('d-none');
      document.getElementById('shiftModalOverlap').classList.add('d-none');
      document.getElementById('shiftTimeRow').style.outline = '';
      document.getElementById('shiftApprovedBanner').classList.remove('d-none');
      hideInviteBlock();  // invite control is planned-shifts only
      if (wp) updateModalBanner(wp);
      calcShiftDuration();
      checkOverlapsLive();
      shiftModal.show();
    });
  }

  function updateModalBanner(wp) {
    var avatar = document.getElementById('shiftModalAvatar');
    avatar.style.background = wp.color || 'var(--primary)';
    if (wp.custom_icon_url) {
      avatar.innerHTML = '<img src="' + escapeHtml(wp.custom_icon_url) + '" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">';
    } else if (wp.icon) {
      avatar.innerHTML = '<i class="bi ' + escapeHtml(wp.icon) + '" style="font-size:0.7rem;"></i>';
    } else {
      avatar.textContent = wp.initials;
    }
    document.getElementById('shiftModalWorkplace').textContent = wp.name;
  }

  // ----- Live overlap check -----
  var overlapTimer = null;
  function checkOverlapsLive() {
    clearTimeout(overlapTimer);
    overlapTimer = setTimeout(doOverlapCheck, 300);
  }

  function doOverlapCheck() {
    var dateVal = document.getElementById('shiftDate').value;
    var startVal = document.getElementById('shiftStart').value;
    var endVal = document.getElementById('shiftEnd').value;
    var excludeId = document.getElementById('shiftId').value;
    var isSession = document.getElementById('shiftIsSession').value;
    if (!dateVal || !startVal || !endVal) {
      document.getElementById('shiftModalOverlap').classList.add('d-none');
      document.getElementById('shiftTimeRow').style.outline = '';
      return;
    }
    var url = cfg.checkOverlapsUrl + '?date=' +
      encodeURIComponent(dateVal) + '&start=' + encodeURIComponent(startVal) +
      '&end=' + encodeURIComponent(endVal);
    if (excludeId) url += '&exclude=' + excludeId;
    if (isSession) url += '&exclude_session=' + isSession;
    fetch(url).then(function(r) { return r.json(); }).then(function(data) {
      var box = document.getElementById('shiftModalOverlap');
      var timeRow = document.getElementById('shiftTimeRow');
      if (data.overlaps && data.overlaps.length > 0) {
        var parts = data.overlaps.map(function(o) {
          return o.workplace + ' (' + o.start + '.' + o.end + ')';
        });
        document.getElementById('shiftOverlapText').textContent = 'Overlaps with: ' + parts.join(', ');
        box.classList.remove('d-none');
        timeRow.style.outline = '2px solid var(--warning)';
        timeRow.style.outlineOffset = '2px';
        timeRow.style.borderRadius = '6px';
      } else {
        box.classList.add('d-none');
        timeRow.style.outline = '';
      }
    }).catch(function() {});
  }

  // ----- Duration calculation + time validation -----
  var saveBtn = document.querySelector('#shiftForm button[type="submit"]');

  function fmtSpan(min) {
    return Math.floor(min/60) + 'h ' + (min%60) + 'm (' + toDanish((min/60).toFixed(2)) + 'h)';
  }

  function calcShiftDuration() {
    var start = document.getElementById('shiftStart').value;
    var end = document.getElementById('shiftEnd').value;
    var brk = parseInt(document.getElementById('shiftBreak').value) || 0;
    var display = document.getElementById('shiftDuration');
    var grossRow = document.getElementById('shiftDurationGrossRow');
    var startEl = document.getElementById('shiftStart');
    var endEl = document.getElementById('shiftEnd');

    grossRow.classList.add('d-none');

    if (!start || !end) {
      display.textContent = '.';
      startEl.classList.remove('is-invalid');
      endEl.classList.remove('is-invalid');
      saveBtn.disabled = false;
      return;
    }

    var sp = start.split(':').map(Number);
    var ep = end.split(':').map(Number);
    var grossMin = (ep[0]*60+ep[1]) - (sp[0]*60+sp[1]);

    if (grossMin <= 0) {
      display.textContent = 'End time must be after start time';
      display.style.color = 'var(--danger)';
      startEl.classList.add('is-invalid');
      endEl.classList.add('is-invalid');
      saveBtn.disabled = true;
      return;
    }

    display.style.color = '';
    startEl.classList.remove('is-invalid');
    endEl.classList.remove('is-invalid');
    saveBtn.disabled = false;

    var netMin = Math.max(grossMin - brk, 0);
    display.textContent = fmtSpan(netMin);
    // Only worth a line of its own when a break actually splits the two.
    if (brk > 0) {
      document.getElementById('shiftDurationGrossLabel').textContent = 'Before ' + brk + ' min break';
      document.getElementById('shiftDurationGross').textContent = fmtSpan(grossMin);
      grossRow.classList.remove('d-none');
    }
  }
  ['shiftStart', 'shiftEnd', 'shiftBreak'].forEach(function(id) {
    var el = document.getElementById(id);
    el.addEventListener('input', function() { calcShiftDuration(); checkOverlapsLive(); });
    el.addEventListener('change', function() { calcShiftDuration(); checkOverlapsLive(); });
  });
  document.getElementById('shiftDate').addEventListener('change', checkOverlapsLive);

  // ----- Form submit -----
  document.getElementById('shiftForm').addEventListener('submit', function(e) {
    e.preventDefault();
    var shiftId = document.getElementById('shiftId').value;
    var sessionId = document.getElementById('shiftIsSession').value;
    var url;

    var body = {
      workplace_id: parseInt(document.getElementById('shiftWorkplaceId').value),
      date: document.getElementById('shiftDate').value,
      start_time: document.getElementById('shiftStart').value,
      end_time: document.getElementById('shiftEnd').value,
      break_minutes: parseInt(document.getElementById('shiftBreak').value) || 0,
      shift_type: document.getElementById('shiftType').value,
      notes: document.getElementById('shiftNotes').value,
    };

    if (sessionId) {
      url = cfg.sessionUpdateUrl.replace('/0/', '/' + sessionId + '/');
    } else if (shiftId) {
      url = cfg.shiftUpdateUrl.replace('/0/', '/' + shiftId + '/');
    } else {
      url = API_BASE;
    }

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify(body),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) {
        document.getElementById('shiftModalErrors').textContent = data.error || 'Error saving shift.';
        document.getElementById('shiftModalErrors').classList.remove('d-none');
        return;
      }
      shiftModal.hide();
      // New planned shift: insert chip via JS instead of reloading
      if (!shiftId && !sessionId && data.shift) {
        var newDateStr = data.shift.date;
        var newWp = wpMap[data.shift.workplace_id];
        var newTd = document.querySelector('.planning-calendar td[data-date="' + newDateStr + '"]');
        if (newTd) {
          var newContainer = newTd.querySelector('.planned-shifts-container');
          if (newContainer) {
            var newChip = buildShiftChip(data.shift, newWp);
            insertChipSorted(newContainer, newChip);
            updateDayHourBadge(newTd);
            if (newWp) updateWpCardProgress(data.shift.workplace_id);
          }
        }
        recheckOverlaps();
      } else {
        location.reload();
      }
    });
  });

  // ----- Delete button -----
  document.getElementById('shiftDeleteBtn').addEventListener('click', function() {
    var shiftId = document.getElementById('shiftId').value;
    var sessionId = document.getElementById('shiftIsSession').value;
    var url;
    if (sessionId) {
      if (!confirm('Delete this approved work session?')) return;
      url = cfg.sessionUpdateUrl.replace('/0/', '/' + sessionId + '/');
    } else {
      if (!shiftId || !confirm('Delete this planned shift?')) return;
      url = cfg.shiftUpdateUrl.replace('/0/', '/' + shiftId + '/');
    }
    fetch(url, {
      method: 'DELETE',
      headers: { 'X-CSRFToken': CSRF },
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) { shiftModal.hide(); location.reload(); }
    });
  });

  // ----- Move shift (drag to new date) -----
  function moveShift(shiftId, newDate) {
    var url = cfg.shiftUpdateUrl.replace('/0/', '/' + shiftId + '/');
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify({ date: newDate }),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) {
        if (data.overlaps && data.overlaps.length > 0) {
          // Time conflict on the target date . open editor so user can adjust
          openEditShiftModal(shiftId);
        } else {
          location.reload();
        }
      }
    });
  }

  // ----- Default shift config modal -----
  var defModal = new bootstrap.Modal(document.getElementById('defaultShiftModal'));
  var defWorkplaceId = null;

  function openDefaultShiftModal(wpId) {
    var wp = wpMap[wpId];
    if (!wp) return;
    defWorkplaceId = wpId;
    var banner = document.getElementById('defBanner');
    banner.innerHTML = '<span class="wp-avatar" style="background:' + (wp.color ? escapeHtml(wp.color) : 'var(--primary)') +
      ';width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:0.6rem;font-weight:700;color:var(--on-accent);">' +
      escapeHtml(wp.initials) + '</span><strong class="small">' + escapeHtml(wp.name) + '</strong>';
    var hasDefault = !!(wp.default_start && wp.default_end);
    document.getElementById('defToggle').checked = hasDefault;
    document.getElementById('defFields').style.display = hasDefault ? '' : 'none';
    document.getElementById('saveDefaultShift').style.display = hasDefault ? '' : 'none';
    updateDefDescription(hasDefault);
    window.setTimeValue(document.getElementById('defStart'), wp.default_start || '');
    window.setTimeValue(document.getElementById('defEnd'), wp.default_end || '');
    document.getElementById('defBreak').value = wp.default_break || 0;
    document.getElementById('defType').value = wp.default_type || 'on_site';
    defModal.show();
  }

  function updateDefDescription(on) {
    document.getElementById('defDescription').textContent = on
      ? 'New shifts will be pre-filled with these values.'
      : 'New shifts will not be pre-filled.';
  }

  document.getElementById('defToggle').addEventListener('change', function() {
    document.getElementById('defFields').style.display = this.checked ? '' : 'none';
    document.getElementById('saveDefaultShift').style.display = this.checked ? '' : 'none';
    updateDefDescription(this.checked);
    if (!this.checked) {
      window.setTimeValue(document.getElementById('defStart'), '');
      window.setTimeValue(document.getElementById('defEnd'), '');
      document.getElementById('defBreak').value = 0;
      document.getElementById('defType').value = 'on_site';
      saveDefaultShift(true);
    }
  });

  function saveDefaultShift(autoClose) {
    if (!defWorkplaceId) return;
    var wp = wpMap[defWorkplaceId];
    var body = {
      start_time: document.getElementById('defStart').value,
      end_time: document.getElementById('defEnd').value,
      break_minutes: parseInt(document.getElementById('defBreak').value) || 0,
      shift_type: document.getElementById('defType').value,
    };
    var url = cfg.defaultShiftUrl.replace('/0/', '/' + defWorkplaceId + '/');
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify(body),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) {
        wp.default_start = body.start_time;
        wp.default_end = body.end_time;
        wp.default_break = body.break_minutes;
        wp.default_type = body.shift_type;
        if (autoClose) {
          defModal.hide();
        } else {
          var btn = document.getElementById('saveDefaultShift');
          btn.textContent = 'Saved!';
          btn.classList.replace('btn-primary', 'btn-success');
          setTimeout(function() {
            btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Default';
            btn.classList.replace('btn-success', 'btn-primary');
            defModal.hide();
          }, 800);
        }
      }
    });
  }

  document.getElementById('saveDefaultShift').addEventListener('click', function() {
    saveDefaultShift(false);
  });

  // ----- Direction 1: personal-calendar busy overlay -----
  // Fetches read-only "busy" blocks from the calendar_sync busy endpoint and
  // drops them into day cells. Each busy chip is marked .shift-chip (so the
  // existing recheckOverlaps() counts it, flagging shift↔busy clashes) plus
  // .busy-chip (muted, non-interactive styling). Toggle state is remembered in
  // localStorage. Fails soft: any fetch/parse problem just shows no overlay.
  var BUSY_URL = cfg.busyUrl;
  var CAL_COUNT = parseInt(cfg.calendarCount || '1', 10) || 1;
  var CAL_WORD = CAL_COUNT > 1 ? 'calendars' : 'calendar';
  var CAL_ICON = '<i class="bi bi-calendar-heart me-1"></i>';
  var SHOW_CALENDAR_KEY = 'bitgigs.planning.showCalendar';
  var showCalendarBtn = document.getElementById('showCalendarToggle');
  var busyLegend = document.querySelector('[data-busy-legend]');

  function busyContainerFor(dateStr) {
    return document.querySelector(
      '.planning-calendar .planned-shifts-container[data-date="' + dateStr + '"]'
    );
  }

  function renderBusyChip(cell) {
    var chip = document.createElement('div');
    chip.className = 'shift-chip busy-chip';
    chip.style.setProperty('--busy-color', cell.color || 'var(--text-muted)');
    // All-day blocks get a non-time label so recheckOverlaps() skips them (they
    // shouldn't flag a timed shift as clashing); timed blocks use the HH:MM-HH:MM
    // shape the overlap check parses.
    var timeText = cell.all_day ? 'All day' : (cell.start_time + '-' + cell.end_time);
    var label = cell.summary || 'Busy';
    chip.title = 'Busy — ' + label + (cell.all_day ? ' (all day)' : ' ' + timeText);
    chip.innerHTML =
      '<i class="bi bi-calendar-heart busy-chip__icon"></i>' +
      '<small class="shift-chip__time">' + escapeHtml(timeText) + '</small>' +
      '<small class="busy-chip__label">' + escapeHtml(label) + '</small>';
    return chip;
  }

  function removeBusyChips() {
    document.querySelectorAll('.planning-calendar .busy-chip').forEach(function(c) {
      c.remove();
    });
  }

  function renderBusyOverlay(cells) {
    removeBusyChips();
    cells.forEach(function(cell) {
      var container = busyContainerFor(cell.date);
      if (!container) return;
      container.insertBefore(renderBusyChip(cell), container.firstChild);
    });
    recheckOverlaps();
  }

  // Reveal (or hide) the "External calendar event" swatch in the help panel.
  // Only shown while the overlay is active on the planning page.
  function setBusyLegend(on) {
    if (busyLegend) busyLegend.classList.toggle('d-none', !on);
  }

  // Button visuals mirror two existing idioms: the Power Edit toggle
  // (btn-outline-primary at rest, filled btn-primary when active) and the
  // Settings → Email Test button's busy look (a disabled btn-primary renders as
  // the greyscale gradient, with a spinner + label) while feeds are polled.
  // Label flips Show ↔ Hide and stays singular/plural with the calendar count.
  function setBtnVisual(state) {
    if (!showCalendarBtn) return;
    showCalendarBtn.classList.toggle('btn-outline-primary', state === 'off');
    showCalendarBtn.classList.toggle('btn-primary', state !== 'off');
    if (state === 'loading') {
      showCalendarBtn.disabled = true;
      showCalendarBtn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-1"></span>Fetching ' + CAL_WORD + '…';
    } else {
      showCalendarBtn.disabled = false;
      showCalendarBtn.innerHTML =
        CAL_ICON + (state === 'on' ? 'Hide my ' : 'Show my ') + CAL_WORD;
    }
  }

  // The visible planning grid can reach well past the selected month when a
  // workplace has an offset payroll period (e.g. JKF's 20th→21st), so ask the
  // server for the exact span of rendered day cells rather than the month —
  // otherwise the leading/trailing days show no busy blocks.
  function visibleDateRange() {
    var dates = Array.from(
      document.querySelectorAll('.planning-calendar td[data-date]')
    ).map(function(td) { return td.dataset.date; }).filter(Boolean).sort();
    return dates.length ? { start: dates[0], end: dates[dates.length - 1] } : null;
  }

  // Session cache of the last fetched busy cells. Turning the overlay on hits
  // the network once; after that a passive reload (a shift edit re-rendering the
  // page, month navigation, …) restores the chips from here without re-polling
  // the provider. Cleared when the tab closes — sessionStorage, not localStorage.
  var BUSY_CACHE_KEY = 'bitgigs.planning.busyCache';
  // Fingerprint of the calendars' colour/enabled state (server-computed). Stored
  // with the cache so a colour change (which bumps the token) invalidates the
  // stale cached chips and triggers a re-fetch — see loadBusyCache.
  var BUSY_TOKEN = cfg.busyToken || '';
  function saveBusyCache(cells) {
    try {
      sessionStorage.setItem(
        BUSY_CACHE_KEY, JSON.stringify({ token: BUSY_TOKEN, cells: cells || [] })
      );
    } catch (e) {}
  }
  function loadBusyCache() {
    // Return the cached cells only when they were stored under the *current*
    // config token. A calendar colour or enabled-state edit bumps the token, so
    // stale chips are ignored and setCalendarShown re-fetches (from the server's
    // ~15 min feed cache, so no external poll). An old bare-array cache from
    // before this format has no token → treated as a miss, self-healing.
    try {
      var raw = sessionStorage.getItem(BUSY_CACHE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || parsed.token !== BUSY_TOKEN) return null;
      return parsed.cells || null;
    } catch (e) { return null; }
  }

  function loadBusyOverlay(refresh) {
    if (!BUSY_URL) return;
    var range = visibleDateRange();
    var url = BUSY_URL + (range
      ? '?start=' + range.start + '&end=' + range.end
      : '?year=' + CURRENT_YEAR + '&month=' + CURRENT_MONTH) +
      (refresh ? '&refresh=1' : '');
    setBtnVisual('loading');
    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function(r) { return r.ok ? r.json() : { busy: [] }; })
      .then(function(data) {
        var cells = data.busy || [];
        saveBusyCache(cells);
        renderBusyOverlay(cells);
      })
      .catch(function() { /* fail soft — no overlay */ })
      .finally(function() { setBtnVisual('on'); });
  }

  var calendarOn = false;

  // Turning the overlay on is the *only* thing that polls the provider (a fresh
  // fetch, refresh=1 to bust the ~15 min server cache) — pressing the button
  // means "show my calendar now". A passive restore on page load renders the
  // session-cached cells instead, so reloads caused by editing a shift, or month
  // navigation, never re-hit the feed. Re-poll = simply toggle off then on.
  function setCalendarShown(on, opts) {
    opts = opts || {};
    calendarOn = on;
    setBusyLegend(on);
    if (on) {
      if (opts.refresh) {
        loadBusyOverlay(true);  // deliberate turn-on → fresh poll, 'loading' → 'on'
      } else {
        var cached = loadBusyCache();
        if (cached) {
          renderBusyOverlay(cached);  // restore from this session's cache, no poll
          setBtnVisual('on');
        } else {
          loadBusyOverlay(false);  // first time this session → populate the cache once
        }
      }
    } else {
      setBtnVisual('off');
      removeBusyChips();
      recheckOverlaps();
    }
    if (opts.persist) {
      try { localStorage.setItem(SHOW_CALENDAR_KEY, on ? '1' : '0'); } catch (e) {}
    }
  }

  if (showCalendarBtn) {
    showCalendarBtn.addEventListener('click', function() {
      setCalendarShown(!calendarOn, { persist: true, refresh: !calendarOn });
    });
    var pref = '0';
    try { pref = localStorage.getItem(SHOW_CALENDAR_KEY) || '0'; } catch (e) {}
    if (pref === '1') setCalendarShown(true, { persist: false, refresh: false });
  }

  // ----- Direction 2: send calendar invites for the shown planned shifts -----
  // Emails real invites, so it's confirmed first. On success we reload, letting
  // the server re-render chips with the invited marker. Uses the same greyscale-
  // gradient busy look as the other buttons while the batch sends.
  var SEND_INVITES_URL = cfg.sendInvitesUrl;
  var sendInvitesBtn = document.getElementById('sendInvitesBtn');
  if (sendInvitesBtn && SEND_INVITES_URL) {
    sendInvitesBtn.addEventListener('click', function() {
      if (!window.confirm(
        'Send calendar invites for the planned shifts shown?\n\n' +
        'Each invite-enabled workplace’s recipients (and your own calendar) ' +
        'will be emailed. Already-synced shifts are skipped.'
      )) return;

      var range = visibleDateRange();
      var url = SEND_INVITES_URL + (range
        ? '?start=' + range.start + '&end=' + range.end
        : '?year=' + CURRENT_YEAR + '&month=' + CURRENT_MONTH);

      sendInvitesBtn.disabled = true;
      sendInvitesBtn.classList.remove('btn-outline-primary');
      sendInvitesBtn.classList.add('btn-primary');
      sendInvitesBtn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-1"></span>Sending…';

      fetch(url, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF, 'X-Requested-With': 'XMLHttpRequest' },
      })
        .then(function(r) { return r.ok ? r.json() : { activated: 0 }; })
        .then(function() { window.location.reload(); })
        .catch(function() {
          sendInvitesBtn.disabled = false;
          sendInvitesBtn.classList.add('btn-outline-primary');
          sendInvitesBtn.classList.remove('btn-primary');
          sendInvitesBtn.innerHTML = '<i class="bi bi-envelope-paper me-1"></i>Send invites';
        });
    });
  }

  // DOM is the single source of truth for the overlap warning: recompute on
  // load so the banner + amber highlights always match what's rendered.
  recheckOverlaps();
})();
