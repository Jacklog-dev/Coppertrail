// One way for the page to reach Python: pywebview's js_api inside the app,
// the 127.0.0.1 dev server (devserver.py) in a normal browser.

const listeners = new Map();

/** Subscribe to events Python pushes with `ct.emit(event, payload)`. */
export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

window.ct = {
  emit(event, payload) {
    for (const fn of listeners.get(event) ?? []) fn(payload);
  },
};

// pywebview injects `window.pywebview` after the page's modules may already run, so the
// page cannot just check for it. The dev server answers GET /api with {"dev": true};
// pywebview's own file server does not know that path.
let modePromise = null;
function mode() {
  modePromise ??= window.pywebview
    ? Promise.resolve("app")
    : fetch("/api", { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : {}))
        .then((body) => (body.dev === true ? "dev" : "app"))
        .catch(() => "app");
  return modePromise;
}

/** True inside the pywebview window (resolves once known). */
export async function inApp() {
  return (await mode()) === "app";
}

function pywebviewApi() {
  if (window.pywebview?.api) return Promise.resolve(window.pywebview.api);
  return new Promise((resolve) =>
    window.addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true }),
  );
}

/** Call a bridge method by name; resolves to its return value. */
export async function call(name, ...args) {
  if (await inApp()) {
    const api = await pywebviewApi();
    return api[name](...args);
  }
  const resp = await fetch("/api/" + name, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ args }),
  });
  const body = await resp.json();
  if (!resp.ok) throw new Error(body.error ?? resp.statusText);
  return body.result;
}
