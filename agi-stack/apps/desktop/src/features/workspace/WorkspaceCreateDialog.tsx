import {
  type ComponentType,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { AlertDialog, Button, Dialog, TextArea, TextField } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ChatBubbleIcon,
  CodeIcon,
  CubeIcon,
  MagnifyingGlassIcon,
  PersonIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { DesktopApiError } from '../../api/client';
import type { WorkspaceCreateInput } from '../../api/client';
import { useI18n } from '../../i18n';
import {
  MAX_WORKSPACE_DESCRIPTION_LENGTH,
  MAX_WORKSPACE_NAME_LENGTH,
  MIN_WORKSPACE_DESCRIPTION_LENGTH,
  WORKSPACE_COLLABORATION_MODES,
  WORKSPACE_USE_CASES,
  WorkspaceCreateScopeChangedError,
  buildWorkspaceCreateInput,
  emptyWorkspaceCreateDraft,
  validateWorkspaceCreateDraft,
  workspaceCreateDraftIsDirty,
  workspaceCreateRadioNextValue,
} from './workspaceCreateModel';
import type {
  WorkspaceCollaborationMode,
  WorkspaceCreateDraft,
  WorkspaceCreateScope,
  WorkspaceUseCase,
} from './workspaceCreateModel';
import './WorkspaceCreateDialog.css';

type WorkspaceCreateDialogProps = {
  open: boolean;
  projectName: string;
  scope: WorkspaceCreateScope;
  onOpenChange: (open: boolean) => void;
  onCreate: (
    input: WorkspaceCreateInput,
    scope: WorkspaceCreateScope,
    signal: AbortSignal,
  ) => Promise<void>;
};

type WorkspaceCreateOption<T extends string> = {
  value: T;
  label: string;
  description: string;
  icon: ReactNode;
};

type WorkspaceCreateOptionGroupProps<T extends string> = {
  label: string;
  options: readonly WorkspaceCreateOption<T>[];
  value: T | null;
  disabled: boolean;
  onChange: (value: T) => void;
};

export function WorkspaceCreateDialog({
  open,
  projectName,
  scope,
  onOpenChange,
  onCreate,
}: WorkspaceCreateDialogProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<WorkspaceCreateDraft>(emptyWorkspaceCreateDraft);
  const [busy, setBusy] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [feedback, setFeedback] = useState<{
    tone: 'error' | 'success';
    message: string;
  } | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const validation = validateWorkspaceCreateDraft(draft);
  const useCaseOptions = useMemo(
    (): readonly WorkspaceCreateOption<WorkspaceUseCase>[] => [
      option(
        'general',
        t('workspaceCreate.useCase.general'),
        t('workspaceCreate.useCase.generalDetail'),
        CubeIcon,
      ),
      option(
        'programming',
        t('workspaceCreate.useCase.programming'),
        t('workspaceCreate.useCase.programmingDetail'),
        CodeIcon,
      ),
      option(
        'conversation',
        t('workspaceCreate.useCase.conversation'),
        t('workspaceCreate.useCase.conversationDetail'),
        ChatBubbleIcon,
      ),
      option(
        'research',
        t('workspaceCreate.useCase.research'),
        t('workspaceCreate.useCase.researchDetail'),
        MagnifyingGlassIcon,
      ),
      option(
        'operations',
        t('workspaceCreate.useCase.operations'),
        t('workspaceCreate.useCase.operationsDetail'),
        ActivityLogIcon,
      ),
    ],
    [t],
  );
  const collaborationOptions = useMemo(
    (): readonly WorkspaceCreateOption<WorkspaceCollaborationMode>[] => [
      option(
        'single_agent',
        t('workspaceCreate.collaboration.single'),
        t('workspaceCreate.collaboration.singleDetail'),
        PersonIcon,
      ),
      option(
        'multi_agent_shared',
        t('workspaceCreate.collaboration.shared'),
        t('workspaceCreate.collaboration.sharedDetail'),
        ChatBubbleIcon,
      ),
      option(
        'multi_agent_isolated',
        t('workspaceCreate.collaboration.isolated'),
        t('workspaceCreate.collaboration.isolatedDetail'),
        CubeIcon,
      ),
      option(
        'autonomous',
        t('workspaceCreate.collaboration.autonomous'),
        t('workspaceCreate.collaboration.autonomousDetail'),
        ActivityLogIcon,
      ),
    ],
    [t],
  );

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = null;
    setDraft(emptyWorkspaceCreateDraft());
    setBusy(false);
    setDiscardOpen(false);
    setFeedback(null);
  }, [open, scope.projectId, scope.tenantId]);

  useEffect(
    () => () => {
      requestRef.current?.abort();
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    },
    [],
  );

  const updateDraft = <K extends keyof WorkspaceCreateDraft>(
    key: K,
    value: WorkspaceCreateDraft[K],
  ) => {
    setFeedback(null);
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const requestClose = () => {
    if (busy) return;
    if (workspaceCreateDraftIsDirty(draft)) {
      setDiscardOpen(true);
      return;
    }
    onOpenChange(false);
  };

  const submit = async () => {
    if (busy || requestRef.current) return;
    const input = buildWorkspaceCreateInput(draft);
    if (!input) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    setFeedback(null);
    try {
      await onCreate(input, { ...scope }, controller.signal);
      if (controller.signal.aborted || requestRef.current !== controller) return;
      requestRef.current = null;
      setBusy(false);
      setFeedback({ tone: 'success', message: t('workspaceCreate.success') });
      closeTimerRef.current = window.setTimeout(() => {
        closeTimerRef.current = null;
        setDraft(emptyWorkspaceCreateDraft());
        setFeedback(null);
        onOpenChange(false);
      }, 450);
    } catch (error) {
      if (controller.signal.aborted || requestRef.current !== controller) return;
      requestRef.current = null;
      setBusy(false);
      setFeedback({
        tone: 'error',
        message:
          error instanceof WorkspaceCreateScopeChangedError
            ? t('workspaceCreate.scopeChanged')
            : error instanceof DesktopApiError && error.status === 409
              ? t('workspaceCreate.duplicateError')
              : t('workspaceCreate.genericError'),
      });
    }
  };

  return (
    <>
      <Dialog.Root
        open={open}
        onOpenChange={(next) => (next ? onOpenChange(true) : requestClose())}
      >
        <Dialog.Content className="workspace-create-dialog" maxWidth="780px">
          <Dialog.Title>{t('workspaceCreate.title')}</Dialog.Title>
          <Dialog.Description>
            {t('workspaceCreate.description', { project: projectName })}
          </Dialog.Description>
          <form
            className="workspace-create-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <div className="workspace-create-fields">
              <label>
                <span>{t('workspaceCreate.name')}</span>
                <TextField.Root
                  autoFocus
                  value={draft.name}
                  maxLength={MAX_WORKSPACE_NAME_LENGTH}
                  disabled={busy}
                  placeholder={t('workspaceCreate.namePlaceholder')}
                  aria-label={t('workspaceCreate.name')}
                  onChange={(event) => updateDraft('name', event.currentTarget.value)}
                />
              </label>
              <label>
                <span className="workspace-create-field-heading">
                  <span>{t('workspaceCreate.objective')}</span>
                  <small
                    className={validation.descriptionReady ? 'ready' : ''}
                    aria-label={t('workspaceCreate.objectiveProgress', {
                      count: draft.description.trim().length,
                      minimum: MIN_WORKSPACE_DESCRIPTION_LENGTH,
                    })}
                  >
                    {draft.description.trim().length}/{MIN_WORKSPACE_DESCRIPTION_LENGTH}
                  </small>
                </span>
                <TextArea
                  value={draft.description}
                  maxLength={MAX_WORKSPACE_DESCRIPTION_LENGTH}
                  rows={4}
                  resize="vertical"
                  disabled={busy}
                  placeholder={t('workspaceCreate.objectivePlaceholder')}
                  aria-label={t('workspaceCreate.objective')}
                  onChange={(event) => updateDraft('description', event.currentTarget.value)}
                />
              </label>
            </div>

            <WorkspaceCreateOptionGroup
              label={t('workspaceCreate.useCase')}
              options={useCaseOptions}
              value={draft.useCase}
              disabled={busy}
              onChange={(value) => updateDraft('useCase', value)}
            />

            {draft.useCase === 'programming' ? (
              <label className="workspace-create-code-root">
                <span>{t('workspaceCreate.codeRoot')}</span>
                <TextField.Root
                  value={draft.sandboxCodeRoot}
                  disabled={busy}
                  spellCheck={false}
                  placeholder={t('workspaceCreate.codeRootPlaceholder')}
                  aria-label={t('workspaceCreate.codeRoot')}
                  aria-invalid={draft.sandboxCodeRoot.length > 0 && !validation.codeRootReady}
                  aria-describedby="workspace-create-code-root-hint"
                  onChange={(event) => updateDraft('sandboxCodeRoot', event.currentTarget.value)}
                />
                <small
                  id="workspace-create-code-root-hint"
                  className={validation.codeRootReady ? '' : 'error'}
                >
                  {t('workspaceCreate.codeRootHint')}
                </small>
              </label>
            ) : null}

            <WorkspaceCreateOptionGroup
              label={t('workspaceCreate.collaboration')}
              options={collaborationOptions}
              value={draft.collaborationMode}
              disabled={busy}
              onChange={(value) => updateDraft('collaborationMode', value)}
            />

            <div
              className={`workspace-create-feedback ${feedback?.tone ?? ''}`}
              role={feedback?.tone === 'error' ? 'alert' : 'status'}
              aria-live={feedback?.tone === 'error' ? 'assertive' : 'polite'}
              aria-atomic="true"
            >
              {feedback?.message ?? ''}
            </div>

            <div className="workspace-create-actions">
              <Button
                type="button"
                variant="soft"
                color="gray"
                disabled={busy}
                onClick={requestClose}
              >
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={busy || !validation.canSubmit}>
                <PlusIcon aria-hidden="true" />
                {busy ? t('workspaceCreate.creating') : t('workspaceCreate.create')}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root open={discardOpen} onOpenChange={setDiscardOpen}>
        <AlertDialog.Content maxWidth="420px">
          <AlertDialog.Title>{t('workspaceCreate.discardTitle')}</AlertDialog.Title>
          <AlertDialog.Description>
            {t('workspaceCreate.discardDescription')}
          </AlertDialog.Description>
          <div className="workspace-create-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                {t('workspaceCreate.keepEditing')}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                color="red"
                onClick={() => {
                  setDiscardOpen(false);
                  setDraft(emptyWorkspaceCreateDraft());
                  setFeedback(null);
                  onOpenChange(false);
                }}
              >
                {t('workspaceCreate.discard')}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </>
  );
}

function WorkspaceCreateOptionGroup<T extends string>({
  label,
  options,
  value,
  disabled,
  onChange,
}: WorkspaceCreateOptionGroupProps<T>) {
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const values = useMemo(() => options.map((candidate) => candidate.value), [options]);
  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const next = workspaceCreateRadioNextValue(values, value, event.key);
    if (next === null) return;
    event.preventDefault();
    onChange(next);
    buttonRefs.current[values.indexOf(next)]?.focus();
  };
  return (
    <fieldset className="workspace-create-option-fieldset">
      <legend>{label}</legend>
      <div
        className="workspace-create-option-grid"
        role="radiogroup"
        aria-label={label}
        onKeyDown={handleKeyDown}
      >
        {options.map((candidate, index) => (
          <button
            type="button"
            role="radio"
            aria-checked={value === candidate.value}
            tabIndex={value === candidate.value || (value === null && index === 0) ? 0 : -1}
            disabled={disabled}
            className={value === candidate.value ? 'selected' : ''}
            ref={(element) => {
              buttonRefs.current[index] = element;
            }}
            onClick={() => onChange(candidate.value)}
            key={candidate.value}
          >
            <span aria-hidden="true">{candidate.icon}</span>
            <span>
              <strong>{candidate.label}</strong>
              <small>{candidate.description}</small>
            </span>
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function option<T extends string>(
  value: T,
  label: string,
  description: string,
  Icon: ComponentType,
): WorkspaceCreateOption<T> {
  return { value, label, description, icon: <Icon /> };
}
