// The four views: Market overview, Item detail, Patterns and Movers & outliers.
import * as itemdetail from "./itemdetail.js";
import * as movers from "./movers.js";
import { VIEWS } from "./navrail.js";
import * as overview from "./overview.js";
import * as patterns from "./patterns.js";

/**
 * render(container, state, viewId, banner?, nav) — `banner` (the stale-data notice) goes on
 * top; `nav` lets a view switch views or pick an item (main.js).
 */
export function render(container, state, viewId, banner = null, nav = null) {
  const view = VIEWS.find((v) => v.id === viewId) ?? VIEWS[0];
  if (view.id === "overview") return overview.render(container, state, banner, nav);
  if (view.id === "item") return itemdetail.render(container, state, banner, nav);
  if (view.id === "patterns") return patterns.render(container, state, banner, nav);
  return movers.render(container, state, banner, nav);
}
