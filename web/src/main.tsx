import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import "@fontsource-variable/geist";
import "@fontsource/geist-mono/400.css";
import "./index.css";
import App from "./App";

const root = document.getElementById("root")!;
const app = (
  <StrictMode>
    <App />
  </StrictMode>
);

// The production build prerenders the page into #root (scripts/prerender.mjs),
// so the first paint does not wait for this bundle. The dev server does not.
if (root.hasChildNodes()) hydrateRoot(root, app);
else createRoot(root).render(app);
