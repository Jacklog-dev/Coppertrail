import { call } from "./api.js";

const state = await call("state");
document.getElementById("app").textContent = "Coppertrail · " + state.items.sub;
