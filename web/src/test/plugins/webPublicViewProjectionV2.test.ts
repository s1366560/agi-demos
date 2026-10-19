import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

import { beforeAll, expect, it } from 'vitest';
import {
  createWebRendererDefinitionsV2,
  parseWebPublicViewV2,
  RendererPluginRuntimeV2,
  WebPublicViewReconcilerV2,
} from '@agistack/plugin-runtime';

import { validateWebRendererContributionsV2 } from '../../routes/v2/webRendererArtifactCatalogV2';

let views: Record<string, unknown>;

beforeAll(() => {
  const root = resolve(__dirname, '../../../..');
  const projected = execFileSync(
    'uv',
    [
      'run',
      'python',
      '-c',
      [
        'import json',
        'from src.tests.unit.infrastructure.plugins.v2.test_web_public_view import scoped_override',
        'from src.infrastructure.plugins.v2.web_public_view import project_web_public_view_v2',
        'views = {}',
        'for kind in ("tenant", "project"):',
        '    payload, scope = scoped_override(kind)',
        '    views[kind] = project_web_public_view_v2(payload, authority_id="private-user-canary", authorized_scope=scope)',
        'print(json.dumps(views))',
      ].join('\n'),
    ],
    { cwd: root, encoding: 'utf8' }
  );
  views = JSON.parse(projected) as Record<string, unknown>;
});

it.each(['tenant', 'project'])(
  'loads the actual Python %s override projection without exposing private scope',
  async (scope) => {
    const payload = views[scope];
    expect(JSON.stringify(payload)).not.toContain('private-');
    const view = await parseWebPublicViewV2(payload);
    expect(view.snapshot.entries.every((entry) => entry.scope.kind === 'root')).toBe(true);
    expect(
      view.snapshot.entries.find((entry) => entry.config.id === 'web.feature.tenant-providers')
        ?.enabled
    ).toBe(false);
    const runtime = new RendererPluginRuntimeV2(
      'web',
      createWebRendererDefinitionsV2(validateWebRendererContributionsV2),
      validateWebRendererContributionsV2
    );
    const reconciler = new WebPublicViewReconcilerV2(runtime);
    try {
      await reconciler.apply(payload);
      expect(runtime.getSnapshot()?.snapshot.digest).toBe(view.snapshot.digest);
    } finally {
      await reconciler.close();
    }
  }
);
