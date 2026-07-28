import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import { createRoot, type Root } from 'react-dom/client';

import { SessionSandboxTools } from '../features/sandbox/SessionSandboxTools';
import type {
  SandboxFileDownloadRequest,
  SandboxFileListRequest,
  SandboxFileReadRequest,
  SandboxRuntimeClient,
} from '../features/sandbox/sandboxRuntimeClient';
import type { SessionSandboxRuntimeSurface } from '../features/sandbox/useSandboxRuntimeSurface';
import { I18nProvider } from '../i18n';
import '../styles.css';
import './parityRuntimeQa.css';

declare global {
  var __sandboxRuntimeQaRoot: Root | undefined;
}

type SandboxQaState = 'ready' | 'loading' | 'unavailable' | 'stale' | 'error';
const requestedState = new URLSearchParams(window.location.search).get('state');
const qaState: SandboxQaState =
  requestedState === 'loading' ||
  requestedState === 'unavailable' ||
  requestedState === 'stale' ||
  requestedState === 'error'
    ? requestedState
    : 'ready';

const fileListing = {
  contract_version: 1 as const,
  authority: 'sandbox' as const,
  isolation: 'isolated' as const,
  root: '/',
  path: '/',
  entries: [
    {
      path: '/reports',
      name: 'reports',
      kind: 'directory' as const,
      size_bytes: null,
      mime_type: null,
    },
    {
      path: '/parity-report.md',
      name: 'parity-report.md',
      kind: 'file' as const,
      size_bytes: 142,
      mime_type: 'text/markdown',
    },
  ],
  cursor: null,
  revision: 11,
};

const fileContent = {
  contract_version: 1 as const,
  authority: 'sandbox' as const,
  isolation: 'isolated' as const,
  path: '/parity-report.md',
  encoding: 'utf-8' as const,
  content: '# Parity report\n\nSandbox files are scoped to the active project.',
  mime_type: 'text/markdown',
  size_bytes: 67,
  revision: 'sha256:fixture',
  truncated: false,
};

const fileClient: SandboxRuntimeClient = {
  async createTerminalSession() {
    throw new Error('terminal_session_v2_not_exercised_by_file_fixture');
  },
  async resumeTerminalSession() {
    throw new Error('terminal_session_v2_not_exercised_by_file_fixture');
  },
  listFiles: (async (
    request: string | SandboxFileListRequest,
  ) => {
    if (typeof request === 'string') return fileListing;
    return { status: 'ready', value: { ...fileListing, path: request.path } };
  }) as SandboxRuntimeClient['listFiles'],
  readFile: (async (
    request: string | SandboxFileReadRequest,
  ) => {
    if (typeof request === 'string') return new TextEncoder().encode(fileContent.content).buffer;
    return { status: 'ready', value: { ...fileContent, path: request.path } };
  }) as SandboxRuntimeClient['readFile'],
  downloadFile: (async (
    request: string | SandboxFileDownloadRequest,
  ) => {
    const path = typeof request === 'string' ? request : request.path;
    const bytes = new Blob([fileContent.content], { type: 'text/markdown' });
    if (typeof request === 'string') return bytes;
    return {
      status: 'ready',
      value: {
        contract_version: 1,
        authority: 'sandbox',
        isolation: 'isolated',
        path,
        filename: 'parity-report.md',
        mime_type: 'text/markdown',
        bytes,
      },
    };
  }) as SandboxRuntimeClient['downloadFile'],
};

const available = {
  availability: 'available' as const,
  contract_version: 1,
  reason_code: null,
};

const readyRuntime: SessionSandboxRuntimeSurface = {
  capabilityStatus: 'ready',
  capabilityLoadReason: null,
  capabilities: {
    service_version: '0.1.0',
    contract_version: 2,
    terminal_interactive: available,
    terminal_resume: {
      availability: 'degraded',
      contract_version: 2,
      reason_code: 'terminal_resume_reconnect_in_progress',
    },
    files: available,
    kasm_vnc: available,
  },
  filesCapability: available,
  remoteDesktopCapability: available,
  runtimeClient: fileClient,
  fileClient,
  remoteDesktopSession: {
    descriptor: {
      contract_version: 1,
      project_id: 'project-parity-qa',
      protocol: 'kasmvnc-1',
      proxy_url:
        '/api/v1/projects/project-parity-qa/sandbox/desktop/proxy/vnc.html',
      auth_mode: 'scoped_http_only_cookie',
    },
    frame_url: 'about:blank',
  },
  remoteDesktopRevision: 1,
  remoteDesktopStatus: 'ready',
  remoteDesktopReason: null,
  remoteDesktopResolution: '1920x1080',
  setRemoteDesktopResolution() {},
  reloadCapabilities() {},
  async startRemoteDesktop() {},
};

const unavailableCapability = {
  availability: 'unavailable' as const,
  contract_version: 1,
  reason_code: 'sandbox_runtime_capability_contract_unavailable',
};

function runtimeForQaState(state: SandboxQaState): SessionSandboxRuntimeSurface {
  if (state === 'loading' || state === 'unavailable') {
    return {
      ...readyRuntime,
      capabilityStatus: state,
      capabilityLoadReason:
        state === 'unavailable'
          ? 'sandbox_runtime_capability_request_failed'
          : null,
      capabilities: null,
      filesCapability: unavailableCapability,
      remoteDesktopCapability: unavailableCapability,
      runtimeClient: null,
      fileClient: null,
      remoteDesktopSession: null,
      remoteDesktopStatus: 'unavailable',
      remoteDesktopReason: 'sandbox_runtime_capability_contract_unavailable',
    };
  }
  if (state === 'stale') {
    return {
      ...readyRuntime,
      remoteDesktopSession: null,
      remoteDesktopStatus: 'starting',
      remoteDesktopReason: 'kasm_remote_desktop_reconnecting',
    };
  }
  if (state === 'error') {
    return {
      ...readyRuntime,
      remoteDesktopSession: null,
      remoteDesktopStatus: 'error',
      remoteDesktopReason: 'kasm_remote_desktop_request_failed',
    };
  }
  return readyRuntime;
}

function SandboxRuntimeQa() {
  const runtime = runtimeForQaState(qaState);
  return (
    <Theme accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main className="parity-runtime-qa">
        <header data-qa-state={qaState}>
          <div>
            <h1>Sandbox Runtime</h1>
            <p>
              Credential-free KasmVNC framing and project-scoped sandbox file authority.
            </p>
          </div>
        </header>
        <div className="parity-runtime-qa__surface">
          <SessionSandboxTools runtime={runtime} />
        </div>
      </main>
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__sandboxRuntimeQaRoot ??= createRoot(container);
globalThis.__sandboxRuntimeQaRoot.render(
  <I18nProvider>
    <SandboxRuntimeQa />
  </I18nProvider>,
);
