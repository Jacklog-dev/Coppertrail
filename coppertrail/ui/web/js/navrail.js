// Nav rail: shield + wordmark, the four views, "Data folder" at the bottom.
import { el, replace } from "./dom.js";
import { icon } from "./icons.js";

export const VIEWS = [
  { id: "overview", label: "Market overview", icon: "overview" },
  { id: "item", label: "Item detail", icon: "item" },
  { id: "patterns", label: "Patterns", icon: "patterns" },
  { id: "movers", label: "Movers & outliers", icon: "movers" },
];

/** render(container, {current, onSelect(id), onDataFolder()}) */
export function render(container, { current, onSelect, onDataFolder }) {
  const brand = el(
    "div",
    { class: "brand" },
    el("img", { attrs: { src: "icons/app.svg", alt: "" } }),
    el("span", { class: "wordmark" }, el("span", { class: "copper", text: "Copper" }), el("span", { class: "trail", text: "trail" })),
  );
  const buttons = VIEWS.map((v) =>
    el(
      "button",
      { class: "nav", attrs: { "aria-current": v.id === current ? "page" : false, "aria-label": v.label, "data-tip": v.label }, on: { click: () => onSelect(v.id) } },
      icon(v.icon, 18),
      el("span", { class: "nav-label", text: v.label }),
    ),
  );
  const folder = el(
    "button",
    { class: "nav small", attrs: { "aria-label": "Data folder", "data-tip": "Data folder" }, on: { click: onDataFolder } },
    icon("folder", 18),
    el("span", { class: "nav-label", text: "Data folder" }),
  );
  replace(container, brand, buttons, el("div", { class: "spacer" }), folder);
}
