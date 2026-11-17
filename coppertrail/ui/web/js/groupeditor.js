// Item-group editor (HANDOVER 8b): Groups | Members | Add items, footer Cancel / Save groups.
// Edits a copy of the groups; nothing is saved until "Save groups". Membership is resolved
// by the bridge (globs, ids, exclusions), so this file never matches names itself.
import { call } from "./api.js";
import { coin } from "./coins.js";
import { el, replace } from "./dom.js";
import { icon } from "./icons.js";

const SEARCH_DELAY_MS = 200;

const plain = (g) => ({ name: g.name, itemIds: [...g.itemIds], patterns: [...g.patterns], excludedIds: [...g.excludedIds] });
const plural = (n, word) => `${n.toLocaleString("en-US")} ${word}${n === 1 ? "" : "s"}`;

function uniqueName(base, groups, except = null) {
  const taken = new Set(groups.filter((g) => g !== except).map((g) => g.name));
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base} ${n}`)) n += 1;
  return `${base} ${n}`;
}

/** openGroupEditor(state, {newGroup, onState}) */
export function openGroupEditor(state, { newGroup = false, onState }) {
  const ed = {
    // `orig` remembers the saved name, so renames (even chained ones) map old -> new on save.
    groups: state.groups.map((g) => ({ ...plain(g), orig: g.name, count: g.count })),
    sel: 0,
    members: [],
    note: "",
    search: "",
    results: { rows: [], note: "" },
    checked: new Set(),
    error: "",
    saving: false,
  };
  if (newGroup) {
    ed.groups.push({ name: uniqueName("New group", ed.groups), itemIds: [], patterns: [], excludedIds: [], orig: null, count: 0 });
    ed.sel = ed.groups.length - 1;
  }
  const current = () => ed.groups[ed.sel];

  const dialog = el("div", { class: "dialog group-editor", attrs: { role: "dialog", "aria-modal": "true", "aria-label": "Edit item groups" } });
  const backdrop = el("div", { class: "backdrop" }, dialog);
  const onKey = (e) => {
    if (e.key === "Escape") close();
  };
  document.addEventListener("keydown", onKey);
  document.body.append(backdrop);

  function close() {
    document.removeEventListener("keydown", onKey);
    backdrop.remove();
  }

  // Bridge round trips --------------------------------------------------------------
  async function loadMembers(note = "") {
    const g = current();
    ed.members = g ? await call("group_members", plain(g)) : [];
    if (g) g.count = ed.members.length;
    ed.note = note;
    await runSearch();
  }

  let searchTimer = null;
  async function runSearch() {
    const g = current();
    ed.results = g && ed.search.trim() ? await call("search_items", ed.search, plain(g)) : { rows: [], note: "" };
    ed.checked = new Set([...ed.checked].filter((id) => ed.results.rows.some((r) => r.id === id)));
    draw();
  }

  function addIds(ids) {
    const g = current();
    for (const id of ids) {
      g.excludedIds = g.excludedIds.filter((x) => x !== id);
      if (!g.itemIds.includes(id)) g.itemIds.push(id);
    }
  }

  function removeId(id) {
    const g = current();
    g.itemIds = g.itemIds.filter((x) => x !== id);
    if (!g.excludedIds.includes(id)) g.excludedIds.push(id); // keeps a pattern from adding it back
    loadMembers();
  }

  async function paste(e) {
    if (!current()) return;
    const text = e.clipboardData?.getData("text") ?? "";
    const names = text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (!names.length) return;
    e.preventDefault();
    const found = await call("match_names", names);
    addIds(found.ids);
    loadMembers(found.note);
  }

  async function save() {
    const names = ed.groups.map((g) => g.name.trim());
    if (names.some((n) => !n)) return fail("Every group needs a name.");
    if (new Set(names).size !== names.length) return fail("Two groups have the same name.");
    const renamed = {};
    for (const g of ed.groups) if (g.orig && g.orig !== g.name.trim()) renamed[g.orig] = g.name.trim();
    ed.saving = true;
    draw();
    try {
      const next = await call("save_groups", ed.groups.map((g) => ({ ...plain(g), name: g.name.trim() })), renamed);
      close();
      onState(next);
    } catch (err) {
      ed.saving = false;
      fail(`Saving failed: ${err.message ?? err}`);
    }
  }

  function fail(message) {
    ed.error = message;
    draw();
  }

  // Panes -----------------------------------------------------------------------------
  let dragFrom = null;
  function groupsPane() {
    const rows = ed.groups.map((g, i) =>
      el(
        "button",
        {
          class: "ge-group",
          attrs: { draggable: "true", "aria-current": i === ed.sel ? "true" : false },
          on: {
            click: () => {
              ed.sel = i;
              ed.checked.clear();
              loadMembers();
            },
            dragstart: () => (dragFrom = i),
            dragover: (e) => e.preventDefault(),
            drop: (e) => {
              e.preventDefault();
              if (dragFrom == null || dragFrom === i) return;
              const selected = current();
              const [moved] = ed.groups.splice(dragFrom, 1);
              ed.groups.splice(i, 0, moved);
              ed.sel = ed.groups.indexOf(selected);
              dragFrom = null;
              draw();
            },
          },
        },
        el("span", { class: "grip" }, icon("grip", 14)),
        el("span", { class: "name", text: g.name || "(unnamed)" }),
        el("span", { class: "count", text: g.count.toLocaleString("en-US") }),
      ),
    );
    return el(
      "div",
      { class: "ge-pane ge-groups" },
      el("span", { class: "label", text: "Groups · drag to reorder" }),
      el("div", { class: "ge-list" }, rows),
      el(
        "div",
        { class: "ge-actions" },
        el("button", { class: "btn ghost", on: { click: addGroup } }, icon("plus", 14), "New"),
        el("button", { class: "btn ghost", attrs: { disabled: !current() }, on: { click: duplicate } }, "Duplicate"),
        el("button", { class: "btn ghost", attrs: { disabled: !current(), "aria-label": "Delete group", title: "Delete group" }, on: { click: remove } }, icon("trash", 14)),
      ),
    );
  }

  function addGroup() {
    ed.groups.push({ name: uniqueName("New group", ed.groups), itemIds: [], patterns: [], excludedIds: [], orig: null, count: 0 });
    ed.sel = ed.groups.length - 1;
    loadMembers();
  }
  function duplicate() {
    const g = current();
    ed.groups.splice(ed.sel + 1, 0, { ...plain(g), name: uniqueName(`${g.name} copy`, ed.groups), orig: null, count: g.count });
    ed.sel += 1;
    loadMembers();
  }
  function remove() {
    ed.groups.splice(ed.sel, 1);
    ed.sel = Math.max(0, Math.min(ed.sel, ed.groups.length - 1));
    loadMembers();
  }

  function membersPane() {
    const g = current();
    if (!g) return el("div", { class: "ge-pane ge-members" }, el("p", { class: "muted", text: "No groups. Click New to make one." }));
    const name = el("input", {
      attrs: { value: g.name, "data-focus": "ge-name", "aria-label": "Group name" },
      on: {
        input: (e) => {
          g.name = e.target.value;
          ed.error = "";
          const row = dialog.querySelector('.ge-group[aria-current="true"] .name');
          if (row) row.textContent = g.name || "(unnamed)";
        },
      },
    });
    const table = el(
      "table",
      { class: "data" },
      el("thead", {}, el("tr", {}, el("th", { text: "Item" }), el("th", { text: "Class" }), el("th", { class: "num", text: "Lowest buyout" }), el("th"))),
      el(
        "tbody",
        {},
        ed.members.map((r) =>
          el(
            "tr",
            {},
            el("td", { text: r.name }),
            el("td", { class: "muted", text: r.class }),
            el("td", { class: "num" }, coin(r.price)),
            el("td", { class: "num ge-x" }, el("button", { attrs: { "aria-label": `Remove ${r.name}`, title: "Remove from group" }, on: { click: () => removeId(r.id) } }, icon("x", 14))),
          ),
        ),
      ),
    );
    const list = el(
      "div",
      { class: "ge-table", attrs: { tabindex: "0", title: "Paste a list of names, one per line" }, on: { paste } },
      ed.members.length ? table : el("p", { class: "muted ge-empty", text: "No items yet. Add them on the right, or paste a list of names here." }),
    );
    return el(
      "div",
      { class: "ge-pane ge-members" },
      el("label", { class: "label" }, "Name", el("span", { class: "input" }, name)),
      el(
        "div",
        { class: "ge-meta" },
        el("span", { text: `${plural(ed.members.length, "item")} in this group` }),
        ed.note ? el("span", { class: "attention", text: ed.note }) : el("span", { class: "label", text: "Tip: paste a list of names, one per line" }),
      ),
      list,
    );
  }

  function addPane() {
    const g = current();
    const search = el("input", {
      attrs: { placeholder: "Search items", value: ed.search, "data-focus": "ge-search", disabled: !g },
      on: {
        input: (e) => {
          ed.search = e.target.value;
          clearTimeout(searchTimer);
          searchTimer = setTimeout(runSearch, SEARCH_DELAY_MS);
        },
      },
    });
    const rows = ed.results.rows.map((r) => {
      const on = ed.checked.has(r.id);
      return el(
        "button",
        {
          class: "pop-row ge-result",
          attrs: { role: "menuitemcheckbox", "aria-checked": on ? "true" : "false" },
          on: {
            click: () => {
              if (on) ed.checked.delete(r.id);
              else ed.checked.add(r.id);
              draw();
            },
          },
        },
        el("span", { class: "check", attrs: { "aria-checked": on ? "true" : "false" } }, on ? icon("check", 12) : null),
        el("span", { class: "name", text: r.name }),
        coin(r.price),
      );
    });
    const n = ed.checked.size;
    return el(
      "div",
      { class: "ge-pane ge-add" },
      el("span", { class: "label", text: "Add items" }),
      el("label", { class: "input" }, icon("search", 16), search),
      el("span", { class: "label", text: ed.results.note }),
      el("div", { class: "ge-results" }, rows),
      el(
        "button",
        {
          class: "btn",
          attrs: { disabled: !n },
          on: {
            click: () => {
              addIds([...ed.checked]);
              ed.checked.clear();
              loadMembers();
            },
          },
        },
        icon("plus", 14),
        `Add ${n} selected`,
      ),
    );
  }

  function draw() {
    const focused = document.activeElement?.dataset?.focus;
    const caret = document.activeElement?.selectionStart;
    replace(
      dialog,
      el(
        "div",
        { class: "ge-head" },
        el("h3", { class: "h2", text: "Edit item groups" }),
        el("button", { class: "btn ghost", attrs: { "aria-label": "Close" }, on: { click: close } }, icon("x", 14)),
      ),
      el("div", { class: "ge-body" }, groupsPane(), membersPane(), addPane()),
      el(
        "div",
        { class: "ge-foot" },
        ed.error ? el("span", { class: "ge-error", text: ed.error }) : el("span"),
        el("span", { class: "ge-buttons" }, el("button", { class: "btn ghost", text: "Cancel", on: { click: close } }), el("button", { class: "btn primary", text: ed.saving ? "Saving…" : "Save groups", attrs: { disabled: ed.saving }, on: { click: save } })),
      ),
    );
    if (focused) {
      const node = dialog.querySelector(`[data-focus="${focused}"]`);
      if (node) {
        node.focus();
        if (caret != null) node.setSelectionRange(caret, caret);
      }
    }
  }

  draw();
  loadMembers();
  return { close };
}
