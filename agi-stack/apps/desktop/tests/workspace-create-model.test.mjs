import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  MIN_WORKSPACE_DESCRIPTION_LENGTH,
  WORKSPACE_COLLABORATION_MODES,
  WORKSPACE_USE_CASES,
  buildWorkspaceCreateInput,
  emptyWorkspaceCreateDraft,
  isIsolatedSandboxCodeRoot,
  mergeWorkspaceIntoProjectCatalog,
  normalizeSandboxCodeRoot,
  validateWorkspaceCreateDraft,
  workspaceCreateDraftIsDirty,
  workspaceCreateRadioNextValue,
  workspaceCreateScopeIsCurrent,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceCreateModel.js'
);

const validDraft = {
  name: '  Incident response  ',
  description: '  Coordinate incident response and recovery.  ',
  useCase: 'operations',
  collaborationMode: 'multi_agent_shared',
  sandboxCodeRoot: '',
};

test('workspace creation requires the Web name, objective, use-case, and collaboration contract', () => {
  const empty = emptyWorkspaceCreateDraft();
  assert.equal(validateWorkspaceCreateDraft(empty).canSubmit, false);
  assert.equal(workspaceCreateDraftIsDirty(empty), false);

  const descriptionBoundary = 'x'.repeat(MIN_WORKSPACE_DESCRIPTION_LENGTH);
  const ready = validateWorkspaceCreateDraft({
    ...validDraft,
    name: 'A'.repeat(120),
    description: descriptionBoundary,
  });
  assert.equal(ready.canSubmit, true);
  assert.equal(ready.nameReady, true);
  assert.equal(ready.descriptionReady, true);
  assert.equal(workspaceCreateDraftIsDirty(validDraft), true);

  assert.equal(
    validateWorkspaceCreateDraft({ ...validDraft, name: 'A'.repeat(121) }).canSubmit,
    false,
  );
  assert.equal(
    validateWorkspaceCreateDraft({
      ...validDraft,
      description: 'x'.repeat(MIN_WORKSPACE_DESCRIPTION_LENGTH - 1),
    }).canSubmit,
    false,
  );
  assert.equal(
    validateWorkspaceCreateDraft({ ...validDraft, description: 'x'.repeat(601) }).canSubmit,
    false,
  );
  assert.equal(validateWorkspaceCreateDraft({ ...validDraft, useCase: null }).canSubmit, false);
  assert.equal(
    validateWorkspaceCreateDraft({ ...validDraft, collaborationMode: null }).canSubmit,
    false,
  );

  assert.deepEqual(WORKSPACE_USE_CASES, [
    'general',
    'programming',
    'conversation',
    'research',
    'operations',
  ]);
  assert.deepEqual(WORKSPACE_COLLABORATION_MODES, [
    'single_agent',
    'multi_agent_shared',
    'multi_agent_isolated',
    'autonomous',
  ]);
});

test('programming workspace code roots normalize to an isolated /workspace child', () => {
  assert.equal(normalizeSandboxCodeRoot('repo'), '/workspace/repo');
  assert.equal(normalizeSandboxCodeRoot('/workspace/repo///'), '/workspace/repo');
  assert.equal(normalizeSandboxCodeRoot('/tmp/repo/'), '/tmp/repo');
  assert.equal(isIsolatedSandboxCodeRoot('/workspace/repo'), true);
  assert.equal(isIsolatedSandboxCodeRoot('/workspace'), false);
  assert.equal(isIsolatedSandboxCodeRoot('/tmp/repo'), false);

  assert.equal(
    validateWorkspaceCreateDraft({
      ...validDraft,
      useCase: 'programming',
      sandboxCodeRoot: '/workspace',
    }).canSubmit,
    false,
  );
  assert.equal(
    validateWorkspaceCreateDraft({
      ...validDraft,
      useCase: 'programming',
      sandboxCodeRoot: 'repo',
    }).canSubmit,
    true,
  );
  assert.equal(
    validateWorkspaceCreateDraft({
      ...validDraft,
      useCase: 'general',
      sandboxCodeRoot: '/tmp/not-used',
    }).canSubmit,
    true,
  );
});

test('workspace creation builds the complete Web-equivalent metadata contract', () => {
  const programming = buildWorkspaceCreateInput({
    ...validDraft,
    useCase: 'programming',
    collaborationMode: 'autonomous',
    sandboxCodeRoot: 'service-a/',
  });
  assert.deepEqual(programming, {
    name: 'Incident response',
    description: 'Coordinate incident response and recovery.',
    useCase: 'programming',
    collaborationMode: 'autonomous',
    sandboxCodeRoot: '/workspace/service-a',
    metadata: {
      source: 'desktop',
      workspace_use_case: 'programming',
      workspace_type: 'software_development',
      collaboration_mode: 'autonomous',
      agent_conversation_mode: 'autonomous',
      autonomy_profile: { workspace_type: 'software_development' },
      sandbox_code_root: '/workspace/service-a',
      code_context: { sandbox_code_root: '/workspace/service-a' },
    },
  });

  const conversation = buildWorkspaceCreateInput({
    ...validDraft,
    useCase: 'conversation',
    collaborationMode: 'single_agent',
    sandboxCodeRoot: '/workspace/ignored',
  });
  assert.equal(conversation?.sandboxCodeRoot, undefined);
  assert.deepEqual(conversation?.metadata, {
    source: 'desktop',
    workspace_use_case: 'conversation',
    workspace_type: 'general',
    collaboration_mode: 'single_agent',
    agent_conversation_mode: 'single_agent',
    autonomy_profile: { workspace_type: 'general' },
  });
  assert.equal(buildWorkspaceCreateInput(emptyWorkspaceCreateDraft()), null);
});

test('workspace creation keyboard, scope, and catalog helpers remain deterministic', () => {
  assert.equal(
    workspaceCreateRadioNextValue(WORKSPACE_USE_CASES, 'general', 'ArrowRight'),
    'programming',
  );
  assert.equal(
    workspaceCreateRadioNextValue(WORKSPACE_USE_CASES, 'general', 'ArrowLeft'),
    'operations',
  );
  assert.equal(
    workspaceCreateRadioNextValue(WORKSPACE_USE_CASES, 'research', 'Home'),
    'general',
  );
  assert.equal(
    workspaceCreateRadioNextValue(WORKSPACE_USE_CASES, 'research', 'End'),
    'operations',
  );
  assert.equal(
    workspaceCreateRadioNextValue(WORKSPACE_USE_CASES, 'research', 'Enter'),
    null,
  );

  assert.equal(
    workspaceCreateScopeIsCurrent(
      { tenantId: 'tenant-1', projectId: 'project-1', epoch: 4, contextRevision: 7 },
      { tenantId: 'tenant-1', projectId: 'project-1', epoch: 4, contextRevision: 7 },
    ),
    true,
  );
  assert.equal(
    workspaceCreateScopeIsCurrent(
      { tenantId: 'tenant-1', projectId: 'project-1', epoch: 4, contextRevision: 7 },
      { tenantId: 'tenant-1', projectId: 'project-2', epoch: 5, contextRevision: 7 },
    ),
    false,
  );

  const created = {
    id: 'workspace-new',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'New workspace',
  };
  assert.deepEqual(
    mergeWorkspaceIntoProjectCatalog(
      {
        'project-1': [
          { ...created, name: 'Old duplicate' },
          { id: 'workspace-existing', project_id: 'project-1', name: 'Existing' },
        ],
        'project-2': [{ id: 'workspace-other', project_id: 'project-2', name: 'Other' }],
      },
      created,
    ),
    {
      'project-1': [
        created,
        { id: 'workspace-existing', project_id: 'project-1', name: 'Existing' },
      ],
      'project-2': [{ id: 'workspace-other', project_id: 'project-2', name: 'Other' }],
    },
  );
});
