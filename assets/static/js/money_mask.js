/* App-wide money masking (Settings → Display → Mask money).
 *
 * Every money amount in the app carries the `.money` class (the `money`/
 * `money_wrap` template filters, or the class placed directly on a JS-updated
 * stat span). When <body data-mask-money> is set, this replaces each `.money`
 * element's text with a *fixed-length* run of dots — so neither the value nor
 * the number of digits (and thus the magnitude) can be read off.
 *
 * The original text is stashed in data-money-real and restored when masking
 * turns off, so nothing is lost, and values updated live by other scripts (e.g.
 * the dashboard stat cards) re-mask automatically via a MutationObserver.
 *
 * It requires `.money` to sit on a *leaf* element (text only, no child tags),
 * since it rewrites textContent.
 */
(function () {
  'use strict';

  var MASK_RUN = '•••••';  // fixed length → hides both value and digit count

  function styleNow() {
    return document.body.getAttribute('data-mask-money') || '';
  }
  function jsMasking(style) { return !!style; }

  function maskString(text, style) {
    return MASK_RUN;
  }

  var subtreeObserver = null;
  function ensureSubtree(on) {
    if (on && !subtreeObserver) {
      // Re-mask when the DOM or any text changes (new or updated .money).
      subtreeObserver = new MutationObserver(schedule);
      subtreeObserver.observe(document.body, {
        subtree: true, childList: true, characterData: true,
      });
    } else if (!on && subtreeObserver) {
      subtreeObserver.disconnect();
      subtreeObserver = null;
    }
  }

  function apply() {
    var style = styleNow();
    var on = jsMasking(style);
    ensureSubtree(on);
    var els = document.querySelectorAll('.money');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (on) {
        var current = el.textContent;
        // A change that isn't our own last output is a fresh real value.
        if (current !== el.getAttribute('data-money-mask')) {
          el.setAttribute('data-money-real', current);
        }
        var masked = maskString(el.getAttribute('data-money-real') || '', style);
        if (el.textContent !== masked) el.textContent = masked;  // converges: no-op once masked
        el.setAttribute('data-money-mask', masked);
      } else if (el.hasAttribute('data-money-real')) {
        var real = el.getAttribute('data-money-real');
        if (el.textContent !== real) el.textContent = real;
        el.removeAttribute('data-money-mask');
      }
    }
  }

  // Coalesce bursts of DOM mutations into one re-mask per frame.
  var scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    var run = function () { scheduled = false; apply(); };
    if (window.requestAnimationFrame) window.requestAnimationFrame(run);
    else window.setTimeout(run, 16);
  }

  function init() {
    apply();
    // React to the mask being turned on/off or its style changing — this is what
    // makes the Settings → Display live preview work without extra wiring.
    new MutationObserver(apply).observe(document.body, {
      attributes: true, attributeFilter: ['data-mask-money'],
    });
    // Let scripts that rebuild money nodes request an immediate re-mask, and let
    // chart code ask whether masking is active.
    window.applyMoneyMask = apply;
    window.moneyMaskActive = function () { return !!styleNow(); };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
