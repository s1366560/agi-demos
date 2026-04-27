import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { Button, Input, message, Tag } from 'antd';
import {
  ArrowLeft,
  BookOpenCheck,
  BriefcaseBusiness,
  Code2,
  FolderKanban,
  LayoutGrid,
  MessageSquareText,
  Network,
  Target,
  Users,
} from 'lucide-react';

import { useCurrentProject, useProjectStore } from '@/stores/project';
import { useCurrentTenant } from '@/stores/tenant';
import { useWorkspaceActions } from '@/stores/workspace';

import {
  buildWorkspaceCreateRequest,
  isIsolatedSandboxCodeRoot,
  MIN_WORKSPACE_DESCRIPTION_LENGTH,
  normaliseSandboxCodeRoot,
} from '@/utils/workspaceConfig';

import { EmptyStateSimple } from '@/components/shared/ui/EmptyStateVariant';

import type { WorkspaceCollaborationMode, WorkspaceUseCase } from '@/types/workspace';

interface CreationOption<T extends string> {
  label: string;
  description: string;
  value: T;
  icon: ReactNode;
}

export function WorkspaceCreate() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ tenantId?: string; projectId?: string }>();
  const currentTenant = useCurrentTenant();
  const currentProject = useCurrentProject();
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const { createWorkspace } = useWorkspaceActions();

  const tenantId = params.tenantId ?? currentTenant?.id ?? null;
  const projectId = params.projectId ?? currentProject?.id ?? projects[0]?.id ?? null;
  const listPath =
    tenantId && projectId
      ? `/tenant/${tenantId}/project/${projectId}/workspaces`
      : tenantId
        ? `/tenant/${tenantId}/workspaces`
        : '/tenant/workspaces';

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [workspaceUseCase, setWorkspaceUseCase] = useState<WorkspaceUseCase | null>(null);
  const [collaborationMode, setCollaborationMode] = useState<WorkspaceCollaborationMode | null>(
    null
  );
  const [sandboxCodeRoot, setSandboxCodeRoot] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const useCaseLabels = useMemo(
    () =>
      ({
        general: t('tenant.workspaceList.typeGeneral', 'General'),
        programming: t('tenant.workspaceList.typeProgramming', 'Programming'),
        conversation: t('tenant.workspaceList.typeConversation', 'Conversation'),
        research: t('tenant.workspaceList.typeResearch', 'Research'),
        operations: t('tenant.workspaceList.typeOperations', 'Operations'),
      }) satisfies Record<WorkspaceUseCase, string>,
    [t]
  );
  const collaborationModeLabels = useMemo(
    () =>
      ({
        single_agent: t('tenant.workspaceList.modeSingle', 'Single'),
        multi_agent_shared: t('tenant.workspaceList.modeShared', 'Shared team'),
        multi_agent_isolated: t('tenant.workspaceList.modeIsolated', 'Isolated'),
        autonomous: t('tenant.workspaceList.modeAutonomous', 'Autonomous'),
      }) satisfies Record<WorkspaceCollaborationMode, string>,
    [t]
  );
  const useCaseOptions = useMemo(
    (): Array<CreationOption<WorkspaceUseCase>> => [
      {
        label: useCaseLabels.general,
        description: t('tenant.workspaceList.typeGeneralDescription', 'Flexible goals'),
        value: 'general',
        icon: <LayoutGrid size={15} aria-hidden />,
      },
      {
        label: useCaseLabels.programming,
        description: t('tenant.workspaceList.typeProgrammingDescription', 'Code and tests'),
        value: 'programming',
        icon: <Code2 size={15} aria-hidden />,
      },
      {
        label: useCaseLabels.conversation,
        description: t('tenant.workspaceList.typeConversationDescription', 'Long-running chat'),
        value: 'conversation',
        icon: <MessageSquareText size={15} aria-hidden />,
      },
      {
        label: useCaseLabels.research,
        description: t('tenant.workspaceList.typeResearchDescription', 'Sources and notes'),
        value: 'research',
        icon: <BookOpenCheck size={15} aria-hidden />,
      },
      {
        label: useCaseLabels.operations,
        description: t('tenant.workspaceList.typeOperationsDescription', 'Runbooks and incidents'),
        value: 'operations',
        icon: <BriefcaseBusiness size={15} aria-hidden />,
      },
    ],
    [t, useCaseLabels]
  );
  const collaborationModeOptions = useMemo(
    (): Array<CreationOption<WorkspaceCollaborationMode>> => [
      {
        label: collaborationModeLabels.single_agent,
        description: t('tenant.workspaceList.modeSingleDescription', 'One active owner'),
        value: 'single_agent',
        icon: <Users size={15} aria-hidden />,
      },
      {
        label: collaborationModeLabels.multi_agent_shared,
        description: t('tenant.workspaceList.modeSharedDescription', 'Shared roster'),
        value: 'multi_agent_shared',
        icon: <Network size={15} aria-hidden />,
      },
      {
        label: collaborationModeLabels.multi_agent_isolated,
        description: t('tenant.workspaceList.modeIsolatedDescription', 'Separate focus lanes'),
        value: 'multi_agent_isolated',
        icon: <LayoutGrid size={15} aria-hidden />,
      },
      {
        label: collaborationModeLabels.autonomous,
        description: t('tenant.workspaceList.modeAutonomousDescription', 'Supervisor-led work'),
        value: 'autonomous',
        icon: <Target size={15} aria-hidden />,
      },
    ],
    [collaborationModeLabels, t]
  );

  useEffect(() => {
    if (!tenantId || params.projectId || currentProject || projects.length > 0) return;
    void listProjects(tenantId).catch(() => {
      // Keep the empty-state guidance visible when project loading fails.
    });
  }, [tenantId, params.projectId, currentProject, projects.length, listProjects]);

  const trimmedDescription = description.trim();
  const normalizedCodeRoot = normaliseSandboxCodeRoot(sandboxCodeRoot);
  const needsCodeRoot = workspaceUseCase === 'programming';
  const hasValidCodeRoot = !needsCodeRoot || isIsolatedSandboxCodeRoot(normalizedCodeRoot);
  const descriptionReady = trimmedDescription.length >= MIN_WORKSPACE_DESCRIPTION_LENGTH;
  const canCreate =
    !!tenantId &&
    !!projectId &&
    !!name.trim() &&
    descriptionReady &&
    workspaceUseCase !== null &&
    collaborationMode !== null &&
    hasValidCodeRoot &&
    !submitting;
  const selectedUseCaseOption = useCaseOptions.find((option) => option.value === workspaceUseCase);
  const selectedModeOption = collaborationModeOptions.find(
    (option) => option.value === collaborationMode
  );

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenantId || !projectId || !workspaceUseCase || !collaborationMode || !canCreate) {
      return;
    }

    setSubmitting(true);
    try {
      const workspace = await createWorkspace(
        tenantId,
        projectId,
        buildWorkspaceCreateRequest({
          name,
          description,
          useCase: workspaceUseCase,
          collaborationMode,
          sandboxCodeRoot: normalizedCodeRoot,
        })
      );
      message.success(t('tenant.workspaceList.createSuccess', 'Workspace created'));
      void navigate(
        `/tenant/${tenantId}/project/${projectId}/blackboard?workspaceId=${workspace.id}`
      );
    } catch {
      message.error(t('tenant.workspaceList.createError', 'Failed to create workspace'));
    } finally {
      setSubmitting(false);
    }
  };

  if (!tenantId || !projectId) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <EmptyStateSimple
          icon={FolderKanban}
          title={t('tenant.workspaceList.noContextTitle', 'Pick a tenant and project')}
          description={t(
            'tenant.workspaceList.noContextDescription',
            'Workspaces are scoped to a project. Select a tenant and project to continue.'
          )}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col px-6 py-8 sm:px-8">
      <header className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <Link
            to={listPath}
            className="inline-flex min-h-9 items-center gap-2 rounded-md px-1 text-sm font-medium text-text-secondary transition hover:text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:text-text-muted"
          >
            <ArrowLeft size={15} aria-hidden />
            {t('tenant.workspaceList.backToWorkspaces', 'Back to workspaces')}
          </Link>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary dark:text-text-inverse">
            {t('tenant.workspaceList.createPanelTitle', 'New workspace')}
          </h1>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-text-secondary dark:text-text-muted">
            {t(
              'tenant.workspaceList.createPanelSubtitle',
              'Set the scenario and operating model before the blackboard opens.'
            )}
          </p>
        </div>
        <Button
          type="primary"
          htmlType="submit"
          form="workspace-create-form"
          loading={submitting}
          disabled={!canCreate}
          className="w-full lg:w-auto"
        >
          {t('tenant.workspaceList.createButton', 'Create Workspace')}
        </Button>
      </header>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <form
          id="workspace-create-form"
          onSubmit={(event) => void onSubmit(event)}
          className="rounded-lg border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark sm:p-5"
        >
          <div className="grid gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div className="flex min-w-0 flex-col gap-4">
              <div>
                <label
                  className="mb-1 block text-xs font-semibold text-text-secondary dark:text-text-muted"
                  htmlFor="workspace-name-input"
                >
                  {t('tenant.workspaceList.nameLabel', 'Name')}
                </label>
                <Input
                  id="workspace-name-input"
                  aria-label={t('tenant.workspaceList.namePlaceholder', 'Workspace name')}
                  placeholder={t('tenant.workspaceList.namePlaceholder', 'Workspace name')}
                  value={name}
                  onChange={(event) => {
                    setName(event.target.value);
                  }}
                  maxLength={120}
                  disabled={submitting}
                />
              </div>

              <div>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <label
                    className="block text-xs font-semibold text-text-secondary dark:text-text-muted"
                    htmlFor="workspace-description-input"
                  >
                    {t('tenant.workspaceList.descriptionLabel', 'Objective')}
                  </label>
                  <span
                    className={[
                      'text-[11px]',
                      descriptionReady
                        ? 'text-status-text-success dark:text-status-text-success-dark'
                        : 'text-text-muted dark:text-text-muted',
                    ].join(' ')}
                  >
                    {String(trimmedDescription.length)}/{String(MIN_WORKSPACE_DESCRIPTION_LENGTH)}
                  </span>
                </div>
                <Input.TextArea
                  id="workspace-description-input"
                  aria-label={t('tenant.workspaceList.descriptionLabel', 'Objective')}
                  placeholder={t(
                    'tenant.workspaceList.descriptionPlaceholder',
                    'What should this workspace accomplish?'
                  )}
                  value={description}
                  onChange={(event) => {
                    setDescription(event.target.value);
                  }}
                  autoSize={{ minRows: 4, maxRows: 7 }}
                  maxLength={600}
                  disabled={submitting}
                />
              </div>

              {needsCodeRoot ? (
                <div>
                  <label
                    className="mb-1 block text-xs font-semibold text-text-secondary dark:text-text-muted"
                    htmlFor="workspace-code-root-input"
                  >
                    {t('tenant.workspaceList.codeRootLabel', 'Code root')}
                  </label>
                  <Input
                    id="workspace-code-root-input"
                    aria-label={t('tenant.workspaceList.codeRootPlaceholder', 'Sandbox code root')}
                    prefix={<Code2 size={14} className="text-text-muted" />}
                    placeholder={t('tenant.workspaceList.codeRootPlaceholder', '/workspace/my-evo')}
                    value={sandboxCodeRoot}
                    onChange={(event) => {
                      setSandboxCodeRoot(event.target.value);
                    }}
                    {...(sandboxCodeRoot && !hasValidCodeRoot ? { status: 'error' as const } : {})}
                    disabled={submitting}
                  />
                  <div
                    className={[
                      'mt-1 text-[11px]',
                      hasValidCodeRoot
                        ? 'text-text-muted dark:text-text-muted'
                        : 'text-status-text-error dark:text-status-text-error-dark',
                    ].join(' ')}
                  >
                    {t(
                      'tenant.workspaceList.codeRootHint',
                      'Use an isolated child path such as /workspace/my-evo.'
                    )}
                  </div>
                </div>
              ) : null}
            </div>

            <div className="grid min-w-0 gap-4">
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
                    {t('tenant.workspaceList.typeSelector', 'Use case')}
                  </div>
                  {selectedUseCaseOption ? (
                    <Tag color="blue" className="!m-0">
                      {selectedUseCaseOption.label}
                    </Tag>
                  ) : null}
                </div>
                <div
                  role="radiogroup"
                  aria-label={t('tenant.workspaceList.typeSelector', 'Use case')}
                  className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-5"
                >
                  {useCaseOptions.map((option) => {
                    const selected = workspaceUseCase === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        disabled={submitting}
                        onClick={() => {
                          setWorkspaceUseCase(option.value);
                        }}
                        className={[
                          'flex min-h-[4.75rem] flex-col items-start justify-between rounded-md border px-3 py-2 text-left transition-colors',
                          selected
                            ? 'border-primary bg-primary/5 text-primary dark:border-primary-light dark:bg-primary/10 dark:text-primary-light'
                            : 'border-border-light bg-surface-muted text-text-primary hover:border-primary/40 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse',
                        ].join(' ')}
                      >
                        <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                          {option.icon}
                          <span className="truncate">{option.label}</span>
                        </span>
                        <span className="mt-1 line-clamp-2 text-xs font-normal text-text-secondary dark:text-text-muted">
                          {option.description}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
                    {t('tenant.workspaceList.modeSelector', 'Collaboration mode')}
                  </div>
                  {selectedModeOption ? (
                    <Tag color="purple" className="!m-0">
                      {selectedModeOption.label}
                    </Tag>
                  ) : null}
                </div>
                <div
                  role="radiogroup"
                  aria-label={t('tenant.workspaceList.modeSelector', 'Collaboration mode')}
                  className="grid gap-2 sm:grid-cols-2"
                >
                  {collaborationModeOptions.map((option) => {
                    const selected = collaborationMode === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        disabled={submitting}
                        onClick={() => {
                          setCollaborationMode(option.value);
                        }}
                        className={[
                          'flex min-h-[4.5rem] flex-col items-start justify-between rounded-md border px-3 py-2 text-left transition-colors',
                          selected
                            ? 'border-primary bg-primary/5 text-primary dark:border-primary-light dark:bg-primary/10 dark:text-primary-light'
                            : 'border-border-light bg-surface-muted text-text-primary hover:border-primary/40 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse',
                        ].join(' ')}
                      >
                        <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                          {option.icon}
                          <span className="truncate">{option.label}</span>
                        </span>
                        <span className="mt-1 line-clamp-2 text-xs font-normal text-text-secondary dark:text-text-muted">
                          {option.description}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </form>

        <aside className="rounded-lg border border-border-light bg-surface-light p-4 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
          <div className="mb-3 font-semibold text-text-primary dark:text-text-inverse">
            {t('tenant.workspaceList.creationBriefTitle', 'Creation brief')}
          </div>
          <dl className="grid gap-3">
            <div className="flex items-center justify-between gap-3">
              <dt>{t('tenant.workspaceList.typeSelector', 'Use case')}</dt>
              <dd className="truncate font-medium text-text-primary dark:text-text-inverse">
                {selectedUseCaseOption?.label ?? t('common.required', 'Required')}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt>{t('tenant.workspaceList.modeSelector', 'Collaboration mode')}</dt>
              <dd className="truncate font-medium text-text-primary dark:text-text-inverse">
                {selectedModeOption?.label ?? t('common.required', 'Required')}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt>{t('tenant.workspaceList.descriptionLabel', 'Objective')}</dt>
              <dd className="font-medium text-text-primary dark:text-text-inverse">
                {descriptionReady ? t('common.ready', 'Ready') : t('common.required', 'Required')}
              </dd>
            </div>
            {needsCodeRoot ? (
              <div className="flex items-center justify-between gap-3">
                <dt>{t('tenant.workspaceList.codeRootLabel', 'Code root')}</dt>
                <dd className="max-w-[10rem] truncate font-medium text-text-primary dark:text-text-inverse">
                  {hasValidCodeRoot ? normalizedCodeRoot : t('common.required', 'Required')}
                </dd>
              </div>
            ) : null}
          </dl>
          <div className="mt-4 border-t border-border-light pt-3 text-[11px] leading-5 dark:border-border-dark">
            {t(
              'tenant.workspaceList.creationBriefHint',
              'The selected scenario becomes workspace metadata for blackboard routing, autonomy checks, and future agent team defaults.'
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
