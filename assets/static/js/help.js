/*
 * BitGigs help system (client side).
 *   1. The context-aware popup: F1 / floating button, "for this page" articles,
 *      and instant search-as-you-type over a JSON index. Opens above modals.
 *   2. The editor: live preview, formatting toolbar, "/" slash command menu,
 *      live slug, and an unsaved-changes guard.
 * Each block runs only when its DOM hooks exist, so this loads on every page.
 */
(function () {
  "use strict";

  // ── Popup ──────────────────────────────────────────────────────────────────
  (function initHelpPopup() {
    var root = document.getElementById("helpOffcanvas");
    if (!root || typeof bootstrap === "undefined") return;

    var pageKey = root.getAttribute("data-help-page") || "";
    var contextUrl = root.getAttribute("data-context-url");
    var indexUrl = root.getAttribute("data-index-url");
    var fragmentUrlTpl = root.getAttribute("data-fragment-url"); // .../SLUG/...
    var articleUrlTpl = root.getAttribute("data-article-url");   // full-page /help/SLUG/
    var manualUrl = root.getAttribute("data-manual-url");

    var manualLink = root.querySelector("[data-help-manual-link]");
    var searchInput = root.querySelector("[data-help-search]");
    var contextBox = root.querySelector("[data-help-context]");
    var resultsList = root.querySelector("[data-help-results]");
    var noResults = root.querySelector("[data-help-noresults]");
    var contentBox = root.querySelector("[data-help-content]");
    var views = {
      context: root.querySelector('[data-help-view="context"]'),
      results: root.querySelector('[data-help-view="results"]'),
      content: root.querySelector('[data-help-view="content"]'),
    };
    var backBtn = root.querySelector("[data-help-back]");

    var index = null;
    var activeIdx = -1;
    var previousView = "context";
    var suspendedTrap = null; // an open modal's focus-trap, paused while help shows

    function getOffcanvas() {
      return bootstrap.Offcanvas.getOrCreateInstance(root);
    }
    function showView(name) {
      Object.keys(views).forEach(function (key) {
        if (views[key]) views[key].classList.toggle("d-none", key !== name);
      });
      // "Full manual" jumps to the open article's page, else the manual index.
      if (name !== "content") setManualLink(null);
    }
    function setManualLink(slug) {
      if (!manualLink) return;
      manualLink.href = slug && articleUrlTpl
        ? articleUrlTpl.replace("SLUG", encodeURIComponent(slug))
        : manualUrl;
    }
    function fragmentUrl(slug) {
      return fragmentUrlTpl.replace("SLUG", encodeURIComponent(slug));
    }

    // F1 toggles help from anywhere (including inside a modal).
    document.addEventListener("keydown", function (e) {
      if (e.key === "F1") {
        e.preventDefault();
        getOffcanvas().toggle();
      }
    });

    // A Bootstrap modal traps focus inside itself; while help is open over one,
    // pause that trap so the search box is typeable, then restore it.
    root.addEventListener("show.bs.offcanvas", function () {
      try {
        var modalEl = document.querySelector(".modal.show");
        if (modalEl) {
          var inst = bootstrap.Modal.getInstance(modalEl);
          if (inst && inst._focustrap) {
            inst._focustrap.deactivate();
            suspendedTrap = inst._focustrap;
          }
        }
      } catch (err) {
        /* private API moved — help still opens, focus just stays trapped */
      }
    });
    root.addEventListener("hidden.bs.offcanvas", function () {
      if (suspendedTrap) {
        try { suspendedTrap.activate(); } catch (err) { /* noop */ }
        suspendedTrap = null;
      }
    });

    root.addEventListener("shown.bs.offcanvas", function () {
      // Fresh context each open, so it reflects the current approve-modal state.
      if (searchInput) searchInput.value = "";
      showView("context");
      loadContext();
      if (searchInput) searchInput.focus();
    });

    function loadContext() {
      if (!contextUrl || !contextBox) return;
      // Signal pending approvals (and whether the approval modal is open) so the
      // server can surface the approve-shifts article, at the top when open.
      var approveModal = document.querySelector("[data-approve-modal]");
      var params = "?page=" + encodeURIComponent(pageKey);
      if (approveModal) {
        params += "&approve=1";
        if (approveModal.classList.contains("show")) params += "&approve_open=1";
      }
      if (!pageKey && !approveModal) {
        contextBox.innerHTML = emptyContextHtml();
        return;
      }
      fetch(contextUrl + params)
        .then(function (r) { return r.text(); })
        .then(function (html) { contextBox.innerHTML = html; })
        .catch(function () { contextBox.innerHTML = emptyContextHtml(); });
    }
    function emptyContextHtml() {
      return '<div class="help-empty text-body-secondary">Search above to find help.</div>';
    }

    function ensureIndex() {
      if (index) return Promise.resolve(index);
      return fetch(indexUrl)
        .then(function (r) { return r.json(); })
        .then(function (data) { index = data.articles || []; return index; })
        .catch(function () { index = []; return index; });
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }
    function highlight(text, q) {
      var i = text.toLowerCase().indexOf(q);
      if (i === -1) return escapeHtml(text);
      return (
        escapeHtml(text.slice(0, i)) +
        "<mark>" + escapeHtml(text.slice(i, i + q.length)) + "</mark>" +
        escapeHtml(text.slice(i + q.length))
      );
    }
    function score(article, q) {
      var title = (article.title || "").toLowerCase();
      var kws = (article.keywords || []).join(" ").toLowerCase();
      var summary = (article.summary || "").toLowerCase();
      var body = (article.body || "").toLowerCase();
      var s = 0;
      if (title.indexOf(q) === 0) s += 100;
      else if (title.indexOf(q) !== -1) s += 60;
      if (kws.indexOf(q) !== -1) s += 30;
      if (summary.indexOf(q) !== -1) s += 15;
      if (body.indexOf(q) !== -1) s += 5;
      return s;
    }
    function runSearch(rawQuery) {
      var q = rawQuery.trim().toLowerCase();
      if (!q) { showView("context"); activeIdx = -1; return; }
      ensureIndex().then(function (items) {
        var matches = items
          .map(function (a) { return { a: a, s: score(a, q) }; })
          .filter(function (m) { return m.s > 0; })
          .sort(function (x, y) { return y.s - x.s; })
          .slice(0, 20);
        renderResults(matches, q);
      });
    }
    function renderResults(matches, q) {
      showView("results");
      activeIdx = -1;
      resultsList.innerHTML = "";
      noResults.classList.toggle("d-none", matches.length > 0);
      matches.forEach(function (m, i) {
        var li = document.createElement("li");
        li.className = "help-result";
        li.setAttribute("data-help-open", m.a.slug);
        li.setAttribute("data-idx", i);
        var summary = m.a.summary
          ? '<div class="help-result-summary">' + escapeHtml(m.a.summary) + "</div>" : "";
        li.innerHTML = '<div class="help-result-title">' + highlight(m.a.title, q) + "</div>" + summary;
        resultsList.appendChild(li);
      });
    }
    function setActive(idx) {
      var items = resultsList.querySelectorAll(".help-result");
      if (!items.length) return;
      if (idx < 0) idx = items.length - 1;
      if (idx >= items.length) idx = 0;
      items.forEach(function (el) { el.classList.remove("active"); });
      items[idx].classList.add("active");
      items[idx].scrollIntoView({ block: "nearest" });
      activeIdx = idx;
    }
    function openArticle(slug) {
      previousView = views.results.classList.contains("d-none") ? "context" : "results";
      contentBox.innerHTML = '<div class="help-empty text-body-secondary">Loading…</div>';
      showView("content");
      setManualLink(slug); // Full manual now points at this article's full page
      fetch(fragmentUrl(slug))
        .then(function (r) { return r.text(); })
        .then(function (html) { contentBox.innerHTML = html; contentBox.scrollTop = 0; })
        .catch(function () {
          contentBox.innerHTML = '<div class="help-empty text-body-secondary">Could not load this article.</div>';
        });
    }

    if (searchInput) {
      searchInput.addEventListener("input", function () { runSearch(searchInput.value); });
      searchInput.addEventListener("keydown", function (e) {
        if (views.results.classList.contains("d-none")) return;
        if (e.key === "ArrowDown") { e.preventDefault(); setActive(activeIdx + 1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); setActive(activeIdx - 1); }
        else if (e.key === "Enter") {
          var items = resultsList.querySelectorAll(".help-result");
          var target = activeIdx >= 0 ? items[activeIdx] : items[0];
          if (target) { e.preventDefault(); openArticle(target.getAttribute("data-help-open")); }
        }
      });
    }
    root.addEventListener("click", function (e) {
      var opener = e.target.closest("[data-help-open]");
      if (opener) { e.preventDefault(); openArticle(opener.getAttribute("data-help-open")); }
    });
    // Keyboard-openable context items (role="button" tabindex="0").
    root.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      var opener = e.target.closest("[data-help-open]");
      if (opener) { e.preventDefault(); openArticle(opener.getAttribute("data-help-open")); }
    });
    if (backBtn) backBtn.addEventListener("click", function () { showView(previousView); });
  })();

  // ── Editor ──────────────────────────────────────────────────────────────────
  (function initHelpEditor() {
    var form = document.querySelector(".help-editor");
    if (!form) return;
    var body = form.querySelector("#helpBodyInput");
    if (!body) return;

    var preview = form.querySelector(".help-preview");
    var previewUrl = form.getAttribute("data-preview-url");
    var tabs = form.querySelectorAll("[data-help-tab]");
    var panes = {
      write: form.querySelector('[data-help-pane="write"]'),
      preview: form.querySelector('[data-help-pane="preview"]'),
    };

    function csrf() {
      var el = form.querySelector("[name=csrfmiddlewaretoken]");
      return el ? el.value : "";
    }

    // — Textarea helpers —
    function replaceRange(start, end, text, selStart, selEnd) {
      body.value = body.value.slice(0, start) + text + body.value.slice(end);
      body.focus();
      body.selectionStart = selStart != null ? selStart : start + text.length;
      body.selectionEnd = selEnd != null ? selEnd : body.selectionStart;
      onChanged();
    }
    function wrapInline(before, after, placeholder) {
      var s = body.selectionStart, e = body.selectionEnd;
      var sel = body.value.slice(s, e) || placeholder || "text";
      replaceRange(s, e, before + sel + after, s + before.length, s + before.length + sel.length);
    }
    function prefixLines(prefix) {
      var s = body.selectionStart, e = body.selectionEnd, val = body.value;
      var lineStart = val.lastIndexOf("\n", s - 1) + 1;
      var seg = val.slice(lineStart, e) || "";
      var lines = (seg || "text").split("\n").map(function (l) { return prefix + l; });
      replaceRange(lineStart, e, lines.join("\n"));
    }
    function insertBlock(text) {
      var s = body.selectionStart, val = body.value;
      var before = val.slice(0, s);
      var lead = before.length && !before.endsWith("\n") ? "\n" : "";
      var insertion = lead + text + "\n";
      replaceRange(s, s, insertion);
    }

    // — Command catalogue (shared by toolbar + slash menu) —
    var TABLE = "| Column | Column |\n|---|---|\n| Cell | Cell |";
    var commands = [
      { id: "h1", label: "Heading 1", icon: "H1", group: "Headings", hint: "#", run: function () { prefixLines("# "); } },
      { id: "h2", label: "Heading 2", icon: "H2", group: "Headings", hint: "##", run: function () { prefixLines("## "); } },
      { id: "h3", label: "Heading 3", icon: "H3", group: "Headings", hint: "###", run: function () { prefixLines("### "); } },
      { id: "bold", label: "Bold", icon: "<i class='bi bi-type-bold'></i>", group: "Format", tb: true, run: function () { wrapInline("**", "**", "bold"); } },
      { id: "italic", label: "Italic", icon: "<i class='bi bi-type-italic'></i>", group: "Format", tb: true, run: function () { wrapInline("*", "*", "italic"); } },
      { id: "strike", label: "Strikethrough", icon: "<i class='bi bi-type-strikethrough'></i>", group: "Format", tb: true, run: function () { wrapInline("~~", "~~", "struck"); } },
      { id: "code", label: "Inline code", icon: "<i class='bi bi-code'></i>", group: "Format", tb: true, run: function () { wrapInline("`", "`", "code"); } },
      { id: "quote", label: "Quote", icon: "<i class='bi bi-quote'></i>", group: "Basic blocks", tb: true, run: function () { prefixLines("> "); } },
      { id: "ul", label: "Bullet list", icon: "<i class='bi bi-list-ul'></i>", group: "Basic blocks", tb: true, run: function () { prefixLines("- "); } },
      { id: "ol", label: "Numbered list", icon: "<i class='bi bi-list-ol'></i>", group: "Basic blocks", tb: true, run: function () { prefixLines("1. "); } },
      { id: "check", label: "Check list", icon: "<i class='bi bi-check2-square'></i>", group: "Basic blocks", tb: true, run: function () { prefixLines("- [ ] "); } },
      { id: "codeblock", label: "Code block", icon: "<i class='bi bi-code-square'></i>", group: "Basic blocks", run: function () { insertBlock("```\ncode\n```"); } },
      { id: "divider", label: "Divider", icon: "<i class='bi bi-dash-lg'></i>", group: "Basic blocks", run: function () { insertBlock("---"); } },
      { id: "table", label: "Table", icon: "<i class='bi bi-table'></i>", group: "Advanced", tb: true, run: function () { insertBlock(TABLE); } },
      { id: "link", label: "Link", icon: "<i class='bi bi-link-45deg'></i>", group: "Advanced", tb: true, run: function () { wrapInline("[", "](https://)", "text"); } },
      { id: "image", label: "Image", icon: "<i class='bi bi-image'></i>", group: "Media", tb: true, run: function () { insertBlock("![alt](https://)"); } },
    ];
    function byId(id) { return commands.find(function (c) { return c.id === id; }); }

    // — Toolbar —
    var toolbar = form.querySelector("[data-help-toolbar]");
    if (toolbar) {
      var tbLayout = ["h2", "bold", "italic", "strike", "code", "sep",
        "quote", "ul", "ol", "check", "sep", "link", "image", "table"];
      tbLayout.forEach(function (id) {
        if (id === "sep") {
          var sep = document.createElement("span");
          sep.className = "help-toolbar-sep";
          toolbar.appendChild(sep);
          return;
        }
        var cmd = byId(id);
        var btn = document.createElement("button");
        btn.type = "button";
        btn.title = cmd.label;
        btn.innerHTML = cmd.icon;
        btn.addEventListener("click", function () { cmd.run(); });
        toolbar.appendChild(btn);
      });
    }

    // — Slash command menu —
    var menu = null, slashStart = -1, slashActive = false, slashIdx = 0, slashItems = [];

    function closeSlash() {
      slashActive = false;
      slashStart = -1;
      if (menu) { menu.remove(); menu = null; }
    }
    function currentQuery() {
      return body.value.slice(slashStart + 1, body.selectionStart);
    }
    function openSlash() {
      slashActive = true;
      slashStart = body.selectionStart - 1;
      slashIdx = 0;
      renderSlash();
    }
    function renderSlash() {
      var q = currentQuery().toLowerCase();
      // Close if the "/" was deleted or a space was typed into an empty query.
      if (slashStart < 0 || body.value[slashStart] !== "/" || /\s/.test(q)) { closeSlash(); return; }
      var matched = commands.filter(function (c) {
        return !q || c.label.toLowerCase().indexOf(q) !== -1 || c.id.indexOf(q) !== -1;
      });
      slashItems = matched;
      if (!matched.length) { closeSlash(); return; }
      if (slashIdx >= matched.length) slashIdx = matched.length - 1;

      if (!menu) {
        menu = document.createElement("div");
        menu.className = "help-slash-menu";
        document.body.appendChild(menu);
      }
      var html = "";
      var lastGroup = null;
      matched.forEach(function (c, i) {
        if (c.group !== lastGroup) { html += '<div class="help-slash-group">' + c.group + "</div>"; lastGroup = c.group; }
        html += '<div class="help-slash-item' + (i === slashIdx ? " active" : "") +
          '" data-slash="' + c.id + '">' +
          '<span class="help-slash-icon">' + c.icon + "</span>" +
          '<span class="help-slash-label">' + c.label + "</span>" +
          (c.hint ? '<span class="help-slash-hint">' + c.hint + "</span>" : "") +
          "</div>";
      });
      menu.innerHTML = html;
      positionSlash();

      menu.querySelectorAll(".help-slash-item").forEach(function (el) {
        el.addEventListener("mousedown", function (e) {
          e.preventDefault();
          chooseSlash(byId(el.getAttribute("data-slash")));
        });
      });
    }
    function chooseSlash(cmd) {
      // Remove the "/query" the user typed, then run the command in its place.
      var end = body.selectionStart;
      body.value = body.value.slice(0, slashStart) + body.value.slice(end);
      body.selectionStart = body.selectionEnd = slashStart;
      closeSlash();
      cmd.run();
    }
    function moveSlash(delta) {
      slashIdx = (slashIdx + delta + slashItems.length) % slashItems.length;
      renderSlash();
    }
    function positionSlash() {
      var coords = caretCoords(body, slashStart);
      var rect = body.getBoundingClientRect();
      var top = rect.top + coords.top - body.scrollTop + coords.height + 4;
      var left = rect.left + coords.left - body.scrollLeft;
      // Keep it on screen.
      left = Math.min(left, window.innerWidth - menu.offsetWidth - 12);
      if (top + menu.offsetHeight > window.innerHeight) {
        top = rect.top + coords.top - body.scrollTop - menu.offsetHeight - 4;
      }
      menu.style.top = Math.max(8, top) + "px";
      menu.style.left = Math.max(8, left) + "px";
    }

    body.addEventListener("keydown", function (e) {
      if (slashActive && menu) {
        if (e.key === "ArrowDown") { e.preventDefault(); moveSlash(1); return; }
        if (e.key === "ArrowUp") { e.preventDefault(); moveSlash(-1); return; }
        if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); chooseSlash(slashItems[slashIdx]); return; }
        if (e.key === "Escape") { e.preventDefault(); closeSlash(); return; }
      }
    });
    body.addEventListener("input", function () {
      onChanged();
      var ch = body.value[body.selectionStart - 1];
      if (!slashActive) {
        var prev = body.value[body.selectionStart - 2];
        if (ch === "/" && (body.selectionStart === 1 || prev === "\n" || prev === " ")) {
          openSlash();
        }
      } else {
        renderSlash();
      }
    });
    body.addEventListener("blur", function () { setTimeout(closeSlash, 150); });

    // — Live preview —
    var lastRendered = null, previewTimer = null;
    function renderPreview() {
      if (body.value === lastRendered) return;
      lastRendered = body.value;
      var data = new FormData();
      data.append("body_md", body.value);
      data.append("csrfmiddlewaretoken", csrf());
      fetch(previewUrl, { method: "POST", body: data, headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { if (preview) preview.innerHTML = html; })
        .catch(function () { if (preview) preview.innerHTML = '<em class="text-body-secondary">Preview unavailable.</em>'; });
    }
    function schedulePreview() {
      clearTimeout(previewTimer);
      previewTimer = setTimeout(renderPreview, 250);
    }
    function showTab(name) {
      tabs.forEach(function (t) { t.classList.toggle("active", t.getAttribute("data-help-tab") === name); });
      if (panes.write) panes.write.classList.toggle("d-none", name !== "write");
      if (panes.preview) panes.preview.classList.toggle("d-none", name !== "preview");
      if (name === "preview") renderPreview();
    }
    tabs.forEach(function (t) {
      t.addEventListener("click", function () { showTab(t.getAttribute("data-help-tab")); });
    });

    // — Live slug (only while the slug is empty / untouched) —
    var titleInput = form.querySelector("[name=title]");
    var slugInput = form.querySelector("[name=slug]");
    var autoSlug = slugInput ? slugInput.value.trim() === "" : false;
    function slugify(s) {
      return s.toLowerCase().trim()
        .replace(/[^a-z0-9\s-]/g, "")
        .replace(/[\s_-]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 80);
    }
    if (titleInput && slugInput) {
      slugInput.addEventListener("input", function () { autoSlug = slugInput.value.trim() === ""; });
      titleInput.addEventListener("input", function () {
        if (autoSlug) slugInput.value = slugify(titleInput.value);
      });
    }

    // — Unsaved-changes guard —
    var dirty = false, submitting = false;
    function onChanged() { dirty = true; schedulePreview(); }
    form.addEventListener("input", function () { dirty = true; });
    form.addEventListener("change", function () { dirty = true; });
    form.addEventListener("submit", function () { submitting = true; });
    window.addEventListener("beforeunload", function (e) {
      if (dirty && !submitting) { e.preventDefault(); e.returnValue = ""; }
    });
    form.querySelectorAll("[data-help-cancel]").forEach(function (link) {
      link.addEventListener("click", function (e) {
        if (dirty && !confirm("You have unsaved changes. Leave without saving?")) {
          e.preventDefault();
        } else {
          submitting = true; // allow navigation without the beforeunload prompt
        }
      });
    });
  })();

  // Caret pixel coordinates inside a <textarea> via a mirror element.
  function caretCoords(el, position) {
    var div = document.createElement("div");
    var style = getComputedStyle(el);
    [
      "boxSizing", "width", "height", "overflowX", "overflowY", "borderTopWidth",
      "borderRightWidth", "borderBottomWidth", "borderLeftWidth", "paddingTop",
      "paddingRight", "paddingBottom", "paddingLeft", "fontStyle", "fontVariant",
      "fontWeight", "fontStretch", "fontSize", "fontFamily", "lineHeight",
      "letterSpacing", "wordSpacing", "tabSize", "textIndent", "whiteSpace",
    ].forEach(function (prop) { div.style[prop] = style[prop]; });
    div.style.position = "absolute";
    div.style.visibility = "hidden";
    div.style.whiteSpace = "pre-wrap";
    div.style.wordWrap = "break-word";
    div.textContent = el.value.slice(0, position);
    var span = document.createElement("span");
    span.textContent = el.value.slice(position) || ".";
    div.appendChild(span);
    document.body.appendChild(div);
    var coords = { top: span.offsetTop, left: span.offsetLeft, height: parseInt(style.lineHeight, 10) || 18 };
    document.body.removeChild(div);
    return coords;
  }
})();
