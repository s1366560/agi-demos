import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  desktopApiCredential,
  desktopLaunchCapability,
  DesktopApiClient,
} from '../api/client';
import {
  createCloudSocketBridge,
  desktopCloudSocketTransport,
} from '../api/cloudSocketBridge';
import type { DesktopRuntimeConfig, TerminalServiceResponse } from '../types';
import type { SandboxRuntimeCapabilities } from '../features/sandbox/sandboxRuntimeClient';
import {
  createCloudTerminalSession,
  resumeCloudTerminalSession,
} from '../features/sandbox/terminalSessionV2Client';
import {
  terminalSessionV2SocketUrl,
  type TerminalSessionV2,
} from '../features/sandbox/terminalSessionV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/terminal-lifecycle-authority';
export const DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.terminal-lifecycle-authority';
export const DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopTerminalRunAuthorityV2 = Readonly<{
  id: string;
  conversation_id: string;
  project_id: string;
  revision: number;
  environment: Readonly<{
    id: string;
    workspace_path: string;
  }>;
}>;

export type DesktopTerminalLifecycleBindingInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  run: DesktopTerminalRunAuthorityV2;
  capabilities: SandboxRuntimeCapabilities | null;
}>;

export type DesktopTerminalLifecycleStartedV2 = Readonly<{
  terminal: TerminalServiceResponse;
  session: TerminalSessionV2 | null;
}>;

export type DesktopTerminalLifecycleOpenSocketInputV2 = Readonly<{
  reconnect: boolean;
  afterSequence: number;
}>;

export interface DesktopTerminalLifecycleAuthorityV2 {
  readonly digest: string;
  readonly mode: DesktopRuntimeConfig['mode'];
  readonly start: (signal?: AbortSignal) => Promise<DesktopTerminalLifecycleStartedV2>;
  readonly openSocket: (
    input: DesktopTerminalLifecycleOpenSocketInputV2,
    signal?: AbortSignal,
  ) => Promise<WebSocket>;
  readonly currentSession: () => TerminalSessionV2 | null;
  readonly release: () => Promise<void>;
}

interface DesktopTerminalLifecycleBindingV2 {
  readonly mode: DesktopRuntimeConfig['mode'];
  readonly start: (signal?: AbortSignal) => Promise<DesktopTerminalLifecycleStartedV2>;
  readonly openSocket: (
    input: DesktopTerminalLifecycleOpenSocketInputV2,
    signal?: AbortSignal,
  ) => Promise<WebSocket>;
  readonly currentSession: () => TerminalSessionV2 | null;
  readonly revoke: () => void;
}

export interface DesktopTerminalLifecycleAuthorityServiceV2 {
  readonly bindLifecycle: (
    input: DesktopTerminalLifecycleBindingInputV2,
  ) => DesktopTerminalLifecycleBindingV2;
}

type LocalTerminalPortInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  run: DesktopTerminalRunAuthorityV2;
  signal?: AbortSignal;
}>;

type CloudTerminalPortInputV2 = LocalTerminalPortInputV2;

type LocalTerminalSocketPortInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  terminal: TerminalServiceResponse;
  afterSequence: number;
}>;

type ResumeCloudTerminalPortInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  session: TerminalSessionV2;
  signal?: AbortSignal;
}>;

type CloudTerminalSocketPortInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  session: TerminalSessionV2;
  afterSequence: number;
}>;

export interface DesktopTerminalLifecyclePortV2 {
  readonly seedLocalProxyAuthCookie: (input: LocalTerminalPortInputV2) => Promise<void>;
  readonly createLocalSession: (
    input: LocalTerminalPortInputV2,
  ) => Promise<TerminalServiceResponse>;
  readonly openLocalSocket: (input: LocalTerminalSocketPortInputV2) => WebSocket;
  readonly createCloudSession: (
    input: CloudTerminalPortInputV2,
  ) => Promise<TerminalSessionV2>;
  readonly resumeCloudSession: (
    input: ResumeCloudTerminalPortInputV2,
  ) => Promise<TerminalSessionV2>;
  readonly openCloudSocket: (input: CloudTerminalSocketPortInputV2) => WebSocket;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;

type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;

type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

export class DesktopTerminalLifecycleAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopTerminalLifecycleAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTerminalLifecycleAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-terminal-v2') {
    throw new RuntimeV2Error(
      'desktop_terminal_lifecycle_authority_config_invalid',
      'desktop terminal lifecycle authority requires desktop-terminal-v2 strategy',
    );
  }
  context.provide(
    DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_SERVICE_V2,
    createDesktopTerminalLifecycleAuthorityServiceV2(PRODUCTION_TERMINAL_PORT_V2),
  );
}

export const desktopTerminalLifecycleAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopTerminalLifecycleAuthorityV2,
});

export function createDesktopTerminalLifecycleAuthorityServiceV2(
  port: DesktopTerminalLifecyclePortV2,
): DesktopTerminalLifecycleAuthorityServiceV2 {
  requireTerminalPortV2(port);
  return Object.freeze({
    bindLifecycle: (input: DesktopTerminalLifecycleBindingInputV2) =>
      createDesktopTerminalLifecycleBindingV2(cloneBindingInputV2(input), port),
  });
}

export async function acquireDesktopTerminalLifecycleAuthorityV2(
  actions: DesktopRendererGenerationActionsV2 | null,
  input: DesktopTerminalLifecycleBindingInputV2,
): Promise<DesktopTerminalLifecycleAuthorityV2> {
  if (actions === null) {
    throw new DesktopTerminalLifecycleAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const bindingInput = cloneBindingInputV2(input);
  const admission =
    await actions.acquireServiceOperationLease<DesktopTerminalLifecycleAuthorityServiceV2>({
      service: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'session',
        tenant_id: bindingInput.config.tenantId,
        project_id: bindingInput.run.project_id,
        session_id: bindingInput.run.conversation_id,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTerminalLifecycleAuthorityUnavailableErrorV2(admission);
  }

  let binding: DesktopTerminalLifecycleBindingV2;
  try {
    binding = admission.useService((service) => service.bindLifecycle(bindingInput));
  } catch (error) {
    try {
      await admission.release();
    } catch {
      // The binding failure remains the primary lifecycle error.
    }
    throw error;
  }

  let released = false;
  let releasePromise: Promise<void> | undefined;
  const assertActive = (): void => {
    if (!released) return;
    throw new RuntimeV2Error(
      'desktop_terminal_lifecycle_released',
      'desktop terminal lifecycle authority has been released',
    );
  };
  return Object.freeze({
    digest: admission.digest,
    mode: binding.mode,
    start: async (signal?: AbortSignal) => {
      assertActive();
      return binding.start(signal);
    },
    openSocket: async (
      socketInput: DesktopTerminalLifecycleOpenSocketInputV2,
      signal?: AbortSignal,
    ) => {
      assertActive();
      return binding.openSocket(socketInput, signal);
    },
    currentSession: () => {
      assertActive();
      return binding.currentSession();
    },
    release: () => {
      if (releasePromise === undefined) {
        released = true;
        binding.revoke();
        releasePromise = Promise.resolve().then(() => admission.release());
      }
      return releasePromise;
    },
  });
}

function createDesktopTerminalLifecycleBindingV2(
  input: Readonly<{
    config: DesktopRuntimeConfig;
    run: DesktopTerminalRunAuthorityV2;
    capabilities: SandboxRuntimeCapabilities | null;
  }>,
  port: DesktopTerminalLifecyclePortV2,
): DesktopTerminalLifecycleBindingV2 {
  let active = true;
  let started: DesktopTerminalLifecycleStartedV2 | null = null;
  let startPromise: Promise<DesktopTerminalLifecycleStartedV2> | null = null;
  const assertActive = (): void => {
    if (active) return;
    throw new RuntimeV2Error(
      'desktop_terminal_lifecycle_released',
      'desktop terminal lifecycle authority has been released',
    );
  };

  const start = (signal?: AbortSignal): Promise<DesktopTerminalLifecycleStartedV2> => {
    assertActive();
    if (startPromise !== null) return startPromise;
    startPromise = (async () => {
      signal?.throwIfAborted();
      const result =
        input.config.mode === 'cloud'
          ? await startCloudTerminalV2(input, port, signal)
          : await startLocalTerminalV2(input, port, signal);
      assertActive();
      signal?.throwIfAborted();
      started = result;
      return result;
    })();
    return startPromise;
  };

  return Object.freeze({
    mode: input.config.mode,
    start,
    openSocket: async (
      socketInput: DesktopTerminalLifecycleOpenSocketInputV2,
      signal?: AbortSignal,
    ): Promise<WebSocket> => {
      assertActive();
      requireSocketInputV2(socketInput);
      signal?.throwIfAborted();
      if (started === null) {
        throw new RuntimeV2Error(
          'desktop_terminal_lifecycle_not_started',
          'desktop terminal lifecycle must start before opening a socket',
        );
      }

      let socket: WebSocket;
      if (input.config.mode === 'cloud') {
        let session = requireStartedCloudSessionV2(started);
        if (socketInput.reconnect) {
          session = await port.resumeCloudSession({
            config: input.config,
            session,
            signal,
          });
          requireCloudSessionAuthorityV2(session, input.run);
          assertActive();
          signal?.throwIfAborted();
          started = Object.freeze({
            session,
            terminal: terminalResponseFromCloudSessionV2(session),
          });
        }
        socket = port.openCloudSocket({
          config: input.config,
          session,
          afterSequence: socketInput.afterSequence,
        });
      } else {
        socket = port.openLocalSocket({
          config: input.config,
          terminal: started.terminal,
          afterSequence: socketInput.afterSequence,
        });
      }
      if (!active || signal?.aborted) {
        socket.close();
        assertActive();
        signal?.throwIfAborted();
      }
      return socket;
    },
    currentSession: () => {
      assertActive();
      return started?.session ?? null;
    },
    revoke: () => {
      active = false;
    },
  });
}

async function startCloudTerminalV2(
  input: Readonly<{
    config: DesktopRuntimeConfig;
    run: DesktopTerminalRunAuthorityV2;
    capabilities: SandboxRuntimeCapabilities | null;
  }>,
  port: DesktopTerminalLifecyclePortV2,
  signal?: AbortSignal,
): Promise<DesktopTerminalLifecycleStartedV2> {
  requireCloudTerminalCapabilitiesV2(input.capabilities);
  const session = await port.createCloudSession({
    config: input.config,
    run: input.run,
    signal,
  });
  requireCloudSessionAuthorityV2(session, input.run);
  return Object.freeze({
    session,
    terminal: terminalResponseFromCloudSessionV2(session),
  });
}

async function startLocalTerminalV2(
  input: Readonly<{
    config: DesktopRuntimeConfig;
    run: DesktopTerminalRunAuthorityV2;
  }>,
  port: DesktopTerminalLifecyclePortV2,
  signal?: AbortSignal,
): Promise<DesktopTerminalLifecycleStartedV2> {
  await port.seedLocalProxyAuthCookie({ config: input.config, run: input.run, signal });
  signal?.throwIfAborted();
  const terminal = await port.createLocalSession({
    config: input.config,
    run: input.run,
    signal,
  });
  requireLocalTerminalAuthorityV2(terminal, input.run);
  return Object.freeze({ session: null, terminal: Object.freeze({ ...terminal }) });
}

function requireCloudTerminalCapabilitiesV2(
  capabilities: SandboxRuntimeCapabilities | null,
): void {
  const interactive = capabilities?.terminal_interactive;
  const resume = capabilities?.terminal_resume;
  if (
    interactive?.availability === 'available' &&
    interactive.contract_version === 1 &&
    resume?.availability === 'available' &&
    resume.contract_version === 2
  ) {
    return;
  }
  const reasonCode =
    resume?.reason_code ?? interactive?.reason_code ?? 'terminal_session_v2_capability_unavailable';
  throw new RuntimeV2Error(reasonCode, 'desktop cloud terminal capability is unavailable');
}

function requireCloudSessionAuthorityV2(
  session: TerminalSessionV2,
  run: DesktopTerminalRunAuthorityV2,
): void {
  if (
    session.project_id === run.project_id &&
    session.conversation_id === run.conversation_id &&
    session.run_id === run.id &&
    session.run_revision === run.revision &&
    session.environment_id === run.environment.id &&
    session.cwd === run.environment.workspace_path
  ) {
    return;
  }
  throw new RuntimeV2Error(
    'desktop_terminal_authority_mismatch',
    'desktop terminal session does not match the pinned run authority',
  );
}

function requireLocalTerminalAuthorityV2(
  terminal: TerminalServiceResponse,
  run: DesktopTerminalRunAuthorityV2,
): void {
  if (
    terminal.success === true &&
    typeof terminal.session_id === 'string' &&
    terminal.session_id.trim().length > 0 &&
    terminal.project_id === run.project_id &&
    terminal.conversation_id === run.conversation_id &&
    terminal.run_id === run.id &&
    terminal.run_revision === run.revision &&
    terminal.environment_id === run.environment.id &&
    terminal.cwd === run.environment.workspace_path
  ) {
    return;
  }
  throw new RuntimeV2Error(
    'desktop_terminal_authority_mismatch',
    'desktop terminal session does not match the pinned run authority',
  );
}

function requireStartedCloudSessionV2(
  started: DesktopTerminalLifecycleStartedV2,
): TerminalSessionV2 {
  if (started.session !== null) return started.session;
  throw new RuntimeV2Error(
    'desktop_terminal_cloud_session_missing',
    'desktop cloud terminal lifecycle is missing its resumable session',
  );
}

function terminalResponseFromCloudSessionV2(
  session: TerminalSessionV2,
): TerminalServiceResponse {
  return Object.freeze({
    success: true,
    session_id: session.session_id,
    run_id: session.run_id,
    run_revision: session.run_revision,
    conversation_id: session.conversation_id,
    project_id: session.project_id,
    environment_id: session.environment_id,
    created_at: session.created_at,
    expires_at: session.expires_at,
    resumable: true,
    cwd: session.cwd,
  });
}

function cloneBindingInputV2(input: DesktopTerminalLifecycleBindingInputV2): Readonly<{
  config: DesktopRuntimeConfig;
  run: DesktopTerminalRunAuthorityV2;
  capabilities: SandboxRuntimeCapabilities | null;
}> {
  if (!input || typeof input !== 'object') {
    throw invalidBindingInputV2();
  }
  const config = cloneRuntimeConfigV2(input.config);
  const rawRun = input.run;
  const environment = rawRun?.environment;
  if (
    !isCanonicalIdentifierV2(rawRun?.id) ||
    !isCanonicalIdentifierV2(rawRun?.conversation_id) ||
    !isCanonicalIdentifierV2(rawRun?.project_id) ||
    !Number.isSafeInteger(rawRun?.revision) ||
    rawRun.revision < 1 ||
    !environment ||
    !isCanonicalIdentifierV2(environment.id) ||
    !isCanonicalIdentifierV2(environment.workspace_path) ||
    config.projectId !== rawRun.project_id
  ) {
    throw invalidBindingInputV2();
  }
  const run = Object.freeze({
    id: rawRun.id,
    conversation_id: rawRun.conversation_id,
    project_id: rawRun.project_id,
    revision: rawRun.revision,
    environment: Object.freeze({
      id: environment.id,
      workspace_path: environment.workspace_path,
    }),
  });
  return Object.freeze({
    config,
    run,
    capabilities: cloneCapabilitiesV2(input.capabilities),
  });
}

function cloneRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config?.apiBaseUrl,
    deviceAuthorizationBaseUrl: config?.deviceAuthorizationBaseUrl,
    apiKey: config?.apiKey,
    localApiToken: config?.localApiToken,
    tenantId: config?.tenantId,
    projectId: config?.projectId,
    workspaceId: config?.workspaceId,
    mode: config?.mode,
    workspaceRoot: config?.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalIdentifierV2(copy.tenantId) ||
    !isCanonicalIdentifierV2(copy.projectId)
  ) {
    throw invalidBindingInputV2();
  }
  return Object.freeze(copy);
}

function cloneCapabilitiesV2(
  capabilities: SandboxRuntimeCapabilities | null,
): SandboxRuntimeCapabilities | null {
  if (capabilities === null) return null;
  return Object.freeze({
    terminal_interactive: Object.freeze({ ...capabilities.terminal_interactive }),
    terminal_resume: Object.freeze({ ...capabilities.terminal_resume }),
    files: Object.freeze({ ...capabilities.files }),
    kasm_vnc: Object.freeze({ ...capabilities.kasm_vnc }),
  });
}

function invalidBindingInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_terminal_lifecycle_binding_invalid',
    'desktop terminal lifecycle requires a complete session run scope',
  );
}

function requireSocketInputV2(input: DesktopTerminalLifecycleOpenSocketInputV2): void {
  if (
    typeof input?.reconnect === 'boolean' &&
    Number.isSafeInteger(input.afterSequence) &&
    input.afterSequence >= 0
  ) {
    return;
  }
  throw new RuntimeV2Error(
    'desktop_terminal_socket_request_invalid',
    'desktop terminal socket request is invalid',
  );
}

function requireTerminalPortV2(port: DesktopTerminalLifecyclePortV2): void {
  const methods = [
    port?.seedLocalProxyAuthCookie,
    port?.createLocalSession,
    port?.openLocalSocket,
    port?.createCloudSession,
    port?.resumeCloudSession,
    port?.openCloudSocket,
  ];
  if (methods.every((method) => typeof method === 'function')) return;
  throw new RuntimeV2Error(
    'desktop_terminal_lifecycle_port_invalid',
    'desktop terminal lifecycle port is incomplete',
  );
}

function isCanonicalIdentifierV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

export function openDesktopTerminalSocketV2(
  url: string,
  credential: string,
  launchCapability: string,
  Socket: typeof WebSocket = WebSocket,
  resumeToken = '',
  afterSequence = 0,
): WebSocket {
  const protocols = launchCapability
    ? ['memstack.launch', launchCapability, 'memstack.auth', credential]
    : ['memstack.auth', credential];
  if (resumeToken) protocols.push('memstack.terminal-v2', resumeToken);
  const target = new URL(url);
  if (Number.isSafeInteger(afterSequence) && afterSequence > 0) {
    target.searchParams.set('after_sequence', String(afterSequence));
  }
  return new Socket(target.toString(), protocols);
}

const PRODUCTION_TERMINAL_PORT_V2: DesktopTerminalLifecyclePortV2 = Object.freeze({
  seedLocalProxyAuthCookie: async ({ config }: LocalTerminalPortInputV2) => {
    await new DesktopApiClient(config).seedProxyAuthCookie();
  },
  createLocalSession: ({ config, run }: LocalTerminalPortInputV2) =>
    new DesktopApiClient(config).startTerminal(run.id, run.revision),
  openLocalSocket: ({
    config,
    terminal,
    afterSequence,
  }: LocalTerminalSocketPortInputV2) => {
    const api = new DesktopApiClient(config);
    return openDesktopTerminalSocketV2(
      api.terminalProxyUrl(terminal.session_id, terminal.project_id),
      desktopApiCredential(config),
      desktopLaunchCapability(config),
      WebSocket,
      '',
      afterSequence,
    );
  },
  createCloudSession: async ({ config, run, signal }: CloudTerminalPortInputV2) => {
    const result = await createCloudTerminalSession(
      config,
      run.project_id,
      run.id,
      run.revision,
      signal,
    );
    return result.value;
  },
  resumeCloudSession: async ({
    config,
    session,
    signal,
  }: ResumeCloudTerminalPortInputV2) => {
    const result = await resumeCloudTerminalSession(
      config,
      session.project_id,
      session.session_id,
      session.resume_token,
      signal,
    );
    return result.value;
  },
  openCloudSocket: ({
    config,
    session,
    afterSequence,
  }: CloudTerminalSocketPortInputV2) => {
    const transport = desktopCloudSocketTransport();
    if (transport === null) {
      throw new RuntimeV2Error(
        'desktop_terminal_cloud_socket_transport_unavailable',
        'desktop terminal cloud socket requires the native vault-bound bridge',
      );
    }
    return createCloudSocketBridge(
      {
        kind: 'terminal',
        url: terminalSessionV2SocketUrl(config.apiBaseUrl, session, afterSequence),
        scope: {
          tenant_id: config.tenantId,
          project_id: session.project_id,
          workspace_id: config.workspaceId || null,
          conversation_id: session.conversation_id,
        },
        terminal: {
          session_id: session.session_id,
          resume_token: session.resume_token,
        },
      },
      transport,
    ) as unknown as WebSocket;
  },
});

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_TERMINAL_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_terminal_lifecycle_authority_catalog_missing',
      'desktop terminal lifecycle authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
