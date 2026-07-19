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
})();
