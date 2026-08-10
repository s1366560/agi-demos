import {
  app,
  BrowserWindow,
  desktopCapturer,
  dialog,
  ipcMain,
  net,
  protocol,
  screen,
  session,
  shell,
  systemPreferences,
  type IpcMainInvokeEvent,
} from 'electron';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, isAbsolute, join, normalize, parse, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  DisplayCaptureAuthorizationGate,
  assertPngCaptureWithinLimit,
  captureThumbnailSize,
  selectExactDisplaySource,
  type DesktopDisplayCapture,
} from './displayCapturePolicy';
import {
  RENDERER_ENTRY_URL,
  RENDERER_PROTOCOL_HOST,
  RENDERER_PROTOCOL_SCHEME,
  RendererProtocolError,
  resolveRendererAsset,
} from './rendererProtocol';
import { isTrustedAudioMediaPermission } from './mediaPermissionPolicy';
import {
  isTrustedNativeFileFrameUrl,
  ingestNativeFiles,
  openNativeFileWithDialog,
  readNativeFileNoFollow,
  saveNativeFileWithDialog,
  writeNativeFileAtomically,
  type NativeFileDialogAuthority,
  type NativeFileDialogFilter,
} from './nativeFileDialogPolicy';
import {
  configureQaProfile,
  resolveSidecarLegacyDataDirectories,
} from './qaProfilePolicy';
import { SidecarSupervisor } from './sidecarSupervisor';
import { startAutomaticUpdates } from './updater';
import {
  SIGNED_WEB_CONTROL_PLANE_ORIGIN,
  buildWebControlPlaneUrl,
  resolveWebControlPlaneConfiguration,
  type DesktopNativeCapabilitySnapshot,
} from './webControlPlanePolicy';

const currentDirectory = dirname(fileURLToPath(import.meta.url));
const rendererDirectory = join(currentDirectory, '../renderer');
const DESKTOP_COMMAND_CHANNEL = 'agistack:desktop-command';
const NATIVE_FILE_SAVE_CHANNEL = 'agistack:native-file-save';
const NATIVE_FILE_OPEN_CHANNEL = 'agistack:native-file-open';
const NATIVE_FILE_INGEST_CHANNEL = 'agistack:native-file-ingest';
const SIDECAR_RECOVERED_CHANNEL = 'agistack:sidecar-recovered';
const DEVICE_USER_CODE = /^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}$/u;
const SIDECAR_COMMANDS = new Set([
  'trusted_session_save',
  'trusted_session_load',
  'trusted_session_clear',
  'local_trusted_session_save',
  'local_trusted_session_load',
  'local_trusted_session_clear',
  'local_runtime_status',
  'local_runtime_configure',
  'browser_bridge_install',
  'browser_bridge_uninstall',
  'browser_bridge_status',
]);
const captureAuthorizationGate = new DisplayCaptureAuthorizationGate();
const qaProfileDirectory = configureQaProfile({
  app,
  requestedPath: process.env.AGISTACK_DESKTOP_QA_PROFILE_DIR,
});
const webControlPlaneConfiguration = resolveWebControlPlaneConfiguration({
  developmentOrigin: process.env.AGISTACK_WEB_CONTROL_PLANE_ORIGIN,
  isPackaged: app.isPackaged,
  signedOrigin: SIGNED_WEB_CONTROL_PLANE_ORIGIN,
});

type DesktopCommandArgs = Record<string, unknown> | undefined;

let mainWindow: BrowserWindow | null = null;
let sidecarSupervisor: SidecarSupervisor | null = null;
let sidecarShutdownComplete = false;
let stopAutomaticUpdates: (() => void) | null = null;

protocol.registerSchemesAsPrivileged([
  {
    scheme: RENDERER_PROTOCOL_SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
]);

// Dev-only CDP endpoint for native renderer QA. Enabled explicitly via env so
// packaged builds never expose a debugging surface.
if (!app.isPackaged && process.env.AGISTACK_DESKTOP_DEBUG_PORT) {
  app.commandLine.appendSwitch('remote-debugging-port', process.env.AGISTACK_DESKTOP_DEBUG_PORT);
}

function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname.toLowerCase();
  return (
    normalized === 'localhost' ||
    normalized === '127.0.0.1' ||
    normalized === '[::1]' ||
    normalized === '::1'
  );
}

function isSecureWebUrl(url: URL): boolean {
  return url.protocol === 'https:' || (url.protocol === 'http:' && isLoopbackHost(url.hostname));
}

function parseSecureWebUrl(value: unknown, label: string): URL {
  if (typeof value !== 'string' || /\s/u.test(value)) {
    throw new Error(`${label} is invalid`);
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${label} is invalid`);
  }
  if (!isSecureWebUrl(url) || url.username || url.password || url.hash) {
    throw new Error(`${label} must use HTTPS or loopback HTTP without user info or fragments`);
  }
  return url;
}

function validateDeviceAuthorizationUrl(args: DesktopCommandArgs): string {
  const authorizationUrl = parseSecureWebUrl(args?.url, 'device authorization URL');
  const baseUrl = parseSecureWebUrl(
    args?.deviceAuthorizationBaseUrl,
    'authorization portal URL',
  );
  const expectedUserCode = args?.expectedUserCode;
  if (typeof expectedUserCode !== 'string' || !DEVICE_USER_CODE.test(expectedUserCode)) {
    throw new Error('device user code does not match the expected protocol shape');
  }
  if (authorizationUrl.origin !== baseUrl.origin || authorizationUrl.pathname !== '/device') {
    throw new Error('device authorization URL does not match the authorization portal');
  }
  const queryEntries = [...authorizationUrl.searchParams.entries()];
  if (
    queryEntries.length !== 1 ||
    queryEntries[0]?.[0] !== 'user_code' ||
    queryEntries[0]?.[1] !== expectedUserCode
  ) {
    throw new Error('device authorization URL must contain exactly the expected user_code');
  }
  return authorizationUrl.toString();
}

async function captureCurrentDisplay(): Promise<DesktopDisplayCapture> {
  if (!mainWindow || mainWindow.isDestroyed()) {
    throw new Error('desktop window is unavailable');
  }
  const captureWindow = mainWindow;
  const authorization = await captureAuthorizationGate.authorize(async () => {
    const result = await dialog.showMessageBox(captureWindow, {
      buttons: ['Capture display', 'Cancel'],
      cancelId: 1,
      defaultId: 1,
      detail:
        'The screenshot stays in a local preview until you explicitly attach it.',
      message: 'Allow MemStack to capture the display containing this window?',
      noLink: true,
      title: 'Capture current display',
      type: 'question',
    });
    return result.response === 0;
  });
  captureAuthorizationGate.consume(authorization);
  if (captureWindow.isDestroyed()) {
    throw new Error('desktop window is unavailable');
  }
  const targetDisplay = screen.getDisplayMatching(captureWindow.getBounds());
  const targetDisplayId = String(targetDisplay.id);
  const thumbnailSize = captureThumbnailSize(
    targetDisplay.size.width,
    targetDisplay.size.height,
    targetDisplay.scaleFactor,
  );
  const sources = await desktopCapturer.getSources({
    types: ['screen'],
    thumbnailSize,
    fetchWindowIcons: false,
  });
  const source = selectExactDisplaySource(
    sources.map((candidate) => ({
      displayId: candidate.display_id,
      value: candidate,
    })),
    targetDisplayId,
  ).value;
  const png = source.thumbnail.toPNG();
  const pngBytes = assertPngCaptureWithinLimit(png);
  const captureSize = source.thumbnail.getSize();
  return {
    dataUrl: `data:image/png;base64,${png.toString('base64')}`,
    displayId: targetDisplayId,
    height: captureSize.height,
    mimeType: 'image/png',
    pngBytes,
    width: captureSize.width,
  };
}

async function openWebControlPlane(args: DesktopCommandArgs): Promise<void> {
  if (
    webControlPlaneConfiguration.capability.availability !== 'available' ||
    webControlPlaneConfiguration.origin === null
  ) {
    throw new Error(webControlPlaneConfiguration.capability.reasonCode);
  }
  const target = buildWebControlPlaneUrl(webControlPlaneConfiguration.origin, args);
  await shell.openExternal(target, { activate: true });
}

function desktopNativeCapabilities(): DesktopNativeCapabilitySnapshot {
  return Object.freeze({
    contractVersion: 1,
    webControlPlane: webControlPlaneConfiguration.capability,
  });
}

function electronDialogFilters(
  filters: readonly NativeFileDialogFilter[],
): Electron.FileFilter[] {
  return filters.map((filter) => ({
    name: filter.name,
    extensions: [...filter.extensions],
  }));
}

function nativeFileDialogAuthority(
  event: IpcMainInvokeEvent,
): NativeFileDialogAuthority {
  const ownerWindow = mainWindow;
  if (
    !ownerWindow ||
    ownerWindow.isDestroyed() ||
    event.sender !== ownerWindow.webContents ||
    event.senderFrame !== ownerWindow.webContents.mainFrame ||
    !isTrustedNativeFileFrameUrl(event.senderFrame.url, rendererDevelopmentUrl())
  ) {
    throw new Error('native file request is not authorized');
  }
  return Object.freeze({
    async chooseSaveTarget(input) {
      const result = await dialog.showSaveDialog(ownerWindow, {
        defaultPath: input.suggestedName,
        filters: electronDialogFilters(input.filters),
        properties: ['createDirectory', 'showOverwriteConfirmation'],
      });
      return result.canceled || !result.filePath ? null : result.filePath;
    },
    async chooseOpenTargets(input) {
      const result = await dialog.showOpenDialog(ownerWindow, {
        filters: electronDialogFilters(input.filters),
        properties: input.allowMultiple ? ['openFile', 'multiSelections'] : ['openFile'],
        title:
          input.purpose === 'skill_package'
            ? 'Import Skill ZIP package'
            : 'Import attachment files',
      });
      return result.canceled ? null : Object.freeze([...result.filePaths]);
    },
    readFileNoFollow: readNativeFileNoFollow,
    writeFileAtomically: writeNativeFileAtomically,
  });
}

async function handleNativeFileSave(
  event: IpcMainInvokeEvent,
  request: unknown,
): Promise<unknown> {
  return saveNativeFileWithDialog(request, nativeFileDialogAuthority(event));
}

async function handleNativeFileOpen(
  event: IpcMainInvokeEvent,
  request: unknown,
): Promise<unknown> {
  return openNativeFileWithDialog(request, nativeFileDialogAuthority(event));
}

async function handleNativeFileIngest(
  event: IpcMainInvokeEvent,
  request: unknown,
): Promise<unknown> {
  void nativeFileDialogAuthority(event);
  return ingestNativeFiles(request);
}

async function executeDesktopCommand(
  event: IpcMainInvokeEvent,
  command: unknown,
  args: DesktopCommandArgs,
): Promise<unknown> {
  if (event.sender !== mainWindow?.webContents || typeof command !== 'string') {
    throw new Error('desktop command is not authorized');
  }
  switch (command) {
    case 'frontend_ready':
      return undefined;
    case 'get_desktop_capabilities':
      return desktopNativeCapabilities();
    case 'open_device_authorization_url':
      await shell.openExternal(validateDeviceAuthorizationUrl(args), { activate: true });
      return undefined;
    case 'capture_current_display':
      return captureCurrentDisplay();
    case 'open_web_control_plane':
      await openWebControlPlane(args);
      return undefined;
    case 'request_microphone_access':
      return process.platform === 'darwin'
        ? systemPreferences.askForMediaAccess('microphone')
        : true;
    case 'focus_main_window':
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
      }
      return undefined;
    case 'window_controls': {
      if (!mainWindow) return undefined;
      const action = args?.action;
      if (action === 'minimize') mainWindow.minimize();
      else if (action === 'maximize') mainWindow.maximize();
      else if (action === 'unmaximize') mainWindow.unmaximize();
      else if (action === 'toggle_maximize') {
        if (mainWindow.isMaximized()) mainWindow.unmaximize();
        else mainWindow.maximize();
      } else if (action === 'is_maximized') return mainWindow.isMaximized();
      else if (action === 'close') mainWindow.close();
      else throw new Error('window control action is not supported');
      return undefined;
    }
    default:
      if (SIDECAR_COMMANDS.has(command)) {
        if (!sidecarSupervisor) throw new Error('desktop sidecar is unavailable');
        return sidecarSupervisor.invoke(command, args);
      }
      throw new Error('desktop command is not supported');
  }
}

function sidecarBinaryPath(): string {
  const override = process.env.AGISTACK_SIDECAR_PATH;
  if (override) {
    if (!isAbsolute(override)) {
      throw new Error('AGISTACK_SIDECAR_PATH must be absolute');
    }
    return override;
  }
  const executable =
    process.platform === 'win32'
      ? 'agistack-desktop-sidecar.exe'
      : 'agistack-desktop-sidecar';
  if (app.isPackaged) {
    return join(process.resourcesPath, 'sidecar', executable);
  }
  return join(currentDirectory, '../../../../target/debug', executable);
}

function defaultWorkspaceRoot(): string {
  const configured = process.env.AGISTACK_WORKSPACE_ROOT;
  if (configured && isAbsolute(configured)) return resolve(configured);

  let candidate = resolve(process.cwd());
  const filesystemRoot = parse(candidate).root;
  while (true) {
    if (existsSync(join(candidate, 'AGENTS.md')) || existsSync(join(candidate, '.git'))) {
      return candidate;
    }
    if (candidate === filesystemRoot) break;
    candidate = dirname(candidate);
  }
  return homedir();
}

function legacyTauriDataDirectories(destination: string): string[] {
  const identifier = 'ai.agistack.desktop';
  const candidates = [join(app.getPath('appData'), identifier)];
  if (process.platform === 'linux') {
    const xdgDataHome = process.env.XDG_DATA_HOME;
    candidates.push(
      xdgDataHome && isAbsolute(xdgDataHome)
        ? join(xdgDataHome, identifier)
        : join(homedir(), '.local', 'share', identifier),
    );
  }
  return [...new Set(candidates.map((candidate) => resolve(candidate)))].filter(
    (candidate) => normalize(candidate) !== normalize(destination),
  );
}

function createSidecarSupervisor(): SidecarSupervisor {
  const dataDirectory = join(app.getPath('userData'), 'runtime');
  return new SidecarSupervisor({
    binaryPath: sidecarBinaryPath(),
    dataDirectory,
    workspaceRoot: defaultWorkspaceRoot(),
    legacyDataDirectories: resolveSidecarLegacyDataDirectories({
      qaProfileDirectory,
      resolveNormalCandidates: () => legacyTauriDataDirectories(dataDirectory),
    }),
    onRecovered: () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send(SIDECAR_RECOVERED_CHANNEL);
      }
    },
  });
}

function rendererDevelopmentUrl(): URL | null {
  const value = process.env.ELECTRON_RENDERER_URL;
  if (!value) return null;
  const url = new URL(value);
  if (url.protocol !== 'http:' || !isLoopbackHost(url.hostname)) {
    throw new Error('Electron renderer development URL must use loopback HTTP');
  }
  return url;
}

async function handleRendererRequest(request: Request): Promise<Response> {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method not allowed', {
      status: 405,
      headers: { Allow: 'GET, HEAD' },
    });
  }
  try {
    const assetPath = await resolveRendererAsset(rendererDirectory, request.url);
    const response = await net.fetch(pathToFileURL(assetPath).toString());
    if (request.method === 'HEAD') {
      return new Response(null, {
        status: response.status,
        headers: response.headers,
      });
    }
    return response;
  } catch (error) {
    const status = error instanceof RendererProtocolError ? error.status : 500;
    return new Response(status === 404 ? 'Not found' : 'Request denied', { status });
  }
}

function installRendererProtocol(): void {
  protocol.handle(RENDERER_PROTOCOL_SCHEME, handleRendererRequest);
}

function installMediaPermissionPolicy(): void {
  const developmentUrl = rendererDevelopmentUrl();
  const allowedOrigin =
    developmentUrl?.origin ?? `${RENDERER_PROTOCOL_SCHEME}://${RENDERER_PROTOCOL_HOST}`;
  session.defaultSession.setPermissionCheckHandler(
    (webContents, permission, requestingOrigin, details) =>
      isTrustedAudioMediaPermission({
        senderIsMainWindow: webContents !== null && webContents === mainWindow?.webContents,
        permission,
        requestingUrl: requestingOrigin || webContents?.getURL() || '',
        allowedOrigin,
        mediaTypes: details.mediaType ? [details.mediaType] : [],
      }),
  );
  session.defaultSession.setPermissionRequestHandler(
    (webContents, permission, callback, details) => {
      callback(
        isTrustedAudioMediaPermission({
          senderIsMainWindow: webContents === mainWindow?.webContents,
          permission,
          requestingUrl: details.requestingUrl || webContents.getURL(),
          allowedOrigin,
          mediaTypes: 'mediaTypes' in details ? (details.mediaTypes ?? []) : [],
        }),
      );
    },
  );
}

function installNavigationPolicy(window: BrowserWindow, developmentUrl: URL | null): void {
  window.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const target = new URL(url);
      if (isSecureWebUrl(target)) void shell.openExternal(target.toString());
    } catch {
      // Invalid or privileged URLs stay blocked.
    }
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    let allowedDevelopmentNavigation = false;
    let allowedProductionNavigation = false;
    try {
      const target = new URL(url);
      allowedDevelopmentNavigation =
        developmentUrl !== null && target.origin === developmentUrl.origin;
      allowedProductionNavigation =
        developmentUrl === null &&
        target.protocol === `${RENDERER_PROTOCOL_SCHEME}:` &&
        target.hostname === RENDERER_PROTOCOL_HOST &&
        !target.username &&
        !target.password &&
        !target.port;
    } catch {
      // Malformed navigation targets stay blocked.
    }
    if (!allowedDevelopmentNavigation && !allowedProductionNavigation) {
      event.preventDefault();
    }
  });
}

async function createMainWindow(): Promise<void> {
  const developmentUrl = rendererDevelopmentUrl();
  // Frameless window: the renderer draws its own titlebar. macOS keeps the
  // native traffic lights via `titleBarStyle: 'hidden'`, Windows hides the
  // native titlebar, and Linux drops the frame entirely. `hiddenInset` is
  // deliberately avoided: it keeps an invisible native titlebar strip whose
  // AppKit drag/zoom handling overlaps the renderer's `-webkit-app-region:
  // drag` strip, so a press engages two window-move drivers that fight each
  // other (visible shake while dragging) and double-click zoom lands in the
  // wrong geometry. With 'hidden' there is a single drag driver and Chromium
  // handles double-click maximize consistently.
  const framelessWindowOptions =
    process.platform === 'darwin'
      ? {
          titleBarStyle: 'hidden' as const,
          trafficLightPosition: { x: 12, y: 10 },
        }
      : process.platform === 'win32'
        ? { titleBarStyle: 'hidden' as const }
        : { frame: false as const };
  const window = new BrowserWindow({
    title: 'agi-stack Desktop',
    width: 1728,
    height: 1024,
    minWidth: 1080,
    minHeight: 720,
    center: true,
    show: false,
    ...framelessWindowOptions,
    webPreferences: {
      preload: join(currentDirectory, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  mainWindow = window;
  installNavigationPolicy(window, developmentUrl);
  window.once('ready-to-show', () => window.show());
  window.on('closed', () => {
    if (mainWindow === window) mainWindow = null;
  });
  if (developmentUrl) {
    await window.loadURL(developmentUrl.toString());
  } else {
    await window.loadURL(RENDERER_ENTRY_URL);
  }
}

function handleFatalStartup(error: unknown): void {
  const detail = error instanceof Error ? error.message : String(error);
  console.error('Electron desktop startup failed', error);
  try {
    dialog.showErrorBox('agi-stack Desktop failed to start', detail);
  } finally {
    process.exitCode = 1;
    app.quit();
  }
}

async function bootstrapApplication(): Promise<void> {
  installRendererProtocol();
  installMediaPermissionPolicy();
  sidecarSupervisor = createSidecarSupervisor();
  await sidecarSupervisor.start();
  ipcMain.handle(DESKTOP_COMMAND_CHANNEL, executeDesktopCommand);
  ipcMain.handle(NATIVE_FILE_SAVE_CHANNEL, handleNativeFileSave);
  ipcMain.handle(NATIVE_FILE_OPEN_CHANNEL, handleNativeFileOpen);
  ipcMain.handle(NATIVE_FILE_INGEST_CHANNEL, handleNativeFileIngest);
  await createMainWindow();
  stopAutomaticUpdates = startAutomaticUpdates();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createMainWindow().catch(handleFatalStartup);
    }
  });
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow?.isMinimized()) mainWindow.restore();
    mainWindow?.show();
    mainWindow?.focus();
  });
  void app.whenReady().then(bootstrapApplication).catch(handleFatalStartup);
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });
  app.on('before-quit', (event) => {
    if (!sidecarSupervisor || sidecarShutdownComplete) return;
    event.preventDefault();
    stopAutomaticUpdates?.();
    stopAutomaticUpdates = null;
    const supervisor = sidecarSupervisor;
    sidecarSupervisor = null;
    void supervisor.stop().finally(() => {
      sidecarShutdownComplete = true;
      app.quit();
    });
  });
}
