import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ClientBoqApp from "./client_boq/App";
import "./index.css";

// Two products, one build. Procurement (Atlas) is the default; client_boq — the tender-review
// product, with its own app bar, palette and full-viewport chrome — lives behind #/tender.
//
// A hash rather than a router: this app has never needed routing, and one branch does not justify
// the dependency. If a third surface appears, that is the moment to reach for react-router.
function Root() {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash.startsWith("#/tender") ? <ClientBoqApp /> : <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
