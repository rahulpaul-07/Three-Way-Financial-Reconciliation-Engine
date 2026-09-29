import { StrictMode } from "react";
import { renderToString } from "react-dom/server";
import App from "./App";

/**
 * The page as it looks before any data has loaded: the opening text, the
 * section headings and the skeletons. Written into dist/index.html at build
 * time (scripts/prerender.mjs) so a visitor sees the page as soon as the HTML
 * and CSS arrive, instead of a blank screen until the bundle has run.
 * main.tsx then hydrates it. Nothing here may depend on the browser: the
 * hooks that fetch or measure do so in effects, which do not run on the server.
 */
export function render(): string {
  return renderToString(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
