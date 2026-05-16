import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MemoryDetail } from '../../../pages/project/MemoryDetail';
import { memoryAPI } from '../../../services/api';

import type { Memory } from '../../../types/memory';

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock('../../../services/api', () => ({
  memoryAPI: {
    get: vi.fn(),
    delete: vi.fn(),
    reprocess: vi.fn(),
  },
}));

vi.mock('../../../hooks/useTaskSSE', () => ({
  subscribeToTask: vi.fn(() => vi.fn()),
  TaskStatus: {
    PENDING: 'PENDING',
    PROCESSING: 'PROCESSING',
    COMPLETED: 'COMPLETED',
    FAILED: 'FAILED',
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  useLazyMessage: () => messageMocks,
}));

const memory: Memory = {
  id: 'memory-1',
  project_id: 'project-1',
  title: 'Memory One',
  content: 'Stored memory content',
  content_type: 'text',
  tags: [],
  entities: [],
  relationships: [],
  version: 1,
  author_id: 'user-1',
  collaborators: [],
  is_public: false,
  status: 'ENABLED',
  processing_status: 'COMPLETED',
  metadata: {},
  created_at: '2024-01-01T00:00:00Z',
};

describe('MemoryDetail', () => {
  const createObjectURL = vi.fn(() => 'blob:memory-export');
  const revokeObjectURL = vi.fn();
  let clickSpy: ReturnType<typeof vi.spyOn>;
  let writeTextSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(memoryAPI.get).mockResolvedValue(memory);
    writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURL,
    });
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    clickSpy?.mockRestore();
    writeTextSpy?.mockRestore();
  });

  const renderDetail = () =>
    render(
      <MemoryRouter initialEntries={['/tenant/t1/project/project-1/memories/memory-1']}>
        <Routes>
          <Route
            path="/tenant/:tenantId/project/:projectId/memories/:memoryId"
            element={<MemoryDetail />}
          />
        </Routes>
      </MemoryRouter>
    );

  it('copies the current detail link from the share action', async () => {
    renderDetail();

    expect((await screen.findAllByText('Memory One')).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'memory.detail.shareAria' }));

    await waitFor(() => {
      expect(writeTextSpy).toHaveBeenCalledWith(expect.any(String));
    });
    expect(messageMocks.success).toHaveBeenCalledWith('Link copied to clipboard!');
  });

  it('exports the memory JSON from the download action', async () => {
    renderDetail();

    expect((await screen.findAllByText('Memory One')).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'memory.detail.downloadAria' }));

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:memory-export');
    expect(messageMocks.success).toHaveBeenCalledWith('Memory exported');
  });
});
