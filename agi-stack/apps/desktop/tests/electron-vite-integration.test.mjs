import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import {
  mkdir,
  mkdtemp,
  realpath,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  RENDERER_ENTRY_URL,
  RendererProtocolError,
  resolveRendererAsset,
} = require('/tmp/agistack-desktop-test-dist/electron/main/rendererProtocol.js');
const packageJson = JSON.parse(
  readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
);
const configSource = readFileSync(
  new URL('../electron.vite.config.ts', import.meta.url),
  'utf8',
);
const mainSource = readFileSync(
  new URL('../electron/main/index.ts', import.meta.url),
  'utf8',
);
const preloadSource = readFileSync(
  new URL('../electron/preload/index.ts', import.meta.url),
  'utf8',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const loginScreenSource = readFileSync(
  new URL('../src/features/auth/LoginScreen.tsx', import.meta.url),
  'utf8',
);
const rendererHtml = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const ciWorkflow = readFileSync(
  new URL('../../../../.github/workflows/ci.yml', import.meta.url),
  'utf8',
);
const sidecarControlSource = readFileSync(
  new URL('../sidecar/src/control.rs', import.meta.url),
  'utf8',
);
const makefileSource = readFileSync(
  new URL('../../../Makefile', import.meta.url),
  'utf8',
);

test('electron-vite is the canonical desktop build and launch surface', () => {
  assert.equal(packageJson.main, './out/main/index.js');
  assert.equal(packageJson.scripts.dev, 'vite --host 127.0.0.1 --port 5173 --strictPort');
  assert.match(packageJson.scripts['dev:electron'], /^electron-vite dev/);
  assert.match(packageJson.scripts['build:electron'], /electron-vite build/);
  assert.match(packageJson.scripts['preview:electron'], /electron-vite preview/);
  assert.equal(packageJson.devDependencies['electron-vite'], '5.0.0');
  assert.ok(packageJson.devDependencies.electron);
  assert.ok(packageJson.dependencies['electron-updater']);
  assert.ok(packageJson.devDependencies['electron-builder']);
  assert.deepEqual(packageJson.pnpm.onlyBuiltDependencies, ['electron', 'esbuild']);
  assert.match(makefileSource, /run-desktop:[\s\S]*install-electron --no/);
  assert.match(makefileSource, /\$\(CARGO\) build -p agistack-desktop-sidecar/);
  assert.doesNotMatch(makefileSource, /@tauri-apps|TAURI_CLI/u);
  for (const legacyPath of [
    new URL('../src-tauri/', import.meta.url),
    new URL('../../../scripts/run-macos-tauri-cargo.sh', import.meta.url),
    new URL('../../../scripts/run-macos-dev-signed.sh', import.meta.url),
    new URL('../../../scripts/check-macos-dev-signing.sh', import.meta.url),
  ]) {
    assert.equal(existsSync(legacyPath), false, `${legacyPath.pathname} must stay removed`);
  }
});

test('electron-vite reuses the existing React renderer and isolates its output', () => {
  assert.match(configSource, /defineConfig/);
  assert.match(configSource, /root:\s*desktopRoot/);
  assert.match(configSource, /input:\s*resolve\(desktopRoot,\s*'index\.html'\)/);
  assert.match(configSource, /outDir:\s*resolve\(desktopRoot,\s*'out\/renderer'\)/);
  assert.match(configSource, /plugins:\s*\[react\(\)\]/);
  assert.match(ciWorkflow, /node-version: '22'/);
  assert.match(ciWorkflow, /run: make desktop-bundle/);
  assert.match(ciWorkflow, /apps\/desktop\/release\/\*\.dmg/u);
  assert.match(ciWorkflow, /apps\/desktop\/release\/latest\*\.yml/u);
  assert.doesNotMatch(ciWorkflow, /apps\/desktop\/release\/\*\*/u);
  assert.doesNotMatch(ciWorkflow, /tauri-cli|src-tauri/u);
});

test('Electron window keeps renderer privileges isolated and navigation constrained', () => {
  assert.match(mainSource, /contextIsolation:\s*true/);
  assert.match(mainSource, /nodeIntegration:\s*false/);
  assert.match(mainSource, /sandbox:\s*true/);
  assert.match(mainSource, /setWindowOpenHandler/);
  assert.match(mainSource, /setPermissionRequestHandler/);
  assert.match(mainSource, /ELECTRON_RENDERER_URL/);
  assert.match(mainSource, /protocol\.registerSchemesAsPrivileged/);
  assert.match(mainSource, /protocol\.handle\(RENDERER_PROTOCOL_SCHEME/);
  assert.match(mainSource, /loadURL\(RENDERER_ENTRY_URL\)/);
  assert.doesNotMatch(mainSource, /\.loadFile\(/);
  assert.match(rendererHtml, /http-equiv="Content-Security-Policy"/);
  assert.match(
    rendererHtml,
    /frame-src 'self' blob: https: http:\/\/127\.0\.0\.1:\* http:\/\/localhost:\*/,
  );
  assert.doesNotMatch(rendererHtml, /http:\/\/\[::1\]:\*/u);
  assert.match(rendererHtml, /object-src 'none'/);
  assert.match(rendererHtml, /script-src 'self'/);
  assert.doesNotMatch(
    rendererHtml,
    /customprotocol:|asset:|ipc:|(?:ipc|asset)\.localhost/,
  );
});

test('preload exposes only the command bridge instead of raw ipcRenderer', () => {
  assert.match(preloadSource, /contextBridge\.exposeInMainWorld/);
  assert.match(preloadSource, /invoke:\s*invokeDesktopCommand/);
  assert.doesNotMatch(preloadSource, /exposeInMainWorld\([^)]*ipcRenderer/s);
  assert.doesNotMatch(preloadSource, /send:\s*ipcRenderer\.send/);
  assert.doesNotMatch(preloadSource, /on:\s*ipcRenderer\.on/);
  assert.doesNotMatch(preloadSource, /['"]__TAURI__['"]/);
  assert.match(preloadSource, /SIDECAR_RECOVERED_CHANNEL/u);
  assert.match(preloadSource, /onSidecarRecovered/u);
  assert.match(preloadSource, /removeListener\(SIDECAR_RECOVERED_CHANNEL/u);
});

test('Electron renderer protocol confines assets to the real application directory', async () => {
  const temporaryDirectory = await mkdtemp(join(tmpdir(), 'agistack-renderer-protocol-'));
  const rendererRoot = join(temporaryDirectory, 'renderer');
  const outsideFile = join(temporaryDirectory, 'outside.txt');
  try {
    await mkdir(join(rendererRoot, 'assets'), { recursive: true });
    await writeFile(join(rendererRoot, 'index.html'), '<main>safe</main>');
    await writeFile(join(rendererRoot, 'assets', 'app.js'), 'export {};');
    await writeFile(outsideFile, 'private');

    assert.equal(
      await resolveRendererAsset(rendererRoot, RENDERER_ENTRY_URL),
      await realpath(join(rendererRoot, 'index.html')),
    );
    assert.equal(
      await resolveRendererAsset(rendererRoot, 'agistack://app/assets/app.js'),
      await realpath(join(rendererRoot, 'assets', 'app.js')),
    );
    await assert.rejects(
      resolveRendererAsset(rendererRoot, 'agistack://app/%2e%2e%2foutside.txt'),
      (error) => error instanceof RendererProtocolError && error.status === 403,
    );
    await assert.rejects(
      resolveRendererAsset(rendererRoot, 'agistack://other/index.html'),
      (error) => error instanceof RendererProtocolError && error.status === 403,
    );

    if (process.platform !== 'win32') {
      await symlink(outsideFile, join(rendererRoot, 'linked-outside.txt'));
      await assert.rejects(
        resolveRendererAsset(rendererRoot, 'agistack://app/linked-outside.txt'),
        (error) => error instanceof RendererProtocolError && error.status === 403,
      );
    }
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true });
  }
});

test('Electron startup failures are caught and local mode follows native sidecar authority', () => {
  assert.match(mainSource, /whenReady\(\)\.then\(bootstrapApplication\)\.catch\(handleFatalStartup\)/);
  assert.match(mainSource, /createMainWindow\(\)\.catch\(handleFatalStartup\)/);
  assert.match(mainSource, /dialog\.showErrorBox/);
  assert.match(appSource, /localModeAvailable=\{runsInNativeDesktop\}/);
  assert.match(loginScreenSource, /localModeAvailable \?/);
  assert.match(mainSource, /onRecovered:[\s\S]*SIDECAR_RECOVERED_CHANNEL/u);
  assert.match(appSource, /onSidecarRecovered[\s\S]*refreshRuntime\(configRef\.current\)/u);
});

test('Electron delegates trusted-session secrets to the authenticated Rust sidecar', () => {
  assert.match(mainSource, /SidecarSupervisor/u);
  assert.match(mainSource, /sidecarSupervisor\.invoke/u);
  assert.match(sidecarControlSource, /ApplicationCredentialVault/u);
  assert.match(sidecarControlSource, /trusted_session_save/u);
  assert.doesNotMatch(mainSource, /safeStorage|keytar|keyring|localStorage/u);
  assert.doesNotMatch(mainSource, /console\.(?:log|info|debug)\([^)]*credential/s);
});
