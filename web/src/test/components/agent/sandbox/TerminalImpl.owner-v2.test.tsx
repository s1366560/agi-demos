import { StrictMode } from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({
  sessions: [] as any[],
  terminals: [] as any[],
  observers: [] as any[],
  fits: [] as any[],
  fitFailure: false,
}));
vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    options = {};
    cols = 80;
    rows = 24;
    input: any;
    dispose = vi.fn();
    write = vi.fn();
    writeln = vi.fn();
    loadAddon = vi.fn();
    open = vi.fn();
    inputDispose = vi.fn();
    onData = vi.fn((callback: any) => {
      this.input = callback;
      return { dispose: this.inputDispose };
    });
    constructor() {
      state.terminals.push(this);
    }
  },
}));
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit = vi.fn();
    constructor() {
      if (state.fitFailure) throw new Error('Fit constructor failed');
      state.fits.push(this);
    }
  },
}));
vi.mock('@xterm/addon-web-links', () => ({ WebLinksAddon: class {} }));
vi.mock('../../../../hooks/useThemeColor', () => ({ useThemeColors: () => ({}) }));
vi.mock('../../../../services/terminalRetainedSessionV2', () => ({
  TerminalRetainedSessionV2: class {
    options: any;
    controller = new AbortController();
    clean: any;
    input = vi.fn();
    resize = vi.fn();
    active = false;
    operation = {
      signal: this.controller.signal,
      check: () => {
        if (!this.active) throw new DOMException('Retired', 'AbortError');
      },
    };
    constructor(options: any) {
      this.options = options;
      state.sessions.push(this);
    }
    connect = vi.fn(async () => {
      this.active = true;
      this.clean = this.options.onAdmitted(this.operation);
    });
    sendInput = (data: string) => {
      if (!this.active) return false;
      this.input(data);
      return true;
    };
    getOperationContext = () => (this.active ? this.operation : undefined);
    disconnect = vi.fn(async () => {
      this.active = false;
      this.controller.abort();
      const close = this.clean;
      this.clean = undefined;
      await close?.();
    });
  },
}));
import { TerminalImpl } from '../../../../components/agent/sandbox/TerminalImpl';
beforeEach(() => {
  state.sessions = [];
  state.terminals = [];
  state.observers = [];
  state.fits = [];
  state.fitFailure = false;
  vi.useFakeTimers();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      callback: any;
      disconnect = vi.fn();
      observe = vi.fn();
      constructor(callback: any) {
        this.callback = callback;
        state.observers.push(this);
      }
    }
  );
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const props = {
  sandboxId: 'sandbox',
  projectId: 'project',
  status: 'connecting' as const,
  isFullscreen: false,
  onConnect: vi.fn(),
  onDisconnect: vi.fn(),
  onError: vi.fn(),
};
it('registers one input listener across reconnect notifications and drops retired input', async () => {
  const view = render(<TerminalImpl {...props} />);
  await act(async () => {});
  const session = state.sessions[0],
    terminal = state.terminals[0];
  session.options.onConnect('one');
  session.options.onConnect('one');
  expect(terminal.onData).toHaveBeenCalledOnce();
  terminal.input('a');
  expect(session.input).toHaveBeenCalledExactlyOnceWith('a');
  view.unmount();
  terminal.input('b');
  expect(session.input).toHaveBeenCalledOnce();
  expect(terminal.inputDispose).toHaveBeenCalledOnce();
  expect(terminal.dispose).toHaveBeenCalledOnce();
  expect(state.observers[0].disconnect).toHaveBeenCalledOnce();
});
it('retired output, resize and fullscreen timers never affect the replacement terminal', async () => {
  const view = render(<TerminalImpl {...props} />);
  await act(async () => {});
  const old = state.sessions[0],
    terminal = state.terminals[0],
    fit = state.fits[0];
  view.rerender(<TerminalImpl {...props} isFullscreen />);
  view.rerender(<TerminalImpl {...props} sandboxId="replacement" />);
  await act(async () => {});
  const calls = fit.fit.mock.calls.length;
  old.options.onOutput('stale');
  state.observers[0].callback();
  await act(async () => vi.advanceTimersByTime(200));
  expect(terminal.write).not.toHaveBeenCalled();
  expect(fit.fit).toHaveBeenCalledTimes(calls);
  expect(old.resize).not.toHaveBeenCalled();
  expect(state.terminals).toHaveLength(2);
});
it('parent onConnect retirement prevents the welcome write that follows it', async () => {
  let view: ReturnType<typeof render>;
  const onConnect = () => view.unmount();
  view = render(<TerminalImpl {...props} onConnect={onConnect} />);
  await act(async () => {});
  state.sessions[0].options.onConnect('session');
  expect(state.terminals[0].writeln).not.toHaveBeenCalled();
  expect(state.sessions[0].resize).not.toHaveBeenCalled();
});

it('StrictMode closes the first UI lifetime before installing the replacement subscription', async () => {
  const view = render(
    <StrictMode>
      <TerminalImpl {...props} />
    </StrictMode>
  );
  await act(async () => {});
  expect(state.sessions).toHaveLength(2);
  expect(state.terminals[0].dispose).toHaveBeenCalledOnce();
  expect(state.terminals[0].inputDispose).toHaveBeenCalledOnce();
  state.terminals[0].input('old');
  state.terminals[1].input('new');
  expect(state.sessions[0].input).not.toHaveBeenCalled();
  expect(state.sessions[1].input).toHaveBeenCalledExactlyOnceWith('new');
  view.unmount();
});
it('all UI disposals run when an earlier cleanup fails', async () => {
  const view = render(<TerminalImpl {...props} />);
  await act(async () => {});
  const terminal = state.terminals[0];
  terminal.inputDispose.mockImplementation(() => {
    throw new Error('dispose failed');
  });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  view.unmount();
  await act(async () => {});
  expect(terminal.dispose).toHaveBeenCalledOnce();
  expect(state.observers[0].disconnect).toHaveBeenCalledOnce();
  await expect(state.sessions[0].disconnect.mock.results[0].value).rejects.toMatchObject({
    name: 'WebOperationCleanupErrorV2',
  });
});

it('connected and reconnected frames refresh the current terminal dimensions', async () => {
  render(<TerminalImpl {...props} />);
  await act(async () => {});
  const session = state.sessions[0];
  const terminal = state.terminals[0];
  terminal.cols = 132;
  terminal.rows = 44;
  const before = state.fits[0].fit.mock.calls.length;
  session.options.onConnect('session');
  expect(state.fits[0].fit).toHaveBeenCalledTimes(before + 1);
  expect(session.resize).toHaveBeenLastCalledWith(132, 44);
  terminal.cols = 100;
  terminal.rows = 36;
  session.options.onConnect('session');
  expect(state.fits[0].fit).toHaveBeenCalledTimes(before + 2);
  expect(session.resize).toHaveBeenLastCalledWith(100, 36);
  expect(terminal.onData).toHaveBeenCalledOnce();
});

it('disposes the admitted terminal when FitAddon construction fails', async () => {
  state.fitFailure = true;
  const onError = vi.fn();
  render(<TerminalImpl {...props} onError={onError} />);
  await act(async () => {});
  expect(state.terminals).toHaveLength(1);
  expect(state.terminals[0].dispose).toHaveBeenCalledOnce();
  expect(state.terminals[0].onData).not.toHaveBeenCalled();
  expect(state.observers).toHaveLength(0);
});
