// Status strip: data age · Pull latest data · (error) · spacer · Prices from AHledger (always).
import { el, replace } from "./dom.js";
import { icon } from "./icons.js";

/**
 * render(container, state, {pulling, error: {message, detail} | null, onPull(), onCredit(event)})
 */
export function render(container, state, { pulling, error, onPull, onCredit }) {
  const st = state.status;
  const warn = st.stale || st.error;
  const dot = st.empty && !st.error ? null : el("span", { class: "dot " + (warn ? "attention" : "rise") });
  const text = el("span", { class: warn ? "attention" : "", text: st.text, attrs: { title: st.errorDetail || false } });
  const pull = el(
    "button",
    {
      class: "btn link",
      attrs: { disabled: pulling || !st.canPull, title: st.canPull ? false : st.pullHint },
      on: { click: onPull },
    },
    icon("download", 14),
    pulling ? "Pulling…" : "Pull latest data",
  );
  const err = error ? el("span", { class: "error", text: error.message, attrs: { title: error.detail || false } }) : null;
  const credit = el(
    "a",
    { class: "credit", attrs: { href: state.creditUrl, target: "_blank", rel: "noopener" }, on: { click: onCredit } },
    "Prices from AHledger",
    icon("external", 13),
  );
  replace(container, el("span", { class: "state" }, dot, text), el("span", { class: "sep" }), pull, err, el("div", { class: "spacer" }), credit);
}
