import { execFileSync, spawn, spawnSync } from 'node:child_process';
import { constants, existsSync } from 'node:fs';
import { access, mkdir, mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { parseDocument } from 'yaml';

import { verifyReleaseRootMetadata } from './release-artifact-contract.mjs';
import {
  INSTALL_LAUNCH_SMOKE_SCHEMA,
  releaseEvidenceDir,
  writeEvidenceFragment,
} from './release-evidence.mjs';
import { probeSidecarHealth } from './sidecar-health-probe.mjs';

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const LAUNCH_OBSERVATION_MS = 12_000;
const SIDECAR_DISCOVERY_TIMEOUT_MS = 90_000;
const EXIT_TIMEOUT_MS = 30_000;
const INSTALLER_TIMEOUT_MS = 300_000;

const SIDECAR_NAME =
  process.platform === 'win32' ? 'agistack-desktop-sidecar.exe' : 'agistack-desktop-sidecar';
const WORKSPACE_CORE_NAME =
  process.platform === 'win32' ? 'memstack-workspace-core.exe' : 'memstack-workspace-core';

function requireUniquePath(paths, label) {
  if (paths.length !== 1) {
    throw new Error(`${label} must have exactly one match; found ${paths.length}`);
  }
  return paths[0];
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

async function waitFor(check, timeoutMs, label, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await check();
    if (value) return value;
    if (Date.now() >= deadline) throw new Error(`${label} timed out`);
    await sleep(intervalMs);
  }
}

/** Launch flags: only the headless Linux leg disables the Chromium sandbox. */
export function launchArgumentsFor(platform) {
  return platform === 'linux' ? ['--no-sandbox'] : [];
}

export function parseUnixProcessTable(output) {
  return output
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^(\d+)\s+(\d+)\s+(.*)$/u);
      if (!match) return null;
      return { pid: Number(match[1]), ppid: Number(match[2]), command: match[3] };
    })
    .filter(Boolean);
}

export function parseWindowsProcessTable(jsonText) {
  const parsed = JSON.parse(jsonText);
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  return rows
    .filter((row) => row && Number.isSafeInteger(row.ProcessId))
    .map((row) => ({
      pid: row.ProcessId,
      ppid: Number.isSafeInteger(row.ParentProcessId) ? row.ParentProcessId : 0,
      command: typeof row.ExecutablePath === 'string' ? row.ExecutablePath : '',
    }));
}

export function isDescendantOf(processes, pid, ancestorPid) {
  const byPid = new Map(processes.map((entry) => [entry.pid, entry]));
  let current = byPid.get(pid);
  let hops = 0;
  while (current && hops <= processes.length) {
    if (current.ppid === ancestorPid) return true;
    current = byPid.get(current.ppid);
    hops += 1;
  }
  return false;
}

function normalizeCommandPath(value) {
  return value.replaceAll('\\', '/').toLowerCase();
}

/**
 * Locate a spawned sidecar that descends from the observed app process and
 * whose command path contains the installed sidecar path. Parentage is
 * asserted, not just process presence.
 */
export function findSpawnedSidecar(processes, appPid, sidecarPath) {
  const needle = normalizeCommandPath(sidecarPath);
  return processes.find(
    (entry) =>
      normalizeCommandPath(entry.command).includes(needle) &&
      isDescendantOf(processes, entry.pid, appPid),
  );
}

function unixProcessTable() {
  const argsFlag = process.platform === 'darwin' ? '-axo' : '-eo';
  return parseUnixProcessTable(
    execFileSync('ps', [argsFlag, 'pid=,ppid=,args='], { encoding: 'utf8' }),
  );
}

function windowsProcessTable() {
  const output = execFileSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      'Get-CimInstance Win32_Process | ' +
        'Select-Object ProcessId,ParentProcessId,ExecutablePath | ConvertTo-Json -Compress',
    ],
    { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 },
  );
  return parseWindowsProcessTable(output);
}

function processTable(platform) {
  return platform === 'win32' ? windowsProcessTable() : unixProcessTable();
}

async function terminateLaunchedApp(child, platform, label) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return { exit_observed: true, termination: 'already_exited' };
  }
  if (platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/t'], { stdio: 'ignore' });
  } else if (platform === 'linux') {
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      child.kill('SIGTERM');
    }
  } else {
    child.kill('SIGTERM');
  }
  const exited = await Promise.race([
    new Promise((resolveExit) => child.once('exit', () => resolveExit(true))),
    sleep(EXIT_TIMEOUT_MS).then(() => false),
  ]);
  if (!exited) {
    if (platform === 'win32') {
      spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore' });
    } else if (platform === 'linux') {
      try {
        process.kill(-child.pid, 'SIGKILL');
      } catch {
        child.kill('SIGKILL');
      }
    } else {
      child.kill('SIGKILL');
    }
    await Promise.race([
      new Promise((resolveExit) => child.once('exit', () => resolveExit(true))),
      sleep(EXIT_TIMEOUT_MS).then(() => false),
    ]);
    if (child.exitCode === null && child.signalCode === null) {
      throw new Error(`${label} did not exit after termination`);
    }
    return { exit_observed: true, termination: 'forced_kill' };
  }
  return { exit_observed: true, termination: platform === 'win32' ? 'taskkill' : 'sigterm' };
}

/**
 * Launch an installed app, require it to stay alive for the observation
 * window, require its packaged sidecar to spawn beneath it, then terminate it.
 */
async function observeLaunchedApp({ command, args, env, detached = false, sidecarPath, platform, label }) {
  const child = spawn(command, args, {
    env: env ?? process.env,
    stdio: 'ignore',
    detached,
    windowsHide: true,
  });
  const childError = new Promise((_, reject) => {
    child.once('error', (error) => reject(new Error(`${label} failed to launch: ${error.message}`)));
  });
  // The observation race may settle before an error; never leave it unhandled.
  childError.catch(() => {});
  const childExit = new Promise((resolveExit) => {
    child.once('exit', () => resolveExit(true));
  });
  try {
    const exitedEarly = await Promise.race([
      sleep(LAUNCH_OBSERVATION_MS).then(() => false),
      childExit.then(() => true),
      childError,
    ]);
    if (exitedEarly) {
      throw new Error(`${label} exited during the launch observation window`);
    }
    const sidecar = await Promise.race([
      waitFor(
        async () => findSpawnedSidecar(processTable(platform), child.pid, sidecarPath),
        SIDECAR_DISCOVERY_TIMEOUT_MS,
        `${label} packaged sidecar spawn`,
      ),
      childError,
    ]);
    const termination = await terminateLaunchedApp(child, platform, label);
    return {
      launched: true,
      uptime_ms: LAUNCH_OBSERVATION_MS,
      sidecar_spawned: true,
      sidecar_pid: sidecar.pid,
      ...termination,
    };
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill('SIGKILL');
    }
  }
}

function packagedRuntimePaths(appRoot, layout) {
  const resources = layout === 'mac' ? join(appRoot, 'Contents', 'Resources') : join(appRoot, 'resources');
  return {
    sidecarPath: join(resources, 'sidecar', SIDECAR_NAME),
    workspaceCorePath: join(resources, 'workspace-core', WORKSPACE_CORE_NAME),
  };
}

async function macMainExecutable(appPath) {
  const executable = execFileSync(
    '/usr/libexec/PlistBuddy',
    ['-c', 'Print :CFBundleExecutable', join(appPath, 'Contents', 'Info.plist')],
    { encoding: 'utf8' },
  ).trim();
  if (!executable || basename(executable) !== executable) {
    throw new Error('installed macOS CFBundleExecutable is invalid');
  }
  return join(appPath, 'Contents', 'MacOS', executable);
}

async function smokeMacInstall({ installers }) {
  const dmgPath = requireUniquePath(
    installers.filter((path) => path.endsWith('.dmg')),
    'macOS disk image',
  );
  const workRoot = await mkdtemp(join(tmpdir(), 'agistack-install-smoke-mac-'));
  const mountRoot = join(workRoot, 'mounted');
  const installRoot = join(workRoot, 'installed');
  await mkdir(mountRoot);
  await mkdir(installRoot);
  let attached = false;
  try {
    execFileSync(
      '/usr/bin/hdiutil',
      ['attach', dmgPath, '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', mountRoot],
      { stdio: 'inherit' },
    );
    attached = true;
    const mountedEntries = await readdir(mountRoot, { withFileTypes: true });
    const mountedApp = requireUniquePath(
      mountedEntries
        .filter((entry) => entry.isDirectory() && entry.name.endsWith('.app'))
        .map((entry) => join(mountRoot, entry.name)),
      'mounted macOS application',
    );
    const installedApp = join(installRoot, basename(mountedApp));
    execFileSync('/usr/bin/ditto', [mountedApp, installedApp], { stdio: 'inherit' });
    const executable = await macMainExecutable(installedApp);
    const { sidecarPath, workspaceCorePath } = packagedRuntimePaths(installedApp, 'mac');
    const launch = await observeLaunchedApp({
      command: executable,
      args: launchArgumentsFor('darwin'),
      sidecarPath,
      platform: 'darwin',
      label: 'installed macOS app',
    });
    const probe = await probeSidecarHealth({ sidecarPath, workspaceCorePath });
    return {
      kind: 'macos_dmg_install',
      installer: basename(dmgPath),
      installed_to: installedApp,
      display: 'runner_window_server',
      launch_flags: launchArgumentsFor('darwin'),
      sandbox_disabled: false,
      ...launch,
      sidecar_probe: probe,
    };
  } finally {
    if (attached) {
      spawnSync('/usr/bin/hdiutil', ['detach', mountRoot], { stdio: 'ignore' });
    }
    await rm(workRoot, { recursive: true, force: true });
  }
}

async function desktopProductName() {
  const config = parseDocument(await readFile(join(desktopRoot, 'electron-builder.yml'), 'utf8'), {
    maxAliasCount: 0,
    uniqueKeys: true,
  }).toJS({ maxAliasCount: 0 });
  if (!config || typeof config.productName !== 'string' || config.productName.length === 0) {
    throw new Error('electron-builder.yml productName is missing');
  }
  return config.productName;
}

async function smokeWindowsInstall({ installers }) {
  const installerPath = requireUniquePath(
    installers.filter((path) => path.endsWith('.exe')),
    'Windows NSIS installer',
  );
  const productName = await desktopProductName();
  const localAppData = process.env.LOCALAPPDATA;
  if (!localAppData) {
    throw new Error('LOCALAPPDATA is required to locate the silent NSIS install');
  }
  const installDir = join(localAppData, 'Programs', productName);
  const installedExe = join(installDir, `${productName}.exe`);
  const uninstaller = join(installDir, `Uninstall ${productName}.exe`);
  try {
    const install = spawnSync(installerPath, ['/S'], {
      timeout: INSTALLER_TIMEOUT_MS,
      windowsHide: true,
    });
    if (install.error) throw install.error;
    if (install.status !== 0) {
      throw new Error(`silent NSIS install failed with exit ${install.status ?? 'unknown'}`);
    }
    await access(installedExe, constants.X_OK);
    const { sidecarPath, workspaceCorePath } = packagedRuntimePaths(installDir, 'windows');
    const launch = await observeLaunchedApp({
      command: installedExe,
      args: launchArgumentsFor('win32'),
      sidecarPath,
      platform: 'win32',
      label: 'installed Windows app',
    });
    const probe = await probeSidecarHealth({ sidecarPath, workspaceCorePath });
    return {
      kind: 'windows_nsis_silent_install',
      installer: basename(installerPath),
      installed_to: installDir,
      display: 'runner_session',
      launch_flags: launchArgumentsFor('win32'),
      sandbox_disabled: false,
      ...launch,
      sidecar_probe: probe,
    };
  } finally {
    if (existsSync(uninstaller)) {
      spawnSync(uninstaller, ['/S'], { timeout: INSTALLER_TIMEOUT_MS, stdio: 'ignore' });
    }
  }
}

async function extractAppImage(appImagePath, workRoot) {
  const extraction = spawnSync(appImagePath, ['--appimage-extract'], {
    cwd: workRoot,
    encoding: 'utf8',
    timeout: INSTALLER_TIMEOUT_MS,
  });
  if (extraction.error) throw extraction.error;
  if (extraction.status !== 0) {
    throw new Error(`AppImage extract failed: ${extraction.stderr || extraction.stdout}`);
  }
  const root = join(workRoot, 'squashfs-root');
  await access(join(root, 'AppRun'), constants.X_OK);
  return root;
}

async function launchUnderXvfb(appCommand, args, sidecarPath, label) {
  const preflight = spawnSync('xvfb-run', ['--help'], { timeout: 10_000, stdio: 'ignore' });
  if (preflight.error) {
    throw new Error(`xvfb-run is required for the headless Linux launch gate: ${preflight.error}`);
  }
  return observeLaunchedApp({
    command: 'xvfb-run',
    args: ['-a', appCommand, ...args],
    detached: true,
    sidecarPath,
    platform: 'linux',
    label,
  });
}

async function smokeLinuxAppImage({ installers }) {
  const appImagePath = requireUniquePath(
    installers.filter((path) => path.endsWith('.AppImage')),
    'Linux AppImage',
  );
  const workRoot = await mkdtemp(join(tmpdir(), 'agistack-install-smoke-appimage-'));
  try {
    const appRoot = await extractAppImage(appImagePath, workRoot);
    const { sidecarPath, workspaceCorePath } = packagedRuntimePaths(appRoot, 'linux');
    const launch = await launchUnderXvfb(
      join(appRoot, 'AppRun'),
      launchArgumentsFor('linux'),
      sidecarPath,
      'extracted AppImage app',
    );
    const probe = await probeSidecarHealth({ sidecarPath, workspaceCorePath });
    return {
      kind: 'linux_appimage_extract_run',
      installer: basename(appImagePath),
      installed_to: appRoot,
      display: 'xvfb-run',
      launch_flags: launchArgumentsFor('linux'),
      sandbox_disabled: true,
      ...launch,
      sidecar_probe: probe,
    };
  } finally {
    await rm(workRoot, { recursive: true, force: true });
  }
}

function debPackageName(debPath) {
  const name = execFileSync('dpkg-deb', ['--field', debPath, 'Package'], {
    encoding: 'utf8',
  }).trim();
  if (!/^[a-z0-9][a-z0-9+.-]*$/u.test(name)) {
    throw new Error(`deb package name is invalid: ${name}`);
  }
  return name;
}

function debInstalledExecutable(packageName) {
  const owned = execFileSync('dpkg', ['-L', packageName], { encoding: 'utf8' })
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  const desktopEntry = requireUniquePath(
    owned.filter((path) => /^\/usr\/share\/applications\/[^/]+\.desktop$/u.test(path)),
    'installed deb desktop entry',
  );
  const execLine = execFileSync('grep', ['-m', '1', '^Exec=', desktopEntry], {
    encoding: 'utf8',
  }).trim();
  const executable = execLine
    .slice('Exec='.length)
    .trim()
    .match(/^"([^"]+)"|^(\S+)/u)
    ?.slice(1)
    .find(Boolean);
  if (!executable || !executable.startsWith(`/opt${sep}`)) {
    throw new Error(`installed deb executable must live under /opt: ${execLine}`);
  }
  return executable;
}

async function smokeLinuxDeb({ installers }) {
  const debPath = requireUniquePath(
    installers.filter((path) => path.endsWith('.deb')),
    'Linux deb',
  );
  const packageName = debPackageName(debPath);
  let installed = false;
  try {
    execFileSync('sudo', ['-n', 'dpkg', '-i', debPath], { stdio: 'inherit' });
    installed = true;
    const executable = debInstalledExecutable(packageName);
    const appRoot = dirname(executable);
    const { sidecarPath, workspaceCorePath } = packagedRuntimePaths(appRoot, 'linux');
    const launch = await launchUnderXvfb(
      executable,
      launchArgumentsFor('linux'),
      sidecarPath,
      'deb-installed app',
    );
    const probe = await probeSidecarHealth({ sidecarPath, workspaceCorePath });
    return {
      kind: 'linux_deb_system_install',
      installer: basename(debPath),
      installed_to: appRoot,
      display: 'xvfb-run',
      launch_flags: launchArgumentsFor('linux'),
      sandbox_disabled: true,
      ...launch,
      sidecar_probe: probe,
    };
  } finally {
    if (installed) {
      spawnSync('sudo', ['-n', 'dpkg', '-r', packageName], { stdio: 'ignore' });
    }
  }
}

async function smokeLinuxInstall(context) {
  return [await smokeLinuxAppImage(context), await smokeLinuxDeb(context)];
}

export async function runInstallLaunchSmoke({
  platform = process.platform,
  releaseRoot = resolve(desktopRoot, 'release'),
  evidenceDir = releaseEvidenceDir(),
  env = process.env,
} = {}) {
  const version = env.AGISTACK_EXPECTED_VERSION;
  const tag = env.AGISTACK_EXPECTED_TAG;
  if (!version || !tag) {
    throw new Error('AGISTACK_EXPECTED_VERSION and AGISTACK_EXPECTED_TAG are required');
  }
  const metadataResult = await verifyReleaseRootMetadata({
    releaseRoot,
    platform,
    version,
    expectedTag: tag,
    expectedVersion: version,
  });
  const installers = metadataResult.installers;
  const context = { installers, version, tag, evidenceDir };
  let legs;
  if (platform === 'darwin') {
    legs = [await smokeMacInstall(context)];
  } else if (platform === 'win32') {
    legs = [await smokeWindowsInstall(context)];
  } else if (platform === 'linux') {
    legs = await smokeLinuxInstall(context);
  } else {
    throw new Error(`unsupported install-launch smoke platform: ${platform}`);
  }
  const fragment = {
    schema: INSTALL_LAUNCH_SMOKE_SCHEMA,
    platform,
    version,
    tag,
    generated_at: new Date().toISOString(),
    legs,
    not_covered: [
      'renderer_window_content_not_asserted',
      'no_interactive_signin_or_cloud_grant_flows',
      'electron_updater_feed_not_contacted',
    ],
  };
  const path = await writeEvidenceFragment('install-launch-smoke.json', fragment, { evidenceDir });
  process.stdout.write(
    `INSTALL_LAUNCH_SMOKE_OK platform=${platform} legs=${legs.length} evidence=${path}\n`,
  );
  return fragment;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await runInstallLaunchSmoke();
}
