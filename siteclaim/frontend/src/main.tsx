import React from "react";
import ReactDOM from "react-dom/client";
import ClientBoqApp from "./client_boq/App";
import "./index.css";

// One shell. The tender desk is the app now — it is where a tender arrives, where it is split,
// reviewed, routed, sourced, levelled and priced, and where the reference data behind all of that
// (subcontractors, benchmarks, projects) is kept.
//
// This used to branch on `location.hash`: `#/tender` rendered the desk, anything else rendered the
// procurement wizard (`./App`). Two products in one build meant two palettes, two app bars, two
// navigation models and one seam down the middle that a user could fall through — the wizard's
// five steps and the desk's tabs were the SAME work, reached two ways, with no shared idea of
// which tender you were looking at. The desk now covers both, so the fork has nothing left to
// choose between and is gone.
//
// Nothing was deleted. `./App` and everything below it stays on disk and stays inside
// `tsconfig.json`'s `include`, so it is still type-checked on every build and cannot rot silently.
// It is simply no longer imported: vite starts at this file, so the procurement subtree is now
// outside the bundle. The hash still routes — inside the desk (`nav/routes.ts`) — it just no
// longer selects a product.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ClientBoqApp />
  </React.StrictMode>,
);
