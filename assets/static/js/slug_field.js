/* Workplace form slug field: live slug preview from the name input, a [change]
   link to reveal the manual slug editor, and initial display state. Form field
   ids, the current slug value, and the server-side error flag are read from
   #slugRow data-* attributes (set in _form_fields.html). */
(function () {
  var slugRow = document.getElementById('slugRow');
  if (!slugRow) return;

  var nameInput = document.getElementById(slugRow.dataset.nameId);
  var slugInput = document.getElementById(slugRow.dataset.slugId);
  var previewText = document.getElementById('slugPreviewText');
  var previewRow = document.getElementById('slugPreview');
  var editRow = document.getElementById('slugEditRow');
  var changeLink = document.getElementById('slugChangeLink');
  if (!nameInput || !slugInput) return;

  function toSlug(s) {
    return s.toLowerCase()
      .replace(/[^\w\s-]/g, '')
      .trim()
      .replace(/[\s_]+/g, '-')
      .replace(/-+/g, '-');
  }

  nameInput.addEventListener('input', function () {
    var slug = toSlug(this.value);
    previewText.textContent = slug;
    if (editRow.style.display === 'none') {
      previewRow.style.display = slug ? '' : 'none';
    } else {
      // Edit mode: update the placeholder so the auto-generated slug stays visible
      slugInput.placeholder = slug || 'auto-generated from name';
    }
  });

  changeLink.addEventListener('click', function (e) {
    e.preventDefault();
    slugInput.value = '';
    slugInput.placeholder = toSlug(nameInput.value) || 'auto-generated from name';
    previewRow.style.display = 'none';
    editRow.style.display = '';
    slugInput.focus();
  });

  // Initialise on page load
  if (slugRow.dataset.hasError) {
    // Server returned a slug error — show edit row directly
    editRow.style.display = '';
  } else {
    var initialSlug = (slugRow.dataset.slugValue || '') || toSlug(nameInput.value);
    if (initialSlug) {
      previewText.textContent = initialSlug;
      previewRow.style.display = '';
    }
    // If both are empty (blank new form), leave both rows hidden
  }
})();
