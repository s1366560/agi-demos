import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  skillCreateMutationFromDraft,
  skillDraftFrom,
  skillUpdateMutationFromDraft,
  validateSkillDraft,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/skillEditorModel.js');

const skill = {
  id: 'skill-review',
  tenant_id: 'tenant-a',
  project_id: 'project-a',
  name: 'release-review',
  description: 'Review release readiness.',
  status: 'active',
  scope: 'project',
  tools: ['read', 'git_diff'],
  full_content:
    '---\nname: release-review\ndescription: "Review release readiness."\nlicense: "MIT"\n---\n\n# Release review\n\nVerify the evidence.\n',
  metadata: { owner: 'platform' },
  license: 'MIT',
  compatibility: 'Requires git',
  allowed_tools_raw: 'read git_diff',
  spec_version: '1.0',
};

test('new skill drafts default to the selected project and AgentSkills-safe values', () => {
  assert.deepEqual(skillDraftFrom(null, 'project-a'), {
    name: '',
    description: '',
    scope: 'project',
    projectId: 'project-a',
    body: '# new-skill\n\n## Instructions\n\n',
    allowedToolsRaw: '',
    metadata: '{}',
    license: '',
    compatibility: '',
    specVersion: '1.0',
  });
});

test('editing a skill preserves scope, advanced package metadata, and the SKILL.md body', () => {
  assert.deepEqual(skillDraftFrom(skill, 'project-other'), {
    name: 'release-review',
    description: 'Review release readiness.',
    scope: 'project',
    projectId: 'project-a',
    body: '# Release review\n\nVerify the evidence.',
    allowedToolsRaw: 'read git_diff',
    metadata: '{\n  "owner": "platform"\n}',
    license: 'MIT',
    compatibility: 'Requires git',
    specVersion: '1.0',
  });
});

test('skill mutations normalize tools and produce a complete AgentSkills package', () => {
  const draft = {
    ...skillDraftFrom(skill, null),
    name: 'release-readiness',
    scope: 'tenant',
    projectId: '',
    allowedToolsRaw: 'read  git_diff read',
    metadata: '{"owner":"release"}',
    license: '',
  };

  const create = skillCreateMutationFromDraft(draft);
  assert.deepEqual(create, {
    name: 'release-readiness',
    description: 'Review release readiness.',
    scope: 'tenant',
    project_id: null,
    tools: ['read', 'git_diff'],
    full_content:
      '---\nname: release-readiness\ndescription: "Review release readiness."\ncompatibility: "Requires git"\nallowed-tools: "read  git_diff read"\nmetadata: {"owner":"release"}\n---\n\n# Release review\n\nVerify the evidence.\n',
    metadata: { owner: 'release' },
    license: null,
    compatibility: 'Requires git',
    allowed_tools_raw: 'read  git_diff read',
    spec_version: '1.0',
  });

  const update = skillUpdateMutationFromDraft(draft);
  assert.equal('scope' in update, false);
  assert.equal('project_id' in update, false);
  assert.equal(update.full_content, create.full_content);
});

test('skill validation covers package naming, scope, metadata, and backend length constraints', () => {
  assert.deepEqual(validateSkillDraft(skillDraftFrom(skill, null)), {});
  assert.deepEqual(
    validateSkillDraft({
      ...skillDraftFrom(skill, null),
      name: 'Release Review',
      description: '',
      scope: 'project',
      projectId: '',
      metadata: '[]',
      compatibility: 'x'.repeat(501),
      allowedToolsRaw: 'x'.repeat(2001),
      specVersion: 'x'.repeat(33),
    }),
    {
      name: 'invalid_name',
      description: 'required',
      projectId: 'required',
      metadata: 'invalid_metadata',
      compatibility: 'too_long',
      allowedToolsRaw: 'too_long',
      specVersion: 'too_long',
    }
  );
});
