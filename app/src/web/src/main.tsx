import React from "react";
import ReactDOM from "react-dom/client";
import { initAuth } from "./auth";
import { loadBrands } from "./brand";
import "./styles.css";

// The brand manifest must be in place before App (and the dashboard snapshot
// it imports) is evaluated, so App is imported only once brands are loaded.
Promise.all([
  initAuth().catch((e) => console.error("auth init failed", e)),
  loadBrands(),
])
  .then(() => import("./App"))
  .then(({ default: App }) => {
    ReactDOM.createRoot(document.getElementById("root")!).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    );
  })
  .catch((e) => console.error("app failed to start", e));
