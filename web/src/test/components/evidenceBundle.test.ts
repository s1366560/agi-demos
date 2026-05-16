import { describe, expect, it } from 'vitest';

import {
  buildEvidenceBundle,
  selectEvidenceBundle,
} from '@/components/agent/evidence/evidenceBundle';
import type { Artifact, ArtifactCategory } from '@/types/agent/config';

const BASE = {
  projectId: 'p1',
  tenantId: 't1',
  status: 'ready' as const,
  createdAt: '2025-01-01T00:00:00Z',
};

function make(
  partial: Partial<Artifact> & Pick<Artifact, 'id' | 'filename' | 'mimeType'>
): Artifact {
  return {
    ...BASE,
    sizeBytes: 1024,
    category: 'other' as ArtifactCategory,
    ...partial,
  } as Artifact;
}

describe('evidenceBundle', () => {
  it('buckets test runs, diffs, screenshots, and logs', () => {
    const artifacts: Artifact[] = [
      make({ id: '1', filename: 'shot.png', mimeType: 'image/png', category: 'image' }),
      make({ id: '2', filename: 'change.diff', mimeType: 'text/plain' }),
      make({
        id: '3',
        filename: 'pytest.json',
        mimeType: 'application/json',
        sourceTool: 'run_tests',
      }),
      make({ id: '4', filename: 'agent.log', mimeType: 'text/plain' }),
      make({ id: '5', filename: 'misc.bin', mimeType: 'application/octet-stream' }),
    ];
    const bundle = buildEvidenceBundle(artifacts);

    expect(bundle.testRuns.map((a) => a.id)).toEqual(['3']);
    expect(bundle.diffs.map((a) => a.id)).toEqual(['2']);
    expect(bundle.screenshots.map((a) => a.id)).toEqual(['1']);
    expect(bundle.logs.map((a) => a.id)).toEqual(['4']);
    expect(bundle.total).toBe(4); // misc.bin not bucketed
  });

  it('returns an empty bundle for no artifacts', () => {
    expect(buildEvidenceBundle([]).total).toBe(0);
  });

  it('selectEvidenceBundle filters by conversationId', () => {
    const artifacts: Artifact[] = [
      make({
        id: '1',
        filename: 'a.png',
        mimeType: 'image/png',
        category: 'image',
        conversationId: 'c1',
      }),
      make({
        id: '2',
        filename: 'b.png',
        mimeType: 'image/png',
        category: 'image',
        conversationId: 'c2',
      }),
    ];
    const bundle = selectEvidenceBundle(artifacts, 'c1');
    expect(bundle.screenshots.map((a) => a.id)).toEqual(['1']);
  });

  it('test-run preference wins over diff when sourceTool matches', () => {
    const artifact = make({
      id: '1',
      filename: 'changes.diff',
      mimeType: 'text/plain',
      sourceTool: 'run_tests',
    });
    const bundle = buildEvidenceBundle([artifact]);
    expect(bundle.testRuns).toHaveLength(1);
    expect(bundle.diffs).toHaveLength(0);
  });
});
