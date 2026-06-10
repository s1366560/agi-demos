import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/services/artifactService', () => ({
  artifactService: { list: vi.fn() },
}));

vi.mock('@/stores/sandbox', () => ({
  useSandboxStore: { getState: vi.fn() },
}));

vi.mock('@/stores/project', () => ({
  useProjectStore: { getState: vi.fn(() => ({ currentProject: null })) },
}));

vi.mock('@/stores/agent/timelineStore', () => ({
  useTimelineStore: { getState: vi.fn(() => ({ timeline: [], agentTimeline: [] })) },
}));

import { artifactService } from '@/services/artifactService';
import { useSandboxStore } from '@/stores/sandbox';
import { useTimelineStore } from '@/stores/agent/timelineStore';
import type { Artifact } from '@/types/agent';

import {
  findArtifactForSandboxPath,
  isSafeArtifactUrl,
  normalizeSandboxPath,
  pathMatchesArtifact,
  resolveSandboxArtifactUrl,
} from '@/utils/sandboxArtifactPath';

const makeArtifact = (overrides: Partial<Artifact>): Artifact => ({
  id: 'a1',
  projectId: 'p1',
  tenantId: 't1',
  filename: 'chart.png',
  mimeType: 'image/png',
  category: 'image',
  sizeBytes: 1,
  status: 'ready',
  createdAt: '2026-01-01',
  ...overrides,
});

beforeEach(() => {
  vi.mocked(artifactService.list).mockReset();
  vi.mocked(useTimelineStore.getState).mockReturnValue({
    timeline: [],
    agentTimeline: [],
  } as never);
  vi.mocked(useSandboxStore.getState).mockReturnValue({
    activeProjectId: 'proj-1',
    artifacts: new Map<string, Artifact>(),
  } as never);
});

describe('normalizeSandboxPath', () => {
  it('expands ~/ to /workspace/', () => {
    expect(normalizeSandboxPath('~/output/chart.png')).toBe('/workspace/output/chart.png');
  });

  it('leaves absolute sandbox paths unchanged', () => {
    expect(normalizeSandboxPath('/workspace/output/chart.png')).toBe(
      '/workspace/output/chart.png'
    );
  });
});

describe('pathMatchesArtifact', () => {
  it('matches by exact sourcePath', () => {
    const artifact = makeArtifact({ sourcePath: '/workspace/output/chart.png' });
    expect(pathMatchesArtifact('/workspace/output/chart.png', artifact)).toBe(true);
  });

  it('matches by bare filename', () => {
    const artifact = makeArtifact({ filename: 'chart.png' });
    expect(pathMatchesArtifact('chart.png', artifact)).toBe(true);
  });

  it('matches normalized ~/ path against sourcePath', () => {
    const artifact = makeArtifact({ sourcePath: '/workspace/output/chart.png' });
    expect(pathMatchesArtifact('~/output/chart.png', artifact)).toBe(true);
  });

  it('does not match unrelated paths', () => {
    const artifact = makeArtifact({ sourcePath: '/workspace/output/other.png', filename: 'other.png' });
    expect(pathMatchesArtifact('/workspace/output/chart.png', artifact)).toBe(false);
  });
});

describe('isSafeArtifactUrl', () => {
  it('accepts http/https/blob and app-relative URLs', () => {
    expect(isSafeArtifactUrl('https://files.example.com/x.png')).toBe(true);
    expect(isSafeArtifactUrl('http://localhost:9000/x.png')).toBe(true);
    expect(isSafeArtifactUrl('/api/v1/artifacts/a1/download')).toBe(true);
  });

  it('rejects empty and non-pdf data URIs', () => {
    expect(isSafeArtifactUrl('')).toBe(false);
    expect(isSafeArtifactUrl('data:text/html,<script>')).toBe(false);
  });
});

describe('findArtifactForSandboxPath', () => {
  it('resolves from the sandbox store without a network call', async () => {
    const artifact = makeArtifact({ id: 'store-1', sourcePath: '/workspace/output/chart.png' });
    vi.mocked(useSandboxStore.getState).mockReturnValue({
      activeProjectId: 'proj-1',
      artifacts: new Map([[artifact.id, artifact]]),
    } as never);

    const result = await findArtifactForSandboxPath('/workspace/output/chart.png');

    expect(result?.id).toBe('store-1');
    expect(artifactService.list).not.toHaveBeenCalled();
  });

  it('falls back to the artifact list request when not in the store', async () => {
    const artifact = makeArtifact({ id: 'remote-1', sourcePath: '/workspace/output/chart.png' });
    vi.mocked(artifactService.list).mockResolvedValue({ artifacts: [artifact], total: 1 });

    const result = await findArtifactForSandboxPath('/workspace/output/chart.png');

    expect(result?.id).toBe('remote-1');
    expect(artifactService.list).toHaveBeenCalledWith('proj-1', { limit: 500 });
  });

  it('returns undefined when there is no active project', async () => {
    vi.mocked(useSandboxStore.getState).mockReturnValue({
      activeProjectId: null,
      artifacts: new Map<string, Artifact>(),
    } as never);

    const result = await findArtifactForSandboxPath('/workspace/output/chart.png');

    expect(result).toBeUndefined();
    expect(artifactService.list).not.toHaveBeenCalled();
  });
});

describe('resolveSandboxArtifactUrl', () => {
  it('resolves from the conversation timeline without a project lookup', async () => {
    vi.mocked(useTimelineStore.getState).mockReturnValue({
      timeline: [
        {
          type: 'artifact_created',
          filename: 'memstack-logical-architecture.png',
          sourcePath: '/workspace/output/memstack-logical-architecture.png',
          url: 'https://files.example.com/memstack-logical-architecture.png',
        },
      ],
      agentTimeline: [],
    } as never);
    // No artifacts in the store and no project available.
    vi.mocked(useSandboxStore.getState).mockReturnValue({
      activeProjectId: null,
      artifacts: new Map<string, Artifact>(),
    } as never);

    const url = await resolveSandboxArtifactUrl(
      '/workspace/output/memstack-logical-architecture.png'
    );

    expect(url).toBe('https://files.example.com/memstack-logical-architecture.png');
    expect(artifactService.list).not.toHaveBeenCalled();
  });

  it('matches a bare filename against a timeline batch event', async () => {
    vi.mocked(useTimelineStore.getState).mockReturnValue({
      timeline: [],
      agentTimeline: [
        {
          type: 'artifacts_batch',
          artifacts: [
            { filename: 'chart.png', url: 'https://files.example.com/chart.png' },
          ],
        },
      ],
    } as never);
    vi.mocked(useSandboxStore.getState).mockReturnValue({
      activeProjectId: null,
      artifacts: new Map<string, Artifact>(),
    } as never);

    const url = await resolveSandboxArtifactUrl('output/chart.png');

    expect(url).toBe('https://files.example.com/chart.png');
  });

  it('falls back to the artifact list when the timeline has no match', async () => {
    const artifact = makeArtifact({
      sourcePath: '/workspace/output/chart.png',
      url: 'https://files.example.com/chart.png',
    });
    vi.mocked(artifactService.list).mockResolvedValue({ artifacts: [artifact], total: 1 });

    const url = await resolveSandboxArtifactUrl('/workspace/output/chart.png');

    expect(url).toBe('https://files.example.com/chart.png');
    expect(artifactService.list).toHaveBeenCalledWith('proj-1', { limit: 500 });
  });

  it('returns null when nothing resolves', async () => {
    vi.mocked(useSandboxStore.getState).mockReturnValue({
      activeProjectId: null,
      artifacts: new Map<string, Artifact>(),
    } as never);

    const url = await resolveSandboxArtifactUrl('/workspace/output/missing.png');

    expect(url).toBeNull();
  });
});
