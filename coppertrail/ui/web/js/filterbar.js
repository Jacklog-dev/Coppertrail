// Filter bar (filled in by Task 8 of the plan). For now: the active-filter label only.
import { el, replace } from "./dom.js";

export function render(container, state) {
  replace(container, el("div", { class: "spacer" }), el("span", { class: "label", text: state.activeLabel }));
}
