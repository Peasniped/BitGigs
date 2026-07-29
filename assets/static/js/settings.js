/* Settings page: accent + secondary colour pickers (Display tab).
 *
 * Swatches, the colour wheel and the hex box each drive their form's hidden
 * input, and preview live by overriding a CSS token on <html> — everything
 * else (tints, gradients, Bootstrap primary) derives from those tokens, so
 * the whole page follows. Only Save persists; navigating away drops the
 * preview. Same wiring for both pickers, parameterised by PICKERS below.
 */
(function () {
  var HEX_RE = /^#[0-9a-f]{6}$/;

  function rgbStr(hex) {
    return parseInt(hex.substr(1, 2), 16) + ',' +
           parseInt(hex.substr(3, 2), 16) + ',' +
           parseInt(hex.substr(5, 2), 16);
  }

  var PICKERS = [
    { name: 'primary', hiddenId: 'id_accent_color', wheelId: 'accentWheel',
      hexId: 'accentHex', resetId: 'accentReset', cssVar: '--primary', rgbVar: '--primary-rgb' },
    { name: 'secondary', hiddenId: 'id_secondary_color', wheelId: 'secondaryWheel',
      hexId: 'secondaryHex', resetId: 'secondaryReset', cssVar: '--secondary', rgbVar: null },
  ];

  PICKERS.forEach(function (cfg) {
    var block = document.querySelector('[data-accent-picker="' + cfg.name + '"]');
    if (!block) return;
    var hidden = document.getElementById(cfg.hiddenId);
    var wheel = document.getElementById(cfg.wheelId);
    var hexInput = document.getElementById(cfg.hexId);
    var resetBtn = document.getElementById(cfg.resetId);
    if (!hidden || !wheel || !hexInput) return;

    function setColor(hex, source) {
      hex = hex.toLowerCase();
      if (!HEX_RE.test(hex)) return;   // ignore partial hex-box input
      hidden.value = hex;
      wheel.value = hex;
      if (source !== hexInput) hexInput.value = hex;
      block.querySelectorAll('.color-swatch').forEach(function (b) {
        b.classList.toggle('ring-selected', b.dataset.colorOption.toLowerCase() === hex);
      });
      var root = document.documentElement;
      root.style.setProperty(cfg.cssVar, hex);
      if (cfg.rgbVar) root.style.setProperty(cfg.rgbVar, rgbStr(hex));
      // Nothing to restore while the colour already is the default.
      if (resetBtn) {
        resetBtn.classList.toggle('d-none', hex === block.dataset.defaultAccent);
      }
    }

    block.querySelectorAll('.color-swatch').forEach(function (b) {
      b.addEventListener('click', function () { setColor(b.dataset.colorOption, b); });
    });
    wheel.addEventListener('input', function () { setColor(wheel.value, wheel); });
    hexInput.addEventListener('input', function () { setColor(hexInput.value.trim(), hexInput); });
    if (resetBtn) {
      resetBtn.addEventListener('click', function () { setColor(block.dataset.defaultAccent, null); });
    }
  });

  /* Mask-money live preview: keep <body data-mask-money> in sync with the
   * unsaved switch so the example (and any real amount on the page) previews the
   * masking immediately. Only Save persists. */
  (function () {
    var check = document.getElementById('id_mask_money');
    var wrap = document.querySelector('[data-mask-style-wrap]');
    if (!check) return;
    function apply() {
      if (wrap) wrap.classList.toggle('d-none', !check.checked);
      if (check.checked) document.body.setAttribute('data-mask-money', 'on');
      else document.body.removeAttribute('data-mask-money');
    }
    check.addEventListener('change', apply);
    apply();
  })();

  /* A switch that is its own Save — it posts the form it sits in as soon as it
   * changes (same shape as the Jobs tab's per-job toggle). For a setting that
   * is one switch and nothing else, a Save button beside it is a step that is
   * easy to walk away without pressing. */
  document.querySelectorAll('[data-autosubmit]').forEach(function (input) {
    input.addEventListener('change', function () {
      if (input.form) input.form.submit();
    });
  });

  /* Master-arm boxes (calendar invites, outgoing mail). The tint answers "is
   * this actually going to work?" — green armed and ready, yellow armed but
   * something downstream is off, red switched off. data-arm-ready is the
   * server's verdict on the downstream half (a mail connection exists, the
   * mail master switch is on); it can't change without a reload, so only the
   * switch is watched. The warning shows only while armed: what's missing
   * downstream doesn't matter while nothing is being sent. */
  document.querySelectorAll('[data-master-arm]').forEach(function (box) {
    var input = box.querySelector('.form-check-input');
    if (!input) return;
    var warn = box.querySelector('[data-arm-warn]');
    var ready = box.getAttribute('data-arm-ready') === '1';
    function apply() {
      var on = input.checked;
      box.classList.toggle('master-arm--on', on && ready);
      box.classList.toggle('master-arm--warn', on && !ready);
      box.classList.toggle('master-arm--off', !on);
      if (warn) warn.hidden = !(on && !ready);
    }
    input.addEventListener('change', apply);
    apply();
  });

  /* Settings → Features: a card dims when its switch goes off, and any settings
   * it owns fold away with it. The panel is only *hidden*, never removed, so
   * those fields still post — saving with a feature off must not wipe how it was
   * configured, or turning it back on would lose the setup. */
  document.querySelectorAll('[data-feature]').forEach(function (card) {
    var input = card.querySelector('.form-check-input');
    if (!input) return;
    var panel = card.querySelector('[data-feature-settings]');
    function apply() {
      card.classList.toggle('is-off', !input.checked);
      if (panel) panel.classList.toggle('d-none', !input.checked);
    }
    input.addEventListener('change', apply);
    apply();
  });
})();
