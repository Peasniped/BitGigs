/* Unified period picker for the analytics filter bar: one inline Air Datepicker
   range calendar plus quick-pick chips (years, YTD, and — on rate history — All
   time). Writes the hidden period_mode / year / start / end fields the form
   submits, so the backend contract (year = Jan 1–Dec 31, range = start/end,
   all = whole history) is unchanged. Needs ADP_EN_LOCALE + AirDatepicker from
   app.js. */
function initPeriodPicker() {
  if (typeof AirDatepicker === 'undefined') return;
  var cal = document.getElementById('periodRangeCal');
  if (!cal) return;

  var fMode = document.getElementById('periodModeField');
  var fYear = document.getElementById('periodYearField');
  var fStart = document.getElementById('periodStartField');
  var fEnd = document.getElementById('periodEndField');
  var label = document.getElementById('periodCardValue');

  function pad(n) { return ('0' + n).slice(-2); }
  function iso(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function fmt(d) {
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }
  function parseIso(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
  }
  function isFullYear(d1, d2) {
    return d1.getFullYear() === d2.getFullYear()
      && d1.getMonth() === 0 && d1.getDate() === 1
      && d2.getMonth() === 11 && d2.getDate() === 31;
  }

  var guard = false;  // suppress onSelect while we set dates programmatically

  function applyRange(d1, d2) {
    if (d2 < d1) { var t = d1; d1 = d2; d2 = t; }
    fStart.value = iso(d1);
    fEnd.value = iso(d2);
    if (isFullYear(d1, d2)) {
      // A full Jan–Dec span is submitted as the backend's calendar-year mode.
      fMode.value = 'year';
      fYear.value = d1.getFullYear();
      if (label) label.textContent = String(d1.getFullYear());
    } else {
      fMode.value = 'range';
      if (label) label.textContent = fmt(d1) + ' → ' + fmt(d2);
    }
  }

  var startD = parseIso(fStart.value);
  var endD = parseIso(fEnd.value);
  var selected = (startD && endD) ? [startD, endD] : [];

  var dp = new AirDatepicker(cal, {
    inline: true,
    range: true,
    locale: ADP_EN_LOCALE,
    dateFormat: 'dd/MM/yyyy',
    multipleDatesSeparator: ' – ',
    selectedDates: selected,
    startDate: startD || new Date(),
    onSelect: function (o) {
      if (guard) return;
      var dates = o.date;
      if (Array.isArray(dates) && dates.length === 2) {
        applyRange(dates[0], dates[1]);
      }
    }
  });

  // Clicks inside the inline calendar (esp. month/year nav, which detaches
  // nodes mid-click) must not bubble to Bootstrap's outside-close handler.
  cal.addEventListener('mousedown', function (e) { e.stopPropagation(); });
  cal.addEventListener('click', function (e) { e.stopPropagation(); });

  function setRange(d1, d2) {
    guard = true;
    dp.clear();
    dp.selectDate([d1, d2]);
    guard = false;
    applyRange(d1, d2);
  }

  // When there are many years the strip scrolls horizontally; center the
  // current-year chip. Done on dropdown-show because a hidden element has no
  // measurable width.
  function centerCurrentYear() {
    var strip = document.querySelector('#periodQuickPicks .period-quick-years');
    if (!strip) return;
    var cur = strip.querySelector('.period-quick-current');
    if (cur && strip.scrollWidth > strip.clientWidth) {
      strip.scrollLeft = cur.offsetLeft - strip.clientWidth / 2 + cur.clientWidth / 2;
    }
  }
  var dropdown = document.getElementById('periodDropdown');
  if (dropdown) dropdown.addEventListener('shown.bs.dropdown', centerCurrentYear);

  var quick = document.getElementById('periodQuickPicks');
  if (quick) {
    quick.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-quick-year],[data-quick]');
      if (!btn) return;
      e.preventDefault();
      if (btn.dataset.quickYear) {
        var y = parseInt(btn.dataset.quickYear, 10);
        setRange(new Date(y, 0, 1), new Date(y, 11, 31));
      } else if (btn.dataset.quick === 'all') {
        // Rate history only — whole history, no date bounds.
        guard = true; dp.clear(); guard = false;
        fMode.value = 'all';
        if (label) label.textContent = 'All time';
      }
    });
  }
}
window.initPeriodPicker = initPeriodPicker;
