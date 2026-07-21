/* Settings → Email: provider presets and the staged connection test.
 *
 * The test posts to core:email-test and renders one row per stage of a real
 * SMTP session (resolve → connect → TLS → auth → optional send). The first
 * failing row is the answer, so it carries the diagnosis and a hint; the rows
 * after it stay "not reached" rather than pretending to be fine.
 */
(function () {
  var root = document.querySelector('[data-email-settings]');
  if (!root) return;   // Another settings tab is rendered.

  // ── Clear-configuration confirm ────────────────────────────────────────────
  root.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  // ── Sender auto-fills from the username while it's blank ───────────────────
  // Most providers require the from-address to equal the account you sign in as,
  // so mirror the username into an empty From field as you type — but back off
  // the moment the operator edits From themselves (a pre-filled value counts as
  // already-theirs). Same "only while untouched" rule the help-editor slug uses.
  var usernameInput = document.getElementById('id_username');
  var fromInput = document.getElementById('id_from_email');
  if (usernameInput && fromInput) {
    var fromTouched = fromInput.value.trim() !== '';
    fromInput.addEventListener('input', function () { fromTouched = true; });
    usernameInput.addEventListener('input', function () {
      if (!fromTouched) fromInput.value = usernameInput.value;
    });
  }

  // ── Provider presets ───────────────────────────────────────────────────────
  var noteBox = root.querySelector('[data-preset-note]');

  root.querySelectorAll('[data-email-preset]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var host = document.getElementById('id_host');
      var port = document.getElementById('id_port');
      var security = document.getElementById('id_security');
      if (host) host.value = btn.dataset.host;
      if (port) port.value = btn.dataset.port;
      if (security) security.value = btn.dataset.security;

      root.querySelectorAll('[data-email-preset]').forEach(function (other) {
        other.classList.toggle('active', other === btn);
      });
      if (noteBox) {
        noteBox.textContent = btn.dataset.note || '';
        noteBox.classList.toggle('d-none', !btn.dataset.note);
      }
    });
  });

  // ── Connection test ────────────────────────────────────────────────────────
  var runBtn = document.getElementById('emailTestRun');
  var toInput = document.getElementById('emailTestTo');
  var results = document.getElementById('emailTestResults');
  if (!runBtn || !results) return;

  var ICONS = {
    ok: 'bi-check-circle-fill text-success',
    failed: 'bi-x-circle-fill text-danger',
    skipped: 'bi-dash-circle text-muted',
    pending: 'bi-circle text-muted'
  };

  function stageRow(stage) {
    var row = document.createElement('div');
    row.className = 'd-flex gap-2 align-items-start py-2 border-bottom';

    var icon = document.createElement('i');
    icon.className = 'bi ' + (ICONS[stage.status] || ICONS.pending) + ' mt-1 flex-shrink-0';
    row.appendChild(icon);

    var body = document.createElement('div');
    body.className = 'flex-grow-1';

    var label = document.createElement('div');
    label.className = stage.status === 'failed' ? 'fw-medium text-danger' : 'fw-medium';
    label.textContent = stage.label;
    body.appendChild(label);

    if (stage.detail) {
      var detail = document.createElement('div');
      detail.className = 'form-text mt-0';
      detail.textContent = stage.detail;
      body.appendChild(detail);
    }
    if (stage.hint) {
      // The hint is the actionable half — give it more weight than the detail.
      var hint = document.createElement('div');
      hint.className = 'small mt-1';
      var bulb = document.createElement('i');
      bulb.className = 'bi bi-lightbulb me-1';
      hint.appendChild(bulb);
      hint.appendChild(document.createTextNode(stage.hint));
      body.appendChild(hint);
    }

    row.appendChild(body);
    return row;
  }

  // The "Last test passed/failed" badge on the summary card. run_and_record has
  // already persisted this result server-side, so it survives a later reload —
  // this just spares the operator a refresh to see the outcome flip. Re-queried
  // on each call rather than cached at load, so it can't go stale.
  function updateBadge(ok) {
    var badge = document.getElementById('emailLastTestBadge');
    if (!badge) return;
    badge.classList.remove('d-none', 'status-pill--ok', 'status-pill--bad');
    badge.classList.add(ok ? 'status-pill--ok' : 'status-pill--bad');
    badge.innerHTML = '<i class="bi bi-' +
      (ok ? 'check-circle-fill' : 'exclamation-triangle-fill') + '"></i>Last test ' +
      (ok ? 'passed' : 'failed');
  }

  // The "Email log" button's red "!" dot. The server tells us the live unseen-
  // failure state on every test, so this mirrors it whether the test passed or
  // failed (a pass doesn't clear older, still-undismissed failures).
  function updateLogAlert(hasFailures) {
    var dot = document.getElementById('emailLogAlert');
    if (dot) dot.classList.toggle('d-none', !hasFailures);
  }

  function render(data) {
    results.textContent = '';
    updateBadge(data.ok);
    updateLogAlert(data.failures_unseen);

    var summary = document.createElement('div');
    summary.className = 'alert py-2 px-3 ' + (data.ok ? 'alert-success' : 'alert-danger');
    summary.innerHTML = '<i class="bi bi-' +
      (data.ok ? 'check-circle' : 'exclamation-triangle') + ' me-1"></i>';
    summary.appendChild(document.createTextNode(
      data.ok ? 'Everything checked out.' : 'The test stopped at the step marked below.'
    ));
    results.appendChild(summary);

    data.stages.forEach(function (stage) { results.appendChild(stageRow(stage)); });
  }

  function renderError(message) {
    results.textContent = '';
    var box = document.createElement('div');
    box.className = 'alert alert-danger py-2 px-3 mb-0';
    box.textContent = message;
    results.appendChild(box);
  }

  runBtn.addEventListener('click', function () {
    var body = new URLSearchParams();
    if (toInput && toInput.value.trim()) body.set('send_to', toInput.value.trim());

    runBtn.disabled = true;
    var original = runBtn.innerHTML;
    runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Testing…';
    results.textContent = '';

    fetch(runBtn.dataset.url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': getCsrfToken()
      },
      body: body.toString()
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) { renderError(res.data.error || 'The test could not be run.'); return; }
        render(res.data);
      })
      .catch(function () {
        renderError('Could not reach the server to run the test.');
      })
      .finally(function () {
        runBtn.disabled = false;
        runBtn.innerHTML = original;
      });
  });
})();
