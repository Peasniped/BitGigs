/* Settings page: accent colour picker (Display tab).
 *
 * Swatches, the colour wheel and the hex box all drive the form's hidden
 * accent_color input, and preview live by overriding the --primary /
 * --primary-rgb tokens on <html> — everything else (tints, gradients,
 * Bootstrap primary) derives from those two, so the whole page follows.
 * Only Save persists; navigating away drops the preview.
 */
(function () {
  var block = document.querySelector('[data-accent-picker]');
  if (!block) return;
  var hidden = document.getElementById('id_accent_color');
  var wheel = document.getElementById('accentWheel');
  var hexInput = document.getElementById('accentHex');
  if (!hidden || !wheel || !hexInput) return;
  var HEX_RE = /^#[0-9a-f]{6}$/;

  function rgbStr(hex) {
    return parseInt(hex.substr(1, 2), 16) + ',' +
           parseInt(hex.substr(3, 2), 16) + ',' +
           parseInt(hex.substr(5, 2), 16);
  }

  function setAccent(hex, source) {
    hex = hex.toLowerCase();
    if (!HEX_RE.test(hex)) return;   // ignore partial hex-box input
    hidden.value = hex;
    wheel.value = hex;
    if (source !== hexInput) hexInput.value = hex;
    block.querySelectorAll('.color-swatch').forEach(function (b) {
      b.classList.toggle('ring-selected', b.dataset.colorOption.toLowerCase() === hex);
    });
    var root = document.documentElement;
    root.style.setProperty('--primary', hex);
    root.style.setProperty('--primary-rgb', rgbStr(hex));
  }

  block.querySelectorAll('.color-swatch').forEach(function (b) {
    b.addEventListener('click', function () { setAccent(b.dataset.colorOption, b); });
  });
  wheel.addEventListener('input', function () { setAccent(wheel.value, wheel); });
  hexInput.addEventListener('input', function () { setAccent(hexInput.value.trim(), hexInput); });
  document.getElementById('accentReset').addEventListener('click', function () {
    setAccent(block.dataset.defaultAccent, null);
  });
})();
