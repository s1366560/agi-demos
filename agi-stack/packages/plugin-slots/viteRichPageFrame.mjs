import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const framePath = "memstack-package-frame.html";
const bootstrap = readFileSync(
  new URL("./src/richPageFrame.js", import.meta.url),
  "utf8",
);
const hash = createHash("sha256").update(bootstrap).digest("base64");
const policy =
  "default-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; " +
  "connect-src 'none'; object-src 'none'; worker-src 'none'; img-src data:; font-src data:; " +
  "style-src 'unsafe-inline' data:; script-src 'sha256-" +
  hash +
  "' data:";
const html =
  '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' +
  policy +
  '"><style>html,body,iframe{height:100%;width:100%;border:0;margin:0;display:block}</style>' +
  "</head><body><script>" +
  bootstrap +
  "</script></body></html>";

export function richPageFramePlugin() {
  return {
    name: "memstack-package-frame",
    configureServer(server) {
      server.middlewares.use("/" + framePath, (_request, response) => {
        response.writeHead(200, {
          "Content-Type": "text/html; charset=utf-8",
          "X-Frame-Options": "SAMEORIGIN",
          "Cache-Control": "no-store",
        });
        response.end(html);
      });
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: framePath, source: html });
    },
  };
}
