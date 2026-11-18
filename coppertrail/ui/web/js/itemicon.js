// Item icons: the bridge's icons() map (URL template + item id -> icon file id, see
// coppertrail/ui/icons.py), loaded once at start. Without an entry, or when the image does not load (offline), a plain square.
import { call } from "./api.js";
import { el } from "./dom.js";

let map = { url: "", ids: {} };

export async function loadIcons() {
  try {
    map = (await call("icons")) ?? map;
  } catch {
    // icons are decoration: the app works without them
  }
}

/** The icon for `id`: an <img> (lazy) or the fallback square. */
export function itemIcon(id, large = false) {
  const cls = "item-icon" + (large ? " large" : "");
  const file = map.ids?.[String(id)];
  const url = file && map.url ? map.url.replace("{}", String(file)) : null;
  if (!url) return el("span", { class: cls + " none", attrs: { "aria-hidden": "true" } });
  const img = el("img", { class: cls, attrs: { src: url, alt: "", loading: "lazy", decoding: "async", draggable: "false" } });
  img.addEventListener("error", () => img.replaceWith(el("span", { class: cls + " none", attrs: { "aria-hidden": "true" } })), { once: true });
  return img;
}

/** Icon plus `label` (a node or text) on one line; the label keeps its ellipsis. */
export function withIcon(id, label, large = false) {
  return el("span", { class: "with-icon" + (large ? " large" : "") }, itemIcon(id, large), typeof label === "string" ? el("span", { class: "icon-label", text: label }) : label);
}
