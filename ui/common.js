/* Shared helpers for the flight-recorder pages. Global namespace: cortex. */

window.cortex = {
  key: localStorage.getItem("cortex_api_key") || "",
  _imgCache: new Map(),
};

window.cortex.api = function (path, opts = {}) {
  return fetch(path, {
    ...opts,
    headers: { "x-api-key": window.cortex.key, "Content-Type": "application/json", ...(opts.headers || {}) },
  }).then((r) => {
    if (r.status === 401 || r.status === 403) throw new Error("unauthorized");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.status === 204 ? null : r.json();
  });
};

window.cortex.esc = function (s) {
  return (s || "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
};

window.cortex.ago = function (iso) {
  const s = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
};

window.cortex.chip = function (status) {
  return `<span class="chip ${window.cortex.esc(status)}"><span class="dot"></span>${window.cortex.esc(status)}</span>`;
};

window.cortex.loadImage = function (path) {
  if (window.cortex._imgCache.has(path)) return Promise.resolve(window.cortex._imgCache.get(path));
  return fetch(path, { headers: { "x-api-key": window.cortex.key } })
    .then((r) => (r.ok ? r.blob() : null))
    .then((b) => {
      if (!b) return null;
      const url = URL.createObjectURL(b);
      window.cortex._imgCache.set(path, url);
      return url;
    })
    .catch(() => null);
};
