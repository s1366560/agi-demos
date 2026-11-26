import { describe, expect, it } from 'vitest';

import {
  runningSandboxTool,
  sandboxConnection,
} from '../../../../plugins/business/agent/ui/signed/sandboxStatus';

describe('the sandbox slot of the status bar', () => {
  it('names the connection of the project sandbox as the original workbench does', () => {
    expect(sandboxConnection(undefined)).toBe('idle');
    expect(sandboxConnection(null)).toBe('idle');
    expect(sandboxConnection({ status: 'pending' })).toBe('connecting');
    expect(sandboxConnection({ status: 'creating' })).toBe('connecting');
    expect(sandboxConnection({ status: 'running', is_healthy: true })).toBe('connected');
    // A sandbox that answers but is not healthy is not a connection to rely on.
    expect(sandboxConnection({ status: 'running', is_healthy: false })).toBe('error');
    expect(sandboxConnection({ status: 'error' })).toBe('error');
    expect(sandboxConnection({ status: 'stopped' })).toBe('idle');
    expect(sandboxConnection({ status: 'retired' })).toBeUndefined();
    expect(sandboxConnection({ status: '' })).toBe('idle');
  });

  it('names the sandbox tool that started and has not returned', () => {
    const events = [
      { id: '1', type: 'act', execution_id: 'e1', toolName: 'bash' },
      { id: '2', type: 'act', execution_id: 'e2', toolName: 'write' },
      { id: '3', type: 'observe', execution_id: 'e2', toolName: 'write' },
    ];
    expect(runningSandboxTool([])).toBeUndefined();
    expect(runningSandboxTool(events)).toBe('bash');
    // The latest one of several that still run is shown.
    expect(
      runningSandboxTool([
        ...events,
        { id: '4', type: 'act', execution_id: 'e3', toolName: 'read' },
      ])
    ).toBe('read');
    expect(
      runningSandboxTool([
        ...events,
        { id: '3', type: 'observe', execution_id: 'e1', toolName: 'bash' },
      ])
    ).toBeUndefined();
  });

  it('ignores tools that do not work inside the sandbox and calls without an execution', () => {
    expect(
      runningSandboxTool([
        { id: '1', type: 'act', execution_id: 'e1', toolName: 'memory_search' },
        { id: '2', type: 'act', toolName: 'bash' },
        { id: '3', type: 'thought' },
      ])
    ).toBeUndefined();
    expect(
      runningSandboxTool([{ id: '4', type: 'observe', execution_id: 'e1', toolName: 'bash' }])
    ).toBeUndefined();
  });
});
