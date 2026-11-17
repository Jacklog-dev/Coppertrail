// Status strip: data age · Pull latest data · (error) · spacer · Prices from AHledger (always).
import { el, replace } from "./dom.js";
import { icon } from "./icons.js";

/**
 * render(container, state | null, {pulling, pct?, error: {message, detail} | null, onPull(), onCredit(event)})
 * Stale data: clock icon and text in --attention. While pulling: "Pulling…" (with a percent
 * once one is known) instead of the button. Before the first state only the credit shows.
 */
export function render(container, state, { pulling, pct = null, error, onPull, onCredit }) {
  if (!state) {
    // Before the first state: the credit as text (its link comes from the bridge).
    replace(container, el("div", { class: "spacer" }), el("span", { class: "credit", text: "Prices from AHledger" }));
    return;
  }
  const credit = el(
    "a",
    { class: "credit", attrs: { href: state.creditUrl, target: "_blank", rel: "noopener" }, on: { click: onCredit } },
    "Prices from AHledger",
    icon("external", 13),
  );
  const st = state.status;
  const warn = st.stale || st.error;
  const mark = st.stale ? icon("clock", 14) : st.empty && !st.error ? null : el("span", { class: "dot " + (warn ? "attention" : "rise") });
  const text = el("span", { text: st.text, attrs: { title: st.errorDetail || false } });
  const action = pulling
    ? el("span", { class: "pulling" }, icon("refresh", 14), pct == null ? "Pulling…" : `Pulling… ${pct} %`)
    : el(
        "button",
        { class: "btn link", attrs: { disabled: !st.canPull, title: st.canPull ? false : st.pullHint }, on: { click: onPull } },
        icon("download", 14),
        "Pull latest data",
      );
  const err = error ? el("span", { class: "error", text: error.message, attrs: { title: error.detail || false } }) : null;
  replace(container, el("span", { class: "strip-state" + (warn ? " attention" : "") + (st.stale ? " stale" : "") }, mark, text), el("span", { class: "sep" }), action, err, el("div", { class: "spacer" }), credit);
}
