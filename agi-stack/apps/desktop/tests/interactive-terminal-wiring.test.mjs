import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const interactiveTerminalSource = readFileSync(
  new URL('../src/features/sandbox/InteractiveTerminal.tsx', import.meta.url),
  'utf8'
);
const sessionTerminalSource = readFileSync(
  new URL('../src/features/session/SessionTerminalCanvas.tsx', import.meta.url),
  'utf8'
);
const sandboxFilesSource = readFileSync(
  new URL('../src/features/sandbox/SandboxFileBrowser.tsx', import.meta.url),
  'utf8'
);
const sandboxToolsSource = readFileSync(
  new URL('../src/features/sandbox/SessionSandboxTools.tsx', import.meta.url),
  'utf8'
);
const remoteDesktopSource = readFileSync(
  new URL('../src/features/sandbox/RemoteDesktopSurface.tsx', import.meta.url),
  'utf8'
);
const sandboxRuntimeHookSource = readFileSync(
  new URL('../src/features/sandbox/useSandboxRuntimeSurface.ts', import.meta.url),
  'utf8'
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('Desktop interactive terminal uses xterm, Fit, and WebLinks', () => {
  assert.match(interactiveTerminalSource, /from '@xterm\/xterm'/);
  assert.match(interactiveTerminalSource, /from '@xterm\/addon-fit'/);
  assert.match(interactiveTerminalSource, /from '@xterm\/addon-web-links'/);
  assert.match(interactiveTerminalSource, /terminal\.loadAddon\(fit\)/);
  assert.match(interactiveTerminalSource, /terminal\.loadAddon\(webLinks\)/);
  assert.match(interactiveTerminalSource, /terminal\.onData/);
  assert.match(interactiveTerminalSource, /new ResizeObserver/);
  assert.match(interactiveTerminalSource, /onResize/);
});

test('terminal canvas gates xterm and retains the history fallback', () => {
  assert.match(
    sessionTerminalSource,
    /sandboxRuntime\?\.capabilities\?\.terminal_interactive/
  );
  assert.match(sessionTerminalSource, /declaredInteractiveCapability\.availability === 'available'/);
  assert.match(sessionTerminalSource, /<InteractiveTerminal/);
  assert.match(sessionTerminalSource, /<pre[\s\S]*className="terminal-preview"/);
  assert.match(appSource, /interactiveCapability=\{terminalInteractiveCapability\}/);
  assert.match(appSource, /onTerminalInput=\{terminalProxy\.sendInput\}/);
  assert.match(appSource, /onTerminalResize=\{terminalProxy\.resize\}/);
});

test('sandbox file browser uses structured sandbox authority operations', () => {
  assert.match(sandboxFilesSource, /data-authority=\{authority\?\.authority \?\? 'sandbox'\}/);
  assert.match(sandboxFilesSource, /data-isolation=\{authority\?\.isolation \?\? 'unknown'\}/);
  assert.match(sandboxFilesSource, /capability\.availability !== 'available'/);
  assert.match(sandboxFilesSource, /client\.listFiles/);
  assert.match(sandboxFilesSource, /client\.readFile/);
  assert.match(sandboxFilesSource, /client\.downloadFile/);
  assert.doesNotMatch(sandboxFilesSource, /WorkspaceFile|workspace files|workspaceFiles/);
});

test('session terminal exposes files and desktop through an optional runtime prop', () => {
  assert.match(sessionTerminalSource, /sandboxRuntime\?: SessionSandboxRuntimeSurface/);
  assert.match(sessionTerminalSource, /<SessionSandboxTools runtime=\{sandboxRuntime\}/);
  assert.match(sandboxToolsSource, /<SandboxFileBrowser/);
  assert.match(sandboxToolsSource, /runtime\.fileClient/);
  assert.match(sandboxToolsSource, /onOpenFile=\{setPreviewFile\}/);
  assert.match(sandboxToolsSource, /onDownloadFile=\{downloadSandboxFile\}/);
  assert.match(appSource, /const sandboxRuntime = useSandboxRuntimeSurface/);
  assert.match(appSource, /sandboxRuntime=\{sandboxRuntime\}/);
});

test('remote desktop iframe is credential-free and reconnectable', () => {
  assert.match(remoteDesktopSource, /src=\{session\.frame_url\}/);
  assert.match(
    remoteDesktopSource,
    /sandbox="allow-scripts allow-same-origin allow-forms allow-pointer-lock"/
  );
  assert.match(remoteDesktopSource, /allow="autoplay; clipboard-read; clipboard-write"/);
  assert.match(remoteDesktopSource, /requestFullscreen/);
  assert.match(remoteDesktopSource, /document\.exitFullscreen/);
  assert.match(remoteDesktopSource, /event\.key === 'Escape'/);
  assert.match(remoteDesktopSource, /remoteDesktopReconnectDelay/);
  assert.match(remoteDesktopSource, /onReconnect/);
  assert.doesNotMatch(remoteDesktopSource, /password|token|Authorization|sendCredentials/iu);
});

test('runtime hook consumes capabilities without inference', () => {
  assert.match(sandboxRuntimeHookSource, /client\s*\.loadCapabilities/);
  assert.match(sandboxRuntimeHookSource, /createSandboxRuntimeClient\(config, capabilities\)/);
  assert.match(sandboxRuntimeHookSource, /capabilityLoadReason/);
  assert.doesNotMatch(
    sandboxRuntimeHookSource,
    /config\.mode\s*===|status\s*===\s*404|message\.includes|error\.message/iu
  );
});
