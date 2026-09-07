#!/usr/bin/env node
/**
 * Route naming check (warn-only).
 *
 * Borrowed from multica's naming convention: new top-level routes should
 * be single words or `/{noun}/{verb}` — NOT hyphenated phrases that mask
 * missing noun/verb decomposition.
 *
 * Usage: node scripts/check-route-naming.mjs
 * Exits 0 always (warning-only). Prints violations to stderr.
 */
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const WEB_SRC = path.join(__dirname, "..", "web", "src");
const ROUTE_SOURCES = [
  path.join(WEB_SRC, "App.tsx"),
  path.join(WEB_SRC, "routes", "v2", "webDefaultBusinessRouteElementsV2.tsx"),
  path.join(WEB_SRC, "routes", "v2", "webProjectRouteElementsV2.tsx"),
  path.join(WEB_SRC, "routes", "v2", "webTenantGenericRouteElementsV2.tsx"),
  path.join(WEB_SRC, "routes", "v2", "webTenantScopedRouteElementsV2.tsx"),
];

// Top-level routes that were already in use when this rule was introduced.
// These are grandfathered in; DO NOT add to this list without a design
// discussion. New hyphenated top-level paths will be flagged.
const ALLOWLIST = new Set([
  "/force-change-password",
  "agent-workspace",
  "agent-workspace/:conversation",
  "agent-definitions",
  "agent-bindings",
  "mcp-servers",
]);

function main() {
  const missing = ROUTE_SOURCES.filter(
    (sourcePath) => !fs.existsSync(sourcePath),
  );
  if (missing.length > 0) {
    for (const sourcePath of missing)
      console.error(`[check-route-naming] ${sourcePath} not found`);
    return;
  }
  const source = ROUTE_SOURCES.map((sourcePath) =>
    fs.readFileSync(sourcePath, "utf8"),
  ).join("\n");
  const regex = /path=["']([^"']+)["']/g;
  const violations = [];
  let m;
  while ((m = regex.exec(source)) !== null) {
    const value = m[1];
    // Strip leading slash and param segments.
    const firstSegment = value.replace(/^\/+/, "").split("/")[0];
    if (!firstSegment) continue;
    if (!firstSegment.includes("-")) continue;
    if (ALLOWLIST.has(value) || ALLOWLIST.has(firstSegment)) continue;

    violations.push(value);
  }

  if (violations.length === 0) {
    console.log("[check-route-naming] No new hyphenated top-level routes.");
    return;
  }
  console.warn(
    "[check-route-naming] WARNING: hyphenated top-level routes detected.",
  );
  console.warn(
    "  Prefer `/{noun}/{verb}` or a single word. Add to ALLOWLIST only",
  );
  console.warn("  when there is no reasonable decomposition.");
  for (const v of violations) console.warn(`  - ${v}`);
}

main();
