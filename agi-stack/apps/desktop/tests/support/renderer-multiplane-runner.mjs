/** Real sidecar/TypeScript protocol runner. This does not launch Electron or prove native QA. */
import { createRequire } from 'node:module';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(import.meta.url);
const { SidecarSupervisor } = require(
  '/tmp/agistack-desktop-test-dist/apps/desktop/electron/main/sidecarSupervisor.js',
);
const { RendererPluginRuntimeV2, DesktopRendererDeliveryReconcilerV2, createDesktopRendererDefinitionsV2 } = require(
  '/tmp/agistack-desktop-test-dist/packages/plugin-runtime/src/index.js',
);
const ownerId = 'postgres-integration-renderer';
let directory;
let supervisor;
let runtime;
let reconciler;
let initialized = false;

async function close() {
  let failed = false;
  try { await reconciler?.close(); } catch { failed = true; }
  try { await supervisor?.stop(); } catch { failed = true; }
  try { if (directory) await rm(directory, { recursive: true, force: true }); } catch { failed = true; }
  reconciler = undefined;
  supervisor = undefined;
  directory = undefined;
  runtime = undefined;
  initialized = false;
  if (failed) throw new Error('renderer_runner_cleanup_failed');
}

async function initialize(command) {
  if (initialized || supervisor) throw new Error('renderer_runner_already_initialized');
  const binary = process.env.AGISTACK_REAL_SIDECAR;
  const core = process.env.AGISTACK_REAL_WORKSPACE_CORE;
  if (!binary || !core) throw new Error('renderer_runner_binary_required');
  directory = await mkdtemp(join(tmpdir(), 'cordis-renderer-multiplane-'));
  const workspaceRoot = join(directory, 'workspace');
  await mkdir(workspaceRoot);
  supervisor = new SidecarSupervisor({
    binaryPath: resolve(binary),
    workspaceCoreBinaryPath: resolve(core),
    dataDirectory: join(directory, 'data'),
    workspaceRoot,
    legacyDataDirectories: [],
    handshakeTimeoutMs: 30_000,
  });
  await supervisor.start();
  try {
    await supervisor.invoke('plugin_renderer_data_plane_credential_import_v2', { input: {
      version: 2,
      api_base_url: command.base_url,
      data_plane_id: 'desktop-renderer-v2',
      credential: command.renderer_credential,
      ack_participation: true,
    } });
  } finally {
    delete command.renderer_credential;
  }
  runtime = new RendererPluginRuntimeV2('desktop-renderer', createDesktopRendererDefinitionsV2());
  reconciler = new DesktopRendererDeliveryReconcilerV2(
    runtime,
    (token, receipt) => supervisor.invoke('platform_plugin_renderer_receipt_submit_v2', {
      owner_id: ownerId, delivery_token: token, receipt,
    }),
    () => supervisor.invoke('platform_plugin_renderer_owner_retire_v2', { owner_id: ownerId }),
  );
  await supervisor.invoke('platform_plugin_authority_select_v2', { mode: 'cloud' });
  initialized = true;
  return { ok: true, command: 'init' };
}

async function enableSidecar(command) {
  if (!initialized) throw new Error('renderer_runner_not_initialized');
  try {
    await supervisor.invoke('plugin_data_plane_credential_import_v2', { input: {
      version: 2,
      api_base_url: command.base_url,
      data_plane_id: 'desktop-sidecar-v2',
      credential: command.sidecar_credential,
      ack_participation: true,
    } });
  } finally {
    delete command.sidecar_credential;
  }
  return { ok: true, command: 'enable_sidecar' };
}

async function apply(command) {
  if (!initialized) throw new Error('renderer_runner_not_initialized');
  const delivery = await supervisor.invoke('platform_plugin_renderer_delivery_current_v2', { owner_id: ownerId });
  if (delivery?.source !== 'cloud' || delivery.distribution.envelope.version !== command.version) {
    throw new Error('renderer_runner_requested_version_mismatch');
  }
  const receipt = await reconciler.apply(delivery);
  if (!receipt || (command.expected_renderer_status && receipt.status !== command.expected_renderer_status)) {
    throw new Error('renderer_runner_receipt_mismatch');
  }
  return {
    ok: true,
    command: 'apply',
    receipt,
    active_digest: runtime.getSnapshot()?.snapshot.digest ?? null,
  };
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
try {
  for await (const line of input) {
    let operation = 'invalid';
    try {
      const command = JSON.parse(line);
      operation = ['init', 'enable_sidecar', 'apply', 'close'].includes(command.command) ? command.command : 'invalid';
      let response;
      if (operation === 'init') response = await initialize(command);
      else if (operation === 'enable_sidecar') response = await enableSidecar(command);
      else if (operation === 'apply') response = await apply(command);
      else if (operation === 'close') { await close(); response = { ok: true, command: 'close' }; }
      else throw new Error('renderer_runner_command_invalid');
      process.stdout.write(`${JSON.stringify(response)}\n`);
      if (operation === 'close') break;
    } catch {
      // Errors can originate in private control replies; never echo their payload or input.
      process.stdout.write(`${JSON.stringify({ ok: false, command: operation, error: 'renderer_multiplane_runner_failed' })}\n`);
      process.exitCode = 1;
      break;
    }
  }
} finally {
  input.close();
  try { await close(); } catch { process.exitCode = 1; }
}
