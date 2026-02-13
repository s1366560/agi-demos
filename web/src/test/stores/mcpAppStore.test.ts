import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useMCPAppStore } from '../../stores/mcpAppStore';

import type { MCPApp } from '../../types/mcpApp';

const makeMockApp = (overrides: Partial<MCPApp> = {}): MCPApp => ({
  id: `app-${Math.random().toString(36).slice(2, 8)}`,
  project_id: 'proj-1',
  tenant_id: 'tenant-1',
  server_id: 'srv-1',
  server_name: 'test-server',
  tool_name: 'test_tool',
  ui_metadata: { resourceUri: 'ui://test-server/app.html' },
  source: 'user_added',
  status: 'discovered',
  has_resource: false,
  ...overrides,
});

describe('useMCPAppStore', () => {
  beforeEach(() => {
    useMCPAppStore.getState().reset();
  });

  it('should initialize with empty state', () => {
    const state = useMCPAppStore.getState();
    expect(state.apps).toEqual({});
    expect(state.resources).toEqual({});
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });

  it('should add an app', () => {
    const app = makeMockApp({ id: 'app-1' });
    useMCPAppStore.getState().addApp(app);

    const state = useMCPAppStore.getState();
    expect(state.apps['app-1']).toBeDefined();
    expect(state.apps['app-1'].tool_name).toBe('test_tool');
  });

  it('should add multiple apps', () => {
    const app1 = makeMockApp({ id: 'app-1', tool_name: 'tool_a' });
    const app2 = makeMockApp({ id: 'app-2', tool_name: 'tool_b' });

    useMCPAppStore.getState().addApp(app1);
    useMCPAppStore.getState().addApp(app2);

    const state = useMCPAppStore.getState();
    expect(Object.keys(state.apps)).toHaveLength(2);
  });

  it('should remove an app', () => {
    const app = makeMockApp({ id: 'app-1' });
    useMCPAppStore.getState().addApp(app);
    expect(useMCPAppStore.getState().apps['app-1']).toBeDefined();

    useMCPAppStore.getState().removeApp('app-1');
    expect(useMCPAppStore.getState().apps['app-1']).toBeUndefined();
  });

  it('should remove associated resources when removing an app', () => {
    const app = makeMockApp({ id: 'app-1' });
    useMCPAppStore.getState().addApp(app);

    // Manually insert a cached resource
    useMCPAppStore.setState((state) => ({
      resources: {
        ...state.resources,
        'app-1': {
          app_id: 'app-1',
          resource_uri: 'ui://s/a.html',
          html_content: '<h1>Test</h1>',
          mime_type: 'text/html;profile=mcp-app',
          size_bytes: 12,
          ui_metadata: { resourceUri: 'ui://s/a.html' },
        },
      },
    }));
    expect(useMCPAppStore.getState().resources['app-1']).toBeDefined();

    useMCPAppStore.getState().removeApp('app-1');
    expect(useMCPAppStore.getState().resources['app-1']).toBeUndefined();
  });

  it('should reset all state', () => {
    useMCPAppStore.getState().addApp(makeMockApp({ id: 'app-1' }));
    useMCPAppStore.getState().addApp(makeMockApp({ id: 'app-2' }));
    useMCPAppStore.setState({ loading: true, error: 'some error' });

    useMCPAppStore.getState().reset();

    const state = useMCPAppStore.getState();
    expect(state.apps).toEqual({});
    expect(state.resources).toEqual({});
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });

  it('should fetch apps from API', async () => {
    const mockApps: MCPApp[] = [
      makeMockApp({ id: 'app-1', tool_name: 'chart' }),
      makeMockApp({ id: 'app-2', tool_name: 'dashboard' }),
    ];

    // Mock the mcpAppAPI.list
    const { mcpAppAPI } = await import('../../services/mcpAppService');
    vi.spyOn(mcpAppAPI, 'list').mockResolvedValueOnce(mockApps);

    await useMCPAppStore.getState().fetchApps('proj-1');

    const state = useMCPAppStore.getState();
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
    expect(Object.keys(state.apps)).toHaveLength(2);
    expect(state.apps['app-1'].tool_name).toBe('chart');
    expect(state.apps['app-2'].tool_name).toBe('dashboard');
  });

  it('should handle fetch error', async () => {
    const { mcpAppAPI } = await import('../../services/mcpAppService');
    vi.spyOn(mcpAppAPI, 'list').mockRejectedValueOnce(new Error('Network error'));

    await useMCPAppStore.getState().fetchApps('proj-1');

    const state = useMCPAppStore.getState();
    expect(state.loading).toBe(false);
    expect(state.error).toBe('Network error');
  });

  it('should distinguish app sources', () => {
    const userApp = makeMockApp({ id: 'app-1', source: 'user_added' });
    const agentApp = makeMockApp({ id: 'app-2', source: 'agent_developed' });

    useMCPAppStore.getState().addApp(userApp);
    useMCPAppStore.getState().addApp(agentApp);

    const state = useMCPAppStore.getState();
    expect(state.apps['app-1'].source).toBe('user_added');
    expect(state.apps['app-2'].source).toBe('agent_developed');
  });
});
