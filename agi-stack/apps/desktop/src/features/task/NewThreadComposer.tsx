import { useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CodeIcon,
  CubeIcon,
  FileTextIcon,
  MixerHorizontalIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentCapabilityMode,
  AgentConversation,
  ComposerContextItem,
  WorkspaceAgentPolicy,
  WorkspacePermissionMode,
  WorkspaceReasoningEffort,
  WorkspaceSummary,
} from '../../types';
import type { WorkspaceRuntimeModelOption } from '../settings/workspaceRuntimeProviderModel';
import { ComposerPlusMenu } from '../chat/ComposerPlusMenu';
import { appendComposerContextItem } from '../chat/chatComposerModel';
import type { ComposerCatalogClient } from '../chat/composerCatalogModel';
import { PickerMenu } from '../chat/PickerMenu';
import '../chat/ComposerMenus.css';
import './NewThreadComposer.css';

export type NewThreadComposerInput = {
  prompt: string;
  mode: AgentCapabilityMode;
  workspaceId: string;
  model: WorkspaceRuntimeModelOption | null;
  reasoningEffort: WorkspaceReasoningEffort;
  permissionMode: WorkspacePermissionMode;
  contextItems: ComposerContextItem[];
};

type NewThreadComposerProps = {
  workspaceId: string;
  workspace: WorkspaceSummary | null;
  workspaces: WorkspaceSummary[];
  api: ComposerCatalogClient;
  conversations: AgentConversation[];
  mode: AgentCapabilityMode;
  policy: WorkspaceAgentPolicy | null;
  modelOptions: WorkspaceRuntimeModelOption[];
  canManagePolicy: boolean;
  loadingPolicy: boolean;
  compatibilityMode: boolean;
  disabledReason: string | null;
  creating: boolean;
  error: string | null;
  onModeChange: (mode: AgentCapabilityMode) => void;
  onWorkspaceChange: (workspaceId: string) => void;
  onCreate: (input: NewThreadComposerInput) => void;
  onOpenThread: (conversation: AgentConversation) => void;
  onManageModels: () => void;
};

const SUGGESTIONS: Record<AgentCapabilityMode, Array<{ title: string; prompt: string }>> = {
  work: [
    { title: 'task.suggestionBriefTitle', prompt: 'task.suggestionBriefPrompt' },
    { title: 'task.suggestionResearchTitle', prompt: 'task.suggestionResearchPrompt' },
    { title: 'task.suggestionDigestTitle', prompt: 'task.suggestionDigestPrompt' },
  ],
  code: [
    { title: 'task.suggestionFixTitle', prompt: 'task.suggestionFixPrompt' },
    { title: 'task.suggestionBuildTitle', prompt: 'task.suggestionBuildPrompt' },
    { title: 'task.suggestionUpgradeTitle', prompt: 'task.suggestionUpgradePrompt' },
  ],
};

export function NewThreadComposer({
  workspaceId,
  workspace,
  workspaces,
  api,
  conversations,
  mode,
  policy,
  modelOptions,
  canManagePolicy,
  loadingPolicy,
  compatibilityMode,
  disabledReason,
  creating,
  error,
  onModeChange,
  onWorkspaceChange,
  onCreate,
  onOpenThread,
  onManageModels,
}: NewThreadComposerProps) {
  const { t } = useI18n();
  const [prompt, setPrompt] = useState('');
  const [modelSelection, setModelSelection] = useState({ workspaceId: '', value: '' });
  const [reasoningSelection, setReasoningSelection] = useState<{
    workspaceId: string;
    value: WorkspaceReasoningEffort;
  }>({ workspaceId: '', value: 'medium' });
  const [permissionSelection, setPermissionSelection] = useState<{
    workspaceId: string;
    value: WorkspacePermissionMode;
  }>({ workspaceId: '', value: 'ask' });
  const [contextItems, setContextItems] = useState<ComposerContextItem[]>([]);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);

  const defaultModelValue = workspaceId
    ? (modelOptions.find((option) => option.selected)?.value ?? modelOptions[0]?.value ?? '')
    : '';
  const modelValue =
    modelSelection.workspaceId === workspaceId &&
    (modelSelection.value === '' ||
      modelOptions.some((option) => option.value === modelSelection.value))
      ? modelSelection.value
      : defaultModelValue;
  const reasoningEffort =
    reasoningSelection.workspaceId === workspaceId
      ? reasoningSelection.value
      : (policy?.reasoning_effort ?? 'medium');
  const permissionMode =
    permissionSelection.workspaceId === workspaceId
      ? permissionSelection.value
      : (policy?.permission_mode ?? 'ask');
  const selectedModel = useMemo(
    () => modelOptions.find((option) => option.value === modelValue) ?? null,
    [modelOptions, modelValue],
  );
  const recentThreads = conversations.slice(0, 5);
  const canSend = Boolean(
    prompt.trim() &&
      (!workspaceId || selectedModel) &&
      !disabledReason &&
      !creating &&
      !loadingPolicy &&
      !uploadingAttachments,
  );
  const send = () => {
    if (!canSend) return;
    onCreate({
      prompt: prompt.trim(),
      mode,
      workspaceId,
      model: selectedModel,
      reasoningEffort,
      permissionMode,
      contextItems,
    });
  };

  const addContextItem = (item: ComposerContextItem) => {
    setContextItems((current) => appendComposerContextItem(current, item));
  };
  const workspacePickerOptions = [
    {
      value: '',
      label: t('task.noWorkspace'),
      description: t('task.noWorkspaceDescription'),
    },
    ...workspaces.map((option) => ({
      value: option.id,
      label: option.name || option.title || option.id,
      description: option.description ?? undefined,
    })),
  ];
  const modelPickerOptions = [
    ...(workspaceId
      ? []
      : [
          {
            value: '',
            label: t('task.projectDefaultModel'),
            description: t('task.projectDefaultModelDescription'),
            meta: null,
            badges: [],
          },
        ]),
    ...modelOptions.map((option) => ({
      value: option.value,
      label: option.modelId,
      description: option.description,
      meta: option.contextWindow ?? t('task.contextWindowUnavailable'),
      badges: option.roles.map((role) => t(`task.modelRole.${role}`)),
    })),
  ];
  const effortOptions = [
    {
      value: 'low',
      label: t('task.effortLow'),
      description: t('task.effortLowDescription'),
    },
    {
      value: 'medium',
      label: t('task.effortMedium'),
      description: t('task.effortMediumDescription'),
    },
    {
      value: 'high',
      label: t('task.effortHigh'),
      description: t('task.effortHighDescription'),
    },
  ];
  const permissionOptions = [
    {
      value: 'ask',
      label: t('task.permissionAsk'),
      description: t('task.permissionAskDescription'),
    },
    {
      value: 'automatic',
      label: t('task.permissionAutomatic'),
      description: t('task.permissionAutomaticDescription'),
    },
    {
      value: 'full_access',
      label: t('task.permissionModeFullAccess'),
      description: t('task.permissionModeFullAccessDescription'),
    },
  ];

  return (
    <main className="new-thread-view" aria-busy={creating || loadingPolicy}>
      <div className="new-thread-content">
        <header className="new-thread-heading">
          <span className="eyebrow">{t('task.newThreadEyebrow')}</span>
          <h1>{t('task.newThreadTitle')}</h1>
          <p>{t('task.newThreadDescription')}</p>
          <span className="new-thread-workspace">
            <CubeIcon />{' '}
            {workspace?.name ?? workspace?.title ?? t('task.noWorkspace')}
          </span>
        </header>

        <section className="new-thread-composer">
          {contextItems.length ? (
            <div className="composer-context-chips" aria-label={t('composer.addedContext')}>
              {contextItems.map((item) => (
                <button
                  type="button"
                  key={`${item.kind}:${item.resource_id}`}
                  aria-label={t('composer.removeContext', { context: item.label })}
                  onClick={() =>
                    setContextItems((current) => current.filter((candidate) => candidate !== item))
                  }
                >
                  {item.label}
                  <span aria-hidden="true">×</span>
                </button>
              ))}
            </div>
          ) : null}
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') send();
            }}
            placeholder={t(mode === 'work' ? 'task.workPromptPlaceholder' : 'task.codePromptPlaceholder')}
            aria-label={t('task.newThreadPrompt')}
            disabled={creating}
          />
          <div className="new-thread-composer-toolbar">
            <ComposerPlusMenu
              key={workspaceId || 'unbound'}
              api={api}
              conversations={conversations}
              onAdd={addContextItem}
              onUploadingChange={setUploadingAttachments}
            />
            <div className="composer-pickers">
              <div className="mode-picker" role="group" aria-label={t('task.mode')}>
                <button
                  className={mode === 'work' ? 'active' : ''}
                  type="button"
                  onClick={() => onModeChange('work')}
                >
                  <MixerHorizontalIcon /> {t('sidebar.workMode')}
                </button>
                <button
                  className={mode === 'code' ? 'active' : ''}
                  type="button"
                  onClick={() => onModeChange('code')}
                >
                  <CodeIcon /> {t('sidebar.codeMode')}
                </button>
              </div>
              <PickerMenu
                label={t('task.workspace')}
                value={workspaceId}
                options={workspacePickerOptions}
                onChange={(value) => {
                  setContextItems([]);
                  onWorkspaceChange(value);
                }}
              />
              <PickerMenu
                label={t('task.model')}
                value={modelValue}
                options={modelPickerOptions}
                readOnly={Boolean(workspaceId) && !canManagePolicy}
                onChange={(value) => setModelSelection({ workspaceId, value })}
                footer={{
                  label: t('task.manageModels'),
                  icon: <CubeIcon />,
                  onClick: onManageModels,
                }}
              />
              {workspaceId ? (
                <>
                  <PickerMenu
                    label={t('task.effort')}
                    value={reasoningEffort}
                    options={effortOptions}
                    readOnly={!canManagePolicy}
                    onChange={(value) =>
                      setReasoningSelection({
                        workspaceId,
                        value: value as WorkspaceReasoningEffort,
                      })
                    }
                  />
                  <PickerMenu
                    label={t('task.permissionMode')}
                    value={permissionMode}
                    options={permissionOptions}
                    readOnly={!canManagePolicy}
                    hideLabel
                    onChange={(value) =>
                      setPermissionSelection({
                        workspaceId,
                        value: value as WorkspacePermissionMode,
                      })
                    }
                  />
                </>
              ) : null}
            </div>
            <button
              className="send-button"
              type="button"
              disabled={!canSend}
              onClick={send}
              aria-label={t('task.startThread')}
            >
              <ArrowRightIcon />
            </button>
          </div>
        </section>

        {compatibilityMode ? <p className="new-thread-notice">{t('task.policyUpgradeRequired')}</p> : null}
        {disabledReason || error ? (
          <p className="new-thread-error" role="alert">{error ?? disabledReason}</p>
        ) : null}

        <section className="new-thread-suggestions" aria-label={t('task.suggestions')}>
          {SUGGESTIONS[mode].map((suggestion) => (
            <button type="button" key={suggestion.title} onClick={() => setPrompt(t(suggestion.prompt))}>
              <FileTextIcon />
              <span>
                <b>{t(suggestion.title)}</b>
                <small>{t(suggestion.prompt)}</small>
              </span>
            </button>
          ))}
        </section>

        <section className="new-thread-recent" aria-label={t('task.recentThreads')}>
          <header>
            <span>{t('task.recentThreads')}</span>
            <em>{workspace?.name ?? workspace?.title ?? ''}</em>
          </header>
          <div>
            {recentThreads.map((conversation) => {
              const isCode = conversation.agent_config?.capability_mode === 'code';
              const ModeIcon = isCode ? CodeIcon : ActivityLogIcon;
              return (
                <button type="button" key={conversation.id} onClick={() => onOpenThread(conversation)}>
                  <i className={`thread-status ${conversation.status}`} aria-hidden="true" />
                  <ModeIcon />
                  <span>
                    <b>{conversation.title}</b>
                    <small>{conversation.summary || t('task.planFirstStatus')}</small>
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </main>
  );
}
