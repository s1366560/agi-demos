import { useEffect, useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CodeIcon,
  CubeIcon,
  FileTextIcon,
  LockClosedIcon,
  MixerHorizontalIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentCapabilityMode,
  AgentConversation,
  WorkspaceAgentPolicy,
  WorkspacePermissionMode,
  WorkspaceReasoningEffort,
  WorkspaceSummary,
} from '../../types';
import type { WorkspaceRuntimeModelOption } from '../settings/workspaceRuntimeProviderModel';
import './NewThreadComposer.css';

export type NewThreadComposerInput = {
  prompt: string;
  mode: AgentCapabilityMode;
  model: WorkspaceRuntimeModelOption;
  reasoningEffort: WorkspaceReasoningEffort;
  permissionMode: WorkspacePermissionMode;
};

type NewThreadComposerProps = {
  workspace: WorkspaceSummary | null;
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
  onCreate: (input: NewThreadComposerInput) => void;
  onOpenThread: (conversation: AgentConversation) => void;
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
  workspace,
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
  onCreate,
  onOpenThread,
}: NewThreadComposerProps) {
  const { t } = useI18n();
  const [prompt, setPrompt] = useState('');
  const [modelValue, setModelValue] = useState('');
  const [reasoningEffort, setReasoningEffort] = useState<WorkspaceReasoningEffort>('medium');
  const [permissionMode, setPermissionMode] = useState<WorkspacePermissionMode>('ask');

  useEffect(() => {
    setModelValue(modelOptions.find((option) => option.selected)?.value ?? modelOptions[0]?.value ?? '');
  }, [modelOptions]);
  useEffect(() => {
    setReasoningEffort(policy?.reasoning_effort ?? 'medium');
    setPermissionMode(policy?.permission_mode ?? 'ask');
  }, [policy]);

  const selectedModel = useMemo(
    () => modelOptions.find((option) => option.value === modelValue) ?? null,
    [modelOptions, modelValue],
  );
  const recentThreads = conversations.slice(0, 5);
  const canSend = Boolean(prompt.trim() && selectedModel && !disabledReason && !creating);
  const send = () => {
    if (!canSend || !selectedModel) return;
    onCreate({
      prompt: prompt.trim(),
      mode,
      model: selectedModel,
      reasoningEffort,
      permissionMode,
    });
  };

  return (
    <main className="new-thread-view" aria-busy={creating || loadingPolicy}>
      <div className="new-thread-content">
        <header className="new-thread-heading">
          <span className="eyebrow">{t('task.newThreadEyebrow')}</span>
          <h1>{t('task.newThreadTitle')}</h1>
          <p>{t('task.newThreadDescription')}</p>
          <span className="new-thread-workspace">
            <CubeIcon /> {workspace?.name ?? workspace?.title ?? t('overview.none')}
          </span>
        </header>

        <section className="new-thread-composer">
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
              <label className="picker-chip">
                <span>{t('task.model')}</span>
                <select
                  value={modelValue}
                  onChange={(event) => setModelValue(event.target.value)}
                  disabled={!canManagePolicy || modelOptions.length === 0}
                  aria-label={t('task.model')}
                >
                  {modelOptions.map((option) => (
                    <option value={option.value} key={option.value}>
                      {option.providerLabel} · {option.modelId}
                    </option>
                  ))}
                </select>
              </label>
              <label className="picker-chip">
                <span>{t('task.effort')}</span>
                <select
                  value={reasoningEffort}
                  onChange={(event) => setReasoningEffort(event.target.value as WorkspaceReasoningEffort)}
                  disabled={!canManagePolicy}
                  aria-label={t('task.effort')}
                >
                  <option value="low">{t('task.effortLow')}</option>
                  <option value="medium">{t('task.effortMedium')}</option>
                  <option value="high">{t('task.effortHigh')}</option>
                </select>
              </label>
              <label className="picker-chip">
                <LockClosedIcon />
                <select
                  value={permissionMode}
                  onChange={(event) => setPermissionMode(event.target.value as WorkspacePermissionMode)}
                  disabled={!canManagePolicy}
                  aria-label={t('task.permissionMode')}
                >
                  <option value="ask">{t('task.permissionAsk')}</option>
                  <option value="automatic">{t('task.permissionAutomatic')}</option>
                  <option value="full_access">{t('task.permissionModeFullAccess')}</option>
                </select>
              </label>
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
