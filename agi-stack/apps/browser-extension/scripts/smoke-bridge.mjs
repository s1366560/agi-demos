// Live smoke test for the MemStack browser bridge (M1).
//
// Spawns the real sidecar (debug build), enables the bridge, installs the
// native messaging manifest, launches a Playwright Chromium instance with the
// built extension loaded (branded Chrome blocks --load-extension), then
// asserts: broker connects, and the 4 browser tools appear in /mcp/tools/list.
// Cleans up everything it touched.
//
// Usage: pnpm test:bridge   (from apps/browser-extension; build the extension
// and the sidecar first: pnpm build && cargo build -p agistack-desktop-sidecar)
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { randomBytes } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const EXT_DIR = resolve(here, '../.output/chrome-mv3');
const extensionManifest = JSON.parse(readFileSync(join(EXT_DIR, 'manifest.json'), 'utf8'));
const SIDECAR =
  process.env.AGISTACK_SIDECAR_PATH ??
  resolve(here, '../../../target/debug/agistack-desktop-sidecar');

const scratch = mkdtempSync(join(tmpdir(), 'memstack-bridge-smoke-'));
const profileDir = join(scratch, 'profile');
const profileHosts = join(profileDir, 'NativeMessagingHosts');
const expectedManifestPath = join(profileHosts, 'com.memstack.browserbridge.json');
let context = null;
let sidecar = null;
let failed = false;

const log = (...a) => console.log('[smoke]', ...a);
const fail = (msg) => {
  failed = true;
  console.error('[smoke] FAIL:', msg);
};

// Minimal fixture page server: a button that records clicks on window.__smokeClicks.
async function startFixtureServer() {
  const { createServer } = await import('node:http');
  const html = `<!doctype html><html><body style="margin:40px">
    <button id="smoke-button" style="font-size:20px;padding:12px 24px">Smoke</button>
    <script>window.__smokeClicks = 0;
      document.getElementById('smoke-button').addEventListener('click', () => {
        window.__smokeClicks += 1;
        document.getElementById('smoke-button').textContent = 'clicked';
      });</script>
    </body></html>`;
  const server = createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(html);
  });
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));
  const { port } = server.address();
  return {
    url: `http://127.0.0.1:${port}/fixture.html`,
    close: () => server.close(),
  };
}

async function cleanup() {
  try {
    await context?.close();
  } catch {}
  if (sidecar) {
    try {
      sidecar.stdin.write(
        JSON.stringify({
          type: 'request',
          id: 'uninstall',
          command: 'browser_bridge_uninstall',
        }) + '\n',
      );
      await new Promise((r) => setTimeout(r, 1500));
      sidecar.stdin.end();
    } catch {}
    try {
      sidecar.kill('SIGKILL');
    } catch {}
  }
  try {
    rmSync(scratch, { recursive: true, force: true });
  } catch {}
}

setTimeout(async () => {
  fail('hard watchdog 120s');
  await cleanup();
  process.exit(1);
}, 120_000);

async function main() {
  mkdirSync(profileHosts, { recursive: true });
  sidecar = spawn(SIDECAR, [], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      AGISTACK_BROWSER_BRIDGE_MANIFEST_DIR: profileHosts,
    },
  });
  createInterface({ input: sidecar.stderr }).on('line', (l) => {
    if (/error|warn/i.test(l)) console.log('[sidecar]', l.slice(0, 300));
  });
  const rl = createInterface({ input: sidecar.stdout });
  const pending = new Map();
  let nextId = 1;
  let ready = null;
  rl.on('line', (line) => {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return;
    }
    if (msg.type === 'ready') {
      ready = msg;
      return;
    }
    if (msg.type === 'response' && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  });
  const request = (command, args) => {
    const id = `req-${nextId++}`;
    return new Promise((resolveReq, reject) => {
      const timer = setTimeout(() => reject(new Error(`timeout waiting for ${command}`)), 20_000);
      pending.set(id, (msg) => {
        clearTimeout(timer);
        resolveReq(msg);
      });
      sidecar.stdin.write(JSON.stringify({ type: 'request', id, command, args }) + '\n');
    });
  };
  const b64url = () => randomBytes(32).toString('base64url');
  sidecar.stdin.write(
    JSON.stringify({
      type: 'initialize',
      protocolVersion: 1,
      nonce: b64url(),
      secret: b64url(),
      dataDirectory: join(scratch, 'data'),
      workspaceRoot: scratch,
      legacyDataDirectories: [],
    }) + '\n',
  );

  for (let i = 0; i < 100 && !ready; i++) await new Promise((r) => setTimeout(r, 100));
  if (!ready) return fail('sidecar did not become ready');
  log('sidecar ready at', ready.apiBaseUrl);

  const cfg = await request('local_runtime_configure', {
    config: { workspace_root: scratch, browser_bridge: { enabled: true } },
  });
  if (!cfg.ok) return fail('configure failed: ' + JSON.stringify(cfg.error));
  log('bridge enabled');

  const inst = await request('browser_bridge_install');
  if (!inst.ok) return fail('install failed: ' + JSON.stringify(inst.error));
  if (
    inst.result.installed.length !== 1 ||
    resolve(inst.result.installed[0].manifestPath) !== resolve(expectedManifestPath)
  ) {
    return fail(`install escaped isolated profile: ${JSON.stringify(inst.result.installed)}`);
  }
  log('manifest installed:', inst.result.installed.map((i) => i.browser).join(', '));

  // Branded Chrome blocks --load-extension; Playwright's Chromium allows it.
  // Extensions require headed mode. The sidecar writes directly into this
  // disposable profile's NativeMessagingHosts directory and nowhere else.
  context = await chromium.launchPersistentContext(profileDir, {
    headless: false,
    args: [`--disable-extensions-except=${EXT_DIR}`, `--load-extension=${EXT_DIR}`],
  });
  await context.newPage();
  log('chromium launched with extension, waiting for broker…');

  for (let i = 0; i < 10; i++) {
    const sws = context.serviceWorkers();
    log('service workers:', JSON.stringify(sws.map((s) => s.url())));
    if (sws.some((s) => s.url().startsWith('chrome-extension://'))) break;
    await new Promise((r) => setTimeout(r, 1000));
  }

  let connected = false;
  let connectedStatus = null;
  for (let i = 0; i < 45 && !connected; i++) {
    const t0 = performance.now();
    try {
      const st = await request('browser_bridge_status');
      log(
        `poll ${i}: ${(performance.now() - t0).toFixed(0)}ms brokerConnected=${st.result?.brokerConnected}`,
      );
      if (st.ok && st.result.brokerConnected) {
        connected = true;
        connectedStatus = st.result;
      }
    } catch (e) {
      log(`poll ${i}: ${(performance.now() - t0).toFixed(0)}ms ERROR ${e.message}`);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  if (!connected) return fail('broker never connected (45s)');
  log('broker connected ✔');
  if (connectedStatus.extensionId !== 'enbljdpbhdllbbkcjhccmbgpkfmcdkkl') {
    return fail(`unexpected extension identity ${connectedStatus.extensionId}`);
  }
  if (connectedStatus.extensionVersion !== extensionManifest.version) {
    return fail(
      `extension version ${connectedStatus.extensionVersion}, expected ${extensionManifest.version}`,
    );
  }
  if (
    connectedStatus.protocolMin !== 1 ||
    connectedStatus.protocolMax !== 2 ||
    typeof connectedStatus.hostVersion !== 'string' ||
    connectedStatus.hostVersion.length === 0
  ) {
    return fail(`invalid host protocol status ${JSON.stringify(connectedStatus)}`);
  }
  const qaRegistration = connectedStatus.manifests?.find(
    (manifest) => manifest.browser === 'QA Chromium',
  );
  if (
    qaRegistration?.state !== 'valid' ||
    qaRegistration.reasonCode !== 'registration_valid' ||
    qaRegistration.registrationLocation !== expectedManifestPath ||
    !qaRegistration.allowedActions?.includes('uninstall') ||
    !/^[a-f0-9]{64}$/u.test(qaRegistration.brokerDigest ?? '')
  ) {
    return fail(`invalid registration status ${JSON.stringify(qaRegistration)}`);
  }
  log('version/protocol/registration status contract ✔');

  // M3: the broker must prefer the unix socket transport (0600, 0700 dir).
  {
    const { homedir } = await import('node:os');
    const { statSync } = await import('node:fs');
    const sock = join(homedir(), '.memstack/browser-bridge/bridge.sock');
    try {
      const st = statSync(sock);
      const mode = (st.mode & 0o777).toString(8);
      log(`bridge socket present, mode ${mode}`);
      if (mode !== '600') return fail(`bridge.sock mode ${mode}, expected 600`);
    } catch {
      log('bridge socket absent — broker is on TCP fallback (acceptable on Windows only)');
    }
  }

  // /mcp/tools/list sits behind require_user_session: mint a local session
  // first (empty body), then present both the launch capability and the
  // session credential like the renderer does.
  const sessionRes = await fetch(`${ready.apiBaseUrl}/api/v1/auth/local-session`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-agistack-launch': ready.apiToken,
    },
    body: '{}',
  });
  const sessionBody = await sessionRes.text();
  const credential = sessionBody.match(/local-session-[0-9a-f-]+\.[A-Za-z0-9_-]+/)?.[0];
  if (!credential)
    return fail(
      `local session mint failed: HTTP ${sessionRes.status} ${sessionBody.slice(0, 200)}`,
    );

  const res = await fetch(`${ready.apiBaseUrl}/mcp/tools/list`, {
    headers: {
      Authorization: `Bearer ${credential}`,
      'x-agistack-launch': ready.apiToken,
    },
  });
  if (res.status !== 200) return fail(`tools/list HTTP ${res.status}`);
  const body = await res.json();
  const names = (body.tools ?? []).map((t) => t.name);
  const browserTools = names.filter((n) => n.startsWith('browser_'));
  log('browser tools visible:', JSON.stringify(browserTools));
  if (browserTools.length !== 13)
    return fail(`expected 13 browser tools (4 read + 9 mutating), got ${browserTools.length}`);

  // ── M2: exercise the new bridge methods against the real extension ──
  const fixture = await startFixtureServer();
  try {
    const dev = (method, params) => request('browser_bridge_dev_call', { method, params });

    const group = await dev('ensureTabGroup', {
      key: 'smoke-run',
      title: 'MemStack Smoke',
    });
    if (!group.ok) return fail('ensureTabGroup: ' + JSON.stringify(group.error));
    const groupId = group.result.groupId;
    log('tab group created:', groupId);

    const created = await dev('createTab', { url: fixture.url });
    if (!created.ok) return fail('createTab: ' + JSON.stringify(created.error));
    const tabId = created.result.tabId;
    log('tab created:', tabId);

    const assigned = await dev('assignTab', { tabId, groupId });
    if (!assigned.ok) return fail('assignTab: ' + JSON.stringify(assigned.error));

    const focused = await dev('focusTab', { tabId });
    if (!focused.ok) return fail('focusTab: ' + JSON.stringify(focused.error));

    // find the Playwright-side page for the new tab
    let page = null;
    for (let i = 0; i < 20 && !page; i++) {
      page = context.pages().find((p) => p.url().startsWith(fixture.url));
      if (!page) await new Promise((r) => setTimeout(r, 500));
    }
    if (!page) return fail('playwright cannot see the agent tab');
    await page.waitForSelector('#smoke-button', { timeout: 10_000 });

    // virtual cursor: moveMouse must resolve (arrival handshake or breaker)
    // and the overlay must be present in the page.
    const moved = await dev('moveMouse', { tabId, x: 120, y: 120 });
    if (!moved.ok) return fail('moveMouse: ' + JSON.stringify(moved.error));
    const hasOverlay = await page.evaluate(
      () => !!document.querySelector('[data-memstack-agent-cursor]'),
    );
    if (!hasOverlay) return fail('cursor overlay not found in page after moveMouse');
    log('virtual cursor overlay ✔');

    // CDP input passthrough: click the fixture button via Input.dispatchMouseEvent
    const box = await page.locator('#smoke-button').boundingBox();
    const cx = Math.round(box.x + box.width / 2);
    const cy = Math.round(box.y + box.height / 2);
    for (const type of ['mousePressed', 'mouseReleased']) {
      const step = await dev('executeCdp', {
        tabId,
        method: 'Input.dispatchMouseEvent',
        params: { type, x: cx, y: cy, button: 'left', clickCount: 1 },
      });
      if (!step.ok) return fail(`dispatchMouseEvent ${type}: ` + JSON.stringify(step.error));
    }
    await page.waitForFunction(() => window.__smokeClicks === 1, null, {
      timeout: 5000,
    });
    log('CDP input click ✔');

    // turnEnded: unmarked agent tab must be closed
    const ended = await dev('turnEnded', {
      leases: [{ tabId, origin: 'agent' }],
    });
    if (!ended.ok) return fail('turnEnded: ' + JSON.stringify(ended.error));
    if (ended.result.closed !== 1) return fail('turnEnded closed=' + ended.result.closed);
    const stillThere = context.pages().some((p) => p.url().startsWith(fixture.url));
    if (stillThere) return fail('agent tab survived turnEnded');
    log('turnEnded cleanup ✔');
  } finally {
    fixture.close();
  }

  log('PASS: transport chain + tool gating + M2 bridge methods verified end to end');
}

try {
  await main();
} catch (e) {
  fail(e?.message ?? String(e));
}
await cleanup();
process.exit(failed ? 1 : 0);
