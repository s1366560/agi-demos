import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RendererPluginRuntimeV2, webRendererDefinitionsV2 } from '@agistack/plugin-runtime';
import profile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
import { useSandboxStore } from '@/stores/sandbox';
import { projectSandboxService } from '@/services/projectSandboxService';
import type { TerminalStatus } from '@/types/agent';

vi.mock('@/services/projectSandboxService', () => ({
  projectSandboxService: { startTerminal: vi.fn(), stopTerminal: vi.fn() },
}));
vi.mock('@/services/sandboxSSEService', () => ({ sandboxSSEService: {} }));
const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { resolve, reject, promise };
};
const status = (sessionId: string): TerminalStatus => ({
  running: true,
  sessionId,
  url: null,
  pid: 1,
  port: 7681,
});
let runtime: RendererPluginRuntimeV2;
let admission: WebOperationAdmissionV2;
let uninstall: () => void;
beforeEach(async () => {
  vi.clearAllMocks();
  runtime = new RendererPluginRuntimeV2('web', webRendererDefinitionsV2);
  await runtime.bootstrap(profile);
  admission = new WebOperationAdmissionV2(runtime);
  admission.setEnabled(true);
  uninstall = installWebOperationAdmissionV2(admission);
  useSandboxStore.getState().reset();
  useSandboxStore.setState({ activeProjectId: 'project-a', activeSandboxId: 'sandbox-a' });
});
afterEach(async () => {
  useSandboxStore.getState().reset();
  await admission.close();
  uninstall();
  await runtime.close();
});
describe('terminal control response ownership', () => {
  it('rejects disabled control before service invocation', async () => {
    admission.setEnabled(false);
    await expect(useSandboxStore.getState().startTerminal()).rejects.toThrow(
      'web_operation_generation_unavailable'
    );
    expect(projectSandboxService.startTerminal).not.toHaveBeenCalled();
    expect(useSandboxStore.getState().isTerminalLoading).toBe(false);
  });
  it('does not issue a request when a loading listener retires the owner synchronously', async () => {
    const detach = useSandboxStore.subscribe((state) => {
      if (state.isTerminalLoading) admission.invalidate();
    });
    try {
      await expect(useSandboxStore.getState().startTerminal()).rejects.toMatchObject({
        name: 'AbortError',
      });
      expect(projectSandboxService.startTerminal).not.toHaveBeenCalled();
      expect(useSandboxStore.getState().isTerminalLoading).toBe(false);
    } finally {
      detach();
    }
  });

  it('does not adopt late success after owner replacement and clears its loading state', async () => {
    const pending = deferred<TerminalStatus>();
    vi.mocked(projectSandboxService.startTerminal).mockReturnValueOnce(pending.promise);
    const task = useSandboxStore.getState().startTerminal();
    const rejection = expect(task).rejects.toMatchObject({ name: 'AbortError' });
    expect(useSandboxStore.getState().isTerminalLoading).toBe(true);
    admission.invalidate();
    expect(useSandboxStore.getState().isTerminalLoading).toBe(false);
    pending.resolve(status('old'));
    await rejection;
    expect(useSandboxStore.getState().terminalStatus).toBeNull();
  });
  it('rejects an A to B to A stale response even when owner and project names match again', async () => {
    const pending = deferred<TerminalStatus>();
    vi.mocked(projectSandboxService.startTerminal).mockReturnValueOnce(pending.promise);
    const task = useSandboxStore.getState().startTerminal();
    const rejection = expect(task).rejects.toMatchObject({ name: 'AbortError' });
    useSandboxStore.setState({ activeProjectId: 'project-b' });
    useSandboxStore.setState({ activeProjectId: 'project-a' });
    pending.resolve(status('old'));
    await rejection;
    expect(useSandboxStore.getState().terminalStatus).toBeNull();
  });
  it('does not let an earlier failure clear a newer request loading state', async () => {
    const older = deferred<TerminalStatus>();
    const newer = deferred<TerminalStatus>();
    vi.mocked(projectSandboxService.startTerminal)
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    const first = useSandboxStore.getState().startTerminal();
    const rejection = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    const second = useSandboxStore.getState().startTerminal();
    older.reject(new Error('Old request failed'));
    await rejection;
    expect(useSandboxStore.getState().isTerminalLoading).toBe(true);
    newer.resolve(status('new'));
    await second;
    expect(useSandboxStore.getState().terminalStatus?.sessionId).toBe('new');
    expect(useSandboxStore.getState().isTerminalLoading).toBe(false);
  });
  it('keeps a completed stop authoritative when an earlier start responds late', async () => {
    const pending = deferred<TerminalStatus>();
    vi.mocked(projectSandboxService.startTerminal).mockReturnValueOnce(pending.promise);
    vi.mocked(projectSandboxService.stopTerminal).mockResolvedValueOnce(undefined);
    const first = useSandboxStore.getState().startTerminal();
    const rejection = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    await useSandboxStore.getState().stopTerminal();
    pending.resolve(status('old'));
    await rejection;
    expect(useSandboxStore.getState().terminalStatus?.running).toBe(false);
  });
});
