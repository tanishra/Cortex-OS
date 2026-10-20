/* Ops dashboard — /stats readout, 10s poll. */

const $ = (id) => document.getElementById(id);
const { api, esc, chip } = window.cortex;

function gateOpen(open) {
  $("keyGate").classList.toggle("hidden", !open);
}
$("keySave").onclick = () => {
  window.cortex.key = $("keyInput").value.trim();
  localStorage.setItem("cortex_api_key", window.cortex.key);
  gateOpen(false);
  refresh();
};
$("keyBtn").onclick = () => {
  $("keyInput").value = window.cortex.key;
  gateOpen(true);
};

function stat(label, value, cls = "") {
  return `<div class="stat ${cls}"><div class="stat-label">${label}</div><div class="stat-value">${value}</div></div>`;
}

async function refresh() {
  let s;
  try {
    s = await api("/stats");
  } catch (e) {
    if (e.message === "unauthorized") gateOpen(true);
    $("statBand").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }

  $("statBand").innerHTML = [
    stat("tasks", s.tasks_total),
    stat("success rate", s.success_rate != null ? `${(s.success_rate * 100).toFixed(1)}%` : "—", "accent"),
    stat("avg steps", s.avg_steps != null ? s.avg_steps.toFixed(1) : "—"),
    stat("avg duration", s.avg_duration_s != null ? `${s.avg_duration_s.toFixed(0)}s` : "—"),
    stat("tokens in", s.tokens_in_total != null ? `${(s.tokens_in_total / 1000).toFixed(0)}k` : "—"),
    stat("cost", s.cost_usd_total != null ? `$${s.cost_usd_total.toFixed(2)}` : "—", "accent"),
  ].join("");

  const total = s.tasks_total || 1;
  const order = ["running", "queued", "waiting_human", "waiting_approval", "done", "failed", "cancelled", "dead_letter"];
  $("byStatus").innerHTML = Object.entries(s.by_status || {})
    .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]) || b[1] - a[1])
    .map(([k, v]) => `
      <div class="status-row">
        ${chip(k)}
        <div class="status-bar"><div class="status-fill ${esc(k)}" style="width:${Math.round((v / total) * 100)}%"></div></div>
        <span class="mono dim">${v}</span>
      </div>`)
    .join("");

  $("queues").innerHTML = [
    stat("running now", s.running_now),
    stat("task queue", s.queue_depth ?? "—"),
    stat("session queue", s.session_queue_depth ?? "—"),
  ].join("");
}

refresh();
setInterval(refresh, 10_000);
