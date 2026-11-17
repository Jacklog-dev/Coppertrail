// uPlot charts styled by the CHART tokens (HANDOVER 8b "Charts in uPlot"):
// horizontal grid only, dashed reference lines and crosshair, 8 px hover dots with a
// 2 px surface ring, a tooltip that flips left near the right edge, drag to zoom.
import uPlot from "../vendor/uPlot.esm.js";
import { el } from "./dom.js";

const TZ = "Europe/Berlin";

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** A token colour ("s1", "--grid" or "grid") with alpha, as rgba(). */
export function withAlpha(token, alpha) {
  const hex = cssVar(token.startsWith("--") ? token : "--" + token).replace("#", "");
  const n = parseInt(hex, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

const colour = (token) => cssVar(token.startsWith("--") ? token : "--" + token);
const num = (name) => parseFloat(cssVar(name));

const dateFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
});
/** "16 Nov 2026, 08:42" in local time (CET), for tooltips. */
export const dateTime = (unixSeconds) => dateFmt.format(new Date(unixSeconds * 1000));

const dayFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "short" });
const hourFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
/** Time axis ticks: "18 Oct" over days, "08:00" within two days (HANDOVER 8b date style). */
function timeTicks(u, splits) {
  const span = u.scales.x.max - u.scales.x.min;
  const fmt = span > 2 * 86400 ? dayFmt : hourFmt;
  return splits.map((ts) => fmt.format(new Date(ts * 1000)));
}

function axisFont() {
  return `${cssVar("--chart-axis-font")} ${cssVar("--type-small-family")}`;
}

function axis(extra = {}) {
  return {
    stroke: colour("text3"),
    font: axisFont(),
    grid: { show: false },
    ticks: { show: true, stroke: colour("border"), width: 1, size: 4 },
    border: { show: true, stroke: colour("border"), width: 1 },
    ...extra,
  };
}

/** Draws dashed horizontal reference lines (index 100, vendor floor) under the series. */
function referenceLines(values) {
  return {
    hooks: {
      drawAxes: [
        (u) => {
          const { ctx } = u;
          const { left, width } = u.bbox;
          ctx.save();
          ctx.strokeStyle = colour("text3");
          ctx.lineWidth = devicePixelRatio;
          ctx.setLineDash([4 * devicePixelRatio, 4 * devicePixelRatio]);
          for (const v of values) {
            const y = Math.round(u.valToPos(v, "y", true)) + 0.5;
            ctx.beginPath();
            ctx.moveTo(left, y);
            ctx.lineTo(left + width, y);
            ctx.stroke();
          }
          ctx.restore();
        },
      ],
    },
  };
}

/** Horizontal grid only, in --grid, drawn under everything. */
function horizontalGrid() {
  return {
    hooks: {
      drawAxes: [
        (u) => {
          const { ctx } = u;
          const { left, width } = u.bbox;
          const splits = u.axes[1]._splits ?? [];
          ctx.save();
          ctx.strokeStyle = colour("grid");
          ctx.lineWidth = devicePixelRatio;
          for (const v of splits) {
            const y = Math.round(u.valToPos(v, "y", true)) + 0.5;
            ctx.beginPath();
            ctx.moveTo(left, y);
            ctx.lineTo(left + width, y);
            ctx.stroke();
          }
          ctx.restore();
        },
      ],
    },
  };
}

/** Tooltip in --overlay with --borderStrong; flips to the left of the crosshair near the edge. */
function tooltip(format) {
  let tip;
  return {
    hooks: {
      init: (u) => {
        tip = el("div", { class: "tooltip", attrs: { role: "status" } });
        tip.style.display = "none";
        document.body.append(tip);
        u.over.addEventListener("mouseleave", () => (tip.style.display = "none"));
      },
      setCursor: (u) => {
        const { idx, left, top } = u.cursor;
        if (idx == null || left < 0) {
          tip.style.display = "none";
          return;
        }
        tip.replaceChildren(el("div", { class: "muted", text: dateTime(u.data[0][idx]) }));
        u.series.forEach((s, i) => {
          if (i === 0 || !s.show) return;
          const v = u.data[i][idx];
          const sw = el("i");
          sw.style.cssText = `display:inline-block;width:14px;height:2px;margin-right:6px;vertical-align:3px;background:${s._stroke}`;
          tip.append(el("div", {}, sw, `${s.label}  `, el("span", { text: v == null ? "—" : format(v) })));
        });
        tip.style.display = "block";
        const box = u.over.getBoundingClientRect();
        const gap = 14;
        const w = tip.offsetWidth;
        let x = box.left + left + gap;
        if (x + w > box.right) x = box.left + left - gap - w;
        tip.style.left = Math.max(4, x) + "px";
        tip.style.top = box.top + Math.max(0, top - tip.offsetHeight / 2) + "px";
      },
      destroy: () => tip?.remove(),
    },
  };
}

const WIDTHS = { primary: "--chart-line-primary", secondary: "--chart-line-secondary", tertiary: "--chart-line-tertiary" };

/**
 * lineChart(el, {x, series: [{label, color: "s1", width: "primary", fill?: true, values}],
 *                refLine?: number, height, format?: v => string})
 * `x` are unix seconds. Returns the uPlot instance with an added `reset()` (undo zoom).
 */
export function lineChart(target, { x, series, refLine, height = 300, format = (v) => v.toLocaleString("en-US") }) {
  const surface = colour("surface");
  const opts = {
    width: Math.max(200, target.clientWidth),
    height,
    tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), TZ),
    legend: { show: false },
    cursor: {
      x: true,
      y: true,
      drag: { x: true, y: false, setScale: true },
      points: {
        size: num("--chart-marker-dot"),
        width: 2,
        stroke: () => surface,
        fill: (u, i) => u.series[i]._stroke,
      },
    },
    scales: { x: { time: true } },
    axes: [axis({ values: timeTicks }), axis({ size: 56, values: (u, vals) => vals.map((v) => format(v)) })],
    series: [
      {},
      ...series.map((s) => ({
        label: s.label,
        stroke: colour(s.color),
        width: num(WIDTHS[s.width ?? "secondary"]),
        fill: s.fill ? withAlpha(s.color, num("--chart-area-alpha")) : undefined,
        points: { show: false },
      })),
    ],
    plugins: [horizontalGrid(), ...(refLine != null ? [referenceLines([refLine])] : []), tooltip(format)],
  };
  const data = [x, ...series.map((s) => s.values)];
  const chart = new uPlot(opts, data, target);
  chart.reset = () => chart.setScale("x", { min: x[0], max: x[x.length - 1] });
  new ResizeObserver(() => chart.setSize({ width: Math.max(200, target.clientWidth), height })).observe(target);
  return chart;
}

/** Legend row above a plot: line swatch + label in --text2 (not uPlot's legend). */
export function legend(series) {
  return el(
    "div",
    { class: "legend" },
    series.map((s) => {
      const swatch = el("i");
      swatch.style.background = colour(s.color);
      return el("span", {}, swatch, s.label);
    }),
  );
}
