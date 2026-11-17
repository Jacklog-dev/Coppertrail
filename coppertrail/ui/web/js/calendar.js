// Month calendar for the date-range popover: Monday first, English month names,
// days outside the archive disabled, two clicks pick a range (in either order).
import { el } from "./dom.js";
import { icon } from "./icons.js";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** ISO "2026-11-16" -> "16 Nov 2026" (the format.py `day` style). */
export function dayLabel(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${SHORT[m - 1]} ${y}`;
}

const iso = (y, m, d) => `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

/**
 * calendar({from, to, min, max, month: "YYYY-MM", pending, onMonth(ym), onDay(iso)})
 * `pending` is a first click waiting for its partner (highlighted alone).
 */
export function calendar({ from, to, min, max, month, pending, onMonth, onDay }) {
  const [y, m] = month.split("-").map(Number);
  const year = y;
  const mon = m - 1;
  const first = new Date(Date.UTC(year, mon, 1));
  const offset = (first.getUTCDay() + 6) % 7; // Monday = 0
  const days = new Date(Date.UTC(year, mon + 1, 0)).getUTCDate();
  const shift = (delta) => {
    const d = new Date(Date.UTC(year, mon + delta, 1));
    onMonth(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`);
  };
  const lo = pending ?? from;
  const hi = pending ?? to;

  const cells = [];
  for (let i = 0; i < offset; i++) cells.push(el("span", { class: "cal-day blank" }));
  for (let d = 1; d <= days; d++) {
    const day = iso(year, mon, d);
    const disabled = (min && day < min) || (max && day > max);
    const end = day === lo || day === hi;
    const inside = day > lo && day < hi;
    cells.push(
      el("button", {
        class: "cal-day" + (end ? " end" : inside ? " inside" : ""),
        text: d,
        attrs: { disabled, "aria-label": dayLabel(day), "aria-pressed": end ? "true" : false },
        on: { click: () => onDay(day) },
      }),
    );
  }
  return el(
    "div",
    { class: "calendar" },
    el(
      "div",
      { class: "cal-head" },
      el("span", { text: `${MONTHS[mon]} ${year}` }),
      el(
        "span",
        { class: "cal-nav" },
        el("button", { class: "btn ghost cal-prev", attrs: { "aria-label": "Previous month" }, on: { click: () => shift(-1) } }, icon("chevron", 14)),
        el("button", { class: "btn ghost cal-next", attrs: { "aria-label": "Next month" }, on: { click: () => shift(1) } }, icon("chevron", 14)),
      ),
    ),
    el("div", { class: "cal-grid cal-weekdays" }, ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => el("span", { text: d }))),
    el("div", { class: "cal-grid" }, cells),
  );
}
