// Settings → API tab: copy buttons, the all/selected scope toggle, and a
// confirm prompt on revoke. Guarded so it no-ops on every other tab.
(function () {
  const root = document.querySelector("[data-api-settings]");
  if (!root) return;

  // Copy-to-clipboard: works for both the one-time key <input> and the
  // sample-code <code> blocks. Brief visual confirmation on the button.
  root.querySelectorAll("[data-copy-target]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const el = document.getElementById(btn.dataset.copyTarget);
      if (!el) return;
      const text = "value" in el && el.value !== undefined && el.tagName === "INPUT"
        ? el.value
        : el.textContent;
      navigator.clipboard.writeText(text).then(() => {
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Copied';
        setTimeout(() => { btn.innerHTML = original; }, 1500);
      });
    });
  });

  // "Only selected endpoints" reveals the checkbox list; switching back to
  // "All" hides and clears it so a stale tick can't ride along in the POST.
  const scopeList = root.querySelector("[data-scope-list]");
  const radios = root.querySelectorAll('input[name="scope_mode"]');
  const syncScopes = () => {
    const selected = root.querySelector('input[name="scope_mode"]:checked');
    const showList = selected && selected.value === "selected";
    if (scopeList) {
      scopeList.hidden = !showList;
      if (!showList) {
        scopeList.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
          cb.checked = false;
        });
      }
    }
  };
  radios.forEach((radio) => radio.addEventListener("change", syncScopes));
  syncScopes();

  // Revoking is immediate and irreversible — ask first.
  root.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
})();
