// Pieces shared by the real views: tiles, foot lines, notes, the keyed view host.
// Every string comes from the bridge (viewdata.py); this file only lays it out.
import { change, coin } from "./coins.js";
import { el, replace } from "./dom.js";
import * as states from "./states.js";

/** A foot line: a string or a list of strings, {change} and {coin} segments. */
export function foot(f, cls = "sub tile-foot") {
  if (f == null) return null;
  const parts = Array.isArray(f) ? f : [f];
  return el(
    "div",
    { class: cls },
    parts.map((p) => (typeof p === "string" ? p : p?.change ? change(p.change.text, p.change.dir) : p?.coin ? coin(p.coin) : null)),
  );
}

/** A headline tile {label, value | change | coin, accent?, foot, extra?}. */
export function tile(t) {
  let value;
  if ("change" in t) value = t.change ? el("div", { class: "kpi" }, change(t.change.text, t.change.dir)) : el("div", { class: "kpi muted", text: "–" });
  else if (t.coin) value = el("div", { class: "kpi" }, coin(t.coin));
  else value = el("div", { class: "kpi" + (t.accent ? " s1" : ""), text: t.value ?? "–" });
  return el("div", { class: "card tile" + (t.extra ? " tile-extra" : "") }, el("div", { class: "label", text: t.label }), value, foot(t.foot));
}

/** A card with just a title, the subtitle and a one-line note (no data, an error). */
export function noteCard(title, payload, className = "") {
  return el(
    "section",
    { class: "card " + className },
    el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: title }), payload?.sub ? el("div", { class: "sub", text: payload.sub }) : null)),
    el("p", { class: "card-note", text: payload?.note ?? "Nothing to show." }),
  );
}

/** The stale-data tail for time charts (HANDOVER 8b States B), or null. */
export function staleTail(state) {
  const st = state.status;
  return st.stale && st.lastPoint ? { from: st.lastPoint, to: st.now, label: st.noDataSince } : null;
}

/** View header: h1 + sub, optional tools on the right. */
export function viewHead(title, sub, tools = null, lead = null) {
  const text = el("div", {}, el("h1", { class: "h1", text: title }), el("p", { class: "sub", text: sub }));
  return el("header", { class: "view-head" }, lead ? el("div", { class: "head-lead" }, lead, text) : text, tools);
}

/** Puts the stale banner above `root` without rebuilding the view. */
export function placeBanner(container, banner, root) {
  for (const c of [...container.children]) if (c !== root) c.remove();
  if (root.parentNode !== container) container.append(root);
  if (banner) container.prepend(banner);
}

/**
 * A view whose content comes from async bridge calls. `show(container, banner, key, load)`
 * keeps the DOM when `key` did not change (the frame re-rendered for other reasons); else
 * it shows the loading state (first time) or dims the old content, runs `load(root, isCurrent)`
 * and drops answers that a newer render overtook.
 */
export function viewHost(className) {
  const host = { root: null, key: null, seq: 0 };
  host.show = (container, banner, key, head, load) => {
    const attached = host.root && host.root.parentNode === container;
    if (attached && host.key === key) {
      placeBanner(container, banner, host.root);
      return;
    }
    host.key = key;
    const seq = ++host.seq;
    const isCurrent = () => seq === host.seq && host.root?.isConnected;
    if (!attached) {
      host.root = el("div", { class: "view-body " + className });
      replace(container, banner, host.root);
      container.scrollTop = 0;
      replace(host.root, head, states.loading({ text: "Reading prices…" }));
    } else {
      placeBanner(container, banner, host.root);
      host.root.classList.add("refreshing");
    }
    Promise.resolve()
      .then(() => load(host.root, isCurrent))
      .catch((err) => {
        if (!isCurrent()) return;
        replace(host.root, head, el("p", { class: "card-note fall", text: `Could not load this view: ${err}` }));
        host.key = null; // try again on the next render
      })
      .finally(() => isCurrent() && host.root.classList.remove("refreshing"));
  };
  return host;
}
