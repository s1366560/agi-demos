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
import {
  MAX_COMPOSER_ATTACHMENT_BYTES,
  composerFileDragActive,
  composerFileDropAction,
  uploadComposerFilesSequentially,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/composerFileDropModel.js';

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
const composerCatalogSource = readFileSync(
  new URL('../src/features/chat/composerCatalogModel.ts', import.meta.url),
  'utf8',
);
const composerFileDropSource = readFileSync(
  new URL('../src/features/chat/useComposerFileDrop.ts', import.meta.url),
  'utf8',
);
const composerFileUploadSource = readFileSync(
  new URL('../src/features/chat/useComposerFileUpload.ts', import.meta.url),
  'utf8',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const agentConversationSource = [
  '../src/hooks/useAgentConversation.ts',
  '../src/hooks/useConversationThreads.ts',
  '../src/hooks/useConversationMessaging.ts',
]
  .map((path) => readFileSync(new URL(path, import.meta.url), 'utf8'))
  .join('\n');
const conversationThreadsSource = readFileSync(
  new URL('../src/hooks/useConversationThreads.ts', import.meta.url),
  'utf8',
);
const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');
const newThreadComposerSource = readFileSync(
  new URL('../src/features/task/NewThreadComposer.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

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
  assert.match(chatPanelSource, /onModelReset\?: \(\) => Promise<void>/);
  assert.match(
    chatPanelSource,
    /composerVariant === 'session'[\s\S]*?<ComposerControls[\s\S]*?onModelChange=\{onModelChange\}/,
  );
  assert.match(composerControlsSource, /chat\.resetModelOverride/);
  assert.match(composerControlsSource, /onReset/);
  assert.match(appSource, /updateAgentConversationConfig/);
  assert.match(appSource, /conversationRuntimeModelSelection/);
  assert.match(appSource, /onModelReset=\{[\s\S]{0,180}resetChatRuntimeModel/);
  assert.match(composerControlsSource, /role="listbox"/);
  assert.match(composerControlsSource, /type="search"/);
  assert.match(qaSource, /model-override-events/);
  assert.equal(
    i18nSource.split("'chat.resetModelOverride'").length - 1,
    2,
    'model reset must cover both locales',
  );
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
  assert.match(composerCatalogSource, /listWorkspaceAgents/);
  assert.match(composerPlusMenuSource, /mention_target: true/);
  assert.match(agentConversationSource, /workspaceMessageRequiresDefaultAgentLaunch\(saved\)/);
});

test('composer plus menu captures Escape and restores focus to its trigger', () => {
  assert.match(
    composerPlusMenuSource,
    /const triggerRef = useRef<HTMLButtonElement>\(null\)/,
  );
  assert.match(
    composerPlusMenuSource,
    /document\.addEventListener\('keydown', closeOnEscape, true\)/,
  );
  assert.match(
    composerPlusMenuSource,
    /event\.preventDefault\(\);[\s\S]{0,80}close\(true\)/,
  );
  assert.match(
    composerPlusMenuSource,
    /window\.requestAnimationFrame\(\(\) => triggerRef\.current\?\.focus\(\)\)/,
  );
  assert.match(composerPlusMenuSource, /ref=\{triggerRef\}/);
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
    message: '/review Review this change',
    mentions: ['agent-research'],
    agentId: 'definition-reviewer',
    forcedSkillName: 'source-research',
    subAgentId: 'subagent-security',
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

test('new composer threads forward the selected Sub Agent through every launch transport', () => {
  assert.match(conversationThreadsSource, /subAgentId: input\.subAgentId/);
  assert.equal(
    conversationThreadsSource.split('subAgentId: execution.subAgentId').length - 1,
    2,
  );
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

test('file drag activation accepts only supported enabled file payloads', () => {
  assert.equal(
    composerFileDragActive({
      disabled: false,
      supportsUpload: true,
      types: ['Files'],
    }),
    true,
  );
  assert.equal(
    composerFileDragActive({
      disabled: false,
      supportsUpload: true,
      types: ['text/plain'],
    }),
    false,
  );
  assert.equal(
    composerFileDragActive({
      disabled: true,
      supportsUpload: true,
      types: ['Files'],
    }),
    false,
  );
  assert.equal(
    composerFileDragActive({
      disabled: false,
      supportsUpload: false,
      types: ['Files'],
    }),
    false,
  );
});

test('file drop action distinguishes upload, unsupported, and ignored drops', () => {
  assert.equal(
    composerFileDropAction({
      disabled: false,
      supportsUpload: true,
      fileCount: 2,
    }),
    'upload',
  );
  assert.equal(
    composerFileDropAction({
      disabled: false,
      supportsUpload: false,
      fileCount: 1,
    }),
    'unsupported',
  );
  assert.equal(
    composerFileDropAction({
      disabled: true,
      supportsUpload: true,
      fileCount: 1,
    }),
    'ignore',
  );
  assert.equal(
    composerFileDropAction({
      disabled: false,
      supportsUpload: true,
      fileCount: 0,
    }),
    'ignore',
  );
});

test('composer uploads files sequentially and preserves partial success', async () => {
  assert.equal(MAX_COMPOSER_ATTACHMENT_BYTES, 16 * 1_048_576);
  let activeUploads = 0;
  let maximumActiveUploads = 0;
  const uploadedNames = [];
  const arrayBufferReads = [];
  const remaining = [];
  const files = [
    {
      name: 'evidence.txt',
      type: 'text/plain',
      size: 42,
      arrayBuffer: async () => {
        arrayBufferReads.push('evidence.txt');
        return new ArrayBuffer(42);
      },
    },
    {
      name: 'too-large.bin',
      type: 'application/octet-stream',
      size: MAX_COMPOSER_ATTACHMENT_BYTES + 1,
      arrayBuffer: async () => {
        arrayBufferReads.push('too-large.bin');
        return new ArrayBuffer(0);
      },
    },
    {
      name: 'failed.txt',
      type: 'text/plain',
      size: 18,
      arrayBuffer: async () => {
        arrayBufferReads.push('failed.txt');
        return new ArrayBuffer(18);
      },
    },
  ];

  const result = await uploadComposerFilesSequentially(
    files,
    async (file) => {
      activeUploads += 1;
      maximumActiveUploads = Math.max(maximumActiveUploads, activeUploads);
      uploadedNames.push(file.name);
      await file.arrayBuffer();
      activeUploads -= 1;
      if (file.name === 'failed.txt') throw new Error('sandbox unavailable');
      return {
        filename: file.name,
        sandbox_path: `/workspace/input/${file.name}`,
        mime_type: file.type,
        size_bytes: file.size,
      };
    },
    (count) => remaining.push(count),
  );

  assert.equal(maximumActiveUploads, 1);
  assert.deepEqual(uploadedNames, ['evidence.txt', 'failed.txt']);
  assert.deepEqual(arrayBufferReads, ['evidence.txt', 'failed.txt']);
  assert.deepEqual(remaining, [2, 1, 0]);
  assert.deepEqual(result.uploaded, [
    {
      file: files[0],
      metadata: {
        filename: 'evidence.txt',
        sandbox_path: '/workspace/input/evidence.txt',
        mime_type: 'text/plain',
        size_bytes: 42,
      },
    },
  ]);
  assert.deepEqual(result.failures, [
    { filename: 'too-large.bin', reason: 'too_large' },
    {
      filename: 'failed.txt',
      reason: 'upload_failed',
      error: 'sandbox unavailable',
    },
  ]);
});

test('Desktop composer wires Web-compatible file drag and drop to sandbox upload authority', () => {
  assert.match(composerFileDropSource, /composerFileDragActive/);
  assert.match(composerFileDropSource, /composerFileDropAction/);
  assert.match(composerFileDropSource, /dataTransfer\.types/);
  assert.match(composerFileDropSource, /dataTransfer\.files/);
  assert.match(composerFileDropSource, /ingestFilesWithDesktopBridge/);
  assert.doesNotMatch(composerFileDropSource, /onUploadFiles\(files\)/);
  assert.doesNotMatch(composerFileDropSource, /\.path\b|webkitGetAsEntry|text\/html|text\/uri-list/);
  assert.match(composerFileUploadSource, /uploadComposerFilesSequentially/);
  assert.match(composerFileUploadSource, /api\.uploadSandboxFile/);
  assert.match(chatPanelSource, /onDragEnter=\{handleFileDragEnter\}/);
  assert.match(chatPanelSource, /onDrop=\{handleFileDrop\}/);
  assert.match(chatPanelSource, /className="composer-file-drop-overlay"/);
  assert.match(chatPanelSource, /aria-busy=\{uploadingAttachments\}/);
  assert.match(chatPanelSource, /useComposerFileUpload/);
  assert.match(newThreadComposerSource, /useComposerFileUpload/);
  assert.match(newThreadComposerSource, /disabled=\{uploadingAttachments\}/);
  assert.match(composerPlusMenuSource, /onUploadFiles/);
  assert.match(composerPlusMenuSource, /openFilesWithDesktopDialog/);
  assert.doesNotMatch(composerPlusMenuSource, /type="file"|fileInputRef/);
  assert.doesNotMatch(composerPlusMenuSource, /MAX_ATTACHMENT_BYTES|api\.uploadSandboxFile/);
  assert.equal(i18nSource.split("'composer.dropFilesToUpload'").length - 1, 2);
  assert.equal(i18nSource.split("'composer.fileDropUnsupported'").length - 1, 2);
  assert.equal(i18nSource.split("'composer.filePickerFailed'").length - 1, 2);
  assert.match(i18nSource, /Files must be 16 MiB or smaller\./u);
  assert.match(i18nSource, /文件大小不能超过 16 MiB。/u);
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
  assert.match(composerCatalogSource, /listManagedSubAgents/);
  assert.match(composerPlusMenuSource, /execution_agent_id/);
  assert.match(composerPlusMenuSource, /execution_subagent_name/);
  assert.match(composerPlusMenuSource, /execution_skill_name/);
  assert.match(composerPlusMenuSource, /execution_slot: 'command'/);
  assert.match(agentConversationSource, /composerAgentExecutionContext\(content, contextItems\)/);
  assert.match(agentConversationSource, /agentId: execution\.agentId/);
  assert.match(agentConversationSource, /forcedSkillName: execution\.forcedSkillName/);
  assert.match(agentConversationSource, /appModelContext: execution\.appModelContext/);
  assert.match(
    agentConversationSource,
    /composerAgentExecutionContext\([\s\S]*?buildPlanningPrompt\(definition\)[\s\S]*?input\.contextItems/,
  );
  assert.match(composerFileUploadSource, /api\.uploadSandboxFile/);
  assert.match(composerFileUploadSource, /metadata\.sandbox_path/);
  assert.match(chatPanelSource, /uploadingFileCount/);
  assert.match(chatPanelSource, /composerHasSendableAttachment\(contextItems\)/);
  assert.match(chatPanelSource, /!uploadingAttachments/);
  assert.match(composerPlusMenuSource, /onUploadFiles/);
});

test('composer catalog reloads managed resources whenever the same-scope menu reopens', () => {
  const openMenu = composerPlusMenuSource.match(
    /function openMenu\(\) \{[\s\S]*?\n  \}/u,
  );
  assert.ok(openMenu, 'ComposerPlusMenu should own an explicit open boundary');
  assert.match(
    openMenu[0],
    /setCatalog\(null\);[\s\S]*setCatalogError\(null\);[\s\S]*setOpen\(true\);/u,
  );
  assert.doesNotMatch(openMenu[0], /window\.(?:addEventListener|dispatchEvent)/u);
  assert.match(
    composerPlusMenuSource,
    /onClick=\{\(\) => \(open \? close\(\) : openMenu\(\)\)\}/u,
  );
  assert.match(
    composerPlusMenuSource,
    /if \(!open \|\| catalog\) return;[\s\S]*loadComposerCatalog\(api, controller\.signal\)/u,
  );
});
