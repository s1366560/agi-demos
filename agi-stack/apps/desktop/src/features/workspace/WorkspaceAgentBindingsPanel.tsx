import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertDialog, Button, Dialog, TextArea, TextField } from '@radix-ui/themes';
import { Cross2Icon, PersonIcon, PlusIcon } from '@radix-ui/react-icons';

import { DesktopApiError } from '../../api/client';
import type { WorkspaceBindingAgentDefinition } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
} from '../../types';
import {
  availableWorkspaceAgentDefinitions,
  canManageWorkspaceAgentBindings,
} from './workspaceAgentBindingsModel';
import { WorkspaceSettingsScopeChangedError } from './workspaceSettingsModel';
import type { WorkspaceSettingsScope } from './workspaceSettingsModel';
import './WorkspaceAgentBindingsPanel.css';

type WorkspaceAgentBindingsPanelProps = {
  active: boolean;
  agents: WorkspaceAuthorityCollection<WorkspaceAgentBinding>;
  members: WorkspaceAuthorityCollection<WorkspaceMemberSummary>;
  actorUserId: string;
  scope: WorkspaceSettingsScope;
  onLoadAgentDefinitions: (
    scope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ) => Promise<WorkspaceBindingAgentDefinition[]>;
  onBindAgent: (
    agentId: string,
    displayName: string,
    description: string,
    scope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ) => Promise<WorkspaceAgentBinding>;
  onUnbindAgent: (
    bindingId: string,
    scope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ) => Promise<void>;
};

type DefinitionState =
  | { status: 'idle' | 'loading'; items: WorkspaceBindingAgentDefinition[] }
  | { status: 'ready'; items: WorkspaceBindingAgentDefinition[] }
  | { status: 'error'; items: WorkspaceBindingAgentDefinition[] };

type AgentFeedback = {
  tone: 'error' | 'success';
  message: string;
};

export function WorkspaceAgentBindingsPanel({
  active,
  agents,
  members,
  actorUserId,
  scope,
  onLoadAgentDefinitions,
  onBindAgent,
  onUnbindAgent,
}: WorkspaceAgentBindingsPanelProps) {
  const { t } = useI18n();
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [definitions, setDefinitions] = useState<DefinitionState>({
    status: 'idle',
    items: [],
  });
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [pendingBindingId, setPendingBindingId] = useState<string | null>(null);
  const [removeCandidate, setRemoveCandidate] =
    useState<WorkspaceAgentBinding | null>(null);
  const [feedback, setFeedback] = useState<AgentFeedback | null>(null);
  const catalogRequestRef = useRef<AbortController | null>(null);
  const mutationRequestRef = useRef<AbortController | null>(null);
  const canManage = canManageWorkspaceAgentBindings(members, actorUserId);
  const availableDefinitions = useMemo(
    () => availableWorkspaceAgentDefinitions(definitions.items, agents.items),
    [agents.items, definitions.items],
  );
  const selectedDefinition = availableDefinitions.find(
    (definition) => definition.id === selectedAgentId,
  );
  const panelFeedback = selectorOpen ? null : feedback;

  useEffect(() => {
    catalogRequestRef.current?.abort();
    mutationRequestRef.current?.abort();
    catalogRequestRef.current = null;
    mutationRequestRef.current = null;
    setSelectorOpen(false);
    setDefinitions({ status: 'idle', items: [] });
    setSelectedAgentId('');
    setDisplayName('');
    setDescription('');
    setPendingBindingId(null);
    setRemoveCandidate(null);
    setFeedback(null);
  }, [
    active,
    scope.contextRevision,
    scope.epoch,
    scope.projectId,
    scope.tenantId,
    scope.workspaceId,
  ]);

  useEffect(
    () => () => {
      catalogRequestRef.current?.abort();
      mutationRequestRef.current?.abort();
    },
    [],
  );

  const loadDefinitions = async () => {
    if (!active || !canManage || catalogRequestRef.current) return;
    const controller = new AbortController();
    catalogRequestRef.current = controller;
    setDefinitions((current) => ({
      status: 'loading',
      items: current.items,
    }));
    try {
      const items = await onLoadAgentDefinitions(
        { ...scope },
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        catalogRequestRef.current !== controller
      ) {
        return;
      }
      catalogRequestRef.current = null;
      setDefinitions({ status: 'ready', items });
    } catch {
      if (
        controller.signal.aborted ||
        catalogRequestRef.current !== controller
      ) {
        return;
      }
      catalogRequestRef.current = null;
      setDefinitions({ status: 'error', items: [] });
    }
  };

  const openSelector = () => {
    if (!active || !canManage || pendingBindingId) return;
    setFeedback(null);
    setSelectorOpen(true);
    void loadDefinitions();
  };

  const closeSelector = () => {
    if (pendingBindingId === selectedAgentId) return;
    catalogRequestRef.current?.abort();
    catalogRequestRef.current = null;
    setSelectorOpen(false);
    setDefinitions({ status: 'idle', items: [] });
    setSelectedAgentId('');
    setDisplayName('');
    setDescription('');
  };

  const selectDefinition = (agentId: string) => {
    const definition = availableDefinitions.find(
      (candidate) => candidate.id === agentId,
    );
    setSelectedAgentId(agentId);
    setDisplayName(definition?.display_name ?? definition?.name ?? '');
    setDescription('');
    setFeedback(null);
  };

  const bindAgent = async () => {
    if (
      !active ||
      !canManage ||
      !selectedAgentId ||
      !selectedDefinition ||
      mutationRequestRef.current
    ) {
      return;
    }
    const controller = new AbortController();
    mutationRequestRef.current = controller;
    setPendingBindingId(selectedAgentId);
    setFeedback(null);
    try {
      await onBindAgent(
        selectedAgentId,
        displayName,
        description,
        { ...scope },
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        mutationRequestRef.current !== controller
      ) {
        return;
      }
      mutationRequestRef.current = null;
      setPendingBindingId(null);
      setSelectorOpen(false);
      setDefinitions({ status: 'idle', items: [] });
      setSelectedAgentId('');
      setDisplayName('');
      setDescription('');
      setFeedback({
        tone: 'success',
        message: t('workspaceAgents.bindSuccess'),
      });
    } catch (error) {
      settleAgentMutationError(
        error,
        controller,
        mutationRequestRef,
        setPendingBindingId,
        setFeedback,
        t,
      );
    }
  };

  const unbindAgent = async (binding: WorkspaceAgentBinding) => {
    if (!active || !canManage || mutationRequestRef.current) return;
    const controller = new AbortController();
    mutationRequestRef.current = controller;
    setPendingBindingId(binding.id);
    setRemoveCandidate(null);
    setFeedback(null);
    try {
      await onUnbindAgent(
        binding.id,
        { ...scope },
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        mutationRequestRef.current !== controller
      ) {
        return;
      }
      mutationRequestRef.current = null;
      setPendingBindingId(null);
      setFeedback({
        tone: 'success',
        message: t('workspaceAgents.unbindSuccess'),
      });
    } catch (error) {
      settleAgentMutationError(
        error,
        controller,
        mutationRequestRef,
        setPendingBindingId,
        setFeedback,
        t,
      );
    }
  };

  return (
    <section
      className="workspace-agents-panel"
      aria-labelledby="workspace-agents-title"
    >
      <header>
        <PersonIcon aria-hidden="true" />
        <div>
          <strong id="workspace-agents-title">{t('workspaceAgents.title')}</strong>
          <small>{t('workspaceAgents.description')}</small>
        </div>
        <Button
          type="button"
          size="1"
          disabled={!canManage || agents.status !== 'ready' || Boolean(pendingBindingId)}
          onClick={openSelector}
        >
          <PlusIcon aria-hidden="true" />
          {t('workspaceAgents.add')}
        </Button>
      </header>

      {agents.status === 'loading' ? (
        <AgentAuthorityState
          state="loading"
          message={t('workspaceAgents.loading')}
        />
      ) : agents.status === 'error' ? (
        <AgentAuthorityState
          state="error"
          message={t('workspaceAgents.error')}
          detail={agents.error}
        />
      ) : agents.status === 'unavailable' ? (
        <AgentAuthorityState
          state="unavailable"
          message={t('workspaceAgents.unavailable')}
        />
      ) : (
        <>
          {!canManage ? (
            <p className="workspace-agents-read-only" role="note">
              {t('workspaceAgents.readOnly')}
            </p>
          ) : null}
          {agents.items.length === 0 ? (
            <p className="workspace-agents-empty">
              {t('workspaceAgents.empty')}
            </p>
          ) : (
            <div className="workspace-agents-list">
              {agents.items.map((binding) => {
                const label = binding.display_name?.trim() || binding.agent_id;
                const rowPending = pendingBindingId === binding.id;
                return (
                  <article key={binding.id} aria-busy={rowPending}>
                    <div>
                      <strong>{label}</strong>
                      <small>{binding.agent_id}</small>
                      {binding.description ? <p>{binding.description}</p> : null}
                    </div>
                    <span className={binding.is_active ? 'active' : 'inactive'}>
                      {binding.is_active
                        ? t('workspaceAgents.active')
                        : t('workspaceAgents.inactive')}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      color="red"
                      disabled={!canManage || Boolean(pendingBindingId)}
                      aria-label={t('workspaceAgents.removeAgent', {
                        agent: label,
                      })}
                      onClick={() => setRemoveCandidate(binding)}
                    >
                      <Cross2Icon aria-hidden="true" />
                    </Button>
                  </article>
                );
              })}
            </div>
          )}
        </>
      )}

      <div
        className={`workspace-agents-feedback ${panelFeedback?.tone ?? ''}`}
        role={panelFeedback?.tone === 'error' ? 'alert' : 'status'}
        aria-live={panelFeedback?.tone === 'error' ? 'assertive' : 'polite'}
        aria-atomic="true"
      >
        {panelFeedback?.message ?? ''}
      </div>

      <Dialog.Root
        open={selectorOpen}
        onOpenChange={(next) => (next ? openSelector() : closeSelector())}
      >
        <Dialog.Content className="workspace-agents-selector" maxWidth="540px">
          <Dialog.Title>{t('workspaceAgents.selectorTitle')}</Dialog.Title>
          <Dialog.Description>
            {t('workspaceAgents.selectorDescription')}
          </Dialog.Description>

          {definitions.status === 'loading' ? (
            <AgentAuthorityState
              state="loading"
              message={t('workspaceAgents.loadingDefinitions')}
            />
          ) : definitions.status === 'error' ? (
            <div className="workspace-agents-definition-error" role="alert">
              <span>{t('workspaceAgents.definitionsError')}</span>
              <Button
                type="button"
                size="1"
                variant="soft"
                onClick={() => void loadDefinitions()}
              >
                {t('workspaceAgents.retry')}
              </Button>
            </div>
          ) : definitions.status === 'ready' &&
            availableDefinitions.length === 0 ? (
            <p className="workspace-agents-empty">
              {t('workspaceAgents.noAvailable')}
            </p>
          ) : (
            <div className="workspace-agents-selector-fields">
              <label>
                <span>{t('workspaceAgents.definition')}</span>
                <select
                  autoFocus
                  value={selectedAgentId}
                  disabled={definitions.status !== 'ready' || Boolean(pendingBindingId)}
                  aria-label={t('workspaceAgents.definition')}
                  onChange={(event) => selectDefinition(event.currentTarget.value)}
                >
                  <option value="">{t('workspaceAgents.definitionPlaceholder')}</option>
                  {availableDefinitions.map((definition) => (
                    <option value={definition.id} key={definition.id}>
                      {definition.display_name ?? definition.name}
                      {definition.model ? ` · ${definition.model}` : ''}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>{t('workspaceAgents.displayName')}</span>
                <TextField.Root
                  value={displayName}
                  maxLength={120}
                  disabled={!selectedDefinition || Boolean(pendingBindingId)}
                  placeholder={t('workspaceAgents.displayNamePlaceholder')}
                  aria-label={t('workspaceAgents.displayName')}
                  onChange={(event) => setDisplayName(event.currentTarget.value)}
                />
              </label>
              <label>
                <span>{t('workspaceAgents.descriptionLabel')}</span>
                <TextArea
                  value={description}
                  maxLength={500}
                  rows={3}
                  resize="vertical"
                  disabled={!selectedDefinition || Boolean(pendingBindingId)}
                  placeholder={t('workspaceAgents.descriptionPlaceholder')}
                  aria-label={t('workspaceAgents.descriptionLabel')}
                  onChange={(event) => setDescription(event.currentTarget.value)}
                />
              </label>
            </div>
          )}

          <div
            className={`workspace-agents-feedback ${feedback?.tone ?? ''}`}
            role={feedback?.tone === 'error' ? 'alert' : 'status'}
            aria-live={feedback?.tone === 'error' ? 'assertive' : 'polite'}
            aria-atomic="true"
          >
            {feedback?.message ?? ''}
          </div>

          <div className="workspace-agents-selector-actions">
            <Button
              type="button"
              variant="soft"
              color="gray"
              disabled={Boolean(pendingBindingId)}
              onClick={closeSelector}
            >
              {t('common.cancel')}
            </Button>
            <Button
              type="button"
              disabled={!selectedDefinition || Boolean(pendingBindingId)}
              onClick={() => void bindAgent()}
            >
              {pendingBindingId === selectedAgentId
                ? t('workspaceAgents.binding')
                : t('workspaceAgents.bind')}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root
        open={removeCandidate !== null}
        onOpenChange={(next) => {
          if (!next && !pendingBindingId) setRemoveCandidate(null);
        }}
      >
        <AlertDialog.Content maxWidth="420px">
          <AlertDialog.Title>
            {t('workspaceAgents.removeTitle')}
          </AlertDialog.Title>
          <AlertDialog.Description>
            {t('workspaceAgents.removeDescription', {
              agent:
                removeCandidate?.display_name ??
                removeCandidate?.agent_id ??
                t('workspaceAgents.agent'),
            })}
          </AlertDialog.Description>
          <div className="workspace-agents-confirm-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                {t('common.cancel')}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                color="red"
                onClick={() => {
                  if (removeCandidate) void unbindAgent(removeCandidate);
                }}
              >
                {t('workspaceAgents.removeConfirm')}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </section>
  );
}

function AgentAuthorityState({
  state,
  message,
  detail,
}: {
  state: 'loading' | 'error' | 'unavailable';
  message: string;
  detail?: string | null;
}) {
  return (
    <div
      className={`workspace-agents-authority ${state}`}
      role={state === 'error' ? 'alert' : 'status'}
    >
      <strong>{message}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function settleAgentMutationError(
  error: unknown,
  controller: AbortController,
  requestRef: React.MutableRefObject<AbortController | null>,
  setPendingBindingId: React.Dispatch<React.SetStateAction<string | null>>,
  setFeedback: React.Dispatch<React.SetStateAction<AgentFeedback | null>>,
  t: (key: string) => string,
) {
  if (controller.signal.aborted || requestRef.current !== controller) return;
  requestRef.current = null;
  setPendingBindingId(null);
  setFeedback({
    tone: 'error',
    message:
      error instanceof WorkspaceSettingsScopeChangedError
        ? t('workspaceAgents.scopeChanged')
        : error instanceof DesktopApiError && error.status === 403
          ? t('workspaceAgents.permissionDenied')
          : error instanceof DesktopApiError && error.status === 409
            ? t('workspaceAgents.conflict')
            : t('workspaceAgents.genericError'),
  });
}
