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

    // A [data-help-open="slug"] element anywhere on the page (the in-panel handler
    // on `root` covers ones inside the popup) opens the popup straight to that
    // article — used by the onboarding Review "?" nudges. When the panel is shut
    // we open it, then load the article once it's shown (the shown handler resets
    // to the context view first; ours runs after and wins).
    document.addEventListener("click", function (e) {
      var opener = e.target.closest("[data-help-open]");
      if (!opener || root.contains(opener)) return;
      e.preventDefault();
      var slug = opener.getAttribute("data-help-open");
      if (root.classList.contains("show")) { openArticle(slug); return; }
      root.addEventListener("shown.bs.offcanvas", function once() {
        root.removeEventListener("shown.bs.offcanvas", once);
        openArticle(slug);
      });
      getOffcanvas().show();
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
    // Every occurrence of any term, merged so overlapping terms ("pay",
    // "payroll") don't produce nested <mark>s.
    function matchRanges(text, terms) {
      var lower = text.toLowerCase(), ranges = [];
      terms.forEach(function (t) {
        var i = lower.indexOf(t);
        while (i !== -1) { ranges.push([i, i + t.length]); i = lower.indexOf(t, i + t.length); }
      });
      ranges.sort(function (a, b) { return a[0] - b[0]; });
      var merged = [];
      ranges.forEach(function (r) {
        var last = merged[merged.length - 1];
        if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
        else merged.push([r[0], r[1]]);
      });
      return merged;
    }
    function highlight(text, terms) {
      var out = "", pos = 0;
      matchRanges(text, terms).forEach(function (r) {
        out += escapeHtml(text.slice(pos, r[0])) +
          "<mark>" + escapeHtml(text.slice(r[0], r[1])) + "</mark>";
        pos = r[1];
      });
      return out + escapeHtml(text.slice(pos));
    }
    // The sentence fragment a body-only match was found in. Without it a hit
    // deep in an article is indistinguishable from no reason to be listed.
    var SNIPPET_PAD = 70;
    function bodySnippet(body, terms) {
      var lower = body.toLowerCase(), at = -1, hitLen = 0;
      terms.forEach(function (t) {
        var j = lower.indexOf(t);
        if (j !== -1 && (at === -1 || j < at)) { at = j; hitLen = t.length; }
      });
      if (at === -1) return "";
      var start = Math.max(0, at - SNIPPET_PAD);
      var end = Math.min(body.length, at + hitLen + SNIPPET_PAD * 2);
      if (start > 0) { // don't open mid-word
        var sp = body.indexOf(" ", start);
        if (sp !== -1 && sp < at) start = sp + 1;
      }
      if (end < body.length) {
        var sp2 = body.lastIndexOf(" ", end);
        if (sp2 > at) end = sp2;
      }
      return (start > 0 ? "…" : "") + body.slice(start, end).trim() +
        (end < body.length ? "…" : "");
    }
    // Lower-cased fields are cached on the record: runSearch re-scores the whole
    // index on every keystroke.
    function fields(article) {
      if (!article._lc) {
        article._lc = {
          title: (article.title || "").toLowerCase(),
          kws: (article.keywords || []).join(" ").toLowerCase(),
          summary: (article.summary || "").toLowerCase(),
          body: (article.body || "").toLowerCase(),
        };
      }
      return article._lc;
    }
    // Each term must appear *somewhere* (AND), so extra words narrow rather
    // than widen. ``bodyOnly`` records that a term was found only in the body —
    // that's the result that needs a snippet to explain itself.
    function score(article, terms, phrase) {
      var f = fields(article), total = 0, bodyOnly = false;
      for (var i = 0; i < terms.length; i++) {
        var t = terms[i], named = 0;
        if (f.title.indexOf(t) === 0) named += 100;
        else if (f.title.indexOf(t) !== -1) named += 60;
        if (f.kws.indexOf(t) !== -1) named += 30;
        if (f.summary.indexOf(t) !== -1) named += 15;
        var inBody = f.body.indexOf(t) !== -1;
        if (!named && !inBody) return { s: 0 };
        if (inBody && !named) bodyOnly = true;
        total += named + (inBody ? 8 : 0);
      }
      // A multi-word query that appears verbatim beats the same words scattered.
      if (terms.length > 1) {
        if (f.title.indexOf(phrase) !== -1) total += 40;
        if (f.body.indexOf(phrase) !== -1) total += 10;
      }
      return { s: total, bodyOnly: bodyOnly };
    }
    function runSearch(rawQuery) {
      var phrase = rawQuery.trim().toLowerCase();
      if (!phrase) { showView("context"); activeIdx = -1; return; }
      var terms = phrase.split(/\s+/).filter(function (t) { return t; });
      ensureIndex().then(function (items) {
        var matches = items
          .map(function (a) {
            var r = score(a, terms, phrase);
            return { a: a, s: r.s, bodyOnly: r.bodyOnly };
          })
          .filter(function (m) { return m.s > 0; })
          .sort(function (x, y) { return y.s - x.s; })
          .slice(0, 20);
        renderResults(matches, terms);
      });
    }
    function renderResults(matches, terms) {
      showView("results");
      activeIdx = -1;
      resultsList.innerHTML = "";
      noResults.classList.toggle("d-none", matches.length > 0);
      matches.forEach(function (m, i) {
        var li = document.createElement("li");
        li.className = "help-result";
        li.setAttribute("data-help-open", m.a.slug);
        li.setAttribute("data-idx", i);
        var html = '<div class="help-result-title">' + highlight(m.a.title, terms) + "</div>";
        if (m.a.summary) {
          html += '<div class="help-result-summary">' + highlight(m.a.summary, terms) + "</div>";
        }
        if (m.bodyOnly) {
          var snip = bodySnippet(m.a.body || "", terms);
          if (snip) html += '<div class="help-result-snippet">' + highlight(snip, terms) + "</div>";
        }
        li.innerHTML = html;
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
    // A link inside an article body points at the full manual page. Following it
    // would throw the reader out of the popup — and, mid-onboarding, out of the
    // wizard and into the running app — when all they wanted was a quick look at
    // a related article. Keep those in the panel; anything else (an external
    // link, a deep link into the app) behaves normally.
    function slugFromHref(href) {
      if (!href || !articleUrlTpl) return null;
      var parts = articleUrlTpl.split("SLUG");
      var prefix = parts[0], suffix = parts[1] || "";
      var path = href.split("?")[0].split("#")[0];
      if (path.indexOf(prefix) !== 0) return null;
      var rest = path.slice(prefix.length);
      if (suffix && rest.slice(-suffix.length) === suffix) rest = rest.slice(0, -suffix.length);
      // A single path segment is an article; anything deeper isn't.
      return rest && rest.indexOf("/") === -1 ? decodeURIComponent(rest) : null;
    }

    root.addEventListener("click", function (e) {
      var opener = e.target.closest("[data-help-open]");
      if (opener) { e.preventDefault(); openArticle(opener.getAttribute("data-help-open")); return; }

      var link = e.target.closest("a[href]");
      if (!link || link.hasAttribute("data-help-manual-link")) return;
      var slug = slugFromHref(link.getAttribute("href"));
      if (slug) { e.preventDefault(); openArticle(slug); }
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

  // ── Manage page: search bar, per-column checkbox filters, single-active sort ──
  (function initHelpManage() {
    var root = document.querySelector("[data-help-manage]");
    if (!root) return;
    var search = root.querySelector("[data-manage-search]");
    var clearBtn = root.querySelector("[data-manage-clear]");
    var tbody = root.querySelector("tbody");
    var rows = Array.prototype.slice.call(root.querySelectorAll("tr[data-row]"));
    var originalOrder = rows.slice();
    var emptyMsg = root.querySelector("[data-manage-empty]");
    var filterCols = ["pages", "keywords", "status"];
    var sortKey = null, sortDir = 0; // 1 asc, -1 desc, 0 off

    function selectedFor(col) {
      return Array.prototype.slice
        .call(root.querySelectorAll('[data-filter-options="' + col + '"] input:checked'))
        .map(function (c) { return c.value; });
    }
    function colMatch(row, col, selected) {
      if (!selected.length) return true;
      var vals = (row.getAttribute("data-" + col) || "").split("|");
      return selected.some(function (s) { return vals.indexOf(s) !== -1; });
    }

    function apply() {
      var q = (search && search.value || "").trim().toLowerCase();
      var sel = {};
      filterCols.forEach(function (col) {
        sel[col] = selectedFor(col);
        // Funnel icon reflects whether this column is filtered.
        var btn = root.querySelector('[data-filter-btn="' + col + '"]');
        if (btn) {
          var on = sel[col].length > 0;
          btn.classList.toggle("active", on);
          var icon = btn.querySelector("i");
          if (icon) icon.className = on ? "bi bi-funnel-fill" : "bi bi-funnel";
        }
      });
      var shown = 0;
      rows.forEach(function (r) {
        var ok = !q || (r.getAttribute("data-search") || "").indexOf(q) !== -1;
        filterCols.forEach(function (col) { ok = ok && colMatch(r, col, sel[col]); });
        r.classList.toggle("d-none", !ok);
        if (ok) shown++;
      });
      if (emptyMsg) emptyMsg.classList.toggle("d-none", shown > 0 || rows.length === 0);
      updateClear();
    }

    function anyActive() {
      if (search && search.value.trim()) return true;
      if (sortDir !== 0) return true;
      return root.querySelector("[data-filter-options] input:checked") != null;
    }
    function updateClear() {
      if (clearBtn) clearBtn.classList.toggle("d-none", !anyActive());
    }

    // Search + checkbox changes re-filter.
    if (search) search.addEventListener("input", apply);
    root.querySelectorAll('[data-filter-options] input[type="checkbox"]').forEach(function (cb) {
      cb.addEventListener("change", apply);
    });

    // A "Clear" button at the bottom of each funnel menu clears that column.
    filterCols.forEach(function (col) {
      var opts = root.querySelector('[data-filter-options="' + col + '"]');
      var menu = opts && opts.closest(".help-filter-menu");
      if (!menu) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-sm btn-outline-secondary w-100 mt-2";
      btn.textContent = "Clear";
      btn.addEventListener("click", function () {
        opts.querySelectorAll('input[type="checkbox"]').forEach(function (c) { c.checked = false; });
        apply();
      });
      menu.appendChild(btn);
    });

    // Global "Clear filters": reset search, all checkboxes, menu searches, sort.
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        if (search) search.value = "";
        root.querySelectorAll('[data-filter-options] input[type="checkbox"]').forEach(function (c) { c.checked = false; });
        root.querySelectorAll("[data-filter-search]").forEach(function (b) { b.value = ""; });
        root.querySelectorAll(".help-filter-options .form-check").forEach(function (o) { o.classList.remove("d-none"); });
        sortKey = null; sortDir = 0;
        applyOrder(originalOrder);
        updateSortIcons();
        apply();
      });
    }

    // Per-menu search box narrows that column's checkbox list.
    root.querySelectorAll("[data-filter-search]").forEach(function (box) {
      box.addEventListener("input", function () {
        var q = box.value.trim().toLowerCase();
        var options = box.parentElement.querySelectorAll(".form-check");
        options.forEach(function (opt) {
          var label = (opt.textContent || "").trim().toLowerCase();
          opt.classList.toggle("d-none", q && label.indexOf(q) === -1);
        });
      });
    });

    // ── Sorting: one active column at a time (asc → desc → off) ──
    function applyOrder(list) { list.forEach(function (r) { tbody.appendChild(r); }); }
    function updateSortIcons() {
      root.querySelectorAll("[data-sort]").forEach(function (btn) {
        var active = btn.getAttribute("data-sort") === sortKey && sortDir !== 0;
        btn.classList.toggle("sorted", active);
        var icon = btn.querySelector(".help-sort-icon");
        if (icon) {
          icon.className = "help-sort-icon bi " +
            (active ? (sortDir === 1 ? "bi-sort-down-alt" : "bi-sort-up-alt") : "bi-arrow-down-up");
        }
      });
    }
    function doSort() {
      if (!sortKey || sortDir === 0) { applyOrder(originalOrder); return; }
      var attr = "data-" + sortKey;
      var sorted = rows.slice().sort(function (a, b) {
        var va = a.getAttribute(attr) || "", vb = b.getAttribute(attr) || "";
        return va < vb ? -1 : va > vb ? 1 : 0;
      });
      if (sortDir === -1) sorted.reverse();
      applyOrder(sorted);
    }
    root.querySelectorAll("[data-sort]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.getAttribute("data-sort");
        if (sortKey !== key) { sortKey = key; sortDir = 1; }
        else { sortDir = sortDir === 1 ? -1 : sortDir === -1 ? 0 : 1; }
        if (sortDir === 0) sortKey = null;
        doSort();
        updateSortIcons();
        updateClear();
      });
    });

    apply();
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
