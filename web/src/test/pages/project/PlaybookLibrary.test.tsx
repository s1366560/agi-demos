import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PlaybookLibrary } from '../../../pages/project/PlaybookLibrary';
import type { Playbook, ReflectionVerdict } from '../../../services/playbookService';
import { act, render, screen, waitFor } from '../../utils';

const routeState = vi.hoisted(() => ({
  projectId: 'project-a' as string | undefined,
}));

const serviceMocks = vi.hoisted(() => ({
  listPlaybooks: vi.fn(),
  listReflectionVerdicts: vi.fn(),
  subscribeProject: vi.fn(),
}));

const createDeferred = <T,>() => {
  let resolvePromise: (value: T | PromiseLike<T>) => void = () => {};
  let rejectPromise: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });

  return {
    promise,
    resolve: resolvePromise,
    reject: rejectPromise,
  };
};

const createPlaybook = (id: string, projectId: string, name: string): Playbook => ({
  id,
  project_id: projectId,
  name,
  status: 'active',
  trigger: {
    description: '',
    friction_kinds: [],
    lane_transitions: [],
  },
  steps: [],
  hit_count: 0,
  last_used_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
});

const createVerdict = (id: string, projectId: string, rationale: string): ReflectionVerdict => ({
  id,
  project_id: projectId,
  action: 'create',
  playbook_id: null,
  rationale,
  proposed_payload: null,
  created_at: '2026-01-01T00:00:00Z',
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useParams: () => ({ projectId: routeState.projectId }),
  };
});

vi.mock('../../../services/playbookService', () => ({
  playbookService: {
    listPlaybooks: serviceMocks.listPlaybooks,
    listReflectionVerdicts: serviceMocks.listReflectionVerdicts,
  },
}));

vi.mock('@/services/unifiedEventService', () => ({
  unifiedEventService: {
    subscribeProject: serviceMocks.subscribeProject,
  },
}));

describe('PlaybookLibrary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.projectId = 'project-a';
    serviceMocks.subscribeProject.mockReturnValue(vi.fn());
    serviceMocks.listPlaybooks.mockResolvedValue([]);
    serviceMocks.listReflectionVerdicts.mockResolvedValue([]);
  });

  it('ignores stale playbook loads after the route project changes', async () => {
    const projectAPlaybooks = createDeferred<Playbook[]>();
    const projectAVerdicts = createDeferred<ReflectionVerdict[]>();
    const projectBPlaybooks = createDeferred<Playbook[]>();
    const projectBVerdicts = createDeferred<ReflectionVerdict[]>();

    serviceMocks.listPlaybooks.mockImplementation((projectId: string) => {
      if (projectId === 'project-a') return projectAPlaybooks.promise;
      return projectBPlaybooks.promise;
    });
    serviceMocks.listReflectionVerdicts.mockImplementation((projectId: string) => {
      if (projectId === 'project-a') return projectAVerdicts.promise;
      return projectBVerdicts.promise;
    });

    const { rerender } = render(<PlaybookLibrary />);

    await waitFor(() => {
      expect(serviceMocks.listPlaybooks).toHaveBeenCalledWith('project-a', 200);
    });

    routeState.projectId = 'project-b';
    rerender(<PlaybookLibrary />);

    await waitFor(() => {
      expect(serviceMocks.listPlaybooks).toHaveBeenCalledWith('project-b', 200);
    });

    await act(async () => {
      projectBPlaybooks.resolve([
        createPlaybook('playbook-b', 'project-b', 'Current project playbook'),
      ]);
      projectBVerdicts.resolve([
        createVerdict('verdict-b', 'project-b', 'Current project verdict'),
      ]);
    });

    expect(await screen.findByText('Current project playbook')).toBeInTheDocument();

    await act(async () => {
      projectAPlaybooks.resolve([createPlaybook('playbook-a', 'project-a', 'Stale playbook')]);
      projectAVerdicts.resolve([createVerdict('verdict-a', 'project-a', 'Stale verdict')]);
    });

    expect(screen.queryByText('Stale playbook')).not.toBeInTheDocument();
    expect(screen.queryByText('Stale verdict')).not.toBeInTheDocument();
    expect(screen.getByText('Current project playbook')).toBeInTheDocument();
  });

  it('resets the project event cursor when the route project changes', async () => {
    const { rerender } = render(<PlaybookLibrary />);

    await waitFor(() => {
      expect(serviceMocks.subscribeProject).toHaveBeenCalledWith(
        'project-a',
        expect.any(Function),
        undefined
      );
    });

    const projectAHandler = serviceMocks.subscribeProject.mock.calls[0]?.[1] as
      | ((event: { type: string; sequence_id?: string }) => void)
      | undefined;
    expect(projectAHandler).toBeDefined();

    act(() => {
      projectAHandler?.({ type: 'reflection_complete', sequence_id: 'project-a-seq' });
    });

    routeState.projectId = 'project-b';
    rerender(<PlaybookLibrary />);

    await waitFor(() => {
      expect(serviceMocks.subscribeProject).toHaveBeenCalledWith(
        'project-b',
        expect.any(Function),
        undefined
      );
    });
  });
});
