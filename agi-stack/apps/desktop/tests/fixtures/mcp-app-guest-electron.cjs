const {
  app,
  BrowserWindow,
  ipcMain,
  nativeImage,
  desktopCapturer,
  systemPreferences,
} = require('electron');
const { createServer } = require('node:http');
const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const { dirname, join, resolve, extname } = require('node:path');
const { randomUUID } = require('node:crypto');
const assert = require('node:assert/strict');
const ts = require('typescript');

const desktop = resolve(__dirname, '../..');
const output = process.env.AGISTACK_MCP_APP_GUEST_TEST_OUTPUT;
if (!output) throw new Error('The test runner must supply its owned output directory');
mkdirSync(output, { recursive: true });
app.setPath('userData', join(output, 'profile'));
app.setName('MCP App Guest SDK Fixture');
const cache = new Map();
function load(path) {
  const filename = resolve(path);
  if (cache.has(filename)) return cache.get(filename);
  const module = { exports: {} };
  cache.set(filename, module.exports);
  const code = ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  new Function('exports', 'module', 'require', code)(module.exports, module, (name) =>
    name.startsWith('.') ? load(resolve(dirname(filename), `${name}.ts`)) : require(name),
  );
  return module.exports;
}
const { McpAppGuestHost } = load(join(desktop, 'electron/main/mcpAppGuestHost.ts'));
const { McpAppFrames } = load(join(desktop, 'electron/main/mcpAppFrames.ts'));
const { McpAppFrameHost } = load(join(desktop, 'electron/main/mcpAppFrameHost.ts'));
const { invokeMcpApp } = load(join(desktop, 'src/features/chat/mcpAppAutomation.ts'));
const { computeMcpAppGuestBounds } = load(join(desktop, 'src/features/chat/mcpAppGuestLayout.ts'));
const { MCP_APP_GUEST_CHANNEL, MCP_APP_GUEST_EVENT } = load(
  join(desktop, 'src/features/chat/mcpAppGuestProtocol.ts'),
);
const tabId = `mcpapp-${randomUUID()}`;
const slot = { x: 20, y: 110, width: 760, height: 430 };
const controls = { x: 520, y: 130, width: 260, height: 110 };
const report = {
  checks: [],
  errors: [],
  transportBoundary:
    'Actual invokeMcpApp and McpAppFrameHost; in-process test sidecar transport, not Rust authority acceptance',
};
const invocations = [];
let toolCount = 0;
let currentMount;
let host;
let manager;
let frameHost;
let server;
function check(name, result) {
  report.checks.push({ name, result });
  assert.ok(result, name);
}
async function waitFor(action, test, timeout = 10_000) {
  const until = Date.now() + timeout;
  let last;
  while (Date.now() < until) {
    try {
      last = await action();
      if (test(last)) return last;
    } catch (error) {
      last = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`fixture wait timed out: ${String(last)}`);
}
function countColor(image, red, green, blue, tolerance = 8) {
  const pixels = image.toBitmap();
  let count = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    if (
      Math.abs(pixels[i] - blue) <= tolerance &&
      Math.abs(pixels[i + 1] - green) <= tolerance &&
      Math.abs(pixels[i + 2] - red) <= tolerance
    )
      count++;
  }
  return count;
}
function appHtml() {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;min-height:100%;background:rgb(0,96,255);color:white;font:18px sans-serif}
    button{margin:20px;padding:16px;font:inherit}output,p{margin:20px}
    </style></head><body><p id="status">Connecting</p><button id="increment">Increment App</button>
    <button id="wait">Wait for host</button><output id="count">0</output><output id="receipt"></output><script>
    document.body.dataset.instance=crypto.randomUUID();let next=1;const pending=new Map();
    function rpc(method,params){const id=next++;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});parent.postMessage({jsonrpc:'2.0',id,method,params},'*')})}
    window.addEventListener('message',event=>{if(event.source!==parent)return;const message=event.data;
      if(message?.id!==undefined&&pending.has(message.id)){const request=pending.get(message.id);pending.delete(message.id);message.error?request.reject(new Error(message.error.message)):request.resolve(message.result)}});
    rpc('ui/initialize',{appInfo:{name:'SDK guest test',version:'1'},appCapabilities:{},protocolVersion:'2026-01-26'}).then(()=>{
      parent.postMessage({jsonrpc:'2.0',method:'ui/notifications/initialized',params:{}},'*');document.querySelector('#status').textContent='Connected';
    });
    document.querySelector('#increment').onclick=async()=>{try{const result=await rpc('tools/call',{name:'increment',arguments:{}});document.querySelector('#count').textContent=result.content[0].text;document.querySelector('#receipt').textContent='callback complete'}catch(error){document.querySelector('#receipt').textContent=error.message}};
    document.querySelector('#wait').onclick=async()=>{try{await rpc('tools/call',{name:'wait',arguments:{}})}catch(error){document.querySelector('#receipt').textContent=error.message}};
    </script></body></html>`;
}
function hostHtml() {
  return `<!doctype html><title>MCP App Guest SDK Fixture</title><style>
    html,body{margin:0;background:#202b3d;color:white;font:18px sans-serif}header{padding:20px}
    #controls{position:fixed;left:${controls.x}px;top:${controls.y}px;width:${controls.width}px;height:${controls.height}px;background:rgb(255,0,255);color:black;display:flex;align-items:center;justify-content:space-around}
    button{font:16px sans-serif;padding:12px}#dialog{position:fixed;inset:100px;background:white;color:black;z-index:9999;padding:40px}
    </style><header>Host private marker: HOST_ONLY_MARKER</header>
    <aside id="controls" data-native-view-occluder><button id="pause">Pause</button><button id="stop">Stop</button></aside>
    <script>${invokeMcpApp.toString()}
    window.actions=[];window.requests=[];window.callbackCount=0;window.waiting=[];const pendingCallbacks=new Map();
    for(const action of ['pause','stop'])document.querySelector('#'+action).onclick=()=>actions.push(action);
    fixture.subscribe(event=>{requests.push(event);if(event.kind==='cancel'){pendingCallbacks.get(event.requestId)?.abort();return}if(event.kind!=='request')return;
      const controller=new AbortController();pendingCallbacks.set(event.requestId,controller);
      if(event.method==='callTool'&&event.params.name==='wait')waiting.push(event);
      const result=event.method==='callTool'?invokeMcpApp({tabId:event.tabId,mountNonce:event.frameName,signal:controller.signal},'tools/call',event.params,controller.signal):Promise.resolve({});
      result.then(value=>{if(event.method==='callTool')callbackCount++;return fixture.respond({...event,ok:true,result:value})},error=>fixture.respond({...event,ok:false,error:error.message})).catch(()=>{}).finally(()=>pendingCallbacks.delete(event.requestId));
    });</script>`;
}

async function run() {
  await app.whenReady();
  const renderer = join(desktop, 'out/renderer');
  const proxy = resolve(
    desktop,
    '../../../src/infrastructure/adapters/primary/web/static/sandbox_proxy.html',
  );
  const preload = join(output, 'host-preload.cjs');
  writeFileSync(
    preload,
    `const {contextBridge,ipcRenderer}=require('electron');contextBridge.exposeInMainWorld('__MEMSTACK_DESKTOP__',{core:{invoke:(command,input)=>ipcRenderer.invoke('fixture-command',command,input)}});contextBridge.exposeInMainWorld('fixture',Object.freeze({subscribe(listener){const wrapped=(_event,value)=>listener(value);ipcRenderer.on(${JSON.stringify(MCP_APP_GUEST_EVENT)},wrapped);return()=>ipcRenderer.removeListener(${JSON.stringify(MCP_APP_GUEST_EVENT)},wrapped)},respond:input=>ipcRenderer.invoke('fixture-respond',input)}));`,
  );
  server = createServer((request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    response.setHeader('Cache-Control', 'no-store');
    if (path === '/host') {
      response.setHeader('Content-Type', 'text/html');
      response.end(hostHtml());
      return;
    }
    if (path === '/static/sandbox_proxy.html') {
      response.setHeader('Content-Type', 'text/html');
      response.end(readFileSync(proxy));
      return;
    }
    const file = resolve(renderer, `.${path}`);
    if (!file.startsWith(`${renderer}/`)) {
      response.writeHead(403);
      response.end();
      return;
    }
    try {
      response.setHeader(
        'Content-Type',
        { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' }[extname(file)] ||
          'application/octet-stream',
      );
      response.end(readFileSync(file));
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  host = new BrowserWindow({
    width: 820,
    height: 620,
    show: false,
    webPreferences: { preload, sandbox: true, contextIsolation: true, nodeIntegration: false },
  });
  const frames = new McpAppFrames((owner) => manager.ownsVisibleSurface(owner));
  frameHost = new McpAppFrameHost(
    frames,
    async (input) => {
      assert.equal(input.tabId, tabId);
      if (input.operation === 'attach') {
        if (currentMount && currentMount !== input.mountNonce)
          throw Error('fixture_mount_already_bound');
        currentMount = input.mountNonce;
      } else if (input.operation === 'detach' && currentMount === input.mountNonce)
        currentMount = undefined;
      return { tabId: input.tabId, pending: false };
    },
    async (input, signal) => {
      assert.equal(input.tabId, tabId);
      assert.equal(input.mountNonce, currentMount);
      assert.equal(input.operation, 'tools/call');
      invocations.push(structuredClone(input));
      if (input.arguments.name === 'wait') {
        return new Promise((_resolve, reject) => {
          const abort = () => {
            const error = new Error('fixture operation cancelled');
            error.cancellationConfirmed = true;
            reject(error);
          };
          if (signal.aborted) abort();
          else signal.addEventListener('abort', abort, { once: true });
        });
      }
      assert.equal(input.arguments.name, 'increment');
      return { content: [{ type: 'text', text: String(++toolCount) }] };
    },
  );
  manager = new McpAppGuestHost({
    getWindow: () => host,
    preload: join(desktop, 'out/preload/mcpAppGuest.cjs'),
    entryUrl: () => `${base}/mcp-app.html`,
    installProtocol() {},
    retireMount: (input) => frameHost.unregister(input),
  });
  ipcMain.handle(MCP_APP_GUEST_CHANNEL, (event, command, input) =>
    manager.receive(event, command, input),
  );
  ipcMain.handle('fixture-command', (event, command, input) => {
    if (event.sender !== host.webContents || event.senderFrame !== host.webContents.mainFrame)
      throw Error('fixture owner mismatch');
    if (command === 'mcp_app_operation_prepare') return frameHost.prepare(input);
    if (command === 'mcp_app_operation') return frameHost.operation(input);
    if (command === 'mcp_app_operation_cancel') return frameHost.cancel(input);
    throw Error('fixture command forbidden');
  });
  ipcMain.handle('fixture-respond', (event, input) => {
    if (event.sender !== host.webContents || event.senderFrame !== host.webContents.mainFrame)
      throw Error('fixture owner mismatch');
    return manager.respond(input);
  });
  await host.loadURL(`${base}/host`);
  host.showInactive();
  const config = {
    toolName: 'increment',
    html: appHtml(),
    sandbox: {
      url: `${base.replace('127.0.0.1', 'localhost')}/static/sandbox_proxy.html`,
      permissions: 'allow-scripts allow-same-origin allow-forms',
      csp: {
        frameDomains: ['https://example.invalid'],
        baseUriDomains: ['https://example.invalid'],
      },
    },
  };
  const bounds = computeMcpAppGuestBounds(slot, { x: 0, y: 0, width: 820, height: 580 }, [
    controls,
  ]);
  const activate = async () => {
    const identity = manager.open({
      key: 'owned-app',
      tabId,
      frameName: `mcpapp-${randomUUID()}`,
      config,
    });
    manager.layout({ ...identity, sequence: 1, bounds });
    await manager.start(identity);
    await waitFor(
      async () => {
        const result = await frameHost.register(manager.owner(identity), identity);
        manager.registered(identity);
        return result;
      },
      (result) => result.pending === false,
    );
    return identity;
  };
  let identity = await activate();
  const owner = manager.owner(identity);
  const dom = (expression) =>
    frames.execute({
      tabId,
      mountNonce: identity.frameName,
      operation: 'playwright.locator',
      expression,
    });
  const snapshot = () =>
    dom(
      '({instance:document.body.dataset.instance,count:Number(document.querySelector("#count").textContent),status:document.querySelector("#status").textContent})',
    );
  const first = await snapshot();
  check(
    'actual SDK App initializes inside the registered dedicated guest',
    first.status === 'Connected' && first.count === 0,
  );
  check(
    'guest has no desktop commands or Node ambient bridge',
    await owner.executeJavaScript(
      'typeof window.__MEMSTACK_DESKTOP__ === "undefined" && typeof require === "undefined" && typeof process === "undefined"',
    ),
  );
  check(
    'untrusted App has no guest preload bridge',
    await dom(
      'typeof window.__MEMSTACK_MCP_APP_GUEST__ === "undefined" && typeof window.__MEMSTACK_DESKTOP__ === "undefined"',
    ),
  );
  await owner.executeJavaScript(
    'new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))',
  );
  const initialImage = await owner.capturePage();
  writeFileSync(join(output, 'initial-guest.png'), initialImage.toPNG());
  // The public MCP App locator clicks within this exact registered frame too.
  await dom('document.querySelector("#increment").click()');
  await waitFor(snapshot, (value) => value.count === 1);
  check(
    'actual SDK callback crosses guest/main/root and exact scoped operation once',
    (await host.webContents.executeJavaScript('window.callbackCount')) === 1 &&
      invocations.length === 1 &&
      invocations[0].tabId === tabId &&
      invocations[0].mountNonce === identity.frameName &&
      toolCount === 1,
  );
  const capture = await frames.execute({
    tabId,
    mountNonce: identity.frameName,
    operation: 'tab.screenshot',
  });
  writeFileSync(join(output, 'guest-capture.png'), Buffer.from(capture.data, 'base64'));
  const pixels = nativeImage.createFromBuffer(Buffer.from(capture.data, 'base64'));
  report.capture = {
    width: capture.width,
    height: capture.height,
    bluePixels: countColor(pixels, 0, 96, 255),
    magentaPixels: countColor(pixels, 255, 0, 255),
  };
  check(
    'same visible guest capture contains App pixels and excludes host safety pixels',
    report.capture.bluePixels > 1000 && report.capture.magentaPixels === 0,
  );
  host.webContents.focus();
  for (const action of ['pause', 'stop']) {
    const button = await host.webContents.executeJavaScript(
      `(()=>{const r=document.querySelector('#${action}').getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`,
    );
    host.webContents.sendInputEvent({
      type: 'mouseDown',
      button: 'left',
      clickCount: 1,
      ...button,
    });
    host.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...button });
  }
  await waitFor(
    () => host.webContents.executeJavaScript('window.actions'),
    (values) => values.length === 2,
  );
  check(
    'native presentation keeps Pause and Stop visible and clickable',
    (await host.webContents.executeJavaScript('window.actions')).join(',') === 'pause,stop',
  );
  if (
    process.platform !== 'darwin' ||
    systemPreferences.getMediaAccessStatus('screen') === 'granted'
  ) {
    const sources = await desktopCapturer.getSources({
      types: ['window'],
      thumbnailSize: { width: 820, height: 620 },
    });
    const source = sources.find((candidate) => candidate.name === 'MCP App Guest SDK Fixture');
    check('actual native window thumbnail is available', Boolean(source));
    writeFileSync(join(output, 'guest-native-window.png'), source.thumbnail.toPNG());
    check(
      'native compositor shows safety controls and App together',
      countColor(source.thumbnail, 255, 0, 255, 64) > 100 &&
        countColor(source.thumbnail, 0, 96, 255, 64) > 1000,
    );
  }
  manager.layout({ ...identity, sequence: 2, bounds: null });
  await assert.rejects(
    frames.execute({ tabId, mountNonce: identity.frameName, operation: 'tab.screenshot' }),
    /capture_surface_unavailable/,
  );
  await host.webContents.executeJavaScript(
    `document.body.insertAdjacentHTML('beforeend','<div id="dialog" role="dialog" aria-modal="true"><button id="confirm">Confirm</button></div>');document.querySelector('#confirm').onclick=()=>{actions.push('dialog');document.querySelector('#dialog').remove()};undefined`,
  );
  const confirm = await host.webContents.executeJavaScript(
    `(()=>{const r=document.querySelector('#confirm').getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`,
  );
  host.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...confirm });
  host.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...confirm });
  await waitFor(
    () => host.webContents.executeJavaScript('window.actions'),
    (values) => values.includes('dialog'),
  );
  manager.layout({ ...identity, sequence: 3, bounds });
  check(
    'modal detach and restore preserve the same App state',
    (await snapshot()).instance === first.instance && (await snapshot()).count === 1,
  );
  const old = identity;
  manager.release(identity);
  identity = await activate();
  check(
    'fresh nonce reactivation retains the actual SDK document and owner',
    manager.owner(identity) === owner &&
      (await snapshot()).instance === first.instance &&
      (await snapshot()).count === 1,
  );
  await assert.rejects(
    frames.execute({ tabId, mountNonce: old.frameName, operation: 'tab.screenshot' }),
    /expired/,
  );
  check('old mount is rejected after same-instance reactivation', true);
  await dom('document.querySelector("#wait").click()');
  const waiting = await waitFor(
    () => host.webContents.executeJavaScript('window.waiting'),
    (values) => values.length === 1,
  );
  manager.release(identity);
  assert.throws(() => manager.respond({ ...waiting[0], ok: true, result: {} }), /expired/);
  await waitFor(
    () => Promise.resolve(currentMount),
    (value) => value === undefined,
  );
  check(
    'retirement cancels the scoped SDK operation and rejects its late root response',
    invocations.length === 2 && toolCount === 1,
  );
  manager.clear();
  await frameHost.clear();
  await waitFor(
    () => Promise.resolve(owner.isDestroyed()),
    (destroyed) => destroyed,
  );
  check('clear destroys retained guest and rejects old automation', owner.isDestroyed());
  await assert.rejects(
    frames.execute({ tabId, mountNonce: identity.frameName, operation: 'tab.screenshot' }),
    /unavailable|expired/,
  );
}

run()
  .then(
    () => {
      report.ok = true;
    },
    (error) => {
      report.ok = false;
      report.errors.push(error.stack || String(error));
    },
  )
  .finally(async () => {
    manager?.clear();
    await frameHost?.clear();
    if (host && !host.isDestroyed()) host.destroy();
    if (server) await new Promise((resolve) => server.close(resolve));
    writeFileSync(join(output, 'report.json'), JSON.stringify(report, null, 2));
    app.exit(report.ok ? 0 : 1);
  });
