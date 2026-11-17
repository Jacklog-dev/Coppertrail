// Filter bar (HANDOVER 8b): Groups (+ edit), Class, Search, date range, Min sales/day,
// then the active-filter count and Reset. Every change goes to the bridge (`set_filters`),
// which saves it and returns the new state; the whole frame re-renders from that.
//
// Re-rendering replaces the bar's DOM, so this module remembers which popover is open and
// which field had focus, and restores both after each render.
import { call } from "./api.js";
import { calendar, dayLabel } from "./calendar.js";
import { el, replace } from "./dom.js";
import { openGroupEditor } from "./groupeditor.js";
import { icon } from "./icons.js";
import { closePopover, openPopover } from "./popover.js";

const RANGES = [
  ["24h", "24 h"],
  ["7d", "7 d"],
  ["30d", "30 d"],
  ["all", "All"],
];
const MIN_SALES_PRESETS = [0, 10, 50, 200, 1000];
const SEARCH_DELAY_MS = 250;

const ui = {
  open: null, // "groups" | "class" | "date" | "sales"
  groupSearch: "",
  month: null, // "YYYY-MM" shown in the calendar
  pending: null, // first calendar click
};
let ctx = null; // {container, state, onState}
let searchTimer = null;

async function change(partial) {
  ctx.onState(await call("set_filters", partial));
}

async function reset() {
  ui.open = null;
  closePopover(false);
  ctx.onState(await call("reset_filters"));
}

function editGroups(newGroup = false) {
  ui.open = null;
  closePopover(false);
  openGroupEditor(ctx.state, { newGroup, onState: ctx.onState });
}

function toggle(kind, anchor) {
  if (ui.open === kind) {
    ui.open = null;
    closePopover(false);
    return;
  }
  ui.open = kind;
  ui.pending = null;
  if (kind === "date") ui.month = ctx.state.window.to.slice(0, 7);
  showPopover(anchor);
}

function showPopover(anchor) {
  const build = { groups: groupsPopover, class: classMenu, date: datePopover, sales: salesPopover }[ui.open];
  if (!build || !anchor) return;
  const [content, className] = build();
  openPopover(anchor, content, { className, onClose: () => (ui.open = null) });
}

// Popovers ------------------------------------------------------------------------

function groupsPopover() {
  const s = ctx.state;
  const selected = new Set(s.filters.groups);
  const needle = ui.groupSearch.trim().toLowerCase();
  const rows = s.groups
    .filter((g) => !needle || g.name.toLowerCase().includes(needle))
    .map((g) => {
      const on = selected.has(g.name);
      const box = el("span", { class: "check", attrs: { "aria-checked": on ? "true" : "false" } }, on ? icon("check", 12) : null);
      return el(
        "button",
        {
          class: "pop-row",
          attrs: { role: "menuitemcheckbox", "aria-checked": on ? "true" : "false" },
          on: {
            click: () => {
              const next = on ? s.filters.groups.filter((n) => n !== g.name) : s.groups.map((x) => x.name).filter((n) => n === g.name || selected.has(n));
              change({ groups: next });
            },
          },
        },
        box,
        el("span", { class: "name", text: g.name }),
        el("span", { class: "count", text: `${g.count.toLocaleString("en-US")} ${g.count === 1 ? "item" : "items"}` }),
      );
    });
  const search = el("input", {
    attrs: { placeholder: "Search groups", value: ui.groupSearch, "data-focus": "group-search" },
    on: {
      input: (e) => {
        ui.groupSearch = e.target.value;
        showPopover(ctx.container.querySelector('[data-anchor="groups"]'));
        refocus("group-search");
      },
    },
  });
  const content = el(
    "div",
    {},
    el("div", { class: "pop-search" }, el("label", { class: "input" }, icon("search", 16), search)),
    el(
      "div",
      { class: "pop-summary" },
      el("span", { text: s.groupsSummary }),
      el(
        "span",
        {},
        el("button", { class: "btn link", text: "All", on: { click: () => change({ groups: s.groups.map((g) => g.name) }) } }),
        el("button", { class: "btn link", text: "None", on: { click: () => change({ groups: [] }) } }),
      ),
    ),
    el("div", { class: "rows", attrs: { role: "menu" } }, rows.length ? rows : el("div", { class: "pop-row muted", text: "No group matches" })),
    el(
      "div",
      { class: "pop-foot" },
      el("button", { class: "btn link", on: { click: () => editGroups(true) } }, icon("plus", 14), "New group"),
      el("button", { class: "btn link", on: { click: () => editGroups(false) } }, icon("edit", 14), "Edit groups…"),
    ),
  );
  return [content, "popover pop-groups"];
}

function classMenu() {
  const s = ctx.state;
  const options = [["", "All classes"], ...s.classes.map((c) => [c, c])];
  const content = el(
    "div",
    { attrs: { role: "menu" } },
    options.map(([value, label]) =>
      el("button", {
        text: label,
        attrs: { role: "menuitemradio", "aria-checked": s.filters.item_class === value ? "true" : "false" },
        on: {
          click: () => {
            ui.open = null;
            closePopover(false);
            change({ item_class: value });
          },
        },
      }),
    ),
  );
  return [content, "menu"];
}

function rangeSeg() {
  const current = ctx.state.filters.range;
  return el(
    "div",
    { class: "seg", attrs: { role: "group", "aria-label": "Date range" } },
    RANGES.map(([value, label]) =>
      el("button", {
        text: label,
        attrs: { "aria-pressed": current === value ? "true" : "false" },
        on: { click: () => change({ range: value }) },
      }),
    ),
  );
}

function datePopover() {
  const s = ctx.state;
  const w = s.window;
  const field = (label, iso) => el("label", {}, label, el("span", { class: "input", text: dayLabel(iso) }));
  const note = w.archiveFrom
    ? `Archive: ${dayLabel(w.archiveFrom)} – ${dayLabel(w.archiveTo)}. Click two days for a custom range.`
    : "No data in the archive yet.";
  const content = el(
    "div",
    {},
    rangeSeg(),
    el("div", { class: "fromto" }, field("From", ui.pending ?? w.from), field("To", ui.pending ? null : w.to)),
    calendar({
      from: w.from,
      to: w.to,
      min: w.archiveFrom,
      max: w.archiveTo,
      month: ui.month,
      pending: ui.pending,
      onMonth: (ym) => {
        ui.month = ym;
        showPopover(ctx.container.querySelector('[data-anchor="date"]'));
      },
      onDay: (day) => {
        if (!ui.pending) {
          ui.pending = day;
          showPopover(ctx.container.querySelector('[data-anchor="date"]'));
          return;
        }
        const [lo, hi] = [ui.pending, day].sort();
        ui.pending = null;
        change({ range: "custom", date_from: lo, date_to: hi });
      },
    }),
    el("div", { class: "note", text: note }),
  );
  content.style.display = "contents";
  return [content, "popover pop-date"];
}

function salesPopover() {
  const s = ctx.state;
  const content = el(
    "div",
    {},
    el("div", { class: "label", text: "Minimum sales per day" }),
    el(
      "div",
      { class: "chips" },
      MIN_SALES_PRESETS.map((n) =>
        el("button", {
          class: "chip",
          text: n.toLocaleString("en-US"),
          attrs: { "aria-pressed": s.filters.min_sales === n ? "true" : "false" },
          on: { click: () => change({ min_sales: n }) },
        }),
      ),
    ),
    el("div", { class: "note", text: s.minSalesPass }),
  );
  content.style.display = "contents";
  return [content, "popover pop-sales"];
}

// Focus keeping ---------------------------------------------------------------------

function refocus(key, caret) {
  const node = document.querySelector(`[data-focus="${key}"]`);
  if (!node) return;
  node.focus();
  const pos = caret ?? node.value?.length ?? 0;
  if (node.setSelectionRange && node.type !== "number") node.setSelectionRange(pos, pos);
}

// Render ------------------------------------------------------------------------------

/** render(container, state, onState) — onState(newState) re-renders the whole frame. */
export function render(container, state, onState) {
  const focused = document.activeElement?.dataset?.focus;
  const caret = document.activeElement?.selectionStart;
  ctx = { container, state, onState };
  const f = state.filters;
  const active = new Set(state.active);
  const on = (name) => (active.has(name) ? " active" : "");

  const groups = el(
    "button",
    { class: "ctl groups" + on("Groups"), attrs: { "data-anchor": "groups", "aria-haspopup": "dialog" }, on: { click: (e) => toggle("groups", e.currentTarget) } },
    el("span", { class: "label", text: "Groups" }),
    el("span", { class: "value", text: state.groupsLabel }),
    el("span", { class: "chev" }, icon("chevron", 14)),
  );
  const pencil = el("button", { class: "ctl", attrs: { "aria-label": "Edit item groups", title: "Edit item groups" }, on: { click: () => editGroups(false) } }, icon("edit", 16));
  pencil.style.padding = "0 8px";

  const cls = el(
    "button",
    { class: "ctl" + on("Class"), attrs: { "data-anchor": "class", "aria-haspopup": "menu" }, on: { click: (e) => toggle("class", e.currentTarget) } },
    el("span", { class: "label", text: "Class" }),
    el("span", { class: "value", text: f.item_class || "All classes" }),
    el("span", { class: "chev" }, icon("chevron", 14)),
  );

  const searchInput = el("input", {
    attrs: { type: "search", placeholder: "Search items", value: f.search, "data-focus": "search", "aria-label": "Search items" },
    on: {
      input: (e) => {
        clearTimeout(searchTimer);
        const text = e.target.value;
        searchTimer = setTimeout(() => change({ search: text }), SEARCH_DELAY_MS);
      },
    },
  });
  const search = el("label", { class: "input search" + on("Search") }, icon("search", 16), searchInput);

  const dateBtn = el(
    "button",
    { class: "ctl" + on("Date range"), attrs: { "data-anchor": "date", "aria-haspopup": "dialog" }, on: { click: (e) => toggle("date", e.currentTarget) } },
    icon("calendar", 16),
    el("span", { class: "value", text: state.window.label }),
  );

  const salesInput = el("input", {
    attrs: { type: "number", min: 0, step: 10, value: f.min_sales, "data-focus": "min-sales", "aria-label": "Minimum sales per day" },
    on: {
      change: (e) => change({ min_sales: Math.max(0, parseInt(e.target.value, 10) || 0) }),
      click: (e) => e.stopPropagation(),
    },
  });
  const sales = el(
    "div",
    { class: "ctl minsales" + on("Min sales/day"), attrs: { "data-anchor": "sales", role: "group" }, on: { click: (e) => toggle("sales", e.currentTarget) } },
    el("span", { class: "label", text: "Min sales/day" }),
    salesInput,
  );

  const activeState = state.active.length
    ? el(
        "div",
        { class: "active-state" },
        el("span", { class: "active-label" }, el("span", { class: "dot accent" }), state.activeLabel),
        el("button", { class: "btn ghost", on: { click: reset } }, icon("reset", 14), "Reset"),
      )
    : el("div", { class: "active-state" }, el("span", { class: "no-filters", text: "No filters" }));

  replace(
    container,
    el("div", { class: "group-pair" }, groups, pencil),
    cls,
    search,
    el("div", { class: "group-pair" }, rangeSeg(), dateBtn),
    sales,
    el("div", { class: "spacer" }),
    activeState,
  );

  if (ui.open) showPopover(container.querySelector(`[data-anchor="${ui.open}"]`));
  if (focused) refocus(focused, caret);
}
