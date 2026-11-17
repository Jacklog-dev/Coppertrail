// uPlot charts styled by the CHART tokens (HANDOVER 8b "Charts in uPlot"):
// horizontal grid only, dashed reference lines and crosshair, 8 px hover dots with a
// 2 px surface ring, a tooltip that flips left near the right edge, drag to zoom with a
// reset button in the card header, bands and area fills at 12 %, bars with a 28 % gap,
// linked x-axes (cursor.sync), event markers and the stale-data tail in draw hooks.
// Plus two small SVG blocks for table cells: the 96×26 sparkline and the 140 px range bar.
import uPlot from "../vendor/uPlot.esm.js";
import { el, svg } from "./dom.js";
import { icon } from "./icons.js";

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
const dpr = () => window.devicePixelRatio || 1;

const dateFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
});
/** "16 Nov 2026, 08:42" in local time (CET), for tooltips. */
export const dateTime = (unixSeconds) => dateFmt.format(new Date(unixSeconds * 1000));

const dayFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "short" });
const fullDayFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "short", day: "numeric", month: "short", year: "numeric" });
/** "Mon, 16 Nov 2026" in local time, for tooltips of daily series. */
export const dayLabel = (unixSeconds) => fullDayFmt.format(new Date(unixSeconds * 1000));
/** "07:00" for hour-of-day charts (x = 0..23). */
export const hourLabel = (h) => String(Math.round(h)).padStart(2, "0") + ":00";
const hourFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
/** Time axis ticks: "18 Oct" over days, "08:00" within two days (HANDOVER 8b date style). */
const HOUR = 3600;
const DAY = 86400;
// Tick steps: whole days once the labels are days (else uPlot may pick 12 h and repeat them).
const HOUR_INCRS = [HOUR, 2 * HOUR, 3 * HOUR, 4 * HOUR, 6 * HOUR, 12 * HOUR, DAY];
const DAY_INCRS = [DAY, 2 * DAY, 3 * DAY, 7 * DAY, 14 * DAY, 28 * DAY, 91 * DAY, 182 * DAY];
const timeIncrs = (u, axisIdx, min, max) => (max - min > 2 * DAY ? DAY_INCRS : HOUR_INCRS);
// Whole-number y steps (coins are whole copper; 1.5c would print as a second "2c").
const WHOLE_INCRS = [1, 2, 5].flatMap((m) => Array.from({ length: 12 }, (_, k) => m * 10 ** k)).sort((a, b) => a - b);
function timeTicks(u, splits) {
  const span = u.scales.x.max - u.scales.x.min;
  const fmt = span > 2 * 86400 ? dayFmt : hourFmt;
  return splits.map((ts) => fmt.format(new Date(ts * 1000)));
}

function font(role = "small", weight = 400) {
  return `${weight} ${parseFloat(cssVar("--chart-axis-font")) * dpr()}px ${cssVar(`--type-${role}-family`)}`;
}

function axis(extra = {}) {
  return {
    stroke: colour("text3"),
    font: `${cssVar("--chart-axis-font")} ${cssVar("--type-small-family")}`,
    grid: { show: false },
    ticks: { show: true, stroke: colour("border"), width: 1, size: 4 },
    border: { show: true, stroke: colour("border"), width: 1 },
    ...extra,
  };
}

function hline(ctx, u, y) {
  ctx.beginPath();
  ctx.moveTo(u.bbox.left, y);
  ctx.lineTo(u.bbox.left + u.bbox.width, y);
  ctx.stroke();
}

/** Horizontal grid only, in --grid, drawn under everything. */
function horizontalGrid() {
  return {
    hooks: {
      drawAxes: [
        (u) => {
          const { ctx } = u;
          ctx.save();
          ctx.strokeStyle = colour("grid");
          ctx.lineWidth = dpr();
          for (const v of u.axes[1]._splits ?? []) hline(ctx, u, Math.round(u.valToPos(v, "y", true)) + 0.5);
          ctx.restore();
        },
      ],
    },
  };
}

/** Dashed reference lines ([{value, label?}]: index 100, vendor floor), label above at the right. */
function referenceLines(lines) {
  return {
    hooks: {
      drawAxes: [
        (u) => {
          const { ctx } = u;
          ctx.save();
          ctx.strokeStyle = colour("text3");
          ctx.fillStyle = colour("text3");
          ctx.lineWidth = dpr();
          ctx.font = font();
          ctx.textAlign = "right";
          ctx.textBaseline = "bottom";
          for (const { value, label } of lines) {
            const y = Math.round(u.valToPos(value, "y", true)) + 0.5;
            if (y < u.bbox.top || y > u.bbox.top + u.bbox.height) continue;
            ctx.setLineDash([4 * dpr(), 4 * dpr()]);
            hline(ctx, u, y);
            ctx.setLineDash([]);
            if (label) ctx.fillText(label, u.bbox.left + u.bbox.width - 4 * dpr(), y - 4 * dpr());
          }
          ctx.restore();
        },
      ],
    },
  };
}

// Event markers -----------------------------------------------------------------------------

/** Marker kinds (HANDOVER 8b Item detail): colour, shape and the tooltip/legend label. */
export const MARKERS = {
  mispricing: { color: "s4", shape: "diamond", label: "Mispricing" },
  shock: { color: "s3", shape: "square", label: "Supply shock" },
  buyout: { color: "s2", shape: "triangle", label: "Buyout" },
};
const MARKER_PX = 9;
const MARKER_ROOM = 22; // CSS px above the plot for the markers

function drawShape(ctx, shape, x, y, size) {
  const h = size / 2;
  ctx.beginPath();
  if (shape === "diamond") {
    ctx.moveTo(x, y - h - 1);
    ctx.lineTo(x + h + 1, y);
    ctx.lineTo(x, y + h + 1);
    ctx.lineTo(x - h - 1, y);
  } else if (shape === "square") {
    ctx.rect(x - h, y - h, size, size);
  } else {
    ctx.moveTo(x - h - 1, y - h);
    ctx.lineTo(x + h + 1, y - h);
    ctx.lineTo(x, y + h + 1);
  }
  ctx.closePath();
  ctx.fill();
}

/** Markers [{t, kind, label}] above the plot with a dotted drop line in the marker colour. */
function eventMarkers(markers) {
  return {
    hooks: {
      draw: [
        (u) => {
          const { ctx } = u;
          const { left, top, width, height } = u.bbox;
          const y = top - (MARKER_ROOM / 2) * dpr();
          ctx.save();
          for (const m of markers) {
            const kind = MARKERS[m.kind];
            if (!kind) continue;
            const x = Math.round(u.valToPos(m.t, "x", true)) + 0.5;
            if (x < left || x > left + width) continue;
            const c = colour(kind.color);
            ctx.strokeStyle = c;
            ctx.fillStyle = c;
            ctx.lineWidth = dpr();
            ctx.setLineDash([1.5 * dpr(), 3 * dpr()]);
            ctx.beginPath();
            ctx.moveTo(x, y + (MARKER_PX / 2 + 2) * dpr());
            ctx.lineTo(x, top + height);
            ctx.stroke();
            ctx.setLineDash([]);
            drawShape(ctx, kind.shape, x, y, MARKER_PX * dpr());
          }
          ctx.restore();
        },
      ],
    },
  };
}

/** Marker legend items for legend(): same shapes, as CSS. */
export function markerLegend(kinds = Object.keys(MARKERS)) {
  return kinds.map((k) => ({ label: MARKERS[k].label, color: MARKERS[k].color, shape: MARKERS[k].shape }));
}

// Stale tail ---------------------------------------------------------------------------------

function wrap(ctx, text, maxWidth) {
  const lines = [];
  let line = "";
  for (const word of text.split(" ")) {
    const next = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(next).width > maxWidth) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

/** Shades the area after the last data point (stale data): --raised at 60 %, dashed --attention edge. */
function staleTail({ from, label }) {
  return {
    hooks: {
      draw: [
        (u) => {
          const { ctx } = u;
          const { left, top, width, height } = u.bbox;
          const x = Math.max(left, Math.round(u.valToPos(from, "x", true)) + 0.5);
          const right = left + width;
          if (x >= right) return;
          ctx.save();
          ctx.fillStyle = withAlpha("raised", 0.6);
          ctx.fillRect(x, top, right - x, height);
          ctx.strokeStyle = colour("attention");
          ctx.lineWidth = dpr();
          ctx.setLineDash([3 * dpr(), 3 * dpr()]);
          ctx.beginPath();
          ctx.moveTo(x, top);
          ctx.lineTo(x, top + height);
          ctx.stroke();
          if (label) {
            ctx.fillStyle = colour("attention");
            ctx.font = font("small", 700);
            ctx.textBaseline = "top";
            const pad = 10 * dpr();
            const lineH = 17 * dpr();
            const lines = wrap(ctx, label, Math.max(110 * dpr(), right - x - 2 * pad));
            const w = Math.max(...lines.map((l) => ctx.measureText(l).width));
            // Right of the edge when it fits, else left of it (a short stale stretch).
            const fits = x + pad + w <= right;
            ctx.textAlign = fits ? "left" : "right";
            const tx = fits ? x + pad : x - pad;
            if (!fits) {
              // Over the plotted lines: a --surface backing keeps the label readable.
              ctx.fillStyle = colour("surface");
              ctx.fillRect(tx - w - 4 * dpr(), top + pad - 3 * dpr(), w + 8 * dpr(), lines.length * lineH + 4 * dpr());
              ctx.fillStyle = colour("attention");
            }
            lines.forEach((line, i) => ctx.fillText(line, tx, top + pad + i * lineH));
          }
          ctx.restore();
        },
      ],
    },
  };
}

// Tooltip -------------------------------------------------------------------------------------

/** Tooltip in --overlay with --borderStrong; flips to the left of the crosshair near the edge. */
function tooltip(format, markers, header, extra) {
  let tip;
  const hide = () => tip && (tip.style.display = "none");
  return {
    hooks: {
      init: (u) => {
        tip = el("div", { class: "tooltip chart-tip", attrs: { role: "status" } });
        tip.style.display = "none";
        document.body.append(tip);
        u.over.addEventListener("mouseleave", hide);
      },
      setCursor: (u) => {
        const { idx, left, top } = u.cursor;
        if (idx == null || left < 0) return hide();
        const t = u.data[0][idx];
        tip.replaceChildren(el("div", { class: "muted", text: header(t) }));
        u.series.forEach((s, i) => {
          if (i === 0 || !s.show) return;
          const v = u.data[i][idx];
          if (v == null && s._bars) return; // the other bar series holds this bar
          const sw = el("i", { class: "swatch" });
          sw.style.background = s._stroke;
          const fmt = s._format ?? format;
          tip.append(el("div", { class: "tip-row" }, sw, el("span", { text: s.label }), el("span", { class: "tip-val", text: v == null ? "—" : fmt(v) })));
        });
        for (const row of extra) {
          const v = row.values[idx];
          if (v == null) continue;
          const sw = el("i", { class: "swatch" });
          sw.style.background = colour(row.color ?? "text3");
          tip.append(el("div", { class: "tip-row" }, sw, el("span", { text: row.label }), el("span", { class: "tip-val", text: (row.format ?? format)(v) })));
        }
        // Markers at this point: those closer to this x than to its neighbours.
        const xs = u.data[0];
        const lo = idx > 0 ? (xs[idx - 1] + t) / 2 : -Infinity;
        const hi = idx < xs.length - 1 ? (xs[idx + 1] + t) / 2 : Infinity;
        for (const m of markers) {
          if (m.t < lo || m.t >= hi || !MARKERS[m.kind]) continue;
          tip.append(el("div", { class: "tip-row" }, markerSwatch(MARKERS[m.kind]), el("span", { text: m.label ?? MARKERS[m.kind].label })));
        }
        tip.style.display = "block";
        const box = u.over.getBoundingClientRect();
        const gap = 14;
        const w = tip.offsetWidth;
        let x = box.left + left + gap;
        if (x + w > Math.min(box.right, window.innerWidth - 4)) x = box.left + left - gap - w; // flip left
        tip.style.left = Math.max(4, x) + "px";
        tip.style.top = Math.max(4, box.top + top - tip.offsetHeight / 2) + "px";
      },
      destroy: () => tip?.remove(),
    },
  };
}

function markerSwatch(kind) {
  const s = el("i", { class: "marker " + kind.shape });
  s.style.setProperty("--marker", `var(--${kind.color})`);
  return s;
}

// Point labels ------------------------------------------------------------------------------

/**
 * Labelled points [{x, y, text, color, below}] (daily rhythm minima and maxima, the cheapest
 * and dearest hour): a 6 px dot in the series colour and the text above (or below) it.
 */
function pointLabels(labels) {
  return {
    hooks: {
      draw: [
        (u) => {
          const { ctx } = u;
          const { left, top, width, height } = u.bbox;
          ctx.save();
          ctx.font = font();
          for (const l of labels) {
            const x = u.valToPos(l.x, "x", true);
            const y = u.valToPos(l.y, "y", true);
            if (x < left - 1 || x > left + width + 1) continue;
            const c = colour(l.color ?? "text2");
            if (l.row != null) {
              // Pinned to the headroom above the plot (bar charts): row 0, then row 1 below it.
              const w = ctx.measureText(l.text).width;
              const pad = 4 * dpr();
              ctx.fillStyle = c;
              ctx.textAlign = "center";
              ctx.textBaseline = "top";
              ctx.fillText(l.text, Math.min(Math.max(x, left + w / 2 + pad), left + width - w / 2 - pad), top + (2 + l.row * 17) * dpr());
              continue;
            }
            if (l.dot !== false) {
              ctx.fillStyle = c;
              ctx.beginPath();
              ctx.arc(x, y, 3 * dpr(), 0, 2 * Math.PI);
              ctx.fill();
            }
            const w = ctx.measureText(l.text).width;
            const pad = 4 * dpr();
            // Keep the text inside the plot: shift it in from the edges, flip at the top/bottom.
            const tx = Math.min(Math.max(x, left + w / 2 + pad), left + width - w / 2 - pad);
            let below = !!l.below;
            if (!below && y - 18 * dpr() < top) below = true;
            if (below && y + 18 * dpr() > top + height) below = false;
            ctx.textAlign = "center";
            ctx.textBaseline = below ? "top" : "bottom";
            ctx.fillStyle = c;
            ctx.fillText(l.text, tx, below ? y + 7 * dpr() : y - 7 * dpr());
          }
          ctx.restore();
        },
      ],
    },
  };
}

// Linked charts ---------------------------------------------------------------------------

const groups = new Map(); // sync key -> Set of uPlot instances

/**
 * Destroys charts whose element left the page (views replace their DOM on re-render), so
 * groups do not keep dead charts and their tooltip divs do not pile up in <body>.
 */
function pruneDetached(key) {
  for (const u of [...(groups.get(key) ?? [])]) if (!u.root.isConnected) u.destroy();
}

/** Zooming one chart of a group zooms the others (the cursor is linked by cursor.sync). */
function linked(key) {
  let busy = false;
  return {
    hooks: {
      init: (u) => {
        if (!groups.has(key)) groups.set(key, new Set());
        pruneDetached(key);
        groups.get(key).add(u);
      },
      setScale: (u, scaleKey) => {
        if (scaleKey !== "x" || busy) return;
        pruneDetached(key);
        const { min, max } = u.scales.x;
        busy = true;
        try {
          for (const other of groups.get(key) ?? []) {
            if (other !== u && (other.scales.x.min !== min || other.scales.x.max !== max)) other.setScale("x", { min, max });
          }
        } finally {
          busy = false;
        }
      },
      destroy: (u) => groups.get(key)?.delete(u),
    },
  };
}

// Charts --------------------------------------------------------------------------------------

const WIDTHS = { primary: "--chart-line-primary", secondary: "--chart-line-secondary", tertiary: "--chart-line-tertiary" };
const Y_AXIS_PX = 56; // fixed, so linked charts line their plots up

/** y range: data plus reference lines (a vendor floor below the prices stays visible), 8 % headroom. */
function yRange(fromZero, include, headroom = 0.08) {
  return (u, min, max) => {
    if (min == null || max == null) return [0, 1];
    let lo = Math.min(min, ...include);
    let hi = Math.max(max, ...include);
    if (fromZero) lo = Math.min(0, lo);
    const span = hi - lo || Math.abs(hi) || 1;
    return [fromZero && lo === 0 ? 0 : lo - span * 0.08, hi + span * headroom];
  };
}

function barsPath() {
  return uPlot.paths.bars({ size: [1 - num("--chart-bar-gap"), Infinity], align: 0 });
}

/**
 * chart(el, {x, series, height, format, bands, refLines, markers, stale, sync, yFromZero})
 *  x: unix seconds (shared by every series)
 *  series: [{label, color: "s1", width: "primary", fill?, bars?, values, format?}]
 *  bands: [{upper, lower, color}]: indices into `series`, filled at --chart-band-alpha
 *  refLines: [{value, label?}] dashed; markers: [{t, kind: "mispricing"|"shock"|"buyout", label?}]
 *  stale: {from, to, label}: x runs on to `to` and the part after `from` is shaded
 *  sync: key shared by charts whose cursor and zoom move together (matching x data)
 *  xAxis: false hides the time axis (the upper of two linked plots)
 *  xHours: x is the hour of day 0..23 (ticks "06:00"), not a time
 *  tipDate: "day" shows "Mon, 16 Nov 2026" in the tooltip (daily points), default date + time
 *  tipExtra: [{label, values, color?, format?}] more tooltip rows (not drawn)
 *  labels: [{x, y, text, color, below?, dot?, row?}] labelled points (row: pinned to the top)
 *  yWhole: y ticks on whole numbers (coin axes)
 *  yFromZero: start y at 0 (default for bars; pass false to fit bars to the data)
 * Returns the uPlot instance with `reset()` (undo zoom, for the whole linked group).
 */
export function chart(target, cfg) {
  const { series, height = 300, format = (v) => v.toLocaleString("en-US"), bands = [], markers = [], stale = null, sync = null } = cfg;
  const refLines = cfg.refLines ?? (cfg.refLine != null ? [{ value: cfg.refLine }] : []);
  const x = [...cfg.x];
  const values = series.map((s) => [...s.values]);
  if (stale && stale.to > x[x.length - 1]) {
    x.push(stale.to); // empty point, so the x-axis reaches "now"
    values.forEach((v) => v.push(null));
  }
  const surface = colour("surface");
  const hasBars = series.some((s) => s.bars);
  const hours = !!cfg.xHours;
  const header = hours ? hourLabel : cfg.tipDate === "day" ? dayLabel : dateTime;
  const xScale = hours
    ? { time: false, range: hasBars ? (u, lo, hi) => [lo - 0.5, hi + 0.5] : (u, lo, hi) => [lo, hi] }
    : { time: true };
  const xAxisOpts = hours
    ? { values: (u, vals) => vals.map(hourLabel), splits: () => [0, 6, 12, 18, 23] }
    : { values: timeTicks, incrs: timeIncrs, space: 64 };
  const opts = {
    width: Math.max(200, target.clientWidth),
    height,
    ...(hours ? {} : { tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), TZ) }),
    legend: { show: false },
    padding: [markers.length ? MARKER_ROOM : 10, 20, 0, 0], // 20 px right: room for the last date tick
    cursor: {
      x: true,
      y: true,
      drag: { x: true, y: false, setScale: true },
      points: {
        size: (u, i) => (u.series[i]._bars ? 0 : num("--chart-marker-dot")),
        width: 2,
        stroke: () => surface,
        fill: (u, i) => u.series[i]._stroke,
      },
      ...(sync ? { sync: { key: sync, setSeries: false, scales: ["x", null] } } : {}),
    },
    scales: {
      x: xScale,
      // Labelled points get room above the highest value for their text.
      y: { range: yRange(cfg.yFromZero ?? hasBars, refLines.map((r) => r.value), cfg.labels?.length ? 0.22 : 0.08) },
    },
    axes: [axis({ ...xAxisOpts, show: cfg.xAxis !== false, size: cfg.xAxis === false ? 0 : 50 }), axis({ size: Y_AXIS_PX, values: (u, vals) => vals.map((v) => format(v)), ...(cfg.yWhole ? { incrs: WHOLE_INCRS } : {}) })],
    series: [
      {},
      ...series.map((s) => ({
        label: s.label,
        stroke: colour(s.color),
        width: s.bars ? 0 : num(WIDTHS[s.width ?? "secondary"]),
        fill: s.bars ? colour(s.color) : s.fill ? withAlpha(s.color, num("--chart-area-alpha")) : undefined,
        paths: s.bars ? barsPath() : undefined,
        points: { show: false },
        _bars: !!s.bars,
        _format: s.format,
      })),
    ],
    bands: bands.map((b) => ({ series: [b.upper + 1, b.lower + 1], fill: withAlpha(b.color ?? series[b.lower].color, num("--chart-band-alpha")) })),
    plugins: [
      horizontalGrid(),
      ...(refLines.length ? [referenceLines(refLines)] : []),
      ...(markers.length ? [eventMarkers(markers)] : []),
      ...(stale ? [staleTail(stale)] : []),
      ...(cfg.labels?.length ? [pointLabels(cfg.labels)] : []),
      ...(sync ? [linked(sync)] : []),
      tooltip(format, markers, header, cfg.tipExtra ?? []),
    ],
  };
  const u = new uPlot(opts, [x, ...values], target);
  for (let i = 1; i < u.series.length; i++) Object.assign(u.series[i], { _bars: opts.series[i]._bars, _format: opts.series[i]._format });
  u.reset = () => u.setScale("x", { min: x[0], max: x[x.length - 1] }); // linked() passes it on
  target.uplot = u; // for views that find a chart by its element (and for checks in --dev)
  const ro = new ResizeObserver(() => {
    // Detached (the view re-rendered): free the chart, its tooltip and its group entry.
    if (!target.isConnected) {
      ro.disconnect();
      u.destroy();
      return;
    }
    u.setSize({ width: Math.max(200, target.clientWidth), height });
  });
  ro.observe(target);
  return u;
}

/** A line chart (kept for the existing callers): chart() with line series. */
export const lineChart = chart;

/**
 * barChart(el, {x, values, label, color: "s6", highlight?: bool[], highlightColor: "s3",
 *               highlightLabel, ...chart options}) — bars with the 28 % gap; highlighted
 * bars (supply shocks) in their own colour.
 */
export function barChart(target, { x, values, label, color = "s6", highlight = null, highlightColor = "s3", highlightLabel = label, format, ...rest }) {
  const series = [{ label, color, bars: true, values: highlight ? values.map((v, i) => (highlight[i] ? null : v)) : values }];
  if (highlight) series.push({ label: highlightLabel, color: highlightColor, bars: true, values: values.map((v, i) => (highlight[i] ? v : null)) });
  return chart(target, { x, series, format, yFromZero: true, ...rest });
}

// Card, legend --------------------------------------------------------------------------------

/** Legend row above a plot: line swatch (or marker shape) + label in --text2 (not uPlot's legend). */
export function legend(items) {
  return el(
    "div",
    { class: "legend" },
    items.map((s) => {
      if (s.shape) return el("span", {}, markerSwatch(s), s.label);
      const swatch = el("i", { class: s.dashed ? "dashed" : s.bars ? "bar" : "" });
      swatch.style.setProperty("--swatch", `var(--${s.color})`);
      return el("span", {}, swatch, s.label);
    }),
  );
}

/**
 * chartCard({title, sub, legend: items, build(plotEl, ...) -> uPlot | uPlot[], plots, className,
 *            tools, zoom, reset, legend2})
 * A card with title, subtitle, legend and zoom/reset buttons in the header. `tools` (a node)
 * goes left of them (a current value, a chip); `zoom: true` adds a zoom-in button (the later
 * half of the range); `reset: false` drops the reset button (charts that do not zoom);
 * `legend2` is a second legend row (event markers). `build` runs once the card is in the page
 * (charts need their width). Returns {node, charts, mount()}.
 */
export function chartCard({ title, sub, legend: items = [], build, plots = 1, className = "", tools = null, zoom = false, reset = true, legend2 = null }) {
  const holders = Array.from({ length: plots }, () => el("div", { class: "chart" }));
  const result = { node: null, charts: [] };
  const zoomBtn = zoom
    ? el("button", { class: "btn icon slim-icon", attrs: { title: "Zoom in", "aria-label": "Zoom in" }, on: { click: () => zoomIn(result.charts[0]) } }, icon("zoom", 15))
    : null;
  const resetBtn = reset
    ? el("button", { class: "btn icon slim-icon", attrs: { title: "Reset zoom", "aria-label": "Reset zoom" }, on: { click: () => result.charts[0]?.reset() } }, icon("reset", 15))
    : null;
  const legends = el("div", { class: "legends" }, items.length ? legend(items) : null, legend2?.length ? legend(legend2) : null);
  const head = el(
    "div",
    { class: "card-head" },
    el("div", {}, el("h2", { class: "card-title", text: title }), sub ? el("div", { class: "sub", text: sub }) : null),
    el("div", { class: "card-tools" }, legends, tools, zoomBtn, resetBtn),
  );
  result.node = el("section", { class: "card chart-card " + className }, head, holders);
  result.mount = () => {
    const made = build(...holders);
    result.charts = Array.isArray(made) ? made : [made];
    return result;
  };
  return result;
}

/** Zoom to the later half of what is shown (linked charts follow). */
function zoomIn(u) {
  if (!u) return;
  const { min, max } = u.scales.x;
  if (min == null || max == null) return;
  u.setScale("x", { min: min + (max - min) / 2, max });
}

// Sparkline and range bar (SVG, for table cells) -----------------------------------------

/** 96×26 sparkline (Movers): line in --rise/--fall (--text3 when flat) with an end dot. */
export function sparkline(values, direction = "flat", { width = 96, height = 26 } = {}) {
  const pts = values.filter((v) => v != null && Number.isFinite(v));
  const node = svg("svg", { class: "sparkline " + direction, width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
  if (pts.length < 2) return node;
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const pad = 2.5;
  const xAt = (i) => (i / (pts.length - 1)) * width;
  const yAt = (v) => (hi === lo ? height / 2 : pad + (1 - (v - lo) / (hi - lo)) * (height - 2 * pad));
  const d = pts.map((v, i) => `${i ? "L" : "M"}${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(" ");
  node.append(svg("path", { d }), svg("circle", { cx: width, cy: yAt(pts[pts.length - 1]).toFixed(1), r: 2.2 }));
  return node;
}

/**
 * 140 px range bar (Movers "Where it sits"): typical range [low, high] in --borderStrong,
 * the usual price as a --text2 tick, the current price as a rose (--s4) diamond.
 */
export function rangeBar({ low, high, usual, current }, { width = 140, height = 16 } = {}) {
  const lo = Math.min(low, current, usual);
  const hi = Math.max(high, current, usual);
  const span = hi - lo || 1;
  const pad = 6;
  const xAt = (v) => pad + ((v - lo) / span) * (width - 2 * pad);
  const mid = height / 2;
  const cx = xAt(current);
  return svg(
    "svg",
    { class: "rangebar", width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" },
    svg("line", { class: "track", x1: pad, x2: width - pad, y1: mid, y2: mid }),
    svg("line", { class: "typical", x1: xAt(low), x2: xAt(high), y1: mid, y2: mid }),
    svg("line", { class: "usual", x1: xAt(usual), x2: xAt(usual), y1: mid - 5, y2: mid + 5 }),
    svg("path", { class: "current", d: `M${cx} ${mid - 5} L${cx + 5} ${mid} L${cx} ${mid + 5} L${cx - 5} ${mid} Z` }),
  );
}
