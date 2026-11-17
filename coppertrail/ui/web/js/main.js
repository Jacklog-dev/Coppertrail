// App entry: holds the state from the bridge and renders the frame from it.
// The view area shows one of the HANDOVER 8b states when it applies, else the view:
// loading > pull failed > no data yet > (stale banner +) filter matches nothing | view.
import { call, inApp, on } from "./api.js";
import { replace } from "./dom.js";
import { preload } from "./icons.js";
import * as navrail from "./navrail.js";
import * as states from "./states.js";
import * as statusstrip from "./statusstrip.js";
import * as views from "./views.js";
import * as filterbar from "./filterbar.js";

const $ = (id) => document.getElementById(id);
const ui = {
  view: "overview",
  pulling: false,
  error: null, // {message, detail} for the status strip
  failure: null, // pull failure payload from the bridge: shows the "Pull failed" state
  showLog: false,
  loading: null, // text while the bridge reads a data folder
  dismissed: null, // lastPoint of the stale banner the user closed
};
let state = null;

export function render(next = state) {
  state = next;
  navrail.render($("navrail"), { current: ui.view, onSelect: selectView, onDataFolder: chooseDataFolder });
  if (state) filterbar.render($("filterbar"), state, render);
  renderView();
  statusstrip.render($("statusstrip"), state, { pulling: ui.pulling, error: ui.error, onPull: pull, onCredit: openCredit });
}

function renderView() {
  const view = $("view");
  if (ui.loading || !state) {
    replace(view, states.loading({ text: ui.loading ?? "Reading the data folder…" }));
    return;
  }
  const st = state.status;
  if (ui.failure) {
    replace(view, states.pullFailed(ui.failure, { showLog: ui.showLog, canPull: st.canPull && !ui.pulling, onRetry: pull, onToggleLog: toggleLog }));
    return;
  }
  if (st.empty) {
    replace(view, states.noData({ dataDir: state.dataDir, status: st, pulling: ui.pulling, onSetDir: setDataDir, onChange: chooseDataFolder, onPull: pull }));
    return;
  }
  const banner =
    st.banner && ui.dismissed !== st.lastPoint
      ? states.staleBanner({ banner: st.banner, status: st, pulling: ui.pulling, onPull: pull, onDismiss: dismissBanner })
      : null;
  if (state.noMatch) {
    replace(view, banner, states.noMatch(state.noMatch, { onClear: (partial) => filterChange(partial), onReset: () => filterChange(null) }));
    return;
  }
  views.render(view, state, ui.view, banner);
}

function selectView(id) {
  ui.view = id;
  ui.failure = null; // picking a view leaves the "Pull failed" state
  render();
}

function toggleLog() {
  ui.showLog = !ui.showLog;
  render();
}

function dismissBanner() {
  ui.dismissed = state.status.lastPoint;
  render();
}

async function filterChange(partial) {
  render(await (partial ? call("set_filters", partial) : call("reset_filters")));
}

/** Runs a bridge call that re-reads the data folder, with the loading state meanwhile. */
async function withLoading(text, work) {
  ui.loading = text;
  render();
  try {
    const next = await work();
    ui.loading = null;
    ui.failure = null;
    render(next ?? state);
  } catch (err) {
    ui.loading = null;
    ui.error = { message: "Could not open that folder", detail: String(err) };
    render();
  }
}

function setDataDir(path) {
  return withLoading("Reading the data folder…", () => call("set_data_dir", path));
}

async function chooseDataFolder() {
  if (await inApp()) {
    // The native folder dialog blocks; the loading state shows once a folder is chosen.
    return withLoading("Reading the data folder…", () => call("pick_data_folder"));
  }
  const path = window.prompt("Data folder (dev mode)", state?.dataDir ?? "");
  if (path) return setDataDir(path);
}

function finishPull(result) {
  ui.pulling = false;
  ui.error = result.ok ? null : { message: result.message, detail: result.detail };
  ui.failure = result.ok ? null : (result.failure ?? null);
  ui.showLog = false;
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

await preload("overview", "item", "patterns", "movers", "folder", "download", "external", "refresh", "clock", "sliders");
render(); // loading state until the bridge answers
render(await call("state"));
