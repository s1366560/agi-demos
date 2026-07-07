import { createServer } from "node:http";
import { createReadStream, existsSync } from "node:fs";
import { mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { once } from "node:events";
import net from "node:net";

const ROOT = fileURLToPath(new URL(".", import.meta.url));
const PKG_WEB_DIR = join(ROOT, "pkg-web");
const WASM_FILE = join(PKG_WEB_DIR, "agistack_bindings_wasm_bg.wasm");

async function main() {
  if (!existsSync(WASM_FILE)) {
    throw new Error(
      "missing pkg-web WASM output; run `wasm-pack build crates/bindings-wasm --release --target web --out-dir pkg-web` first"
    );
  }
  if (typeof WebSocket !== "function") {
    throw new Error("Node.js WebSocket global is required for the Chrome CDP smoke");
  }

  const chrome = findChrome();
  if (!chrome) {
    console.log("BROWSER_SMOKE_SKIP Chrome executable not found");
    return;
  }

  const server = await startStaticServer();
  const devtoolsPort = await getFreePort();
  const userDataDir = await mkdtemp(join(tmpdir(), "agistack-browser-smoke-"));
  const chromeProc = spawnChrome(chrome, devtoolsPort, userDataDir);
  let client;

  try {
    await waitForChrome(devtoolsPort);
    const target = await createChromeTarget(
      devtoolsPort,
      `http://127.0.0.1:${server.port}/browser-smoke.html`
    );
    client = await CdpClient.connect(target.webSocketDebuggerUrl);
    await client.send("Runtime.enable");
    await client.send("Page.enable");
    await client.send("Network.enable");
    await waitForPageFunction(client, "runAgistackBrowserSmoke");

    const reload = await evaluateFunction(client, "runAgistackBrowserSmoke", {
      dbName: `agistack-browser-smoke-${Date.now()}`,
    });

    await client.send("Network.emulateNetworkConditions", {
      offline: true,
      latency: 0,
      downloadThroughput: 0,
      uploadThroughput: 0,
    });
    const offline = await evaluateFunction(client, "runAgistackOfflineSmoke", {
      dbName: `agistack-browser-smoke-offline-${Date.now()}`,
    });

    console.log(
      "BROWSER_SMOKE_OK",
      JSON.stringify({
        chrome: basename(chrome),
        reload,
        offline,
      })
    );
  } finally {
    client?.close();
    await stopChrome(chromeProc);
    await server.close();
    await removeWithRetry(userDataDir);
  }
}

function findChrome() {
  const candidates = [
    process.env.CHROME_BIN,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  return candidates.find((candidate) => existsSync(candidate)) ?? null;
}

function spawnChrome(chrome, devtoolsPort, userDataDir) {
  const args = [
    "--headless=new",
    "--disable-gpu",
    "--disable-background-networking",
    "--no-first-run",
    "--no-default-browser-check",
    "--no-sandbox",
    `--remote-debugging-address=127.0.0.1`,
    `--remote-debugging-port=${devtoolsPort}`,
    `--user-data-dir=${userDataDir}`,
    "about:blank",
  ];
  const proc = spawn(chrome, args, { stdio: ["ignore", "ignore", "pipe"] });
  proc.stderr.on("data", (chunk) => {
    const text = chunk.toString();
    if (text.includes("ERROR") || text.includes("FATAL")) {
      process.stderr.write(text);
    }
  });
  return proc;
}

async function waitForChrome(devtoolsPort) {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${devtoolsPort}/json/version`);
      if (response.ok) {
        return await response.json();
      }
    } catch {
      // Chrome is still starting.
    }
    await delay(100);
  }
  throw new Error("Chrome DevTools endpoint did not become ready");
}

async function createChromeTarget(devtoolsPort, url) {
  const response = await fetch(
    `http://127.0.0.1:${devtoolsPort}/json/new?${encodeURIComponent(url)}`,
    { method: "PUT" }
  );
  if (!response.ok) {
    throw new Error(`failed to create Chrome target: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function waitForPageFunction(client, functionName) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const result = await client.send("Runtime.evaluate", {
      expression: `typeof window.${functionName} === "function"`,
      returnByValue: true,
    });
    if (result.result?.value === true) {
      return;
    }
    await delay(100);
  }
  throw new Error(`browser smoke page did not expose ${functionName}`);
}

async function evaluateFunction(client, functionName, arg) {
  const expression = `window.${functionName}(${JSON.stringify(arg)})`;
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(
      result.exceptionDetails.exception?.description ??
        result.exceptionDetails.text ??
        `${functionName} failed`
    );
  }
  return result.result?.value;
}

class CdpClient {
  static async connect(webSocketUrl) {
    const ws = new WebSocket(webSocketUrl);
    await once(ws, "open");
    return new CdpClient(ws);
  }

  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    ws.addEventListener("message", (event) => this.onMessage(event));
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  onMessage(event) {
    const message = JSON.parse(event.data);
    if (!message.id || !this.pending.has(message.id)) {
      return;
    }
    const { resolve, reject } = this.pending.get(message.id);
    this.pending.delete(message.id);
    if (message.error) {
      reject(new Error(`${message.error.message}: ${message.error.data ?? ""}`));
    } else {
      resolve(message.result ?? {});
    }
  }

  close() {
    this.ws.close();
  }
}

async function startStaticServer() {
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? "/", "http://127.0.0.1");
      if (url.pathname === "/browser-smoke.html") {
        res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        res.end(browserSmokeHtml());
        return;
      }

      const filePath = safeResolve(url.pathname);
      const fileStat = await stat(filePath);
      if (!fileStat.isFile()) {
        res.writeHead(404);
        res.end("not found");
        return;
      }
      res.writeHead(200, { "content-type": contentType(filePath) });
      createReadStream(filePath).pipe(res);
    } catch (error) {
      res.writeHead(error.code === "ENOENT" ? 404 : 500);
      res.end(error.message);
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    port: server.address().port,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

function safeResolve(pathname) {
  const relative = decodeURIComponent(pathname).replace(/^\/+/, "");
  const resolved = resolve(ROOT, relative);
  if (resolved !== resolve(ROOT) && !resolved.startsWith(`${resolve(ROOT)}${sep}`)) {
    throw Object.assign(new Error("forbidden"), { code: "EACCES" });
  }
  return resolved;
}

function contentType(filePath) {
  switch (extname(filePath)) {
    case ".html":
      return "text/html; charset=utf-8";
    case ".js":
    case ".mjs":
      return "application/javascript; charset=utf-8";
    case ".wasm":
      return "application/wasm";
    case ".json":
      return "application/json; charset=utf-8";
    default:
      return "application/octet-stream";
  }
}

function browserSmokeHtml() {
  return String.raw`<!doctype html>
<meta charset="utf-8">
<title>agi-stack WASM browser smoke</title>
<body>loading</body>
<script type="module">
import init, { AgistackCore } from "./pkg-web/agistack_bindings_wasm.js";
import {
  createPersistentAgistackCore,
  openIndexedDbSnapshotStore,
} from "./pkg-web/web-persistence.mjs";

const wasmReady = init();

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

window.runAgistackBrowserSmoke = async ({ dbName }) => {
  await wasmReady;
  await deleteDatabase(dbName);

  const firstStore = openIndexedDbSnapshotStore({ dbName });
  const first = await createPersistentAgistackCore(AgistackCore, firstStore);
  assert(first.restored === false, "fresh browser store must not restore");
  await first.ingest(
    "browser-project",
    "browser-user",
    "Browser reload durable IndexedDB state"
  );
  const beforeReload = JSON.parse(await first.search("browser-project", "IndexedDB", 10)).length;
  assert(beforeReload === 1, "fresh browser core must search ingested content");

  const reloaded = await createPersistentAgistackCore(
    AgistackCore,
    openIndexedDbSnapshotStore({ dbName })
  );
  assert(reloaded.restored === true, "browser reload must restore IndexedDB snapshot");
  const afterReload = JSON.parse(await reloaded.search("browser-project", "IndexedDB", 10)).length;
  assert(afterReload === 1, "browser reload must preserve keyword search");
  const semantic = JSON.parse(
    await reloaded.semanticSearch("browser-project", "browser durable storage", 1)
  ).length;
  assert(semantic >= 1, "browser reload must rebuild semantic index");

  const upgradeDbName = dbName + "-upgrade";
  await deleteDatabase(upgradeDbName);
  const legacy = await openRawDatabase(upgradeDbName, 1, (db) => {
    db.createObjectStore("legacy");
  });
  legacy.close();
  const upgradeStore = openIndexedDbSnapshotStore({ dbName: upgradeDbName });
  await upgradeStore.save(first.exportSnapshot());
  const upgradedVersion = await databaseVersion(upgradeDbName);
  assert(upgradedVersion === 2, "missing snapshot store must trigger IndexedDB version upgrade");
  const upgraded = await createPersistentAgistackCore(
    AgistackCore,
    openIndexedDbSnapshotStore({ dbName: upgradeDbName })
  );
  assert(upgraded.restored === true, "upgraded browser store must restore snapshot");
  const afterUpgrade = JSON.parse(
    await upgraded.search("browser-project", "IndexedDB", 10)
  ).length;
  assert(afterUpgrade === 1, "upgraded browser store must preserve keyword search");

  return { beforeReload, afterReload, semantic, upgradedVersion, afterUpgrade };
};

window.runAgistackOfflineSmoke = async ({ dbName }) => {
  await wasmReady;
  assert(navigator.onLine === false, "CDP offline mode must be visible to the page");
  await deleteDatabase(dbName);
  const persistent = await createPersistentAgistackCore(
    AgistackCore,
    openIndexedDbSnapshotStore({ dbName })
  );
  await persistent.ingest(
    "offline-project",
    "browser-user",
    "Offline browser IndexedDB snapshot survives reload"
  );
  const reloaded = await createPersistentAgistackCore(
    AgistackCore,
    openIndexedDbSnapshotStore({ dbName })
  );
  assert(reloaded.restored === true, "offline browser store must restore snapshot");
  const offlineHits = JSON.parse(await reloaded.search("offline-project", "Offline", 10)).length;
  assert(offlineHits === 1, "offline browser store must preserve keyword search");
  return { navigatorOnline: navigator.onLine, restored: reloaded.restored, offlineHits };
};

async function deleteDatabase(name) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(name);
    request.onerror = () => reject(request.error ?? new Error("deleteDatabase failed"));
    request.onblocked = () => reject(new Error("deleteDatabase blocked"));
    request.onsuccess = () => resolve();
  });
}

async function openRawDatabase(name, version, onUpgrade) {
  return new Promise((resolve, reject) => {
    const request = version === undefined ? indexedDB.open(name) : indexedDB.open(name, version);
    request.onupgradeneeded = () => onUpgrade?.(request.result);
    request.onerror = () => reject(request.error ?? new Error("openRawDatabase failed"));
    request.onsuccess = () => resolve(request.result);
  });
}

async function databaseVersion(name) {
  const db = await openRawDatabase(name);
  const version = db.version;
  db.close();
  return version;
}

document.body.textContent = "ready";
</script>`;
}

async function getFreePort() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function stopChrome(proc) {
  if (proc.exitCode !== null || proc.signalCode !== null) {
    return;
  }
  proc.kill("SIGTERM");
  await Promise.race([once(proc, "exit"), delay(2_000)]);
  if (proc.exitCode === null && proc.signalCode === null) {
    proc.kill("SIGKILL");
    await Promise.race([once(proc, "exit"), delay(2_000)]);
  }
}

async function removeWithRetry(path) {
  let lastError;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      await rm(path, { recursive: true, force: true });
      return;
    } catch (error) {
      lastError = error;
      await delay(200);
    }
  }
  throw lastError;
}

main().catch((error) => {
  console.error("BROWSER_SMOKE_FAIL", error);
  process.exit(1);
});
