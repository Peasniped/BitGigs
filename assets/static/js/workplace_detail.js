/* Workplace detail page: month nav, day-modal session create, the customize-
   appearance modal (icon picker + Cropper.js + SVG recolor), and the approve
   modal. Endpoint URLs and appearance defaults (icon mode, avatar colour/
   initials) come from #workplaceDetailConfig data-* attrs; pending shifts come
   from a json_script blob. The day-modal and approve sections guard on their
   DOM anchors so they no-op when not rendered. Uses getCsrfToken() from app.js. */
var _wpdCfgEl = document.getElementById('workplaceDetailConfig');
var cfg = _wpdCfgEl ? _wpdCfgEl.dataset : {};

// Go-to-month navigation
document.getElementById('gotoMonthBtn').addEventListener('click', function() {
  var m = document.getElementById('gotoMonth').value;
  var y = document.getElementById('gotoYear').value;
  if (m && y) {
    var url = new URL(window.location);
    url.searchParams.set('year', y);
    url.searchParams.set('month', m);
    url.searchParams.delete('day');
    window.location = url.toString();
  }
});

// Calendar day click â†’ open modal (with server reload for data)
function onCalendarDayClick(el) {
  var dateStr = el.dataset.date;
  var url = new URL(window.location);
  url.searchParams.set('day', dateStr);
  window.location = url.toString();
}

// Show / hide the inline session creation form inside the day modal
function showShiftForm() {
  document.getElementById('shiftFormPanel').style.display = '';
  document.getElementById('dayModalAddBtn').style.display = 'none';
  document.getElementById('shiftFormErrors').classList.add('d-none');
}
function hideSessionForm() {
  document.getElementById('shiftFormPanel').style.display = 'none';
  document.getElementById('dayModalAddBtn').style.display = '';
}

// Auto-open modal if a day is selected
document.addEventListener('DOMContentLoaded', function() {
  if (!cfg.selectedDate) return;  // only auto-open when the server selected a day
  var dayModalEl = document.getElementById('dayModal');
  if (!dayModalEl) return;
  var modal = new bootstrap.Modal(dayModalEl);
  modal.show();
  // When modal closes, remove the day param from URL without reload
  document.getElementById('dayModal').addEventListener('hidden.bs.modal', function() {
    var url = new URL(window.location);
    url.searchParams.delete('day');
    window.history.replaceState({}, '', url.toString());
    hideSessionForm();
  });

  // AJAX session create
  var form = document.getElementById('ajaxShiftForm');
  if (form) {
    form.addEventListener('submit', function(e) {
      e.preventDefault();
      var formData = new FormData(this);
      var errBox = document.getElementById('shiftFormErrors');
      errBox.classList.add('d-none');

      fetch(cfg.shiftCreateUrl, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCsrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
      })
      .then(function(resp) { return resp.json().then(function(data) { return {ok: resp.ok, data: data}; }); })
      .then(function(result) {
        if (result.ok) {
          // Reload with the day parameter to show the New Shift
          window.location.reload();
        } else {
          // Show validation errors
          var msgs = [];
          for (var field in result.data.errors) {
            msgs.push(result.data.errors[field].join(', '));
          }
          errBox.textContent = msgs.join(' | ');
          errBox.classList.remove('d-none');
        }
      })
      .catch(function() {
        errBox.textContent = 'Something went wrong.';
        errBox.classList.remove('d-none');
      });
    });
  }
});

// â•â•â•â•â•â•â• Customize Modal Logic â•â•â•â•â•â•â•
(function() {
  var modal = document.getElementById('customizeModal');
  if (!modal) return;

  var iconPicker    = document.getElementById('modalIconPicker');
  var iconInput     = document.getElementById('customizeIconInput');
  var bgColorPicker = document.getElementById('modalBgColorPicker');
  var bgColorInput  = document.getElementById('customizeBgColorInput');
  var bgColorWheel  = document.getElementById('bgColorWheel');
  var bgColorHex    = document.getElementById('bgColorHex');
  var clearBgColorBtn = document.getElementById('clearBgColor');
  var accentColorPicker = document.getElementById('modalAccentColorPicker');
  var accentColorInput  = document.getElementById('customizeAccentColorInput');
  var accentColorWheel  = document.getElementById('accentColorWheel');
  var accentColorHex    = document.getElementById('accentColorHex');
  var clearAccentColorBtn = document.getElementById('clearAccentColor');
  var saveBtn       = document.getElementById('customizeSaveBtn');
  var errBox        = document.getElementById('customizeErrors');
  var fileInput     = document.getElementById('customIconFile');
  var previewBox    = document.getElementById('customIconPreview');
  var removeBtn     = document.getElementById('removeCustomIcon');
  var livePreview   = document.getElementById('livePreview');

  // Cropper elements
  var cropModalEl   = document.getElementById('cropModal');
  var cropImage     = document.getElementById('cropImage');
  var cropZoom      = document.getElementById('cropZoom');
  var cropApplyBtn  = document.getElementById('cropApplyBtn');
  var cropFitBtn    = document.getElementById('cropFitBtn');
  var cropPaddingInput = document.getElementById('cropPadding');
  var cropper       = null;
  var cropBsModal   = null;

  // SVG recolor modal elements
  var svgRecolorModalEl = document.getElementById('svgRecolorModal');
  var svgRecolorBsModal = null;
  var svgRecolorPreview = document.getElementById('svgRecolorPreview');
  var svgColorList      = document.getElementById('svgColorList');
  var svgNoColorsHint   = document.getElementById('svgNoColorsHint');
  var svgTintAll        = document.getElementById('svgTintAll');
  var svgTintAllApply   = document.getElementById('svgTintAllApply');
  var svgRecolorReset   = document.getElementById('svgRecolorReset');
  var svgRecolorSkipBtn = document.getElementById('svgRecolorSkip');
  var svgRecolorContinueBtn = document.getElementById('svgRecolorContinue');
  var svgOriginalText   = '';
  var svgColorMap       = {};   // { oldColor: newColor }
  var svgDetectedColors = [];

  // State
  var pendingFile   = null;       // cropped blob to upload
  var pendingDataUrl = null;      // data-url of cropped image for preview
  var willRemoveCustomIcon = false;
  var currentMode   = cfg.iconMode;  // 'icons' or 'logo'
  var defaultColor  = cfg.avatarColor;

  // ---- Live preview updater ----
  function updatePreview() {
    var bgColor = bgColorInput.value || defaultColor;
    var accent  = accentColorInput.value || '';
    livePreview.style.background = bgColor;

    if (currentMode === 'logo' && pendingDataUrl) {
      livePreview.innerHTML = '<img src="' + pendingDataUrl + '" alt="" style="width:100%;height:100%;object-fit:cover;">';
    } else if (currentMode === 'logo' && !willRemoveCustomIcon && previewBox.querySelector('img')) {
      var existingSrc = previewBox.querySelector('img').src;
      livePreview.innerHTML = '<img src="' + existingSrc + '" alt="" style="width:100%;height:100%;object-fit:cover;">';
    } else if (iconInput.value) {
      var iconColor = accent ? 'color:' + accent : '';
      livePreview.innerHTML = '<i class="bi ' + iconInput.value + '" style="font-size:1.6rem;' + iconColor + '"></i>';
    } else {
      livePreview.innerHTML = '<span>' + cfg.avatarInitials + '</span>';
    }
  }

  // ---- Tab switching ----
  document.getElementById('tab-icons').addEventListener('shown.bs.tab', function() {
    currentMode = 'icons';
    // If we had a pending custom logo but switched to icons, clear it
    // but keep it until save so user can switch back
    updatePreview();
  });
  document.getElementById('tab-logo').addEventListener('shown.bs.tab', function() {
    currentMode = 'logo';
    updatePreview();
  });

  // ---- Icon Picker ----
  iconPicker.querySelectorAll('[data-icon-option]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      iconInput.value = btn.dataset.iconOption;
      iconPicker.querySelectorAll('[data-icon-option]').forEach(function(b) {
        b.className = b.className.replace('btn-primary', 'btn-outline-secondary');
      });
      btn.className = btn.className.replace('btn-outline-secondary', 'btn-primary');
      updatePreview();
    });
  });

  // ---- Custom Icon Upload â†’ open cropper ----
  fileInput.addEventListener('change', function() {
    var file = this.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {  // allow bigger before crop, final blob checked later
      alert('File must be under 2 MB.');
      this.value = '';
      return;
    }
    var isSvg = (file.type === 'image/svg+xml') ||
                /\.svg$/i.test(file.name);
    if (isSvg) {
      // Read as text so the user can recolor before we convert to PNG
      var t = new FileReader();
      t.onload = function(e) {
        openSvgRecolorModal(e.target.result);
      };
      t.readAsText(file);
    } else {
      // PNG / JPG / etc. â†’ go straight to cropper
      var reader = new FileReader();
      reader.onload = function(e) {
        cropImage.src = e.target.result;
        if (!cropBsModal) cropBsModal = new bootstrap.Modal(cropModalEl);
        cropBsModal.show();
      };
      reader.readAsDataURL(file);
    }
    this.value = '';  // reset so same file can be re-selected
  });

  // ---- SVG Recolor pipeline ----
  function extractSvgColors(svgText) {
    var set = new Set();
    var pickup = function(v) {
      if (!v) return;
      v = v.trim();
      if (v === 'none' || v === 'currentColor' || v === 'transparent') return;
      // Accept hex colors, rgb()/rgba(), or named colors (left as-is)
      set.add(v);
    };
    var attrRe = /(?:fill|stroke|stop-color)\s*=\s*"([^"]+)"/gi;
    var m;
    while ((m = attrRe.exec(svgText)) !== null) pickup(m[1]);
    var styleRe = /(?:fill|stroke|stop-color)\s*:\s*([^;"}]+)/gi;
    while ((m = styleRe.exec(svgText)) !== null) pickup(m[1]);
    return Array.from(set);
  }

  function escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  function applySvgRecolor(svgText, mapping, tintAllColor) {
    if (tintAllColor) {
      svgText = svgText.replace(
        /(fill|stroke|stop-color)(\s*=\s*")([^"]+)(")/gi,
        function(full, attr, eq, val, q) {
          if (val === 'none' || val === 'currentColor' || val === 'transparent') return full;
          return attr + eq + tintAllColor + q;
        }
      );
      svgText = svgText.replace(
        /(fill|stroke|stop-color)(\s*:\s*)([^;"}]+)/gi,
        function(full, attr, sep, val) {
          var t = val.trim();
          if (t === 'none' || t === 'currentColor' || t === 'transparent') return full;
          return attr + sep + tintAllColor;
        }
      );
      return svgText;
    }
    Object.keys(mapping).forEach(function(from) {
      var to = mapping[from];
      if (!to || from === to) return;
      var esc = escapeRegExp(from);
      var attrRe = new RegExp('((?:fill|stroke|stop-color)\\s*=\\s*")' + esc + '(")', 'gi');
      svgText = svgText.replace(attrRe, '$1' + to + '$2');
      var styleRe = new RegExp('((?:fill|stroke|stop-color)\\s*:\\s*)' + esc + '(\\s*[;"}]|$)', 'gi');
      svgText = svgText.replace(styleRe, '$1' + to + '$2');
    });
    return svgText;
  }

  function svgTextToDataUrl(svgText) {
    // unescape() is deprecated; build a UTF-8 safe base64
    var b64 = btoa(unescape(encodeURIComponent(svgText)));
    return 'data:image/svg+xml;base64,' + b64;
  }

  function refreshSvgRecolorPreview() {
    var working = applySvgRecolor(svgOriginalText, svgColorMap, null);
    svgRecolorPreview.innerHTML = '<img src="' + svgTextToDataUrl(working) + '" alt="" '
      + 'style="max-width:100%;max-height:100%;object-fit:contain;">';
  }

  function buildSvgColorList() {
    svgColorList.innerHTML = '';
    if (svgDetectedColors.length === 0) {
      svgNoColorsHint.classList.remove('d-none');
      return;
    }
    svgNoColorsHint.classList.add('d-none');
    svgDetectedColors.forEach(function(c) {
      var row = document.createElement('div');
      row.className = 'd-flex align-items-center gap-2 mb-1';
      // Try to convert non-hex (like 'rgb(...)' or named) to a hex the input accepts
      var initial = svgColorMap[c] || c;
      var hexInitial = initial;
      if (!/^#[0-9a-fA-F]{6}$/.test(hexInitial)) {
        // Probe via a hidden DOM element to normalise
        var probe = document.createElement('span');
        probe.style.color = hexInitial;
        document.body.appendChild(probe);
        var rgb = getComputedStyle(probe).color;
        document.body.removeChild(probe);
        var mm = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(rgb);
        if (mm) {
          hexInitial = '#' + [mm[1], mm[2], mm[3]].map(function(n) {
            var h = parseInt(n, 10).toString(16); return h.length === 1 ? '0' + h : h;
          }).join('');
        } else {
          hexInitial = '#000000';
        }
      }
      row.innerHTML =
        '<span class="border rounded" style="width:20px;height:20px;background:' + c + ';flex-shrink:0;"></span>'
        + '<code class="small text-muted flex-grow-1" style="word-break:break-all;">' + c + '</code>'
        + '<i class="bi bi-arrow-right text-muted small"></i>';
      var input = document.createElement('input');
      input.type = 'color';
      input.className = 'form-control form-control-color';
      input.style.cssText = 'width:46px;height:32px;padding:2px;';
      input.value = hexInitial;
      var hexInput = document.createElement('input');
      hexInput.type = 'text';
      hexInput.className = 'form-control form-control-sm font-monospace';
      hexInput.style.cssText = 'width:90px;';
      hexInput.maxLength = 7;
      hexInput.spellcheck = false;
      hexInput.value = hexInitial;
      input.addEventListener('input', function() {
        svgColorMap[c] = input.value;
        hexInput.value = input.value;
        refreshSvgRecolorPreview();
      });
      hexInput.addEventListener('input', function() {
        var v = hexInput.value.trim();
        if (v && v.charAt(0) !== '#') v = '#' + v;
        if (/^#[0-9a-fA-F]{6}$/.test(v)) {
          input.value = v.toLowerCase();
          svgColorMap[c] = v.toLowerCase();
          refreshSvgRecolorPreview();
        }
      });
      row.appendChild(input);
      row.appendChild(hexInput);
      svgColorList.appendChild(row);
    });
  }

  function openSvgRecolorModal(svgText) {
    svgOriginalText = svgText;
    svgColorMap = {};
    svgDetectedColors = extractSvgColors(svgText);
    buildSvgColorList();
    refreshSvgRecolorPreview();
    if (!svgRecolorBsModal) svgRecolorBsModal = new bootstrap.Modal(svgRecolorModalEl);
    // Hide the parent customize modal so we don't get stacked backdrops / offset positioning
    var customizeBs = bootstrap.Modal.getInstance(modal);
    if (customizeBs && modal.classList.contains('show')) {
      svgRecolorModalEl.dataset.reopenCustomize = '1';
      customizeBs.hide();
      // Wait for it to fully hide before opening recolor (avoids backdrop flicker)
      modal.addEventListener('hidden.bs.modal', function _once() {
        modal.removeEventListener('hidden.bs.modal', _once);
        svgRecolorBsModal.show();
      });
    } else {
      svgRecolorBsModal.show();
    }
  }

  function passSvgToCropper(svgText) {
    cropImage.src = svgTextToDataUrl(svgText);
    if (!cropBsModal) cropBsModal = new bootstrap.Modal(cropModalEl);
    cropBsModal.show();
  }

  // Sync the single-tint color picker and hex text field
  var svgTintAllHex = document.getElementById('svgTintAllHex');
  svgTintAll.addEventListener('input', function() {
    if (svgTintAllHex) svgTintAllHex.value = svgTintAll.value;
  });
  if (svgTintAllHex) {
    svgTintAllHex.addEventListener('input', function() {
      var v = svgTintAllHex.value.trim();
      if (v && v.charAt(0) !== '#') v = '#' + v;
      if (/^#[0-9a-fA-F]{6}$/.test(v)) svgTintAll.value = v.toLowerCase();
    });
  }
  svgTintAllApply.addEventListener('click', function() {
    var c = svgTintAll.value;
    svgDetectedColors.forEach(function(orig) { svgColorMap[orig] = c; });
    buildSvgColorList();   // rebuild so each row's color input reflects the tint
    refreshSvgRecolorPreview();
  });
  svgRecolorReset.addEventListener('click', function() {
    svgColorMap = {};
    buildSvgColorList();
    refreshSvgRecolorPreview();
  });
  svgRecolorSkipBtn.addEventListener('click', function() {
    svgRecolorBsModal.hide();
    passSvgToCropper(svgOriginalText);
  });
  svgRecolorContinueBtn.addEventListener('click', function() {
    var modified = applySvgRecolor(svgOriginalText, svgColorMap, null);
    svgRecolorBsModal.hide();
    passSvgToCropper(modified);
  });

  // ---- Cropper setup on modal show ----
  cropModalEl.addEventListener('shown.bs.modal', function() {
    if (cropper) cropper.destroy();
    // Ensure the image is fully loaded before creating cropper
    function initCropper() {
      cropper = new Cropper(cropImage, {
        aspectRatio: 1,
        viewMode: 0,
        dragMode: 'move',
        cropBoxResizable: false,
        cropBoxMovable: false,
        toggleDragModeOnDblclick: false,
        background: true,
        modal: true,
        guides: false,
        center: true,
        highlight: false,
        autoCropArea: 0.85,
        minCropBoxWidth: 100,
        minCropBoxHeight: 100,
        ready: function() {
          // Calculate slider range from natural size
          var imgData = cropper.getImageData();
          var initRatio = imgData.width / imgData.naturalWidth;
          cropZoom.min = (initRatio * 0.05).toFixed(4);
          cropZoom.max = Math.max(3, initRatio * 3).toFixed(2);
          cropZoom.step = '0.005';
          cropZoom.value = initRatio.toFixed(4);
          // Auto-fit on open
          fitImageInCrop();
        }
      });
    }
    if (cropImage.complete && cropImage.naturalWidth > 0) {
      initCropper();
    } else {
      cropImage.onload = function() { initCropper(); };
    }
  });

  cropModalEl.addEventListener('hidden.bs.modal', function() {
    if (cropper) { cropper.destroy(); cropper = null; }
    cropImage.src = '';
    maybeReopenCustomize();
  });

  // Reopen the customize modal if we hid it for the SVG recolor / crop flow
  function maybeReopenCustomize() {
    if (svgRecolorModalEl.dataset.reopenCustomize !== '1') return;
    // If the recolor or crop modal is still on its way to showing, skip
    if (svgRecolorModalEl.classList.contains('show') || cropModalEl.classList.contains('show')) return;
    delete svgRecolorModalEl.dataset.reopenCustomize;
    var customizeBs = bootstrap.Modal.getOrCreateInstance(modal);
    customizeBs.show();
  }
  svgRecolorModalEl.addEventListener('hidden.bs.modal', function() {
    // Wait a tick so a follow-up cropModal.show() has had a chance to flip its 'show' class
    setTimeout(maybeReopenCustomize, 50);
  });

  // ---- Fit image inside crop box (by shortest side + margin) ----
  function fitImageInCrop() {
    if (!cropper) return;
    var paddingPx = parseInt(cropPaddingInput && cropPaddingInput.value, 10);
    if (isNaN(paddingPx)) paddingPx = 20;
    paddingPx = Math.max(0, Math.min(120, paddingPx));
    // The output canvas is 256x256, so paddingPx maps directly to a margin
    // ratio = 1 - 2*(paddingPx/256) … but historically `margin` here refers
    // to the fraction of the crop-box the image should occupy. So:
    //   image fraction = 1 - 2 * (paddingPx / 256)
    var margin = Math.max(0.1, 1 - (paddingPx * 2 / 256));
    var cropBox = cropper.getCropBoxData();
    var imgData = cropper.getImageData();
    var scaleW = (cropBox.width * margin) / imgData.naturalWidth;
    var scaleH = (cropBox.height * margin) / imgData.naturalHeight;
    var fitRatio = Math.min(scaleW, scaleH);
    cropper.zoomTo(fitRatio);
    // Center the image in the crop box
    cropper.moveTo(
      cropBox.left + (cropBox.width - imgData.naturalWidth * fitRatio) / 2,
      cropBox.top + (cropBox.height - imgData.naturalHeight * fitRatio) / 2
    );
    cropZoom.value = fitRatio.toFixed(4);
  }

  cropFitBtn.addEventListener('click', fitImageInCrop);
  if (cropPaddingInput) {
    cropPaddingInput.addEventListener('change', fitImageInCrop);
  }

  // ---- Zoom slider ----
  cropZoom.addEventListener('input', function() {
    if (cropper) cropper.zoomTo(parseFloat(this.value));
  });

  // ---- Apply crop ----
  cropApplyBtn.addEventListener('click', function() {
    if (!cropper) return;
    var canvas = cropper.getCroppedCanvas({
      width: 256,
      height: 256,
      imageSmoothingEnabled: true,
      imageSmoothingQuality: 'high',
    });
    canvas.toBlob(function(blob) {
      if (!blob) return;
      if (blob.size > 512 * 1024) {
        alert('Cropped image is too large. Try zooming in more or use a smaller image.');
        return;
      }
      pendingFile = new File([blob], (cfg.slug || 'workplace') + '_icon.png', { type: 'image/png' });
      pendingDataUrl = canvas.toDataURL('image/png');
      willRemoveCustomIcon = false;

      // Update UI
      previewBox.innerHTML = '<img src="' + pendingDataUrl + '" alt="" style="width:100%;height:100%;object-fit:cover;">';
      removeBtn.classList.remove('d-none');

      // Deselect bootstrap icons
      iconInput.value = '';
      iconPicker.querySelectorAll('[data-icon-option]').forEach(function(b) {
        b.className = b.className.replace('btn-primary', 'btn-outline-secondary');
      });
      var noneBtn = iconPicker.querySelector('[data-icon-option=""]');
      if (noneBtn) noneBtn.className = noneBtn.className.replace('btn-outline-secondary', 'btn-primary');

      updatePreview();
      cropBsModal.hide();
    }, 'image/png', 0.92);
  });

  // ---- Remove custom icon ----
  removeBtn.addEventListener('click', function() {
    pendingFile = null;
    pendingDataUrl = null;
    willRemoveCustomIcon = true;
    fileInput.value = '';
    previewBox.innerHTML = '<i class="bi bi-image text-muted" style="font-size:1.4rem;"></i>';
    removeBtn.classList.add('d-none');
    updatePreview();
  });

  // ---- Generic colour picker helper ----
  function setupColorPicker(pickerEl, hiddenInput, wheelEl, hexEl, clearBtn) {
    function selectPreset(hex) {
      hiddenInput.value = hex;
      wheelEl.value = hex || '#6366f1';
      hexEl.value = hex;
      pickerEl.querySelectorAll('[data-color-option]').forEach(function(b) {
        b.classList.remove('ring-selected');
      });
      if (hex) {
        var m = pickerEl.querySelector('[data-color-option="' + hex + '"]');
        if (m) m.classList.add('ring-selected');
      }
      updatePreview();
    }
    pickerEl.querySelectorAll('[data-color-option]').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        selectPreset(btn.dataset.colorOption);
      });
    });
    wheelEl.addEventListener('input', function() {
      hiddenInput.value = this.value;
      hexEl.value = this.value;
      pickerEl.querySelectorAll('[data-color-option]').forEach(function(b) {
        b.classList.remove('ring-selected');
      });
      var m = pickerEl.querySelector('[data-color-option="' + this.value + '"]');
      if (m) m.classList.add('ring-selected');
      updatePreview();
    });
    hexEl.addEventListener('input', function() {
      var v = this.value.trim();
      if (/^#[0-9a-fA-F]{6}$/.test(v)) {
        hiddenInput.value = v;
        wheelEl.value = v;
        pickerEl.querySelectorAll('[data-color-option]').forEach(function(b) {
          b.classList.remove('ring-selected');
        });
        var m = pickerEl.querySelector('[data-color-option="' + v.toLowerCase() + '"]');
        if (m) m.classList.add('ring-selected');
        updatePreview();
      }
    });
    clearBtn.addEventListener('click', function() {
      hiddenInput.value = '';
      hexEl.value = '';
      wheelEl.value = '#6366f1';
      pickerEl.querySelectorAll('[data-color-option]').forEach(function(b) {
        b.classList.remove('ring-selected');
      });
      updatePreview();
    });
  }

  // Wire up both colour pickers
  setupColorPicker(bgColorPicker, bgColorInput, bgColorWheel, bgColorHex, clearBgColorBtn);
  setupColorPicker(accentColorPicker, accentColorInput, accentColorWheel, accentColorHex, clearAccentColorBtn);

  // ---- Save ----
  saveBtn.addEventListener('click', function() {
    errBox.classList.add('d-none');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Savingâ€¦';

    var fd = new FormData();
    // If user is on 'logo' tab and has a pending file, send it; clear bootstrap icon
    if (currentMode === 'logo' && pendingFile) {
      fd.append('custom_icon', pendingFile);
      fd.append('icon', '');
    } else if (currentMode === 'logo' && !willRemoveCustomIcon) {
      // Keeping existing custom logo . don't touch icon/custom_icon fields
      fd.append('icon', '');
    } else {
      fd.append('icon', iconInput.value);
    }
    fd.append('color', bgColorInput.value);
    fd.append('accent_color', accentColorInput.value);
    if (willRemoveCustomIcon && !pendingFile) {
      fd.append('remove_custom_icon', '1');
    }

    fetch(cfg.customizeUrl, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: fd,
    })
    .then(function(resp) { return resp.json().then(function(d){ return {ok: resp.ok, data: d}; }); })
    .then(function(result) {
      if (result.ok) {
        window.location.reload();
      } else {
        errBox.textContent = result.data.error || 'Something went wrong.';
        errBox.classList.remove('d-none');
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save';
      }
    })
    .catch(function() {
      errBox.textContent = 'Network error.';
      errBox.classList.remove('d-none');
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save';
    });
  });
})();

// â•â•â•â•â•â•â• Approve Modal Logic â•â•â•â•â•â•â•
(function() {
  var tbody = document.getElementById('approveTableBody');
  if (!tbody) return;
  var SHIFTS = JSON.parse(document.getElementById('pendingShiftsData').textContent);
  var selectAll = document.getElementById('approveSelectAll');
  var countSpan = document.getElementById('approveSelectedCount');

  function renderTable() {
    tbody.innerHTML = '';
    SHIFTS.forEach(function(s) {
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td><input type="checkbox" class="form-check-input approve-cb" value="' + s.id + '" checked></td>' +
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
        '<td class="small text-end hours-cell">' + s.net_hours.replace('.',',') + 'h</td>' +
        '<td class="text-center"><button type="button" class="btn btn-sm btn-outline-primary py-0 px-1 edit-approve-btn" data-shift-id="' + s.id + '" title="Edit shift"><i class="bi bi-pencil" style="font-size:0.65rem;"></i></button></td>';
      tbody.appendChild(tr);
    });
    updateCount();
    // Attach pencil click handlers
    tbody.querySelectorAll('.edit-approve-btn').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        openEditApproveModal(parseInt(btn.dataset.shiftId));
      });
    });
  }

  function updateCount() {
    var checked = tbody.querySelectorAll('.approve-cb:checked').length;
    countSpan.textContent = checked + ' of ' + SHIFTS.length + ' selected';
  }

  selectAll.addEventListener('change', function() {
    tbody.querySelectorAll('.approve-cb').forEach(function(cb) { cb.checked = selectAll.checked; });
    updateCount();
  });
  tbody.addEventListener('change', function(e) {
    if (e.target.classList.contains('approve-cb')) updateCount();
  });

  document.getElementById('approveConfirmBtn').addEventListener('click', function() {
    var btn = this;
    var ids = [];
    tbody.querySelectorAll('.approve-cb:checked').forEach(function(cb) { ids.push(parseInt(cb.value)); });
    if (ids.length === 0) return;

    // Collect inline edits
    var edits = [];
    ids.forEach(function(id) {
      var edit = { id: id };
      var fields = tbody.querySelectorAll('[data-id="' + id + '"]');
      fields.forEach(function(f) { edit[f.dataset.field] = f.value; });
      edits.push(edit);
    });

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Approvingâ€¦';

    fetch(cfg.approveUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
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

  renderTable();

  // â•â•â•â•â•â•â• Edit Shift from Approve Modal â•â•â•â•â•â•â•
  var editApproveModal = new bootstrap.Modal(document.getElementById('editApproveShiftModal'));
  var UPDATE_URL = cfg.updateUrl;

  function openEditApproveModal(shiftId) {
    var url = UPDATE_URL.replace('/0/', '/' + shiftId + '/');
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({}),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) return;
      var s = data.shift;
      document.getElementById('editApproveShiftId').value = s.id;
      document.getElementById('editApproveDate').value = s.date;
      document.getElementById('editApproveStart').value = s.start_time;
      document.getElementById('editApproveEnd').value = s.end_time;
      document.getElementById('editApproveBreak').value = s.break_minutes;
      document.getElementById('editApproveType').value = s.shift_type;
      document.getElementById('editApproveNotes').value = s.notes;
      document.getElementById('editApproveErrors').classList.add('d-none');
      editApproveModal.show();
    });
  }

  document.getElementById('editApproveSaveBtn').addEventListener('click', function() {
    var shiftId = document.getElementById('editApproveShiftId').value;
    if (!shiftId) return;
    var url = UPDATE_URL.replace('/0/', '/' + shiftId + '/');
    var body = {
      date: document.getElementById('editApproveDate').value,
      start_time: document.getElementById('editApproveStart').value,
      end_time: document.getElementById('editApproveEnd').value,
      break_minutes: parseInt(document.getElementById('editApproveBreak').value) || 0,
      shift_type: document.getElementById('editApproveType').value,
      notes: document.getElementById('editApproveNotes').value,
    };
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify(body),
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (!data.ok) {
        document.getElementById('editApproveErrors').textContent = data.error || 'Error saving.';
        document.getElementById('editApproveErrors').classList.remove('d-none');
        return;
      }
      // Update local SHIFTS array and re-render
      var s = data.shift;
      for (var i = 0; i < SHIFTS.length; i++) {
        if (SHIFTS[i].id === s.id) {
          SHIFTS[i] = s;
          break;
        }
      }
      editApproveModal.hide();
      renderTable();
    });
  });
})();
