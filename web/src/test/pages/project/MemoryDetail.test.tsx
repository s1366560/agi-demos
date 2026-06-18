import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
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

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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
      <MemoryRouter initialEntries={['/tenant/t1/project/project-1/memory/memory-1']}>
        <Routes>
          <Route
            path="/tenant/:tenantId/project/:projectId/memory/:memoryId"
            element={<MemoryDetail />}
          />
        </Routes>
      </MemoryRouter>
    );

  const RouteChangeHarness = () => {
    const navigate = useNavigate();
    return (
      <>
        <button
          type="button"
          onClick={() => navigate('/tenant/t1/project/project-1/memory/memory-2')}
        >
          Go to memory two
        </button>
        <MemoryDetail />
      </>
    );
  };

  const renderRouteChangeHarness = () =>
    render(
      <MemoryRouter initialEntries={['/tenant/t1/project/project-1/memory/memory-1']}>
        <Routes>
          <Route
            path="/tenant/:tenantId/project/:projectId/memory/:memoryId"
            element={<RouteChangeHarness />}
          />
        </Routes>
      </MemoryRouter>
    );

  it('copies the current detail link from the share action', async () => {
    const { container } = renderDetail();

    expect((await screen.findAllByText('Memory One')).length).toBeGreaterThan(0);
    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('>COMPLETED');
    expect(screen.getByRole('button', { name: 'Reprocess' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
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

  it('ignores stale detail responses after the route changes', async () => {
    const firstRequest = createDeferred<Memory>();
    const secondRequest = createDeferred<Memory>();
    vi.mocked(memoryAPI.get)
      .mockReturnValueOnce(firstRequest.promise)
      .mockReturnValueOnce(secondRequest.promise);

    renderRouteChangeHarness();

    await waitFor(() => {
      expect(memoryAPI.get).toHaveBeenCalledWith('project-1', 'memory-1');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Go to memory two' }));

    await waitFor(() => {
      expect(memoryAPI.get).toHaveBeenCalledWith('project-1', 'memory-2');
    });

    await act(async () => {
      secondRequest.resolve({ ...memory, id: 'memory-2', title: 'Memory Two' });
    });

    expect((await screen.findAllByText('Memory Two')).length).toBeGreaterThan(0);

    await act(async () => {
      firstRequest.resolve({ ...memory, id: 'memory-1', title: 'Memory One' });
    });

    await waitFor(() => {
      expect(screen.queryByText('Memory One')).not.toBeInTheDocument();
      expect(screen.getAllByText('Memory Two').length).toBeGreaterThan(0);
    });
  });
});
