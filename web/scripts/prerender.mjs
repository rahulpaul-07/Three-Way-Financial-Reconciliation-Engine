// Writes the server-rendered page into dist/index.html, then removes the
// server bundle, which is a build intermediate and must not be deployed.
//
// Runs after `vite build` (the client) and `vite build --ssr` (the renderer);
// see the "build" script in package.json.
import { readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const web = fileURLToPath(new URL("..", import.meta.url));
const indexPath = `${web}dist/index.html`;
const ssrDir = `${web}dist-ssr`;

const { render } = await import(pathToFileURL(`${ssrDir}/entry-server.js`).href);
const html = render();

const EMPTY_ROOT = '<div id="root"></div>';
const template = await readFile(indexPath, "utf8");
if (!template.includes(EMPTY_ROOT)) {
  throw new Error(`prerender: ${EMPTY_ROOT} not found in dist/index.html`);
}
if (!html.includes("<h1")) {
  throw new Error("prerender: the rendered page has no heading; refusing to write it");
}

await writeFile(indexPath, template.replace(EMPTY_ROOT, `<div id="root">${html}</div>`));
await rm(ssrDir, { recursive: true, force: true });
console.log(`prerender: wrote ${(html.length / 1024).toFixed(1)} kB of markup into dist/index.html`);
