import { describe, expect, it } from 'vitest';

import {
  buildArtifactFileTree,
  buildSandboxFileTree,
  parseSandboxGlobPaths,
} from '@/components/agent/canvas/canvasFileTreeModel';

import type { Artifact } from '@/types/agent';

function makeArtifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: 'artifact-1',
    projectId: 'project-1',
    tenantId: 'tenant-1',
    filename: 'notes.md',
    mimeType: 'text/markdown',
    category: 'document',
    sizeBytes: 12,
    status: 'ready',
    createdAt: '2026-06-24T00:00:00Z',
    ...overrides,
  };
}

describe('canvasFileTreeModel', () => {
  it('normalizes sandbox glob output and filters non-path lines', () => {
    const paths = parseSandboxGlobPaths(
      [
        '',
        'src/app.ts',
        '/workspace/README.md',
        'No files found matching: nope',
        '... and 25 more files',
        'Hint: try another path',
        'src/app.ts',
      ].join('\n')
    );

    expect(paths).toEqual(['/workspace/src/app.ts', '/workspace/README.md']);
  });

  it('builds a sorted sandbox directory tree', () => {
    const tree = buildSandboxFileTree([
      '/workspace/src/app.ts',
      '/workspace/src/index.ts',
      '/workspace/README.md',
    ]);

    expect(tree).toEqual([
      {
        id: 'sandbox:dir:/workspace/src',
        source: 'sandbox',
        kind: 'directory',
        name: 'src',
        path: '/workspace/src',
        children: [
          {
            id: 'sandbox:file:/workspace/src/app.ts',
            source: 'sandbox',
            kind: 'file',
            name: 'app.ts',
            path: '/workspace/src/app.ts',
            children: [],
          },
          {
            id: 'sandbox:file:/workspace/src/index.ts',
            source: 'sandbox',
            kind: 'file',
            name: 'index.ts',
            path: '/workspace/src/index.ts',
            children: [],
          },
        ],
      },
      {
        id: 'sandbox:file:/workspace/README.md',
        source: 'sandbox',
        kind: 'file',
        name: 'README.md',
        path: '/workspace/README.md',
        children: [],
      },
    ]);
  });

  it('builds artifact trees from sourcePath and filename fallback', () => {
    const readyWithSource = makeArtifact({
      id: 'artifact-source',
      filename: 'report.pdf',
      mimeType: 'application/pdf',
      category: 'document',
      sourcePath: '/workspace/reports/report.pdf',
    });
    const readyWithoutSource = makeArtifact({
      id: 'artifact-filename',
      filename: 'chart.png',
      mimeType: 'image/png',
      category: 'image',
    });
    const pending = makeArtifact({ id: 'artifact-pending', status: 'pending' });

    const tree = buildArtifactFileTree([readyWithoutSource, pending, readyWithSource]);

    expect(tree).toHaveLength(2);
    expect(tree[0]).toMatchObject({
      id: 'artifacts:dir:workspace',
      name: 'workspace',
      kind: 'directory',
    });
    expect(tree[0]?.children[0]?.children[0]).toMatchObject({
      id: 'artifacts:file:artifact-source',
      name: 'report.pdf',
      path: '/workspace/reports/report.pdf',
      artifact: readyWithSource,
    });
    expect(tree[1]).toMatchObject({
      id: 'artifacts:file:artifact-filename',
      name: 'chart.png',
      path: 'chart.png',
      artifact: readyWithoutSource,
    });
  });
});
