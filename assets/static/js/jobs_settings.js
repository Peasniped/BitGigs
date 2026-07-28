// Settings → Jobs tab: the on/off switches, the expandable job rows, a confirm
// on the destructive queue clear, and a poll that keeps the heartbeat, the
// schedule table and the task queue live — a queued invite visibly moves
// Queued → Running → Done without touching reload. Guarded so it no-ops on
// every other settings tab.
(function () {
  const root = document.querySelector("[data-jobs-settings]");
  if (!root) return;

  // A switch flip submits its little form (no separate Save button).
  root.querySelectorAll(".job-toggle").forEach(function (input) {
    input.addEventListener("change", function () { input.form.submit(); });
  });

  // Rotate the chevron as its row expands/collapses.
  root.querySelectorAll(".collapse").forEach(function (panel) {
    const btn = root.querySelector('[data-bs-target="#' + panel.id + '"]');
    if (!btn) return;
    const icon = btn.querySelector("i");
    panel.addEventListener("show.bs.collapse", function () { icon.classList.replace("bi-chevron-right", "bi-chevron-down"); });
    panel.addEventListener("hide.bs.collapse", function () { icon.classList.replace("bi-chevron-down", "bi-chevron-right"); });
  });

  // Clearing failures throws away the only record of what went wrong — ask.
  root.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  // ── Live updates ──────────────────────────────────────────────────────────
  const statusUrl = root.dataset.statusUrl;
  if (!statusUrl) return;

  const POLL_MS = 5000;      // the scheduler ticks every 10s; twice that reads as live
  const MAX_FAILURES = 5;    // session gone / server down → stop nagging it
  let timer = null;
  let failures = 0;
  let inFlight = false;

  const setText = (el, text) => { if (el) el.textContent = text; };
  const show = (el, visible) => { if (el) el.hidden = !visible; };
  const showAll = (nodes, visible) => nodes.forEach((el) => { el.hidden = !visible; });

  const STATUS_BADGE = {
    pending: ["text-warning", "Queued"],
    running: ["text-info", "Running"],
    done: ["text-success", "Done"],
    failed: ["text-danger", "Failed"],
  };

  function applyHeartbeat(data) {
    show(root.querySelector('[data-beat="up"]'), data.alive);
    show(root.querySelector('[data-beat="down"]'), !data.alive);
    setText(
      root.querySelector("[data-beat-seen]"),
      data.seconds_since === null ? "" : " — last seen " + data.seconds_since + "s ago"
    );
  }

  function applyJobs(jobs) {
    jobs.forEach(function (job) {
      const row = root.querySelector('[data-job-row="' + job.id + '"]');
      if (!row) return;

      setText(row.querySelector("[data-job-next]"), job.next_run);
      show(row.querySelector("[data-job-next-dash]"), !job.enabled);
      setText(row.querySelector("[data-job-last]"), job.last_run);
      show(row.querySelector("[data-job-never]"), !job.last_run);

      const badge = row.querySelector("[data-job-last-status]");
      if (badge) {
        badge.hidden = !job.last_status;
        badge.textContent = job.last_status === "ok" ? "OK" : "Failed";
        badge.classList.toggle("text-success", job.last_status === "ok");
        badge.classList.toggle("text-danger", job.last_status !== "ok");
      }

      // The expandable detail panel, so an open row doesn't go stale mid-run.
      const detail = document.getElementById("jobDetail" + job.id);
      if (!detail) return;
      setText(
        detail.querySelector("[data-job-detail-status]"),
        !job.enabled ? "Disabled"
          : job.last_status === "ok" ? "Last run OK"
          : job.last_status === "error" ? "Last run failed"
          : "Enabled, not yet run"
      );
      const hasDuration = job.last_duration_ms !== null;
      showAll(detail.querySelectorAll("[data-job-duration-row]"), hasDuration);
      if (hasDuration) setText(detail.querySelector("[data-job-detail-duration]"), job.last_duration_ms);
      showAll(detail.querySelectorAll("[data-job-error-row]"), !!job.last_error);
      setText(detail.querySelector("[data-job-detail-error]"), job.last_error);
    });
  }

  // Mirrors the queue rows rendered server-side in scheduler/_settings_tab.html.
  // Built as nodes with textContent — a task id or an SMTP error is never HTML.
  function taskRow(task) {
    const tr = document.createElement("tr");
    const finished = task.status === "done" || task.status === "failed";
    if (finished) tr.className = "text-body-secondary";

    const name = document.createElement("td");
    name.className = "small";
    name.title = task.task;
    name.textContent = task.label;

    const status = document.createElement("td");
    const [cls, label] = STATUS_BADGE[task.status] || ["text-body-secondary", task.status];
    const badge = document.createElement("span");
    badge.className = "badge-soft " + cls;
    badge.textContent = label;
    status.appendChild(badge);

    const when = document.createElement("td");
    when.className = finished ? "small" : "small text-body-secondary";
    when.textContent = task.when;

    const details = document.createElement("td");
    const failed = task.status === "failed";
    details.className = failed ? "small text-danger" : "small text-body-secondary";
    details.textContent = failed ? task.error : task.result || "";
    if (task.can_retry) details.appendChild(retryButton(task.id));

    tr.append(name, status, when, details);
    return tr;
  }

  // Nothing retries on its own (a re-sent invite would arrive twice), so this is
  // how a failure gets a second attempt — including a cancellation whose shift is
  // already deleted, which has no other control anywhere in the app.
  function retryButton(id) {
    const wrap = document.createElement("div");
    wrap.className = "mt-1";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-outline-secondary btn-sm py-0";
    btn.dataset.retryTask = id;
    btn.title = "Run this task again — the only way to finish work whose shift is already gone";
    btn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i>Retry';
    wrap.appendChild(btn);
    return wrap;
  }

  function applyQueue(data) {
    const body = root.querySelector("[data-queue-body]");
    if (!body) return;
    const empty = body.querySelector("[data-queue-empty]");
    body.replaceChildren(...data.active.concat(data.recent).map(taskRow));
    if (empty) {
      empty.hidden = data.active.length + data.recent.length > 0;
      body.appendChild(empty);
    }

    [["done", data.done_count], ["failed", data.failed_count]].forEach(function ([scope, count]) {
      const btn = root.querySelector('[data-clear="' + scope + '"]');
      if (btn) btn.disabled = !count;
      setText(root.querySelector('[data-clear-count="' + scope + '"]'), count ? " (" + count + ")" : "");
    });

    // The table shows a capped tail; say how much of it is off-screen rather than
    // let a drained batch look like rows quietly went missing.
    show(root.querySelector("[data-queue-more]"), data.hidden_count > 0);
    setText(root.querySelector("[data-queue-more-count]"), data.hidden_count);
  }

  // Retry posts a plain form so the redirect carries the usual flash message —
  // the rows are rebuilt by every poll, so a listener bound to one would die.
  root.addEventListener("click", function (event) {
    const btn = event.target.closest("[data-retry-task]");
    if (!btn || !root.dataset.retryUrl) return;
    const token = root.querySelector('input[name="csrfmiddlewaretoken"]');
    if (!token) return;
    btn.disabled = true;
    const form = document.createElement("form");
    form.method = "post";
    form.action = root.dataset.retryUrl;
    form.hidden = true;
    [["csrfmiddlewaretoken", token.value], ["id", btn.dataset.retryTask]].forEach(
      function ([n, v]) {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = n;
        input.value = v;
        form.appendChild(input);
      }
    );
    document.body.appendChild(form);
    form.submit();
  });

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  async function poll() {
    if (inFlight || document.hidden) return;
    inFlight = true;
    try {
      const resp = await fetch(statusUrl, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!resp.ok) throw new Error("status " + resp.status);
      const data = await resp.json();
      failures = 0;
      applyHeartbeat(data);
      applyJobs(data.jobs);
      applyQueue(data);
    } catch (err) {
      failures += 1;
      if (failures >= MAX_FAILURES) stop();
    } finally {
      inFlight = false;
    }
  }

  timer = setInterval(poll, POLL_MS);
  // Coming back to the tab shouldn't wait out the interval on stale numbers.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) poll();
  });
})();
