import { useCallback, useMemo, useState } from 'react';
import { ArrowRightIcon, CubeIcon } from '@radix-ui/react-icons';

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
import { ComposerOptionsMenu } from '../chat/ComposerOptionsMenu';
import { PickerMenu } from '../chat/PickerMenu';
import { useComposerFileUpload } from '../chat/useComposerFileUpload';
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
  const addContextItem = useCallback((item: ComposerContextItem) => {
    setContextItems((current) => appendComposerContextItem(current, item));
  }, []);
  const { uploadingFileCount, uploadingAttachments, fileUploadErrors, uploadFiles } =
    useComposerFileUpload({
      api,
      onAdd: addContextItem,
      contextKey: JSON.stringify([
        workspace?.tenant_id ?? '',
        workspace?.project_id ?? '',
        workspaceId,
      ]),
    });

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
    <main className="new-thread-view" aria-busy={creating || loadingPolicy || uploadingAttachments}>
      <div className="new-thread-content">
        <header className="new-thread-heading">
          <h1>{t('task.newThreadTitle')}</h1>
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
            placeholder={t(
              mode === 'work' ? 'task.workPromptPlaceholder' : 'task.codePromptPlaceholder',
            )}
            aria-label={t('task.newThreadPrompt')}
            disabled={creating}
          />
          <div className="new-thread-composer-toolbar">
            <ComposerPlusMenu
              key={workspaceId || 'unbound'}
              api={api}
              conversations={conversations}
              onAdd={addContextItem}
              onUploadFiles={uploadFiles}
              uploadingFileCount={uploadingFileCount}
            />
            <div className="composer-pickers">
              <PickerMenu
                label={t('task.mode')}
                value={mode}
                options={[
                  { value: 'work', label: t('sidebar.workMode') },
                  { value: 'code', label: t('sidebar.codeMode') },
                ]}
                hideLabel
                onChange={(value) => onModeChange(value as AgentCapabilityMode)}
              />
              <PickerMenu
                label={t('task.workspace')}
                value={workspaceId}
                options={workspacePickerOptions}
                disabled={uploadingAttachments}
                hideLabel
                onChange={(value) => {
                  setContextItems([]);
                  onWorkspaceChange(value);
                }}
              />
              <PickerMenu
                label={t('task.model')}
                hideLabel
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
                  <ComposerOptionsMenu
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
              title={t('task.startThread')}
            >
              <ArrowRightIcon />
            </button>
          </div>
        </section>

        {compatibilityMode ? (
          <p className="new-thread-notice">{t('task.policyUpgradeRequired')}</p>
        ) : null}
        {disabledReason || error ? (
          <p className="new-thread-error" role="alert">
            {error ?? disabledReason}
          </p>
        ) : null}
        {fileUploadErrors.length ? (
          <div className="new-thread-error" role="alert">
            {fileUploadErrors.map((uploadError, index) => (
              <span key={`${index}:${uploadError}`}>{uploadError}</span>
            ))}
          </div>
        ) : null}
      </div>
    </main>
  );
}
