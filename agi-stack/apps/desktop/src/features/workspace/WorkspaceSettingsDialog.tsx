import { useEffect, useRef, useState } from 'react';
import {
  AlertDialog,
  Button,
  Dialog,
  Switch,
  TextArea,
  TextField,
} from '@radix-ui/themes';
import {
  ArchiveIcon,
  CodeIcon,
  MixerHorizontalIcon,
  ResetIcon,
} from '@radix-ui/react-icons';

import { DesktopApiError } from '../../api/client';
import type { WorkspaceUpdateInput } from '../../api/client';
import { useI18n } from '../../i18n';
import type { WorkspaceSummary } from '../../types';
import {
  WORKSPACE_COLLABORATION_MODES,
  WORKSPACE_USE_CASES,
} from './workspaceCreateModel';
import type {
  WorkspaceCollaborationMode,
  WorkspaceUseCase,
} from './workspaceCreateModel';
import {
  MAX_WORKSPACE_SETTINGS_DESCRIPTION_LENGTH,
  MAX_WORKSPACE_SETTINGS_NAME_LENGTH,
  WorkspaceSettingsScopeChangedError,
  buildWorkspaceUpdateInput,
  hydrateWorkspaceSettingsDraft,
  validateWorkspaceSettingsDraft,
  workspaceSettingsDraftIsDirty,
  workspaceSettingsProjectionSignature,
} from './workspaceSettingsModel';
import type {
  WorkspaceSettingsDraft,
  WorkspaceSettingsScope,
} from './workspaceSettingsModel';
import './WorkspaceSettingsDialog.css';

type WorkspaceSettingsDialogProps = {
  open: boolean;
  workspace: WorkspaceSummary | null;
  scope: WorkspaceSettingsScope;
  onOpenChange: (open: boolean) => void;
  onSave: (
    input: WorkspaceUpdateInput,
    scope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ) => Promise<WorkspaceSummary>;
};

type ConfirmationAction = 'close' | 'reset' | null;

export function WorkspaceSettingsDialog({
  open,
  workspace,
  scope,
  onOpenChange,
  onSave,
}: WorkspaceSettingsDialogProps) {
  const { t } = useI18n();
  const initialDraft = workspace
    ? hydrateWorkspaceSettingsDraft(workspace)
    : emptyWorkspaceSettingsDraft();
  const projectionSignature = workspace
    ? workspaceSettingsProjectionSignature(workspace)
    : '';
  const [draft, setDraft] = useState<WorkspaceSettingsDraft>(initialDraft);
  const [baseline, setBaseline] = useState<WorkspaceSettingsDraft>(initialDraft);
  const [busy, setBusy] = useState(false);
  const [confirmationAction, setConfirmationAction] =
    useState<ConfirmationAction>(null);
  const [feedback, setFeedback] = useState<{
    tone: 'error' | 'success';
    message: string;
  } | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const projectionSignatureRef = useRef(projectionSignature);
  const validation = validateWorkspaceSettingsDraft(draft);
  const dirty = workspaceSettingsDraftIsDirty(draft, baseline);

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    const next = workspace
      ? hydrateWorkspaceSettingsDraft(workspace)
      : emptyWorkspaceSettingsDraft();
    projectionSignatureRef.current = projectionSignature;
    setDraft(next);
    setBaseline(next);
    setBusy(false);
    setConfirmationAction(null);
    setFeedback(null);
  }, [
    open,
    scope.contextRevision,
    scope.epoch,
    scope.projectId,
    scope.tenantId,
    scope.workspaceId,
  ]);

  useEffect(() => {
    if (!open || busy || dirty || !workspace) return;
    if (projectionSignatureRef.current === projectionSignature) return;
    const next = hydrateWorkspaceSettingsDraft(workspace);
    projectionSignatureRef.current = projectionSignature;
    setDraft(next);
    setBaseline(next);
  }, [busy, dirty, open, projectionSignature, workspace]);

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [],
  );

  const updateDraft = <K extends keyof WorkspaceSettingsDraft>(
    key: K,
    value: WorkspaceSettingsDraft[K],
  ) => {
    setFeedback(null);
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const resetDraft = () => {
    if (!workspace) return;
    const next = hydrateWorkspaceSettingsDraft(workspace);
    projectionSignatureRef.current =
      workspaceSettingsProjectionSignature(workspace);
    setDraft(next);
    setBaseline(next);
    setFeedback(null);
    setConfirmationAction(null);
  };

  const requestReset = () => {
    if (busy || !dirty) return;
    setConfirmationAction('reset');
  };

  const requestClose = () => {
    if (busy) return;
    if (dirty) {
      setConfirmationAction('close');
      return;
    }
    onOpenChange(false);
  };

  const submit = async () => {
    if (!workspace || busy || requestRef.current || !dirty) return;
    const input = buildWorkspaceUpdateInput(workspace, draft);
    if (!input) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    setFeedback(null);
    try {
      const updated = await onSave(input, { ...scope }, controller.signal);
      if (controller.signal.aborted || requestRef.current !== controller) return;
      requestRef.current = null;
      const next = hydrateWorkspaceSettingsDraft(updated);
      projectionSignatureRef.current =
        workspaceSettingsProjectionSignature(updated);
      setDraft(next);
      setBaseline(next);
      setBusy(false);
      setFeedback({
        tone: 'success',
        message: t('workspaceSettings.success'),
      });
    } catch (error) {
      if (controller.signal.aborted || requestRef.current !== controller) return;
      requestRef.current = null;
      setBusy(false);
      setFeedback({
        tone: 'error',
        message:
          error instanceof WorkspaceSettingsScopeChangedError
            ? t('workspaceSettings.scopeChanged')
            : error instanceof DesktopApiError && error.status === 409
              ? t('workspaceSettings.duplicateError')
              : t('workspaceSettings.genericError'),
      });
    }
  };

  return (
    <>
      <Dialog.Root
        open={open}
        onOpenChange={(next) => (next ? onOpenChange(true) : requestClose())}
      >
        <Dialog.Content className="workspace-settings-dialog" maxWidth="760px">
          <Dialog.Title>{t('workspaceSettings.title')}</Dialog.Title>
          <Dialog.Description>
            {t('workspaceSettings.description', {
              workspace: workspace?.name ?? workspace?.title ?? scope.workspaceId,
            })}
          </Dialog.Description>
          <form
            className="workspace-settings-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <section>
              <header>
                <MixerHorizontalIcon aria-hidden="true" />
                <div>
                  <strong>{t('workspaceSettings.general')}</strong>
                  <small>{t('workspaceSettings.generalDetail')}</small>
                </div>
              </header>
              <div className="workspace-settings-field-grid">
                <label>
                  <span>{t('workspaceSettings.name')}</span>
                  <TextField.Root
                    autoFocus
                    value={draft.name}
                    maxLength={MAX_WORKSPACE_SETTINGS_NAME_LENGTH}
                    disabled={busy}
                    aria-label={t('workspaceSettings.name')}
                    aria-invalid={!validation.nameReady}
                    onChange={(event) =>
                      updateDraft('name', event.currentTarget.value)
                    }
                  />
                </label>
                <label className="workspace-settings-archive">
                  <span>
                    <ArchiveIcon aria-hidden="true" />
                    <span>
                      <strong>{t('workspaceSettings.archive')}</strong>
                      <small>
                        {draft.isArchived
                          ? t('workspaceSettings.archived')
                          : t('workspaceSettings.active')}
                      </small>
                    </span>
                  </span>
                  <Switch
                    checked={draft.isArchived}
                    disabled={busy}
                    aria-label={t('workspaceSettings.archive')}
                    onCheckedChange={(checked) =>
                      updateDraft('isArchived', checked)
                    }
                  />
                </label>
              </div>
              <label>
                <span className="workspace-settings-field-heading">
                  <span>{t('workspaceSettings.objective')}</span>
                  <small>
                    {draft.description.length}/
                    {MAX_WORKSPACE_SETTINGS_DESCRIPTION_LENGTH}
                  </small>
                </span>
                <TextArea
                  value={draft.description}
                  maxLength={MAX_WORKSPACE_SETTINGS_DESCRIPTION_LENGTH}
                  rows={4}
                  resize="vertical"
                  disabled={busy}
                  aria-label={t('workspaceSettings.objective')}
                  onChange={(event) =>
                    updateDraft('description', event.currentTarget.value)
                  }
                />
              </label>
            </section>

            <section>
              <header>
                <MixerHorizontalIcon aria-hidden="true" />
                <div>
                  <strong>{t('workspaceSettings.operatingModel')}</strong>
                  <small>{t('workspaceSettings.operatingModelDetail')}</small>
                </div>
              </header>
              <div className="workspace-settings-field-grid">
                <WorkspaceSettingsSelect
                  label={t('workspaceSettings.useCase')}
                  value={draft.useCase}
                  disabled={busy}
                  options={WORKSPACE_USE_CASES}
                  optionLabel={(value) => t(`workspaceCreate.useCase.${value}`)}
                  onChange={(value) => updateDraft('useCase', value)}
                />
                <WorkspaceSettingsSelect
                  label={t('workspaceSettings.collaboration')}
                  value={draft.collaborationMode}
                  disabled={busy}
                  options={WORKSPACE_COLLABORATION_MODES}
                  optionLabel={(value) =>
                    collaborationModeLabel(value, t)
                  }
                  onChange={(value) =>
                    updateDraft('collaborationMode', value)
                  }
                />
              </div>
            </section>

            <section>
              <header>
                <CodeIcon aria-hidden="true" />
                <div>
                  <strong>{t('workspaceSettings.codeContext')}</strong>
                  <small>{t('workspaceSettings.codeContextDetail')}</small>
                </div>
              </header>
              <label>
                <span>{t('workspaceSettings.codeRoot')}</span>
                <TextField.Root
                  value={draft.sandboxCodeRoot}
                  disabled={busy}
                  spellCheck={false}
                  placeholder="/workspace/repository"
                  aria-label={t('workspaceSettings.codeRoot')}
                  aria-invalid={!validation.codeRootReady}
                  aria-describedby="workspace-settings-code-root-hint"
                  onChange={(event) =>
                    updateDraft('sandboxCodeRoot', event.currentTarget.value)
                  }
                />
                <small
                  id="workspace-settings-code-root-hint"
                  className={validation.codeRootReady ? '' : 'error'}
                >
                  {validation.codeRootReady
                    ? t('workspaceSettings.codeRootHint')
                    : t('workspaceSettings.codeRootInvalid')}
                </small>
              </label>
            </section>

            <div
              className={`workspace-settings-feedback ${feedback?.tone ?? ''}`}
              role={feedback?.tone === 'error' ? 'alert' : 'status'}
              aria-live={feedback?.tone === 'error' ? 'assertive' : 'polite'}
              aria-atomic="true"
            >
              {feedback?.message ?? ''}
            </div>

            <div className="workspace-settings-actions">
              <Button
                type="button"
                variant="soft"
                color="gray"
                disabled={busy || !dirty}
                onClick={requestReset}
              >
                <ResetIcon aria-hidden="true" />
                {t('workspaceSettings.reset')}
              </Button>
              <span />
              <Button
                type="button"
                variant="soft"
                color="gray"
                disabled={busy}
                onClick={requestClose}
              >
                {t('common.cancel')}
              </Button>
              <Button
                type="submit"
                disabled={busy || !validation.canSubmit || !dirty}
              >
                {busy
                  ? t('workspaceSettings.saving')
                  : t('common.save')}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root
        open={confirmationAction !== null}
        onOpenChange={(next) => {
          if (!next) setConfirmationAction(null);
        }}
      >
        <AlertDialog.Content maxWidth="420px">
          <AlertDialog.Title>
            {confirmationAction === 'reset'
              ? t('workspaceSettings.resetTitle')
              : t('workspaceSettings.discardTitle')}
          </AlertDialog.Title>
          <AlertDialog.Description>
            {confirmationAction === 'reset'
              ? t('workspaceSettings.resetDescription')
              : t('workspaceSettings.discardDescription')}
          </AlertDialog.Description>
          <div className="workspace-settings-confirm-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                {t('workspaceSettings.keepEditing')}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                color={confirmationAction === 'reset' ? 'orange' : 'red'}
                onClick={() => {
                  if (confirmationAction === 'reset') {
                    resetDraft();
                    return;
                  }
                  setConfirmationAction(null);
                  setFeedback(null);
                  onOpenChange(false);
                }}
              >
                {confirmationAction === 'reset'
                  ? t('workspaceSettings.reset')
                  : t('workspaceSettings.discard')}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </>
  );
}

function WorkspaceSettingsSelect<T extends string>({
  label,
  value,
  disabled,
  options,
  optionLabel,
  onChange,
}: {
  label: string;
  value: T;
  disabled: boolean;
  options: readonly T[];
  optionLabel: (value: T) => string;
  onChange: (value: T) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <select
        value={value}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => onChange(event.currentTarget.value as T)}
      >
        {options.map((option) => (
          <option value={option} key={option}>
            {optionLabel(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function collaborationModeLabel(
  value: WorkspaceCollaborationMode,
  t: (key: string) => string,
): string {
  const key = {
    single_agent: 'single',
    multi_agent_shared: 'shared',
    multi_agent_isolated: 'isolated',
    autonomous: 'autonomous',
  }[value];
  return t(`workspaceCreate.collaboration.${key}`);
}

function emptyWorkspaceSettingsDraft(): WorkspaceSettingsDraft {
  return {
    name: '',
    description: '',
    isArchived: false,
    useCase: 'general',
    collaborationMode: 'multi_agent_shared',
    sandboxCodeRoot: '',
  };
}
