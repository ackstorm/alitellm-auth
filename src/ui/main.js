// main.js — SPA render entry. Mounts the App shell into #app.
//
// (Replaces the Plan 09-01 placeholder.) The App component drives the five
// shell states off the live GET /api/session/me via apiFetch + resolveState
// (see app.js / state.js / api.js).
import { App, render, injectShellStyles } from "./app.js";
import { h } from "preact";
import htm from "htm";

const html = htm.bind(h);

injectShellStyles();
render(html`<${App} />`, document.getElementById("app"));
