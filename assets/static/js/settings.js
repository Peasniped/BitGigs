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
    // The hidden field lives outside this block, so point its "Saved" flag back
    // at the picker the owner is actually looking at.
    hidden._autosaveRow = block;

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
      // Persist, debounced: dragging the wheel or typing a hex fires this on
      // every keystroke, and only where it lands is worth storing. The hidden
      // input never sees a `change` event, so the picker has to say so itself.
      if (autosaveSoon) autosaveSoon(hidden);
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

  /* ---- Save on change --------------------------------------------------
   *
   * The settings panes carry no Save button: a control that is one switch or one
   * dropdown has nothing to submit — the change *is* the intent, and a Save
   * button beside it is a step that's easy to walk away without pressing. Each
   * `[data-autosave="<scope>"]` control posts just itself to core:settings-field
   * and reports in place.
   *
   * Two rules make it safe to trust what's on screen. A rejected save **puts the
   * control back** — the server is the only thing that decides what's stored, so
   * a switch that failed validation must not sit there looking on. And the revert
   * re-fires `change` **muted**, so everything keyed on that event (the master-arm
   * tint, the feature card, the inline reveals) re-syncs without the revert
   * itself being mistaken for a new edit and saved back.
   *
   * Typed fields save on `change`, i.e. on blur — half-typed input has no
   * business being stored. The colour pickers are the exception: they drive a
   * hidden input from a swatch/wheel/hex box, so they call saveNow() debounced.
   */
  var page = document.querySelector('[data-settings-autosave-url]');

  function autosaveInit() {
    if (!page) return;
    var url = page.getAttribute('data-settings-autosave-url');
    var csrf = page.getAttribute('data-csrf');

    /* Where the "Saved" tick goes: the switch's own .form-check keeps it beside
     * the label, a crispy field has its div_id_* wrapper, and anything
     * hand-rendered falls back to whatever contains it. `_autosaveRow` is the
     * escape hatch for a control that isn't near what it belongs to — the
     * colour pickers' hidden input sits outside the picker it drives. */
    function rowFor(input) {
      return input._autosaveRow ||
             input.closest('.form-check') ||
             document.getElementById('div_id_' + input.name) ||
             input.parentElement;
    }

    function flag(input, state, message) {
      var row = rowFor(input);
      if (!row) return;
      var el = row.querySelector(':scope > .autosave-flag');
      if (!el) {
        el = document.createElement('span');
        el.className = 'autosave-flag';
        row.appendChild(el);
      }
      // A save during the fade-out reuses this element, so cancel both stages
      // or it would vanish mid-message.
      clearTimeout(el._hide);
      clearTimeout(el._drop);
      el.classList.toggle('autosave-flag--error', state === 'error');
      el.innerHTML = state === 'error'
        ? '<i class="bi bi-exclamation-circle"></i> '
        : '<i class="bi bi-check-lg"></i> ';
      el.appendChild(document.createTextNode(message));
      el.classList.add('is-shown');
      // An error stays until the next attempt — it explains why the control
      // moved back, and a message that vanishes leaves that unexplained.
      if (state !== 'error') {
        el._hide = setTimeout(function () {
          el.classList.remove('is-shown');
          // Fading to opacity 0 leaves the element holding its margin and its
          // width — and on a crispy field or the calendar address input, where
          // it sits *below* a block-level control, a whole line of height. So
          // take it back out of the layout once the fade has run.
          el._drop = setTimeout(function () { el.remove(); }, 250);
        }, 1600);
      }
    }

    function currentValue(input) {
      return input.type === 'checkbox' ? input.checked : input.value;
    }

    function remember(input) { input._autosaved = currentValue(input); }

    function revert(input) {
      if (input.type === 'checkbox') input.checked = input._autosaved;
      else input.value = input._autosaved;
      // Muted: dependent UI listens on `change`, but this is the server undoing
      // an edit, not the owner making one — re-saving it would be a loop.
      input._autosaveMuted = true;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      input._autosaveMuted = false;
    }

    function saveNow(input) {
      var body = new URLSearchParams();
      body.set('scope', input.getAttribute('data-autosave'));
      body.set('field', input.name);
      // An unchecked box posts nothing at all — that is how Django's
      // BooleanField already reads "off", so the server needs no special case.
      if (input.type !== 'checkbox' || input.checked) {
        body.set(input.name, input.type === 'checkbox' ? (input.value || 'on') : input.value);
      }
      fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrf,
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: body.toString(),
      }).then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      // Two-argument then, not a trailing .catch: the rejection handler must see
      // only a failed request. A .catch here would also swallow anything thrown
      // by the success branch below and revert a setting that did save.
      }).then(function (res) {
        if (!res.ok || !res.data.ok) {
          revert(input);
          flag(input, 'error', (res.data && res.data.error) || "That didn't save.");
          return;
        }
        // The form may have normalised the input (a blank invite title becomes
        // the built-in default) — show what was actually stored.
        if (input.type !== 'checkbox' && typeof res.data.value === 'string' &&
            res.data.value !== input.value) {
          input.value = res.data.value;
        }
        remember(input);
        flag(input, 'saved', 'Saved');
        afterSave(input);
      }, function () {
        revert(input);
        flag(input, 'error', 'Could not reach the server.');
      });
    }

    /* Settings whose effect is visible on this very page. Everything else
     * (week start, shift-type colours) simply applies on the next page it
     * touches, which is where you'd see it anyway. */
    function afterSave(input) {
      if (input.name === 'theme') applyTheme(input.value);
      if (input.name === 'show_help_button') {
        var fab = document.querySelector('[data-help-fab]');
        if (fab) fab.hidden = !input.checked;
      }
      var card = input.closest('[data-feature]');
      if (card) {
        // The nav must not disagree with the switch you're looking at.
        var nav = document.querySelector('[data-feature-nav="' + card.dataset.feature + '"]');
        if (nav) nav.hidden = !input.checked;
      }
    }

    function applyTheme(theme) {
      var root = document.documentElement;
      if (theme === 'auto') {
        root.setAttribute('data-theme-auto', '');
        root.setAttribute('data-bs-theme',
          window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      } else {
        root.removeAttribute('data-theme-auto');
        root.setAttribute('data-bs-theme', theme);
      }
    }

    document.querySelectorAll('[data-autosave]').forEach(function (input) {
      remember(input);
      input.addEventListener('change', function () {
        if (input._autosaveMuted) return;
        saveNow(input);
      });
    });

    // Handed to the colour pickers, which drive a hidden input no `change`
    // event ever reaches.
    return function (input, delay) {
      clearTimeout(input._autosaveTimer);
      input._autosaveTimer = setTimeout(function () { saveNow(input); }, delay || 600);
    };
  }

  var autosaveSoon = autosaveInit();

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

  /* Sign-in tab: the "no working mail server" warning under Password reset by
   * email. Server-rendered (whether mail works can't change here) but revealed
   * with the switch, so turning it on warns straight away rather than only after
   * the next page load. */
  (function () {
    var box = document.querySelector('[data-signin-reset]');
    if (!box) return;
    var input = box.querySelector('.form-check-input');
    var warn = box.querySelector('[data-signin-reset-warn]');
    if (!input || !warn) return;
    function apply() { warn.hidden = !input.checked; }
    input.addEventListener('change', apply);
    apply();
  })();

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
