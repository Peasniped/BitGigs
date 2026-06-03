/* Payroll period detail: custom-line edit, drag-reorder, running-totals toggle,
   tax-pull-day inline editor. Server URLs are read from data-* attributes on the
   #payslip-lines table / #custom-line-form. Relies on getCsrfToken() from app.js. */
(function() {
  var table = document.getElementById('payslip-lines');
  if (!table) return;
  var tbody = table.querySelector('tbody');
  if (!tbody) return;

  // ---- Edit custom line via the add-form card ----
  var card = document.getElementById('custom-line-card');
  var form = document.getElementById('custom-line-form');
  var cardTitle = document.getElementById('custom-line-card-title');
  var cancelBtn2 = document.getElementById('cancel-edit-btn');
  var nameInput = document.getElementById('cl-name');
  var qtyInput = document.getElementById('cl-quantity');
  var rateInput = document.getElementById('cl-rate');
  var submitBtn = document.getElementById('cl-submit');
  var addUrl = form ? form.dataset.addUrl : '';
  var editingLineId = null;

  function enterEditMode(btn) {
    editingLineId = btn.dataset.lineId;
    nameInput.value = btn.dataset.lineName;
    qtyInput.value = btn.dataset.lineQty;
    rateInput.value = btn.dataset.lineRate;
    var isAdd = btn.dataset.lineType === 'add';
    document.getElementById('new_type_add').checked = isAdd;
    document.getElementById('new_type_deduct').checked = !isAdd;
    // Update form action to edit endpoint
    form.action = addUrl.replace('/add-line/', '/edit-line/' + editingLineId + '/');
    cardTitle.innerHTML = '<i class="bi bi-pencil me-1"></i>Editing: ' + btn.dataset.lineName;
    submitBtn.textContent = 'Save';
    card.style.backgroundColor = '#fff8e1';
    cancelBtn2.style.display = '';
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    nameInput.focus();
  }

  function exitEditMode() {
    editingLineId = null;
    nameInput.value = '';
    qtyInput.value = '1';
    rateInput.value = '';
    document.getElementById('new_type_add').checked = true;
    document.getElementById('new_type_deduct').checked = false;
    form.action = addUrl;
    cardTitle.innerHTML = '<i class="bi bi-plus-circle me-1"></i>Add custom line';
    submitBtn.textContent = 'Apply';
    card.style.backgroundColor = '';
    cancelBtn2.style.display = 'none';
  }

  if (cancelBtn2) cancelBtn2.addEventListener('click', exitEditMode);

  document.querySelectorAll('.edit-line-btn').forEach(function(btn) {
    btn.addEventListener('click', function() { enterEditMode(this); });
  });

  // ---- Drag-and-drop reorder (only custom lines have drag handles) ----
  var dragEl = null;
  tbody.querySelectorAll('tr').forEach(function(row) {
    var handle = row.querySelector('.drag-handle');
    if (!handle) return;

    row.draggable = true;
    row.addEventListener('dragstart', function() { dragEl = row; row.classList.add('table-active'); });
    row.addEventListener('dragend', function() { if (dragEl) dragEl.classList.remove('table-active'); dragEl = null; });
    row.addEventListener('dragover', function(e) { e.preventDefault(); });
    row.addEventListener('drop', function(e) {
      e.preventDefault();
      if (dragEl && dragEl !== row) {
        var rect = row.getBoundingClientRect();
        if (e.clientY < rect.top + rect.height / 2) {
          tbody.insertBefore(dragEl, row);
        } else {
          tbody.insertBefore(dragEl, row.nextSibling);
        }
        // POST new order
        var order = [];
        tbody.querySelectorAll('tr').forEach(function(r) {
          if (r.dataset.id) order.push(r.dataset.id);
        });
        var reorderUrl = table.dataset.reorderUrl;
        if (reorderUrl) {
          fetch(reorderUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ order: order }),
          });
        }
      }
    });
  });

  // ---- Running totals toggle ----
  var toggleBtn = document.querySelector('[data-toggle-running-totals]');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', function() {
      var cols = document.querySelectorAll('.running-total-col');
      var show = cols.length && cols[0].style.display === 'none';
      cols.forEach(function(c) { c.style.display = show ? '' : 'none'; });
      toggleBtn.classList.toggle('btn-outline-secondary', !show);
      toggleBtn.classList.toggle('btn-primary', show);
    });
  }

  // ---- Tax pull day inline editor ----
  var display = document.querySelector('[data-tax-pull-display]');
  var editor = document.querySelector('[data-tax-pull-editor]');
  var editBtn = document.querySelector('[data-tax-pull-edit-btn]');
  var input = document.querySelector('[data-tax-pull-input]');
  var saveBtn = document.querySelector('[data-tax-pull-save]');
  var cancelBtn = document.querySelector('[data-tax-pull-cancel]');
  var pullUrl = table.dataset.taxPullUrl;

  function showEditor() { display.style.display = 'none'; editor.style.display = ''; input.focus(); }
  function hideEditor() { editor.style.display = 'none'; display.style.display = ''; }

  if (editBtn) editBtn.addEventListener('click', showEditor);
  if (cancelBtn) cancelBtn.addEventListener('click', hideEditor);
  if (saveBtn && pullUrl) {
    saveBtn.addEventListener('click', function() {
      var day = parseInt(input.value, 10);
      if (isNaN(day) || day < 1 || day > 28) return;
      fetch(pullUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ tax_pull_day: day }),
      }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.status === 'ok') {
          var suffix = 'th';
          if (day === 1 || day === 21) suffix = 'st';
          else if (day === 2 || day === 22) suffix = 'nd';
          else if (day === 3 || day === 23) suffix = 'rd';
          display.innerHTML = 'Tax card pull: <strong>' + day + suffix + '</strong> '
            + '<button class="btn btn-link btn-sm p-0 ms-1 text-muted" type="button" data-tax-pull-edit-btn title="Change tax pull day">'
            + '<i class="bi bi-pencil" style="font-size:0.7rem;"></i></button>';
          display.querySelector('[data-tax-pull-edit-btn]').addEventListener('click', showEditor);
          hideEditor();
        }
      });
    });
  }
  if (input) {
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); saveBtn.click(); }
      if (e.key === 'Escape') { hideEditor(); }
    });
  }
})();
