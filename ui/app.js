/* CORTEX-OS Flight Recorder — vanilla SPA over the REST API. */

const $ = (id) => document.getElementById(id);

const state = {
  key: localStorage.getItem("cortex_api_key") || "",
  tasks: [],
  selected: null,
  pollTimer: null,
};

const ACTIVE = new Set(["queued", "running", "waiting_approval", "waiting_human"]);

function api(path, opts = {}) {
  return fetch(path, {
    ...opts,
    headers: { "x-api-key": state.key, "Content-Type": "application/json", ...(opts.headers || {}) },
  }).then((r) => {
    if (r.status === 401 || r.status === 403) throw new Error("unauthorized");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.status === 204 ? null : r.json();
  });
}

function ago(iso) {
  const s = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

function esc(s) {
  return (s || "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

const _imgCache = new Map();
function loadImage(path) {
  if (_imgCache.has(path)) return Promise.resolve(_imgCache.get(path));
  return fetch(path, { headers: { "x-api-key": state.key } })
    .then((r) => (r.ok ? r.blob() : null))
    .then((b) => {
      if (!b) return null;
      const url = URL.createObjectURL(b);
      _imgCache.set(path, url);
      return url;
    })
    .catch(() => null);
}

function chip(status) {
  return `<span class="chip ${esc(status)}"><span class="dot"></span>${esc(status)}</span>`;
}

/* ── key gate ── */
function gateOpen(open) {
  $("keyGate").classList.toggle("hidden", !open);
}
$("keySave").onclick = () => {
  state.key = $("keyInput").value.trim();
  localStorage.setItem("cortex_api_key", state.key);
  gateOpen(false);
  refresh();
};
$("keyBtn").onclick = () => {
  $("keyInput").value = state.key;
  gateOpen(true);
};

/* ── submit ── */
$("submitToggle").onclick = () => $("submitPanel").classList.toggle("hidden");
$("submitGo").onclick = async () => {
  const task = $("submitText").value.trim();
  if (!task) return;
  try {
    const body = { task };
    if ($("submitUrl").value.trim()) body.start_url = $("submitUrl").value.trim();
    const t = await api("/tasks", { method: "POST", body: JSON.stringify(body) });
    $("submitText").value = "";
    state.selected = t.id;
    refresh();
  } catch (e) { toast(e); }
};

/* ── task rail ── */
async function refresh() {
  try {
    state.tasks = await api("/tasks?limit=100");
  } catch (e) {
    if (e.message === "unauthorized") gateOpen(true);
    return;
  }
  renderRail();
  if (state.selected) renderDetail();
  schedulePoll();
}

function schedulePoll() {
  clearTimeout(state.pollTimer);
  if (state.tasks.some((t) => ACTIVE.has(t.status))) {
    state.pollTimer = setTimeout(refresh, 3000);
  }
}

function renderRail() {
  const el = $("taskList");
  if (!state.tasks.length) {
    el.innerHTML = `<div class="empty">no tasks recorded</div>`;
    return;
  }
  el.innerHTML = state.tasks
    .map(
      (t) => `
      <div class="task-item ${t.id === state.selected ? "active" : ""}" data-id="${t.id}">
        <div class="task-text">${esc(t.task)}</div>
        <div class="task-foot">${chip(t.status)}<span class="task-ago">${ago(t.created_at)}</span></div>
      </div>`
    )
    .join("");
  el.querySelectorAll(".task-item").forEach((n) => {
    n.onclick = () => {
      state.selected = n.dataset.id;
      renderRail();
      renderDetail();
    };
  });
}

/* ── detail ── */
async function renderDetail() {
  const t = state.tasks.find((x) => x.id === state.selected);
  if (!t) return;
  $("detailEmpty").classList.add("hidden");
  $("detailBody").classList.remove("hidden");
  $("dChip").outerHTML = chip(t.status).replace('class="chip', 'id="dChip" class="chip');
  $("dTask").textContent = t.task;
  $("dMeta").innerHTML = [
    `id <b>${t.id.slice(0, 8)}</b>`,
    `steps <b>${t.steps_taken}</b>`,
    `created <b>${ago(t.created_at)}</b>`,
    t.retry_count ? `retries <b>${t.retry_count}</b>` : "",
    t.resume_count ? `resumes <b>${t.resume_count}</b>` : "",
    `priority <b>${t.priority}</b>`,
  ].filter(Boolean).join("");

  const acts = [];
  if (["running", "queued", "waiting_human", "waiting_approval"].includes(t.status))
    acts.push(`<button class="ghost-btn btn-deny" id="cancelBtn">cancel</button>`);
  if (t.status === "waiting_human" || t.status === "failed")
    acts.push(`<button class="ghost-btn" id="resumeBtn">resume</button>`);
  $("dActions").innerHTML = acts.join("");
  if ($("cancelBtn")) $("cancelBtn").onclick = () => act(`/tasks/${t.id}/cancel`);
  if ($("resumeBtn")) $("resumeBtn").onclick = () => act(`/tasks/${t.id}/resume`);

  const rb = $("resultBlock");
  if (t.result || t.error) {
    rb.classList.remove("hidden");
    rb.classList.toggle("error", !!t.error);
    rb.textContent = t.result || t.error;
  } else rb.classList.add("hidden");

  renderApprovals(t.id);
  renderSteps(t.id);

  // Steps move faster than status polls — refetch frames every 2s while live.
  clearInterval(tape.ticker);
  tape.ticker = null;
  if (ACTIVE.has(t.status)) {
    tape.ticker = setInterval(() => {
      const cur = state.tasks.find((x) => x.id === state.selected);
      if (!cur || !ACTIVE.has(cur.status)) return clearInterval(tape.ticker);
      renderSteps(cur.id);
    }, 2000);
  }
}

async function act(path) {
  try { await api(path, { method: "POST" }); refresh(); } catch (e) { toast(e); }
}

async function renderApprovals(taskId) {
  const strip = $("approvalsStrip");
  try {
    const pending = await api("/approvals?pending=true");
    const mine = pending.filter((a) => a.task_id === taskId);
    if (!mine.length) { strip.classList.add("hidden"); return; }
    strip.classList.remove("hidden");
    strip.innerHTML = mine
      .map(
        (a) => `
        <div class="approval-row">
          <span class="label">approval</span>
          <span class="approval-reason">${esc(a.reason)} ${a.url ? `<span class="mono">${esc(a.url)}</span>` : ""}</span>
          <button class="ghost-btn btn-approve" data-approve="${a.id}">approve</button>
          <button class="ghost-btn btn-deny" data-deny="${a.id}">deny</button>
        </div>`
      )
      .join("");
    strip.querySelectorAll("[data-approve]").forEach((b) => {
      b.onclick = () => respond(b.dataset.approve, true);
    });
    strip.querySelectorAll("[data-deny]").forEach((b) => {
      b.onclick = () => respond(b.dataset.deny, false);
    });
  } catch (e) { strip.classList.add("hidden"); }
}

async function respond(id, approve) {
  try {
    await api(`/approvals/${id}/respond`, { method: "POST", body: JSON.stringify({ approve }) });
    refresh();
  } catch (e) { toast(e); }
}

/* ── tape panel: live flipbook + scrub ── */
const tape = { taskId: null, frames: [], idx: 1, scrubLock: 0, ticker: null };

function showFrame(taskId, e) {
  if (!e) return;
  const img = `step_${String(e.n).padStart(4, "0")}.png`;
  $("tapePos").textContent = `step ${String(e.n).padStart(3, "0")} / ${String(tape.frames.at(-1)?.n ?? e.n).padStart(3, "0")}`;
  $("tapeUrl").textContent = e.url || "";
  $("tapeActions").textContent = (e.actions || []).join(" · ");
  $("tapeScrub").value = e.n;
  loadImage(`/tasks/${taskId}/screenshots/${img}`).then((url) => {
    if (!url) return;
    const frame = $("tapeFrame");
    frame.replaceChildren();
    const im = document.createElement("img");
    im.src = url;
    im.alt = `step ${e.n} screenshot`;
    frame.appendChild(im);
  });
}

function updateTape(taskId, steps, isLive) {
  const panel = $("tape");
  if (!steps.length) { panel.classList.add("hidden"); return; }
  if (tape.taskId !== taskId) {
    tape.taskId = taskId;
    tape.frames = [];
    tape.scrubLock = 0;
    delete panel.dataset.shown;
  }
  tape.frames = steps;
  panel.classList.remove("hidden");
  const scrub = $("tapeScrub");
  scrub.max = steps.at(-1).n;
  const lamp = $("tapeLamp");
  lamp.innerHTML = isLive
    ? `<span class="dot live"></span>LIVE`
    : `<span class="dot replay"></span>REPLAY`;
  lamp.className = `lamp ${isLive ? "is-live" : "is-replay"}`;
  const scrubbing = Date.now() < tape.scrubLock;
  if (isLive && !scrubbing) {
    showFrame(taskId, steps.at(-1));
    tape.idx = steps.at(-1).n;
  } else if (!isLive && tape.idx > scrub.max) {
    tape.idx = scrub.max;
  }
  if (!isLive && !scrubbing && !panel.dataset.shown) {
    panel.dataset.shown = "1";
    showFrame(taskId, steps.at(-1));
  }
}

$("tapeScrub").addEventListener("input", (e) => {
  tape.scrubLock = Date.now() + 8000;
  tape.idx = +e.target.value;
  const frame = tape.frames.find((f) => f.n === tape.idx) || tape.frames.at(-1);
  showFrame(tape.taskId, frame);
});

async function renderSteps(taskId) {
  const el = $("steps");
  try {
    const events = await api(`/tasks/${taskId}/events?limit=500`);
    const steps = events.filter((e) => e.kind === "step");
    const t = state.tasks.find((x) => x.id === taskId);
    updateTape(taskId, steps, t ? ACTIVE.has(t.status) : false);
    $("stepsHead").textContent = `RECORDED STEPS — ${steps.length}`;
    if (!steps.length) { el.innerHTML = `<div class="empty">no steps recorded yet</div>`; return; }
    el.innerHTML = steps
      .map((e) => {
        const img = `step_${String(e.n).padStart(4, "0")}.png`;
        return `
        <div class="step">
          <div class="step-n">${String(e.n).padStart(3, "0")}</div>
          <div>
            <div class="step-url">${esc(e.url || "—")}</div>
            <div class="step-actions">${esc((e.actions || []).join(" · ") || "—")}</div>
            ${e.duration_ms ? `<div class="step-dur">${(e.duration_ms / 1000).toFixed(1)}s</div>` : ""}
          </div>
          <div class="thumb-slot" data-img="/tasks/${taskId}/screenshots/${img}"></div>
        </div>`;
      })
        .join("");
    // <img> can't send the x-api-key header — fetch blobs for thumbs + lightbox.
    el.querySelectorAll(".thumb-slot").forEach((slot) => {
      loadImage(slot.dataset.img).then((url) => {
        if (!url) return;
        const im = document.createElement("img");
        im.className = "step-thumb";
        im.src = url;
        im.onclick = () => {
          const full = document.createElement("img");
          full.src = url;
          full.alt = `step ${im.src.split("/").pop()} screenshot`;
          const box = $("lightbox");
          box.replaceChildren(full);
          box.classList.remove("hidden");
        };
        slot.appendChild(im);
      });
    });
  } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

$("lightbox").onclick = () => $("lightbox").classList.add("hidden");
$("refreshBtn").onclick = refresh;

function toast(e) {
  $("dTask").textContent = `error: ${e.message}`;
}

refresh();
