/**
 * Unit tests for ComposerPlusMenu.
 *
 * Feature: consolidated "+" composer menu with categorized plugin / agent /
 * command lists and dynamic type-to-search filtering.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

const commandListMock = vi.hoisted(() => vi.fn());
const skillListMock = vi.hoisted(() => vi.fn());
const listDefinitionsMock = vi.hoisted(() => vi.fn());
const fetchAppsMock = vi.hoisted(() => vi.fn());
const openTabMock = vi.hoisted(() => vi.fn());
const setModeMock = vi.hoisted(() => vi.fn());

const mockApps: Record<string, unknown> = {};
const mockCapabilities = {
  supportsAttachment: true,
  supportsVision: true,
  supportsAudio: false,
  model: null,
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallbackOrOptions?: unknown, maybeOptions?: unknown) => {
      const fallback = typeof fallbackOrOptions === 'string' ? fallbackOrOptions : key;
      const options = (
        typeof fallbackOrOptions === 'object' && fallbackOrOptions !== null
          ? fallbackOrOptions
          : maybeOptions
      ) as { query?: string } | null;
      if (options && typeof options.query === 'string') {
        return fallback.replace('{{query}}', options.query);
      }
      return fallback;
    },
  }),
}));

vi.mock('@/services/commandService', () => ({
  commandAPI: { list: commandListMock },
}));

vi.mock('@/services/skillService', () => ({
  skillAPI: { list: skillListMock },
}));

vi.mock('@/stores/agentDefinitions', () => ({
  useDefinitions: () => [
    {
      id: 'agent-1',
      name: 'researcher',
      display_name: 'Researcher',
      enabled: true,
      source: 'database',
    },
    {
      id: 'agent-2',
      name: 'disabled-agent',
      enabled: false,
      source: 'database',
    },
  ],
  useListDefinitions: () => listDefinitionsMock,
}));

vi.mock('@/stores/mcpAppStore', () => ({
  useMCPAppStore: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({ apps: mockApps, loading: false, fetchApps: fetchAppsMock }),
}));

vi.mock('@/stores/canvasStore', () => ({
  useCanvasStore: {
    getState: () => ({ openTab: openTabMock }),
  },
}));

vi.mock('@/stores/layoutMode', () => ({
  useLayoutModeStore: {
    getState: () => ({ setMode: setModeMock }),
  },
}));

vi.mock('@/components/agent/chat/LlmOverridePopover', () => ({
  LlmOverridePopover: () => <div data-testid="llm-override-row" />,
}));

// eslint-disable-next-line no-restricted-imports
import { ComposerPlusMenu } from '@/components/agent/ComposerPlusMenu';

import type { PendingAttachment } from '@/components/agent/FileUploader';

const emptyAttachments: readonly PendingAttachment[] = [];

function renderMenu(overrides: Partial<Parameters<typeof ComposerPlusMenu>[0]> = {}) {
  const onSlashSelect = vi.fn();
  const onAgentSelect = vi.fn();
  const props = {
    fileInputRef: { current: null },
    capabilities: mockCapabilities,
    attachments: emptyAttachments,
    setTemplateLibraryVisible: vi.fn(),
    isListening: false,
    voiceCallStatus: 'idle',
    toggleVoiceInput: vi.fn().mockResolvedValue(undefined),
    handleVoiceCall: vi.fn(),
    onTogglePlanMode: vi.fn(),
    isPlanMode: false,
    onAgentSelect,
    activeAgentId: undefined,
    onSlashSelect,
    projectId: 'project-1',
    activeConversationId: 'conv-1',
    disabled: false,
    ...overrides,
  };
  const utils = render(<ComposerPlusMenu {...props} />);
  return { ...utils, props };
}

async function openMenu() {
  fireEvent.click(screen.getByTestId('composer-plus-button'));
  await waitFor(() => {
    expect(screen.getByTestId('composer-plus-menu')).toBeInTheDocument();
  });
  return screen.getByTestId('composer-plus-search');
}

describe('ComposerPlusMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(mockApps).forEach((key) => delete mockApps[key]);
    commandListMock.mockResolvedValue({
      commands: [{ name: 'goal', description: 'Set a session goal', category: 'core' }],
    });
    skillListMock.mockResolvedValue({
      skills: [{ id: 'skill-1', name: 'planner', description: 'Plan steps', scope: 'tenant' }],
    });
    listDefinitionsMock.mockResolvedValue({ definitions: [], total: 0 });
    fetchAppsMock.mockResolvedValue(undefined);
  });

  it('renders categorized sections with entries after opening', async () => {
    mockApps['app-1'] = {
      id: 'app-1',
      project_id: 'project-1',
      status: 'ready',
      server_name: 'github-mcp',
      tool_name: 'issue_board',
      ui_metadata: { title: 'Issue Board', resourceUri: 'res:issues' },
    };

    renderMenu();
    await openMenu();

    await waitFor(() => {
      expect(screen.getByText('Issue Board')).toBeInTheDocument();
    });

    expect(screen.getByText('Researcher')).toBeInTheDocument();
    expect(screen.getByText('/goal')).toBeInTheDocument();
    expect(screen.getByText('/planner')).toBeInTheDocument();
    expect(screen.getByText('Actions')).toBeInTheDocument();
    expect(screen.getByText('Plugins')).toBeInTheDocument();
    expect(screen.getByText('Agents')).toBeInTheDocument();
    expect(screen.getByText('Commands')).toBeInTheDocument();
    // The disabled agent must not be listed.
    expect(screen.queryByText('disabled-agent')).not.toBeInTheDocument();
  });

  it('filters entries dynamically while typing in the search box', async () => {
    renderMenu();
    const search = await openMenu();

    await waitFor(() => {
      expect(screen.getByText('/goal')).toBeInTheDocument();
    });

    fireEvent.change(search, { target: { value: 'planner' } });

    await waitFor(() => {
      expect(screen.getByText('/planner')).toBeInTheDocument();
    });
    expect(screen.queryByText('/goal')).not.toBeInTheDocument();
    expect(screen.queryByText('Researcher')).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'zzz-no-match' } });
    expect(await screen.findByText('No matches for "zzz-no-match"')).toBeInTheDocument();
  });

  it('selects an agent entry and closes the menu', async () => {
    const { props } = renderMenu();
    await openMenu();

    fireEvent.click(await screen.findByText('Researcher'));

    expect(props.onAgentSelect).toHaveBeenCalledWith('agent-1');
    expect(screen.queryByTestId('composer-plus-menu')).not.toBeInTheDocument();
  });

  it('routes command and skill entries through onSlashSelect', async () => {
    const { props } = renderMenu();
    await openMenu();

    fireEvent.click(await screen.findByText('/goal'));
    expect(props.onSlashSelect).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'command', data: expect.objectContaining({ name: 'goal' }) })
    );

    await openMenu();
    fireEvent.click(await screen.findByText('/planner'));
    expect(props.onSlashSelect).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'skill', data: expect.objectContaining({ name: 'planner' }) })
    );
  });

  it('opens a plugin in the canvas', async () => {
    mockApps['app-1'] = {
      id: 'app-1',
      project_id: 'project-1',
      status: 'ready',
      server_name: 'github-mcp',
      tool_name: 'issue_board',
      ui_metadata: { title: 'Issue Board', resourceUri: 'res:issues' },
    };

    renderMenu();
    await openMenu();

    fireEvent.click(await screen.findByText('Issue Board'));

    expect(openTabMock).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'mcp-app-app-1', type: 'mcp-app' })
    );
    expect(setModeMock).toHaveBeenCalledWith('canvas');
  });

  it('supports keyboard navigation and Enter selection from the search box', async () => {
    const { props } = renderMenu();
    const search = await openMenu();

    await waitFor(() => {
      expect(screen.getByText('/goal')).toBeInTheDocument();
    });

    // Search for the command so it becomes the only entry, then Enter selects it.
    fireEvent.change(search, { target: { value: 'goal' } });
    await waitFor(() => {
      expect(screen.queryByText('/planner')).not.toBeInTheDocument();
    });
    fireEvent.keyDown(search, { key: 'Enter' });

    expect(props.onSlashSelect).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'command' })
    );
    expect(screen.queryByTestId('composer-plus-menu')).not.toBeInTheDocument();
  });

  it('closes on Escape from the search box', async () => {
    renderMenu();
    const search = await openMenu();

    fireEvent.keyDown(search, { key: 'Escape' });

    expect(screen.queryByTestId('composer-plus-menu')).not.toBeInTheDocument();
  });
});
