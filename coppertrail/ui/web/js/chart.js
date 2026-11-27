// The lowest-price history chart (uPlot). Colours come from tokens.css variables.
import uPlot from "../vendor/uPlot.esm.js";
import { axisCoins } from "./coins.js";

const TZ = "Europe/Berlin";
const axisDay = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "short" });
const axisHour = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const tipDate = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Same colour as `token`, with alpha (tokens are #rrggbb). */
function withAlpha(token, alpha) {
  const hex = cssVar(token).replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** X labels: "25 Nov" at local midnight (or when ticks are days apart), else "16:00". */
function timeLabels(u, ticks, _axis, _space, incr) {
  return ticks.map((t) => {
    const d = new Date(t * 1000);
    const midnight = axisHour.format(d) === "00:00";
    return incr >= 86400 || midnight ? axisDay.format(d) : axisHour.format(d);
  });
}

/** The readout line under the chart: "25 Nov, 14:00 · 1g 20s" or "not listed". */
export function readoutText(t, v) {
  const when = tipDate.format(new Date(t * 1000));
  return v == null ? `${when} · not listed` : `${when} · ${axisCoins(v)}`;
}

/**
 * Draw the chart into `target`; `readout(text)` gets the hovered point (or null on leave).
 * Returns a function that removes the chart.
 */
export function priceChart(target, x, y, readout) {
  const font = `${cssVar("--chart-axis-font")} ${cssVar("--type-small-family")}`;
  const axis = {
    stroke: cssVar("--text3"),
    grid: { stroke: cssVar("--grid"), width: 1 },
    ticks: { stroke: cssVar("--grid"), width: 1 },
    font,
  };
  const few = x.length < 3;
  const opts = {
    width: target.clientWidth,
    height: target.clientHeight,
    tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), TZ),
    legend: { show: false },
    cursor: { y: false, points: { size: 8 }, drag: { x: false, y: false } },
    scales: { y: { range: (u, min, max) => (min == null ? [0, 1] : [Math.max(0, min - (max - min) * 0.1 - 1), max + (max - min) * 0.1 + 1]) } },
    axes: [
      { ...axis, values: timeLabels },
      { ...axis, size: 72, values: (u, ticks) => ticks.map(axisCoins) },
    ],
    series: [
      {},
      {
        label: "Lowest price",
        stroke: cssVar("--s1"),
        width: Number(cssVar("--chart-line-primary")) || 2,
        fill: withAlpha("--s1", Number(cssVar("--chart-area-alpha")) || 0.12),
        spanGaps: false,
        points: { show: few, size: 6 },
      },
    ],
    hooks: {
      setCursor: [
        (u) => {
          const i = u.cursor.idx;
          readout(i == null ? null : readoutText(u.data[0][i], u.data[1][i]));
        },
      ],
    },
  };
  const plot = new uPlot(opts, [x, y], target);
  const ro = new ResizeObserver(() => plot.setSize({ width: target.clientWidth, height: target.clientHeight }));
  ro.observe(target);
  return () => {
    ro.disconnect();
    plot.destroy();
  };
}
