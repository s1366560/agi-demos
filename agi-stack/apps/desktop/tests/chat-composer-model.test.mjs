import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  appendComposerContextItem,
  composerAgentExecutionContext,
  composerFileMetadata,
  composerHasSendableAttachment,
  chatComposerPresentation,
  composerMentionIds,
  workspaceMessageRequiresDefaultAgentLaunch,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/chatComposerModel.js';

const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
);
const composerControlsSource = readFileSync(
  new URL('../src/features/chat/ComposerControls.tsx', import.meta.url),
  'utf8',
);
const composerPlusMenuSource = readFileSync(
  new URL('../src/features/chat/ComposerPlusMenu.tsx', import.meta.url),
  'utf8',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('session composer keeps run-scoped steering and queue handoff affordances', () => {
  assert.deepEqual(chatComposerPresentation('session'), {
    placeholderKey: 'session.steerComposerPlaceholder',
    showCommands: false,
    showRuntimeControls: false,
    showRuntimeStatus: false,
    showWorkflowStrip: false,
    showPaneHeader: false,
    showQueueHandoff: true,
  });
});

test('workspace composer omits run-scoped queue handoff without a selected session', () => {
  assert.deepEqual(chatComposerPresentation('workspace'), {
    placeholderKey: null,
    showCommands: true,
    showRuntimeControls: true,
    showRuntimeStatus: true,
    showWorkflowStrip: true,
    showPaneHeader: true,
    showQueueHandoff: false,
  });
});

test('session and workspace composers expose a controlled model switch backed by real options', () => {
  assert.match(chatPanelSource, /modelOptions\?: readonly ComposerModelOption\[\]/);
  assert.match(chatPanelSource, /selectedModelValue\?: string \| null/);
  assert.match(chatPanelSource, /onModelChange\?: \(value: string\) => Promise<void>/);
  assert.match(
    chatPanelSource,
    /composerVariant === 'session'[\s\S]*?<ComposerControls[\s\S]*?onModelChange=\{onModelChange\}/,
  );
  assert.match(composerControlsSource, /role="listbox"/);
  assert.match(composerControlsSource, /type="search"/);
  assert.doesNotMatch(composerControlsSource, /Workspace model|Cloud model/);
});

test('structured workspace Agent selections produce authoritative mention ids only', () => {
  assert.deepEqual(
    composerMentionIds([
      {
        kind: 'agent',
        resource_id: ' agent-research ',
        label: '@Research',
        metadata: { mention_target: true },
      },
      {
        kind: 'agent',
        resource_id: 'definition-reviewer',
        label: 'Reviewer definition',
      },
      {
        kind: 'skill',
        resource_id: 'agent-research',
        label: 'Research skill',
        metadata: { mention_target: true },
      },
      {
        kind: 'agent',
        resource_id: 'agent-research',
        label: '@Research duplicate',
        metadata: { mention_target: true },
      },
    ]),
    ['agent-research'],
  );
});

test('workspace mention routing suppresses the duplicate default Agent launch', () => {
  assert.equal(workspaceMessageRequiresDefaultAgentLaunch({ content: 'Plain message' }), true);
  assert.equal(
    workspaceMessageRequiresDefaultAgentLaunch({
      content: 'Delegate this',
      mentions: ['agent-research'],
    }),
    false,
  );
  assert.match(composerPlusMenuSource, /listWorkspaceAgents/);
  assert.match(composerPlusMenuSource, /mention_target: true/);
  assert.match(appSource, /workspaceMessageRequiresDefaultAgentLaunch\(saved\)/);
});

test('composer execution context routes selected Web resources into the cloud Agent turn', () => {
  const contextItems = [
    {
      kind: 'agent',
      resource_id: 'agent-research',
      label: '@Research',
      metadata: { mention_target: true },
    },
    {
      kind: 'agent',
      resource_id: 'definition-reviewer',
      label: 'Reviewer',
      metadata: {
        mention_target: false,
        execution_slot: 'agent',
        execution_agent_id: 'definition-reviewer',
      },
    },
    {
      kind: 'agent',
      resource_id: 'subagent-security',
      label: 'Security reviewer',
      metadata: {
        mention_target: false,
        execution_slot: 'subagent',
        execution_subagent_name: 'security-reviewer',
      },
    },
    {
      kind: 'skill',
      resource_id: 'skill-source-research',
      label: 'Source research',
      metadata: {
        execution_slot: 'skill',
        execution_skill_name: 'source-research',
      },
    },
    { kind: 'plugin', resource_id: 'github', label: 'GitHub' },
    {
      kind: 'command',
      resource_id: '/review',
      label: '/review',
      metadata: { execution_slot: 'command' },
    },
  ];

  assert.deepEqual(composerAgentExecutionContext('Review this change', contextItems), {
    message:
      '[System Instruction: Delegate this task strictly to SubAgent "security-reviewer"]\n' +
      '/review Review this change',
    mentions: ['agent-research'],
    agentId: 'definition-reviewer',
    forcedSkillName: 'source-research',
    appModelContext: {
      desktop_composer_context: {
        resources: [
          { kind: 'agent', resource_id: 'agent-research' },
          { kind: 'agent', resource_id: 'definition-reviewer' },
          { kind: 'agent', resource_id: 'subagent-security' },
          { kind: 'skill', resource_id: 'skill-source-research' },
          { kind: 'plugin', resource_id: 'github' },
        ],
      },
    },
  });
});

test('uploaded attachment context becomes authoritative sandbox file metadata', () => {
  const contextItems = [
    {
      kind: 'attachment',
      resource_id: '/workspace/input/evidence.txt',
      label: 'evidence.txt',
      metadata: {
        filename: 'evidence.txt',
        sandbox_path: '/workspace/input/evidence.txt',
        mime_type: 'text/plain',
        size_bytes: 42,
      },
    },
    {
      kind: 'attachment',
      resource_id: 'pending:ignored.txt',
      label: 'ignored.txt',
      metadata: { filename: 'ignored.txt', size_bytes: 0 },
    },
  ];

  assert.deepEqual(composerFileMetadata(contextItems), [
    {
      filename: 'evidence.txt',
      sandbox_path: '/workspace/input/evidence.txt',
      mime_type: 'text/plain',
      size_bytes: 42,
    },
  ]);
  assert.equal(composerHasSendableAttachment(contextItems), true);
  assert.deepEqual(composerAgentExecutionContext('Inspect this evidence', contextItems), {
    message: 'Inspect this evidence',
    mentions: [],
    fileMetadata: [
      {
        filename: 'evidence.txt',
        sandbox_path: '/workspace/input/evidence.txt',
        mime_type: 'text/plain',
        size_bytes: 42,
      },
    ],
  });
});

test('single-slot composer resources replace the prior selection without affecting mentions', () => {
  const mention = {
    kind: 'agent',
    resource_id: 'agent-research',
    label: '@Research',
    metadata: { mention_target: true },
  };
  const firstSkill = {
    kind: 'skill',
    resource_id: 'skill-one',
    label: 'Skill one',
    metadata: { execution_slot: 'skill', execution_skill_name: 'skill-one' },
  };
  const secondSkill = {
    kind: 'skill',
    resource_id: 'skill-two',
    label: 'Skill two',
    metadata: { execution_slot: 'skill', execution_skill_name: 'skill-two' },
  };

  const selected = [mention, firstSkill, secondSkill].reduce(
    (current, item) => appendComposerContextItem(current, item),
    [],
  );
  assert.deepEqual(selected, [mention, secondSkill]);
  assert.equal(appendComposerContextItem(selected, secondSkill), selected);
});

test('composer catalog exposes execution metadata for Agents, SubAgents, skills, and commands', () => {
  assert.match(composerPlusMenuSource, /listManagedSubAgents/);
  assert.match(composerPlusMenuSource, /execution_agent_id/);
  assert.match(composerPlusMenuSource, /execution_subagent_name/);
  assert.match(composerPlusMenuSource, /execution_skill_name/);
  assert.match(composerPlusMenuSource, /execution_slot: 'command'/);
  assert.match(appSource, /composerAgentExecutionContext\(content, contextItems\)/);
  assert.match(appSource, /agentId: execution\.agentId/);
  assert.match(appSource, /forcedSkillName: execution\.forcedSkillName/);
  assert.match(appSource, /appModelContext: execution\.appModelContext/);
  assert.match(
    appSource,
    /composerAgentExecutionContext\([\s\S]*?buildPlanningPrompt\(definition\)[\s\S]*?input\.contextItems/,
  );
  assert.match(composerPlusMenuSource, /uploadSandboxFile/);
  assert.match(composerPlusMenuSource, /sandbox_path/);
  assert.match(composerPlusMenuSource, /onUploadingChange\?\.\(true\)/);
  assert.match(chatPanelSource, /composerHasSendableAttachment\(contextItems\)/);
  assert.match(chatPanelSource, /!uploadingAttachments/);
  assert.match(chatPanelSource, /onUploadingChange=\{setUploadingAttachments\}/);
});
