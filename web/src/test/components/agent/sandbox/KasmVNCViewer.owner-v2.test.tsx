import React, { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({
  owner: {} as object,
  available: true,
  snapshot: { owner: {} as object, available: true },
  listeners: new Set<() => void>(),
  sessions: [] as any[],
  rfbs: [] as any[],
  constructorFailure: null as Error | null,
}));
vi.mock('../../../../plugins/webOperationAdmissionV2', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getWebOperationAvailabilityV2: () => state.snapshot,
  subscribeWebOperationAvailabilityV2: (listener: () => void) => {
    state.listeners.add(listener);
    return () => state.listeners.delete(listener);
  },
}));
vi.mock('../../../../vendor/kasmvnc/core/mousebuttonmapper.js', () => ({
  default: class {
    set = vi.fn();
  },
  XVNC_BUTTONS: {
    LEFT_BUTTON: 1,
    MIDDLE_BUTTON: 2,
    RIGHT_BUTTON: 3,
    BACK_BUTTON: 4,
    FORWARD_BUTTON: 5,
  },
}));
vi.mock('../../../../vendor/kasmvnc/core/rfb.js', () => ({
  RfbInitializationError: class extends Error {
    disposal = Promise.resolve();
  },
  default: class {
    callbacks = new Map<string, Set<(event: unknown) => void>>();
    disposed = false;
    dispose = vi.fn(async () => {
      this.disposed = true;
    });
    sendCredentials = vi.fn();
    scaleViewport = false;
    resizeSession = false;
    clipViewport = true;
    background = '';
    qualityLevel = 0;
    mouseButtonMapper: any;
    constructor(
      public target: HTMLElement,
      public touch: HTMLTextAreaElement,
      public socket: WebSocket
    ) {
      if (state.constructorFailure) throw state.constructorFailure;
      state.rfbs.push(this);
    }
    addEventListener(name: string, callback: (event: unknown) => void) {
      const list = this.callbacks.get(name) ?? new Set();
      list.add(callback);
      this.callbacks.set(name, list);
    }
    removeEventListener(name: string, callback: (event: unknown) => void) {
      this.callbacks.get(name)?.delete(callback);
    }
    emit(name: string, detail: unknown = {}) {
      this.callbacks.get(name)?.forEach((fn) => fn({ detail }));
    }
  },
}));
vi.mock('../../../../services/kasmRetainedSessionV2', () => ({
  KasmRetainedSessionV2: class {
    options: any;
    controller = new AbortController();
    resource: any;
    attempt: any;
    operation: any;
    attemptController = new AbortController();
    parentCleanup: any;
    constructor(options: any) {
      this.options = options;
      state.sessions.push(this);
    }
    connect = vi.fn(async () => {
      this.operation = {
        owner: state.owner,
        signal: this.controller.signal,
        check: () => {
          if (this.controller.signal.aborted) throw new DOMException('Retired', 'AbortError');
        },
        runChild: async (work: any) => work(this.operation),
      };
      this.parentCleanup = this.options.onAdmitted?.(this.operation);
      this.options.onStateChange('connecting');
      this.next();
    });
    next() {
      let active = true;
      const controller = new AbortController();
      this.attemptController = controller;
      this.attempt = {
        signal: controller.signal,
        runChild: async (work: any) =>
          work({
            ...this.operation,
            signal: controller.signal,
            check: () => {
              this.operation.check();
              controller.signal.throwIfAborted();
            },
          }),
        check: () => {
          this.operation.check();
          if (!active) throw new DOMException('Old attempt', 'AbortError');
        },
        connected: () => this.options.onStateChange('connected'),
        disconnected: () => {
          active = false;
          controller.abort(new DOMException('Retired', 'AbortError'));
          void this.resource.dispose();
        },
        fail: () => {
          active = false;
        },
      };
      this.resource = this.options.createAttempt({} as WebSocket, this.operation, this.attempt);
      if (!active) void this.resource.dispose();
    }
    disconnect = vi.fn(async () => {
      this.controller.abort();
      this.attemptController.abort();
      await this.resource?.dispose();
      await this.parentCleanup?.();
    });
  },
}));
import { KasmVNCViewer } from '../../../../components/agent/sandbox/KasmVNCViewer';
import { RfbInitializationError } from '../../../../vendor/kasmvnc/core/rfb.js';
const props = {
  projectId: 'project',
  sandboxId: 'sandbox',
  wsUrl: 'ws://localhost/api/v1/projects/project/sandbox/desktop/ws',
};
beforeEach(() => {
  state.owner = {};
  state.available = true;
  state.snapshot = { owner: state.owner, available: true };
  state.sessions = [];
  state.rfbs = [];
  state.constructorFailure = null;
  vi.clearAllMocks();
  vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it('passes structural identity and injected socket to RFB without another connection', async () => {
  const onConnect = vi.fn();
  render(<KasmVNCViewer {...props} onConnect={onConnect} />);
  await act(async () => {});
  const session = state.sessions[0],
    rfb = state.rfbs[0];
  expect(session.options).toMatchObject(props);
  expect(rfb.socket).toEqual({});
  act(() => rfb.emit('connect'));
  expect(onConnect).toHaveBeenCalledOnce();
  expect(rfb.mouseButtonMapper.set).toHaveBeenCalledTimes(5);
  expect(rfb.resizeSession).toBe(true);
});
it('retirement immediately blocks late credentials and clipboard while disposing once', async () => {
  const view = render(<KasmVNCViewer {...props} />);
  await act(async () => {});
  const rfb = state.rfbs[0];
  const credentials = [...rfb.callbacks.get('credentialsrequired')][0];
  const clipboard = [...rfb.callbacks.get('clipboard')][0];
  view.unmount();
  credentials({ detail: {} });
  clipboard({ detail: { text: 'old' } });
  await act(async () => {});
  expect(rfb.sendCredentials).not.toHaveBeenCalled();
  expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  expect(rfb.dispose).toHaveBeenCalledOnce();
  expect(rfb.touch.isConnected).toBe(false);
});
it('an old disconnect cannot clear the replacement attempt', async () => {
  render(<KasmVNCViewer {...props} />);
  await act(async () => {});
  const session = state.sessions[0],
    old = state.rfbs[0];
  const late = [...old.callbacks.get('disconnect')][0];
  act(() => old.emit('disconnect', { reason: 'network' }));
  await act(async () => {});
  act(() => session.next());
  const next = state.rfbs[1];
  act(() => next.emit('connect'));
  late({ detail: { reason: 'late' } });
  expect(next.dispose).not.toHaveBeenCalled();
  expect(screen.getByText('Connected')).toBeDefined();
});
it('owner switch closes old RFB and captures a new session identity', async () => {
  render(<KasmVNCViewer {...props} />);
  await act(async () => {});
  const old = state.rfbs[0];
  act(() => {
    state.owner = {};
    state.snapshot = { owner: state.owner, available: true };
    state.listeners.forEach((fn) => fn());
  });
  await act(async () => {});
  expect(old.dispose).toHaveBeenCalledOnce();
  expect(state.sessions).toHaveLength(2);
  expect(state.sessions[1].operation.owner).toBe(state.owner);
});
it('StrictMode stops the first attempt and leaves only the new touch input', async () => {
  const view = render(
    <StrictMode>
      <KasmVNCViewer {...props} />
    </StrictMode>
  );
  await act(async () => {});
  expect(state.sessions).toHaveLength(2);
  expect(state.rfbs[0].dispose).toHaveBeenCalledOnce();
  expect(view.container.querySelectorAll('textarea')).toHaveLength(1);
});

it('attempt retirement cleans a fullscreen request that resolves late', async () => {
  let resolve!: () => void;
  const pending = new Promise<void>((r) => {
    resolve = r;
  });
  let fullscreen: Element | null = null;
  const exit = vi.fn(async () => {
    fullscreen = null;
  });
  Object.defineProperty(document, 'fullscreenElement', {
    configurable: true,
    get: () => fullscreen,
  });
  Object.defineProperty(document, 'exitFullscreen', { configurable: true, value: exit });
  const view = render(<KasmVNCViewer {...props} />);
  await act(async () => {});
  const target = view.container.firstElementChild as HTMLElement;
  Object.defineProperty(target, 'requestFullscreen', {
    configurable: true,
    value: async () => {
      await pending;
      fullscreen = target;
    },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' }));
  act(() => state.rfbs[0].emit('disconnect', { reason: 'network' }));
  await act(async () => resolve());
  expect(exit).toHaveBeenCalledOnce();
  expect(fullscreen).toBeNull();
});

it('disabled owner immediately hides connected state and cannot reconnect', async () => {
  render(<KasmVNCViewer {...props} />);
  await act(async () => {});
  act(() => state.rfbs[0].emit('connect'));
  expect(screen.getByText('Connected')).toBeDefined();
  act(() => {
    state.snapshot = { owner: state.owner, available: false };
    state.listeners.forEach((fn) => fn());
  });
  expect(screen.queryByText('Connected')).toBeNull();
  fireEvent.click(screen.getAllByRole('button', { name: 'Reconnect' })[0]!);
  expect(state.sessions).toHaveLength(1);
});

it('constructor failure keeps the returned partial-resource cleanup in the attempt drain', async () => {
  let resolve!: () => void;
  const disposal = new Promise<void>((r) => {
    resolve = r;
  });
  state.constructorFailure = Object.assign(new RfbInitializationError('initialization failed'), {
    disposal,
  });
  const view = render(<KasmVNCViewer {...props} />);
  await act(async () => {});
  expect(view.container.querySelectorAll('textarea')).toHaveLength(1);
  await act(async () => resolve());
  expect(view.container.querySelectorAll('textarea')).toHaveLength(0);
});

it('RemoteDesktopViewer forwards declared project and sandbox identity', async () => {
  const { RemoteDesktopViewer } =
    await import('../../../../components/agent/sandbox/RemoteDesktopViewer');
  render(
    <RemoteDesktopViewer
      projectId="declared-project"
      sandboxId="declared-sandbox"
      desktopStatus={{ running: true } as import('../../../../types/agent').DesktopStatus}
    />
  );
  await act(async () => {});
  expect(state.sessions[0].options).toMatchObject({
    projectId: 'declared-project',
    sandboxId: 'declared-sandbox',
  });
});
it('missing project never opens a desktop connection', async () => {
  const { RemoteDesktopViewer } =
    await import('../../../../components/agent/sandbox/RemoteDesktopViewer');
  render(
    <RemoteDesktopViewer
      projectId=""
      sandboxId="sandbox"
      desktopStatus={{ running: true } as import('../../../../types/agent').DesktopStatus}
    />
  );
  await act(async () => {});
  expect(state.sessions).toHaveLength(0);
});
