// Price and change display (HANDOVER 8b "Data display conventions").
// The bridge formats values (format.py); this file only paints them.
import { el } from "./dom.js";

const SHORT_FROM_GOLD = 100;

/** A price from the bridge ({parts: [[12, "g"], ...], text}) as number + coin mark pairs. */
export function coin(value) {
  if (!value) return el("span", { class: "coin muted", text: "—" });
  const node = el("span", { class: "coin", attrs: { title: value.text, "aria-label": value.text } });
  value.parts.forEach(([amount, unit], idx) => {
    if (idx > 0) node.append(" ");
    node.append(el("span", { text: amount.toLocaleString("en-US") }), el("i", { class: unit }));
  });
  return node;
}

/** A signed change string from the bridge ("▲ +14.2 %") in the rise/fall colour. */
export function change(text, direction) {
  const cls = direction === "rise" ? "up" : direction === "fall" ? "dn" : "muted";
  return el("span", { class: cls, text });
}

/**
 * Axis labels in letters: 8g, 1g 50s, 80s, 3,101g (same rules as format.coins_text).
 * The one formatter that lives in JS, because chart ticks are computed here.
 */
export function axisCoins(copper) {
  copper = Math.max(0, Math.round(copper));
  const gold = Math.floor(copper / 10000);
  if (gold >= SHORT_FROM_GOLD) return Math.round(copper / 10000).toLocaleString("en-US") + "g";
  const silver = Math.floor((copper % 10000) / 100);
  const cop = copper % 100;
  const parts = [];
  if (gold) parts.push(gold.toLocaleString("en-US") + "g");
  if (silver) parts.push(silver + "s");
  if (cop) parts.push(cop + "c");
  return parts.join(" ") || "0c";
}
