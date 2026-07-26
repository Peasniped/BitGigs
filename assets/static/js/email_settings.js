/* Settings → Email: mail connections, provider presets and the staged test.
 *
 * There is one shared connection modal: "Add connection" opens it blank, a card's
 * Edit button fills it from that card's data-* attributes. The staged test posts
 * to core:email-test with a connection id and renders one row per stage of a real
 * SMTP session (resolve → connect → TLS → auth → optional send). The first
 * failing row is the answer, so it carries the diagnosis and a hint; the rows
 * after it stay "not reached" rather than pretending to be fine.
 */
(function () {
  var root = document.querySelector('[data-email-settings]');
  if (!root) return;   // Another settings tab is rendered.

  var testUrl = root.dataset.testUrl;

  // ── Confirm guards (delete / clear) ────────────────────────────────────────
  root.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  // ── Shared connection modal: fill for Edit, clear for Add ──────────────────
  var modalForm = document.getElementById('emailSettingsForm');
  var modalTitle = modalForm ? modalForm.querySelector('[data-modal-title]') : null;
  var pkInput = modalForm ? modalForm.querySelector('[data-conn-pk]') : null;

  function setField(id, value) {
    var el = document.getElementById(id);
    if (el) el.value = value == null ? '' : value;
  }

  function fillModal(card) {
    if (!modalForm) return;
    var d = card ? card.dataset : {};
    if (pkInput) pkInput.value = card ? d.pk : '';
    if (modalTitle) modalTitle.textContent = card ? 'Edit connection' : 'Add connection';
    setField('id_name', d.name);
    setField('id_host', d.host);
    setField('id_port', card ? d.port : '587');
    setField('id_security', card ? d.security : 'starttls');
    setField('id_username', d.username);
    setField('id_from_email', d.fromEmail);
    setField('id_from_name', card ? d.fromName : 'BitGigs');
    setField('id_timeout', card ? d.timeout : '10');
    var pwd = document.getElementById('id_password');
    if (pwd) {
      pwd.value = '';
      pwd.setAttribute('placeholder', d.hasPassword ? '•••••••• (unchanged)' : '');
    }
    // Clearing the checkbox: a fresh open shouldn't inherit the last card's state.
    var clearPwd = document.getElementById('id_clear_password');
    if (clearPwd) clearPwd.checked = false;
    // Reset preset highlight + note.
    root.querySelectorAll('[data-email-preset]').forEach(function (b) { b.classList.remove('active'); });
    var note = root.querySelector('[data-preset-note]');
    if (note) { note.textContent = ''; note.classList.add('d-none'); }
  }

  root.querySelectorAll('[data-conn-edit]').forEach(function (btn) {
    btn.addEventListener('click', function () { fillModal(btn.closest('[data-conn-card]')); });
  });
  root.querySelectorAll('[data-conn-add]').forEach(function (btn) {
    btn.addEventListener('click', function () { fillModal(null); });
  });

  // ── Sender auto-fills from the username while it's blank ───────────────────
  // Most providers require the from-address to equal the account you sign in as,
  // so mirror the username into an empty From field as you type — but back off
  // the moment the operator edits From themselves. Re-armed when the modal opens.
  var usernameInput = document.getElementById('id_username');
  var fromInput = document.getElementById('id_from_email');
  if (usernameInput && fromInput) {
    var fromTouched = fromInput.value.trim() !== '';
    fromInput.addEventListener('input', function () { fromTouched = true; });
    usernameInput.addEventListener('input', function () {
      if (!fromTouched) fromInput.value = usernameInput.value;
    });
    var mEl = document.getElementById('emailSettingsModal');
    if (mEl) mEl.addEventListener('shown.bs.modal', function () {
      fromTouched = fromInput.value.trim() !== '';
    });
  }

  // ── Provider presets ───────────────────────────────────────────────────────
  var noteBox = root.querySelector('[data-preset-note]');
  root.querySelectorAll('[data-email-preset]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setField('id_host', btn.dataset.host);
      setField('id_port', btn.dataset.port);
      setField('id_security', btn.dataset.security);
      root.querySelectorAll('[data-email-preset]').forEach(function (other) {
        other.classList.toggle('active', other === btn);
      });
      if (noteBox) {
        noteBox.textContent = btn.dataset.note || '';
        noteBox.classList.toggle('d-none', !btn.dataset.note);
      }
      var host = document.getElementById('id_host');
      if (host) host.dispatchEvent(new Event('input'));
    });
  });

  // ── Live host / port probe ─────────────────────────────────────────────────
  var hostInput = document.getElementById('id_host');
  var portInput = document.getElementById('id_port');
  if (modalForm && modalForm.dataset.probeUrl && hostInput) {
    var probeTimer = null;
    var probeToken = 0;   // guards against out-of-order replies from fast typing

    function attachStatus(input) {
      var wrap = document.createElement('span');
      wrap.className = 'field-status-wrap';
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      input.classList.add('has-field-status');
      var slot = document.createElement('span');
      slot.className = 'field-status';
      wrap.appendChild(slot);
      return slot;
    }

    var hostStatus = attachStatus(hostInput);
    var portStatus = portInput ? attachStatus(portInput) : null;

    function tipFor(part) {
      return part.hint ? part.detail + ' — ' + part.hint : (part.detail || '');
    }

    function setStatus(slot, state, tip) {
      if (!slot) return;
      slot.textContent = '';
      slot.title = tip || '';
      if (state === 'pending') {
        slot.className = 'field-status is-active';
        var sp = document.createElement('span');
        sp.className = 'spinner-border spinner-border-sm text-muted';
        slot.appendChild(sp);
      } else if (state === 'ok' || state === 'failed') {
        slot.className = 'field-status is-active';
        var icon = document.createElement('i');
        icon.className = 'bi ' + (state === 'ok'
          ? 'bi-check-circle-fill text-success' : 'bi-x-circle-fill text-danger');
        slot.appendChild(icon);
      } else {
        slot.className = 'field-status';   // hidden
      }
    }

    function runProbe() {
      var value = hostInput.value.trim();
      if (!value) { setStatus(hostStatus, 'clear'); setStatus(portStatus, 'clear'); return; }
      var token = ++probeToken;
      var hasPort = portInput && portInput.value.trim();
      setStatus(hostStatus, 'pending');
      setStatus(portStatus, hasPort ? 'pending' : 'clear');

      var body = new URLSearchParams();
      body.set('host', value);
      if (hasPort) body.set('port', portInput.value.trim());

      fetch(modalForm.dataset.probeUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCsrfToken() },
        body: body.toString()
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (token !== probeToken) return;
          if (data.host) setStatus(hostStatus, data.host.status, tipFor(data.host));
          else setStatus(hostStatus, 'clear');
          if (data.port) setStatus(portStatus, data.port.status, tipFor(data.port));
          else setStatus(portStatus, 'clear');
        })
        .catch(function () {
          if (token !== probeToken) return;
          setStatus(hostStatus, 'clear');
          setStatus(portStatus, 'clear');
        });
    }

    function scheduleProbe() {
      if (probeTimer) clearTimeout(probeTimer);
      probeTimer = setTimeout(runProbe, 300);
    }

    hostInput.addEventListener('input', scheduleProbe);
    if (portInput) portInput.addEventListener('input', scheduleProbe);

    var modalEl = document.getElementById('emailSettingsModal');
    if (modalEl) modalEl.addEventListener('shown.bs.modal', runProbe);
  }

  // ── Staged test rendering ──────────────────────────────────────────────────
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

  // Rewrite a connection's "Last test passed/failed" badge (run_and_record has
  // already persisted the result, so this just spares a refresh).
  function updateBadge(pk, ok) {
    if (!pk) return;
    var badge = document.getElementById('emailLastTestBadge-' + pk);
    if (!badge) return;
    badge.classList.remove('d-none', 'status-pill--ok', 'status-pill--bad');
    badge.classList.add(ok ? 'status-pill--ok' : 'status-pill--bad');
    badge.innerHTML = '<i class="bi bi-' +
      (ok ? 'check-circle-fill' : 'exclamation-triangle-fill') + '"></i>Last test ' +
      (ok ? 'passed' : 'failed');
  }

  function updateLogAlert(hasFailures) {
    var dot = document.getElementById('emailLogAlert');
    if (dot) dot.classList.toggle('d-none', !hasFailures);
  }

  function render(container, data) {
    container.textContent = '';
    container.classList.remove('d-none');
    updateBadge(data.connection_pk, data.ok);
    updateLogAlert(data.failures_unseen);
    var summary = document.createElement('div');
    summary.className = 'alert py-2 px-3 ' + (data.ok ? 'alert-success' : 'alert-danger');
    summary.innerHTML = '<i class="bi bi-' + (data.ok ? 'check-circle' : 'exclamation-triangle') + ' me-1"></i>';
    summary.appendChild(document.createTextNode(
      data.ok ? 'Everything checked out.' : 'The test stopped at the step marked below.'
    ));
    container.appendChild(summary);
    data.stages.forEach(function (stage) { container.appendChild(stageRow(stage)); });
  }

  function renderError(container, message) {
    container.textContent = '';
    container.classList.remove('d-none');
    var box = document.createElement('div');
    box.className = 'alert alert-danger py-2 px-3 mb-0';
    box.textContent = message;
    container.appendChild(box);
  }

  // Post a prepared body to a test endpoint and render into a container.
  function postTest(url, body, button, container) {
    var original = button ? button.innerHTML : '';
    if (button) {
      button.disabled = true;
      button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Testing…';
    }
    container.classList.remove('d-none');
    container.textContent = '';

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCsrfToken() },
      body: body.toString()
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) { renderError(container, res.data.error || 'The test could not be run.'); return; }
        render(container, res.data);
      })
      .catch(function () { renderError(container, 'Could not reach the server to run the test.'); })
      .finally(function () { if (button) { button.disabled = false; button.innerHTML = original; } });
  }

  // A saved connection's staged test (connection only unless sendTo is given).
  function runConnectionTest(button, container, pk, sendTo) {
    var body = new URLSearchParams();
    if (pk) body.set('connection', pk);
    if (sendTo) body.set('send_to', sendTo);
    postTest(testUrl, body, button, container);
  }

  // Per-connection "Test" (connection only, no message sent).
  root.querySelectorAll('[data-conn-test]').forEach(function (btn) {
    var pk = btn.dataset.pk;
    var container = root.querySelector('[data-conn-results="' + pk + '"]');
    btn.addEventListener('click', function () { runConnectionTest(btn, container, pk); });
  });

  // Send-a-test-message panel (settings), and the onboarding dry-run test.
  var runBtn = document.getElementById('emailTestRun');
  var toInput = document.getElementById('emailTestTo');
  var connSelect = document.getElementById('emailTestConnection');
  var results = document.getElementById('emailTestResults');
  if (runBtn && results) {
    runBtn.addEventListener('click', function () {
      var sendTo = toInput && toInput.value.trim() ? toInput.value.trim() : '';
      // Onboarding: test the typed (unsaved) values against its own endpoint.
      if (modalForm && modalForm.dataset.testValues) {
        var body = new URLSearchParams();
        new FormData(modalForm).forEach(function (v, k) { body.set(k, v); });
        if (sendTo) body.set('send_to', sendTo);
        postTest(runBtn.dataset.url, body, runBtn, results);
        return;
      }
      runConnectionTest(runBtn, results, connSelect ? connSelect.value : '', sendTo);
    });
  }

  // "Save & test" redirects back with ?test=<pk> — run that connection's test
  // once the page has loaded (connection-only, no message), then strip the flag.
  try {
    var url = new URL(window.location.href);
    var testPk = url.searchParams.get('test');
    if (testPk) {
      url.searchParams.delete('test');
      window.history.replaceState({}, '', url.pathname + url.search + url.hash);
      var container = root.querySelector('[data-conn-results="' + testPk + '"]');
      var btn = root.querySelector('[data-conn-test][data-pk="' + testPk + '"]');
      if (container) runTest({ button: btn, container: container, pk: testPk });
    }
  } catch (e) { /* no URL/history support — skip the auto-run */ }
})();
