// App entry: holds the state from the bridge and renders the frame from it.
import { call, inApp, on } from "./api.js";
import { preload } from "./icons.js";
import * as navrail from "./navrail.js";
import * as statusstrip from "./statusstrip.js";
import * as views from "./views.js";
import * as filterbar from "./filterbar.js";

const $ = (id) => document.getElementById(id);
const ui = { view: "overview", pulling: false, error: null };
let state = null;

export function render(next = state) {
  state = next;
  navrail.render($("navrail"), { current: ui.view, onSelect: selectView, onDataFolder: chooseDataFolder });
  filterbar.render($("filterbar"), state, render);
  views.render($("view"), state, ui.view);
  statusstrip.render($("statusstrip"), state, { pulling: ui.pulling, error: ui.error, onPull: pull, onCredit: openCredit });
}

function selectView(id) {
  ui.view = id;
  render();
}

async function chooseDataFolder() {
  try {
    if (await inApp()) {
      render(await call("pick_data_folder"));
      return;
    }
    const path = window.prompt("Data folder (dev mode)", state.dataDir);
    if (path) render(await call("set_data_dir", path));
  } catch (err) {
    ui.error = { message: "Could not open that folder", detail: String(err) };
    render();
  }
}

function finishPull(result) {
  ui.pulling = false;
  ui.error = result.ok ? null : { message: result.message, detail: result.detail };
  render(result.state ?? state);
}

async function pull() {
  ui.pulling = true;
  ui.error = null;
  render();
  try {
    const result = await call("pull_latest");
    if ("started" in result) {
      if (!result.started) ui.pulling = false; // already running
      return; // the app reports with a "pull" event
    }
    finishPull({ ...result, state: result.ok ? await call("state") : state }); // dev server: synchronous
  } catch (err) {
    finishPull({ ok: false, message: "Pull failed", detail: String(err) });
  }
}
on("pull", finishPull);

async function openCredit(event) {
  event.preventDefault(); // synchronously, before any await, or the link opens as well
  if (await inApp()) call("open_credit"); // the system browser, never inside the app window
  else window.open(state.creditUrl, "_blank", "noopener");
}

await preload("overview", "item", "patterns", "movers", "folder", "download", "external");
render(await call("state"));
