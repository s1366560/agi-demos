import { StrictMode } from 'react';

import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';

import { KasmVNCViewer } from '../../../components/agent/sandbox/KasmVNCViewer';

const rfbMocks = vi.hoisted(() => ({
  close: vi.fn(),
  construct: vi.fn(),
  disconnect: vi.fn(),
}));

vi.mock('@/vendor/kasmvnc/core/rfb.js', () => ({
  RfbInitializationError: class extends Error {},
  default: class MockRFB {
    _rfbConnectionState = '';
    _sock = { close: rfbMocks.close };
    mouseButtonMapper: unknown;
    scaleViewport = false;
    resizeSession = false;
    clipViewport = false;
    background = '';
    qualityLevel = 0;

    constructor(...args: unknown[]) {
      rfbMocks.construct(...args);
    }

    addEventListener = vi.fn();
    removeEventListener = vi.fn();
    dispose = async () => {
      rfbMocks.disconnect();
    };
    sendCredentials = vi.fn();

    disconnect() {
      rfbMocks.disconnect();
    }
  },
}));

vi.mock('@/vendor/kasmvnc/core/mousebuttonmapper.js', () => ({
  default: class MockMouseButtonMapper {
    set = vi.fn();
  },
  XVNC_BUTTONS: {
    LEFT_BUTTON: 1,
    MIDDLE_BUTTON: 2,
    RIGHT_BUTTON: 4,
    BACK_BUTTON: 8,
    FORWARD_BUTTON: 16,
  },
}));

class Socket extends EventTarget {
  static instances: Socket[] = [];
  static CLOSED = 3;
  static CLOSING = 2;
  readyState = 0;
  send = vi.fn();
  constructor(
    readonly url: string,
    readonly protocols: string[]
  ) {
    super();
    Socket.instances.push(this);
  }
  close() {
    this.readyState = 3;
    this.dispatchEvent(new Event('close'));
  }
}

const props = {
  projectId: 'project',
  sandboxId: 'sandbox',
  wsUrl: 'ws://localhost/desktop',
  showToolbar: false,
};

describe('KasmVNCViewer', () => {
  let runtime: RendererPluginRuntimeV2;
  let admission: WebOperationAdmissionV2;
  let uninstall: () => void;

  beforeEach(async () => {
    runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
    await runtime.bootstrap(profile);
    admission = new WebOperationAdmissionV2(runtime);
    admission.setEnabled(true);
    uninstall = installWebOperationAdmissionV2(admission);
    Socket.instances = [];
    vi.stubGlobal('WebSocket', Socket);
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'kasm-fixture-token' } })
    );
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(async () => {
    cleanup();
    admission.setEnabled(false);
    await admission.close();
    uninstall();
    await runtime.close();
    vi.unstubAllGlobals();
    localStorage.removeItem('memstack-auth-storage');
    vi.useRealTimers();
  });

  it('creates only one RFB session when mounted in StrictMode', async () => {
    const view = render(
      <StrictMode>
        <KasmVNCViewer {...props} />
      </StrictMode>
    );
    expect(rfbMocks.construct).not.toHaveBeenCalled();
    expect(Socket.instances).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(rfbMocks.construct).toHaveBeenCalledTimes(1);
    expect(Socket.instances).toHaveLength(1);
    expect(view.container.querySelectorAll('textarea')).toHaveLength(1);
    view.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(rfbMocks.disconnect).toHaveBeenCalledTimes(1);
    expect(Socket.instances[0]?.readyState).toBe(Socket.CLOSED);
  });

  it('does not create an RFB session after unmounting', async () => {
    const { unmount } = render(<KasmVNCViewer {...props} />);
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(rfbMocks.construct).not.toHaveBeenCalled();
    expect(Socket.instances).toHaveLength(0);
  });
});
