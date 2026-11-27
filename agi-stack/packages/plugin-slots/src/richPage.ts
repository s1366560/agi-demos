import guestSource from "./richPageGuest.js?raw";

import type { SidebarBindings } from "./sidebar";

export type PageTarget = "web" | "desktop-renderer";
export type PageScope = Readonly<{
  tenantId: string;
  projectId: string | null;
}>;
export interface PackagePage {
  readonly query_params?: readonly string[];
  readonly sidebar?: SidebarBindings;
  readonly navigation_actions?: readonly ("primary-create" | "group-create")[];
  readonly anchored_slots?: Readonly<Record<string, string>>;
  readonly workbench?: boolean;
  readonly home?: boolean;
  readonly slots?: readonly string[];
  readonly contributes_to?: string;
  readonly id: string;
  readonly title: string;
  readonly routes: readonly string[];
  readonly targets: readonly PageTarget[];
}
interface Asset {
  readonly path: string;
  readonly digest: string;
  readonly bytes_base64: string;
}
export interface RichPage {
  readonly voice_authorization?: string;
  readonly anchored_slots?: Readonly<Record<string, string>>;
  readonly workbench?: boolean;
  readonly schema: "memstack.rich-page/1";
  readonly id: string;
  readonly title: string;
  readonly routes: readonly string[];
  readonly query_params?: readonly string[];
  readonly resources?: readonly Asset[];
  readonly page_links?: readonly string[];
  readonly navigation_routes?: readonly string[];
  readonly release_digest: string;
  readonly target: PageTarget;
  readonly commands: readonly string[];
  readonly device_tools: readonly string[];
  readonly entry: Asset;
  readonly style?: Asset | null;
}
export type DevicePageCall = (input: {
  pluginId: string;
  digest: string;
  tool: string;
  payload: Record<string, unknown>;
  signal: AbortSignal;
}) => Promise<unknown>;

async function verifiedBase64(asset: Asset) {
  if (
    !asset ||
    typeof asset.bytes_base64 !== "string" ||
    asset.bytes_base64.length > 16 * 1024 * 1024
  )
    throw new Error("page_asset_invalid");
  const binary = atob(asset.bytes_base64);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  const digest =
    "sha256:" +
    Array.from(hash, (value) => value.toString(16).padStart(2, "0")).join("");
  if (digest !== asset.digest) throw new Error("page_asset_digest_mismatch");
  // Re-encode to canonical base64 before embedding into a data URL.
  return btoa(binary);
}

function isStringList(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

export async function verifyPageDocument(
  page: RichPage,
  target: PageTarget,
  digest: string,
  id: string,
) {
  if (
    page.schema !== "memstack.rich-page/1" ||
    (page.workbench !== undefined && typeof page.workbench !== "boolean") ||
    page.id !== id ||
    page.target !== target ||
    page.release_digest !== digest ||
    !isStringList(page.commands) ||
    !isStringList(page.device_tools) ||
    !isStringList(page.routes) ||
    (page.resources !== undefined &&
      (!Array.isArray(page.resources) || page.resources.length > 64)) ||
    (page.query_params !== undefined && !isStringList(page.query_params)) ||
    (page.anchored_slots !== undefined && (!page.anchored_slots || typeof page.anchored_slots !== "object" ||
      Array.isArray(page.anchored_slots) || Object.entries(page.anchored_slots).length > 8 ||
      Object.entries(page.anchored_slots).some(([name, target]) =>
        !/^[a-z][a-z0-9-]{0,63}@[1-9][0-9]{0,3}$/.test(name) || typeof target !== "string" ||
        !/^[a-z][a-z0-9.-]{0,127}\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(target)))) ||
    (page.page_links !== undefined && !isStringList(page.page_links)) ||
    (page.navigation_routes !== undefined &&
      !isStringList(page.navigation_routes))
  )
    throw new Error("page_release_mismatch");
  const [entry, style] = await Promise.all([
    verifiedBase64(page.entry),
    page.style ? verifiedBase64(page.style) : null,
  ]);
  const css = style
    ? '<link rel="stylesheet" href="data:text/css;base64,' + style + '">'
    : "";
  const assets: Record<string, string> = Object.create(null);
  const media: Record<string, string> = {
    js: "application/javascript",
    css: "text/css",
    woff2: "font/woff2",
    woff: "font/woff",
    png: "image/png",
    webp: "image/webp",
    jpg: "image/jpeg",
  };
  for (const asset of page.resources ?? []) {
    if (!asset || typeof asset.path !== "string")
      throw new Error("page_resource_invalid");
    const extension = asset.path.split(".").pop() ?? "";
    const type = Object.hasOwn(media, extension) ? media[extension] : undefined;
    if (
      !type ||
      !/^[a-zA-Z0-9_./-]+$/.test(asset.path) ||
      asset.path
        .split("/")
        .some((part: string) => !part || part === "." || part === "..") ||
      Object.hasOwn(assets, asset.path)
    )
      throw new Error("page_resource_invalid");
    assets[asset.path] =
      "data:" + type + ";base64," + (await verifiedBase64(asset));
  }
  const resourceTable =
    '<script id="memstack-resources" type="application/json">' +
    JSON.stringify(assets) +
    "</script>";
  const workerPolicy = Object.keys(assets).some((path) =>
    path.endsWith(".worker.js"),
  )
    ? "data:"
    : "'none'";
  const contentSecurityPolicy = richPageContentSecurityPolicy(workerPolicy);
  const guest = btoa(guestSource);
  // The full Web layout inherits the original application typography below the shell.
  const workbenchTypography = target === "web" ? "#root{font-size:14px;line-height:22px}:where(h1,h2,h3,h4,h5,h6){font-size:inherit;line-height:inherit}" : "";
  const baseStyle = page.workbench
    ? "<style>html,body,#root{margin:0;width:100%;height:100%}html{font:16px/1.5 system-ui}*{box-sizing:border-box}" + workbenchTypography + "</style>"
    : "<style>html{font:16px/1.5 system-ui;color-scheme:light dark}body{margin:0;padding:1.25rem}main{max-width:72rem;margin:auto}form,label{display:grid;gap:.5rem}form{gap:1rem;margin-bottom:1rem}input,textarea,select,button{max-width:100%;box-sizing:border-box;font:inherit;padding:.45rem}button{cursor:pointer}fieldset{min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse}td,th{text-align:start;padding:.4rem .65rem}</style>";
  return (
    '<!doctype html><html><head><meta charset="utf-8">' +
    '<meta http-equiv="Content-Security-Policy" content="' +
    contentSecurityPolicy +
    '">' +
    baseStyle +
    css +
    resourceTable +
    '</head><body><main id="root"></main><script src="data:text/javascript;base64,' +
    guest +
    '"></script><script src="data:text/javascript;base64,' +
    entry +
    '"></script></body></html>'
  );
}

function segments(path: string) {
  if (
    !path.startsWith("/") ||
    /[?#\\\u0000-\u001f]/.test(path) ||
    path.startsWith("//")
  )
    return null;
  try {
    const parts = path
      .replace(/\/$/, "")
      .split("/")
      .slice(1)
      .map(decodeURIComponent);
    return parts.some((p) => !p || p === "." || p === ".." || /[/\\?#]/.test(p))
      ? null
      : parts;
  } catch {
    return null;
  }
}
/** Inner signed page. Network stays closed; fonts and images are package data URLs. */
export function richPageContentSecurityPolicy(workerPolicy: "data:" | "'none'"): string {
  return [
    "default-src 'none'",
    "connect-src 'none'",
    "font-src data:",
    "img-src data:",
    "style-src 'unsafe-inline' data:",
    "script-src data:",
    `worker-src ${workerPolicy}`,
    "frame-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join("; ");
}

function scopeParam(key: string, scope: PageScope) {
  if (key === "tenantId" || key === "tenant_id") return scope.tenantId;
  if (key === "projectId" || key === "project_id") return scope.projectId;
  return undefined;
}

export function routeRank(
  pattern: string,
  path: string,
  scope: PageScope,
): string | null {
  const template = segments(pattern),
    actual = segments(path);
  if (!template || !actual || template.length !== actual.length) return null;
  let rank = "";
  for (const [index, part] of template.entries()) {
    const value = actual[index];
    if (part.startsWith(":")) {
      const required = scopeParam(part.slice(1), scope);
      // A tenant page has no project binding. Its declared project route may name one.
      if (required != null && required !== value) return null;
      rank += "0";
    } else if (part === value) rank += "1";
    else return null;
  }
  return rank;
}

export function menuPath(pattern: string, scope: PageScope) {
  const template = segments(pattern);
  if (!template) return null;
  const parts = template.map((part) =>
    part.startsWith(":") ? scopeParam(part.slice(1), scope) : part,
  );
  return parts.some((part) => !part)
    ? null
    : "/" + parts.map((p) => encodeURIComponent(p!)).join("/");
}
