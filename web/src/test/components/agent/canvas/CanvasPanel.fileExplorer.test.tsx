import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CanvasPanel } from '@/components/agent/canvas/CanvasPanel';
import { useCanvasStore } from '@/stores/canvasStore';

import { artifactService, fetchArtifactResource } from '@/services/artifactService';
import { projectSandboxService } from '@/services/projectSandboxService';

import type { Artifact } from '@/types/agent';

const { executeToolMock, listArtifactsMock, getDownloadUrlMock, fetchArtifactResourceMock } =
  vi.hoisted(() => ({
    executeToolMock: vi.fn(),
    listArtifactsMock: vi.fn(),
    getDownloadUrlMock: vi.fn((artifactId: string) => `/api/v1/artifacts/${artifactId}/download`),
    fetchArtifactResourceMock: vi.fn(),
  }));

vi.mock('@/components/mcp-app/StandardMCPAppRenderer', () => ({
  StandardMCPAppRenderer: () => null,
}));

vi.mock('@/components/agent/canvas/A2UISurfaceRenderer', () => ({
  A2UISurfaceRenderer: () => null,
}));

vi.mock('@/components/agent/canvas/useSyntaxHighlighter', () => ({
  useSyntaxHighlighter: () => null,
}));

vi.mock('@/services/projectSandboxService', () => ({
  projectSandboxService: {
    executeTool: executeToolMock,
  },
}));

vi.mock('@/services/artifactService', () => ({
  artifactService: {
    list: listArtifactsMock,
    getDownloadUrl: getDownloadUrlMock,
    updateContent: vi.fn(),
  },
  fetchArtifactResource: fetchArtifactResourceMock,
}));

function makeArtifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: 'artifact-1',
    projectId: 'project-1',
    tenantId: 'tenant-1',
    filename: 'notes.md',
    mimeType: 'text/markdown',
    category: 'document',
    sizeBytes: 7,
    status: 'ready',
    createdAt: '2026-06-24T00:00:00Z',
    ...overrides,
  };
}

describe('CanvasPanel file explorer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCanvasStore.getState().reset();
    executeToolMock.mockResolvedValue({
      success: true,
      is_error: false,
      content: [{ type: 'text', text: '' }],
    });
    listArtifactsMock.mockResolvedValue({ artifacts: [], total: 0 });
    fetchArtifactResourceMock.mockResolvedValue(new Response('', { status: 200 }));
  });

  it('renders source sections and opens a sandbox text file', async () => {
    executeToolMock
      .mockResolvedValueOnce({
        success: true,
        is_error: false,
        content: [{ type: 'text', text: 'src/app.ts\nREADME.md' }],
      })
      .mockResolvedValueOnce({
        success: true,
        is_error: false,
        content: [{ type: 'text', text: 'console.log(1);\n' }],
      });

    render(<CanvasPanel projectId="project-1" tenantId="tenant-1" workspaceId="workspace-1" />);

    expect(await screen.findByText('Sandbox')).toBeInTheDocument();
    expect(screen.getByText('Artifacts')).toBeInTheDocument();

    fireEvent.click(await screen.findByText('src'));
    fireEvent.click(await screen.findByText('app.ts'));

    await waitFor(() => {
      const tab = useCanvasStore.getState().tabs.find((item) => item.title === 'app.ts');
      expect(tab).toMatchObject({
        id: 'sandbox:project-1:/workspace/src/app.ts',
        type: 'code',
        content: 'console.log(1);\n',
      });
    });
    expect(projectSandboxService.executeTool).toHaveBeenLastCalledWith('project-1', {
      tool_name: 'read',
      arguments: { file_path: '/workspace/src/app.ts', offset: 0, limit: 50000, raw: true },
      timeout: 30,
    });
  });

  it('opens a text artifact from object storage into a canvas tab', async () => {
    const artifact = makeArtifact({
      id: 'artifact-1',
      filename: 'notes.md',
      url: '/api/v1/artifacts/artifact-1/download',
    });
    listArtifactsMock.mockResolvedValueOnce({ artifacts: [artifact], total: 1 });
    fetchArtifactResourceMock.mockResolvedValueOnce(
      new Response('# Notes', {
        status: 200,
        headers: { 'content-type': 'text/markdown' },
      })
    );

    render(<CanvasPanel projectId="project-1" tenantId="tenant-1" workspaceId="workspace-1" />);

    fireEvent.click(screen.getByTestId('canvas-file-source-artifacts'));
    fireEvent.click(await screen.findByText('notes.md'));

    await waitFor(() => {
      const tab = useCanvasStore.getState().tabs.find((item) => item.artifactId === 'artifact-1');
      expect(tab).toMatchObject({
        id: 'artifact:artifact-1',
        title: 'notes.md',
        type: 'markdown',
        content: '# Notes',
        artifactUrl: '/api/v1/artifacts/artifact-1/download',
      });
    });
    expect(artifactService.list).toHaveBeenCalledWith('project-1', { limit: 500 });
    expect(fetchArtifactResource).toHaveBeenCalledWith('/api/v1/artifacts/artifact-1/download');
  });
});
