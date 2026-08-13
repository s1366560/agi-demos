import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const mainSource = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const preloadSource = readFileSync(new URL('../electron/preload/index.ts', import.meta.url), 'utf8');
const supervisorSource = readFileSync(
  new URL('../electron/main/sidecarSupervisor.ts', import.meta.url),
  'utf8',
);
const sidecarControlSource = readFileSync(
  new URL('../sidecar/src/control.rs', import.meta.url),
  'utf8',
);
const sidecarHelperSource = readFileSync(
  new URL('../sidecar/src/workspace_core_helper.rs', import.meta.url),
  'utf8',
);
const builderConfig = readFileSync(new URL('../electron-builder.yml', import.meta.url), 'utf8');
const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));

test('Electron passes the helper path to the authenticated Sidecar bootstrap without spawning it', () => {
  assert.match(mainSource, /function workspaceCoreBinaryPath\(\): string/u);
  assert.match(mainSource, /workspaceCoreBinaryPath:\s*workspaceCoreBinaryPath\(\)/u);
  assert.match(mainSource, /const SIDECAR_HANDSHAKE_TIMEOUT_MS = 180_000/u);
  assert.match(mainSource, /handshakeTimeoutMs:\s*SIDECAR_HANDSHAKE_TIMEOUT_MS/u);
  assert.match(mainSource, /\.cache\/avernet-bcs\/target\/debug/u);
  assert.doesNotMatch(mainSource, /third_party\/avernet-bcs\/target\/debug/u);
  assert.doesNotMatch(mainSource, /spawn\([^)]*memstack-workspace-core/u);
  assert.match(supervisorSource, /workspaceCoreBinaryPath:\s*string/u);
  assert.match(supervisorSource, /workspaceCoreBinaryPath:\s*this\.#options\.workspaceCoreBinaryPath/u);
  assert.match(sidecarControlSource, /workspace_core_binary_path:\s*PathBuf/u);
  assert.match(sidecarControlSource, /WorkspaceCoreSupervisor::start/u);
});

test('Sidecar owns private helper credentials, capped recovery, and redacted status', () => {
  assert.match(sidecarHelperSource, /const DEFAULT_MAX_RESTART_ATTEMPTS:\s*usize\s*=\s*4/u);
  assert.match(sidecarHelperSource, /\.arg\("--desktop-control"\)/u);
  assert.match(sidecarHelperSource, /\.env_clear\(\)/u);
  assert.doesNotMatch(sidecarHelperSource, /\.arg\("--config-dir"\)/u);
  assert.doesNotMatch(sidecarHelperSource, /\.env\("WORKSPACE_CORE_/u);
  assert.doesNotMatch(sidecarHelperSource, /\.env\("BCS_SECRET_/u);
  assert.match(sidecarHelperSource, /\.stdin\(Stdio::piped\(\)\)/u);
  assert.match(sidecarHelperSource, /\.stdout\(Stdio::piped\(\)\)/u);
  assert.match(sidecarHelperSource, /desktop-local/u);
  assert.match(sidecarHelperSource, /desktop_initialize/u);
  assert.match(sidecarHelperSource, /desktop_ready/u);
  assert.match(sidecarHelperSource, /desktop_shutdown/u);
  assert.match(sidecarHelperSource, /verify_slice/u);
  assert.match(sidecarHelperSource, /kill_on_drop\(true\)/u);
  assert.doesNotMatch(sidecarHelperSource, /service_token.*Serialize/iu);
  assert.doesNotMatch(sidecarHelperSource, /provider_.*token.*Serialize/iu);
  assert.match(sidecarHelperSource, /cutover_state/u);
  assert.match(sidecarHelperSource, /restart_generation/u);
  assert.match(mainSource, /SIDECAR_COMMANDS[\s\S]*workspace_core_status/u);
  assert.match(preloadSource, /allowedCommands[\s\S]*workspace_core_status/u);
  assert.match(mainSource, /workspaceCore:\s*await workspaceCoreCapabilitySnapshot/u);
  assert.match(mainSource, /terminalFailureReason/u);
});

test('Sidecar freezes the exact Registry, Provider, and Plan runtime endpoints', () => {
  assert.match(sidecarHelperSource, /internal\/v1\/workspace-core\/provider/u);
  assert.match(sidecarHelperSource, /internal\/v1\/workspace-core\/plan-dispatch/u);
  assert.match(sidecarHelperSource, /agent_registry_url:\s*&config\.sidecar_api_base_url/u);
});

test('desktop packages build, stage, and sign the workspace core helper as a nested runtime', () => {
  assert.match(packageJson.scripts['build:workspace-core'], /build-workspace-core\.mjs/u);
  assert.match(packageJson.scripts['stage:workspace-core'], /stage-workspace-core\.mjs/u);
  for (const script of ['package:electron', 'release:electron']) {
    assert.match(packageJson.scripts[script], /build:workspace-core/u);
    assert.match(packageJson.scripts[script], /stage:workspace-core/u);
  }
  assert.match(builderConfig, /from:\s*build\/workspace-core/u);
  assert.match(builderConfig, /to:\s*workspace-core/u);
  assert.match(
    builderConfig,
    /Contents\/Resources\/workspace-core\/memstack-workspace-core/u,
  );
});
