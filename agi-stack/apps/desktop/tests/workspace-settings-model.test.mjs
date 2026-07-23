import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  MAX_WORKSPACE_SETTINGS_DESCRIPTION_LENGTH,
  MAX_WORKSPACE_SETTINGS_NAME_LENGTH,
  buildWorkspaceUpdateInput,
  hydrateWorkspaceSettingsDraft,
  replaceWorkspaceInList,
  replaceWorkspaceInProjectCatalog,
  validateWorkspaceSettingsDraft,
  workspaceSettingsDraftIsDirty,
  workspaceSettingsProjectionSignature,
  workspaceSettingsScopeIsCurrent,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceSettingsModel.js'
);

function workspace(overrides = {}) {
  return {
    id: 'workspace-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'Desktop workspace',
    description: 'Coordinate desktop parity delivery.',
    is_archived: false,
    metadata: {
      unknown_extension: { preserved: true },
      source_control: { provider: 'github', repo: 'memstack/desktop' },
      workspace_type: 'software_development',
      agent_conversation_mode: 'multi_agent_isolated',
      autonomy_profile: {
        workspace_type: 'software_development',
        completion_policy: { minimum_verification_grade: 'pass' },
      },
      code_context: {
        sandbox_code_root: '/workspace/desktop',
        language: 'typescript',
      },
    },
    ...overrides,
  };
}

test('workspace settings hydrate Web fallbacks and current server projection', () => {
  const draft = hydrateWorkspaceSettingsDraft(workspace());
  assert.deepEqual(draft, {
    name: 'Desktop workspace',
    description: 'Coordinate desktop parity delivery.',
    isArchived: false,
    useCase: 'programming',
    collaborationMode: 'multi_agent_isolated',
    sandboxCodeRoot: '/workspace/desktop',
  });

  assert.deepEqual(
    hydrateWorkspaceSettingsDraft(
      workspace({
        metadata: {
          workspace_use_case: 'research',
          collaboration_mode: 'autonomous',
          sandbox_code_root: '/workspace/research',
        },
      }),
    ),
    {
      name: 'Desktop workspace',
      description: 'Coordinate desktop parity delivery.',
      isArchived: false,
      useCase: 'research',
      collaborationMode: 'autonomous',
      sandboxCodeRoot: '/workspace/research',
    },
  );
});

test('workspace settings projection signatures advance with same-scope server updates', () => {
  const initial = workspace({ updated_at: '2026-07-23T00:00:00Z' });
  const updated = workspace({ updated_at: '2026-07-23T00:01:00Z' });
  assert.equal(
    workspaceSettingsProjectionSignature(initial),
    'workspace-1:2026-07-23T00:00:00Z',
  );
  assert.notEqual(
    workspaceSettingsProjectionSignature(initial),
    workspaceSettingsProjectionSignature(updated),
  );
});

test('workspace settings enforce Web field boundaries and isolated code roots', () => {
  const baseline = hydrateWorkspaceSettingsDraft(workspace());
  assert.equal(MAX_WORKSPACE_SETTINGS_NAME_LENGTH, 255);
  assert.equal(MAX_WORKSPACE_SETTINGS_DESCRIPTION_LENGTH, 1000);
  assert.equal(
    validateWorkspaceSettingsDraft({
      ...baseline,
      name: 'A'.repeat(255),
      description: 'D'.repeat(1000),
    }).canSubmit,
    true,
  );
  assert.equal(
    validateWorkspaceSettingsDraft({ ...baseline, name: 'A'.repeat(256) }).canSubmit,
    false,
  );
  assert.equal(
    validateWorkspaceSettingsDraft({
      ...baseline,
      description: 'D'.repeat(1001),
    }).canSubmit,
    false,
  );
  assert.equal(
    validateWorkspaceSettingsDraft({
      ...baseline,
      useCase: 'programming',
      sandboxCodeRoot: '',
    }).canSubmit,
    false,
  );
  assert.equal(
    validateWorkspaceSettingsDraft({
      ...baseline,
      useCase: 'general',
      sandboxCodeRoot: '',
    }).canSubmit,
    true,
  );
  assert.equal(
    validateWorkspaceSettingsDraft({
      ...baseline,
      useCase: 'general',
      sandboxCodeRoot: '/tmp/desktop',
    }).canSubmit,
    false,
  );
});

test('workspace settings preserve unknown metadata while updating exposed fields', () => {
  const current = workspace();
  const draft = {
    ...hydrateWorkspaceSettingsDraft(current),
    name: '  Renamed workspace  ',
    description: '  Updated objective.  ',
    isArchived: true,
    useCase: 'operations',
    collaborationMode: 'autonomous',
    sandboxCodeRoot: '/workspace/ops/',
  };
  const input = buildWorkspaceUpdateInput(current, draft);
  assert.deepEqual(input, {
    name: 'Renamed workspace',
    description: 'Updated objective.',
    isArchived: true,
    metadata: {
      unknown_extension: { preserved: true },
      source_control: { provider: 'github', repo: 'memstack/desktop' },
      workspace_type: 'operations',
      workspace_use_case: 'operations',
      collaboration_mode: 'autonomous',
      agent_conversation_mode: 'autonomous',
      autonomy_profile: {
        workspace_type: 'operations',
        completion_policy: { minimum_verification_grade: 'pass' },
      },
      sandbox_code_root: '/workspace/ops',
      code_context: {
        sandbox_code_root: '/workspace/ops',
        language: 'typescript',
      },
    },
  });
  assert.equal(workspaceSettingsDraftIsDirty(draft, hydrateWorkspaceSettingsDraft(current)), true);

  const cleared = buildWorkspaceUpdateInput(current, {
    ...draft,
    useCase: 'general',
    sandboxCodeRoot: '',
  });
  assert.equal('sandbox_code_root' in cleared.metadata, false);
  assert.deepEqual(cleared.metadata.code_context, { language: 'typescript' });
  assert.equal(cleared.metadata.unknown_extension.preserved, true);
  assert.equal(
    workspaceSettingsDraftIsDirty(
      { ...hydrateWorkspaceSettingsDraft(current), name: ' Desktop workspace ' },
      hydrateWorkspaceSettingsDraft(current),
    ),
    false,
  );
});

test('workspace settings scope and catalog replacement reject stale projections', () => {
  const scope = {
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    epoch: 3,
    contextRevision: 8,
  };
  assert.equal(workspaceSettingsScopeIsCurrent(scope, { ...scope }), true);
  assert.equal(
    workspaceSettingsScopeIsCurrent(scope, { ...scope, workspaceId: 'workspace-2' }),
    false,
  );

  const original = workspace();
  const updated = workspace({ name: 'Updated', is_archived: true });
  const sibling = workspace({ id: 'workspace-2', name: 'Sibling' });
  assert.deepEqual(replaceWorkspaceInList([original, sibling], updated), [updated, sibling]);
  assert.deepEqual(
    replaceWorkspaceInProjectCatalog(
      {
        'project-1': [original, sibling],
        'project-2': [workspace({ id: 'workspace-3', project_id: 'project-2' })],
      },
      updated,
    ),
    {
      'project-1': [updated, sibling],
      'project-2': [workspace({ id: 'workspace-3', project_id: 'project-2' })],
    },
  );
});
