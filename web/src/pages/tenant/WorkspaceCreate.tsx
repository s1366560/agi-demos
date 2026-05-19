import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { Button, Input, message, Select, Tag } from 'antd';
import {
  ArrowLeft,
  BookOpenCheck,
  BriefcaseBusiness,
  Code2,
  FolderKanban,
  GitBranch,
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
  DEFAULT_GITHUB_SERVER_URL,
  DEFAULT_GITLAB_SERVER_URL,
  buildDefaultSourceControlConfig,
  buildDefaultDroneDeliveryConfig,
  buildSourceCloneUrl,
  buildWorkspaceCreateRequest,
  isIsolatedSandboxCodeRoot,
  MIN_WORKSPACE_DESCRIPTION_LENGTH,
  normaliseSandboxCodeRoot,
  normaliseWorkspaceSourceControlConfig,
  sourceControlDefaultsForProvider,
} from '@/utils/workspaceConfig';

import { EmptyStateSimple } from '@/components/shared/ui/EmptyStateVariant';

import type {
  WorkspaceCollaborationMode,
  WorkspaceDeliveryDroneConfig,
  WorkspaceSourceControlProvider,
  WorkspaceUseCase,
} from '@/types/workspace';

interface CreationOption<T extends string> {
  label: string;
  description: string;
  value: T;
  icon: ReactNode;
}

interface DroneEnvironmentDraft {
  repo: string;
  branch: string;
  pollIntervalSeconds: string;
  serverUrlEnv: string;
  tokenEnv: string;
  serverPort: string;
  serverHost: string;
  serverProto: string;
  rpcSecretEnv: string;
  userCreate: string;
  githubClientIdEnv: string;
  githubClientSecretEnv: string;
  gitlabClientIdEnv: string;
  gitlabClientSecretEnv: string;
  runnerPort: string;
  runnerCapacity: string;
  runnerName: string;
  runnerRpcProto: string;
  runnerRpcHost: string;
  runnerRpcSecretEnv: string;
}

interface SourceControlDraft {
  provider: WorkspaceSourceControlProvider;
  repo: string;
  defaultBranch: string;
  serverUrl: string;
  cloneUrl: string;
  authTokenEnv: string;
}

const EMPTY_DRONE_ENVIRONMENT_DRAFT: DroneEnvironmentDraft = {
  repo: '',
  branch: '',
  pollIntervalSeconds: '',
  serverUrlEnv: '',
  tokenEnv: '',
  serverPort: '',
  serverHost: '',
  serverProto: '',
  rpcSecretEnv: '',
  userCreate: '',
  githubClientIdEnv: '',
  githubClientSecretEnv: '',
  gitlabClientIdEnv: '',
  gitlabClientSecretEnv: '',
  runnerPort: '',
  runnerCapacity: '',
  runnerName: '',
  runnerRpcProto: '',
  runnerRpcHost: '',
  runnerRpcSecretEnv: '',
};

const EMPTY_SOURCE_CONTROL_DRAFT: SourceControlDraft = {
  provider: 'github',
  repo: '',
  defaultBranch: '',
  serverUrl: '',
  cloneUrl: '',
  authTokenEnv: '',
};

function positiveInteger(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : fallback;
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
  const [sourceControlDraft, setSourceControlDraft] = useState<SourceControlDraft>(
    EMPTY_SOURCE_CONTROL_DRAFT
  );
  const [droneDraft, setDroneDraft] = useState<DroneEnvironmentDraft>(
    EMPTY_DRONE_ENVIRONMENT_DRAFT
  );
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
  const defaultSourceControl = needsCodeRoot
    ? buildDefaultSourceControlConfig(name.trim() || 'workspace', sourceControlDraft.provider)
    : null;
  const sourceControlProvider = sourceControlDraft.provider;
  const sourceControlServerUrl =
    sourceControlDraft.serverUrl ||
    defaultSourceControl?.server_url ||
    sourceControlDefaultsForProvider(sourceControlProvider).serverUrl;
  const sourceControlRepo = sourceControlDraft.repo || defaultSourceControl?.repo || '';
  const sourceControlDefaultBranch =
    sourceControlDraft.defaultBranch || defaultSourceControl?.default_branch || 'main';
  const sourceControlForm = {
    provider: sourceControlProvider,
    repo: sourceControlRepo,
    defaultBranch: sourceControlDefaultBranch,
    serverUrl: sourceControlServerUrl,
    cloneUrl:
      sourceControlDraft.cloneUrl ||
      buildSourceCloneUrl(sourceControlProvider, sourceControlServerUrl, sourceControlRepo),
    authTokenEnv:
      sourceControlDraft.authTokenEnv ||
      defaultSourceControl?.auth_token_env ||
      sourceControlDefaultsForProvider(sourceControlProvider).authTokenEnv,
  };
  const normalizedSourceControl = needsCodeRoot
    ? normaliseWorkspaceSourceControlConfig(
        {
          provider: sourceControlForm.provider,
          repo: sourceControlForm.repo,
          default_branch: sourceControlForm.defaultBranch,
          server_url: sourceControlForm.serverUrl,
          clone_url: sourceControlForm.cloneUrl,
          auth_token_env: sourceControlForm.authTokenEnv,
        },
        name.trim() || 'workspace'
      )
    : undefined;
  const defaultDroneDelivery = needsCodeRoot
    ? buildDefaultDroneDeliveryConfig(
        name.trim() || 'workspace',
        normalizedCodeRoot,
        normalizedSourceControl
      )
    : null;
  const defaultDrone = defaultDroneDelivery?.drone;
  const defaultDroneEnvironment = defaultDrone?.environment;
  const droneForm = {
    repo: droneDraft.repo || defaultDrone?.repo || '',
    branch: droneDraft.branch || defaultDrone?.branch || 'main',
    pollIntervalSeconds:
      droneDraft.pollIntervalSeconds || String(defaultDrone?.poll_interval_seconds ?? 5),
    serverUrlEnv:
      droneDraft.serverUrlEnv ||
      defaultDroneEnvironment?.api?.server_url_env ||
      defaultDrone?.server_url_env ||
      'DRONE_SERVER_URL',
    tokenEnv:
      droneDraft.tokenEnv ||
      defaultDroneEnvironment?.api?.token_env ||
      defaultDrone?.token_env ||
      'DRONE_TOKEN',
    serverPort:
      droneDraft.serverPort || String(defaultDroneEnvironment?.server?.server_port ?? 8080),
    serverHost:
      droneDraft.serverHost || defaultDroneEnvironment?.server?.server_host || 'localhost:8080',
    serverProto: droneDraft.serverProto || defaultDroneEnvironment?.server?.server_proto || 'http',
    rpcSecretEnv:
      droneDraft.rpcSecretEnv ||
      defaultDroneEnvironment?.server?.rpc_secret_env ||
      'DRONE_RPC_SECRET',
    userCreate:
      droneDraft.userCreate ||
      defaultDroneEnvironment?.server?.user_create ||
      'username:memstack,admin:true',
    githubClientIdEnv:
      droneDraft.githubClientIdEnv ||
      defaultDroneEnvironment?.server?.github_client_id_env ||
      'DRONE_GITHUB_CLIENT_ID',
    githubClientSecretEnv:
      droneDraft.githubClientSecretEnv ||
      defaultDroneEnvironment?.server?.github_client_secret_env ||
      'DRONE_GITHUB_CLIENT_SECRET',
    gitlabClientIdEnv:
      droneDraft.gitlabClientIdEnv ||
      defaultDroneEnvironment?.server?.gitlab_client_id_env ||
      'DRONE_GITLAB_CLIENT_ID',
    gitlabClientSecretEnv:
      droneDraft.gitlabClientSecretEnv ||
      defaultDroneEnvironment?.server?.gitlab_client_secret_env ||
      'DRONE_GITLAB_CLIENT_SECRET',
    runnerPort:
      droneDraft.runnerPort || String(defaultDroneEnvironment?.runner?.runner_port ?? 3001),
    runnerCapacity:
      droneDraft.runnerCapacity || String(defaultDroneEnvironment?.runner?.runner_capacity ?? 2),
    runnerName:
      droneDraft.runnerName ||
      defaultDroneEnvironment?.runner?.runner_name ||
      'memstack-drone-runner',
    runnerRpcProto:
      droneDraft.runnerRpcProto || defaultDroneEnvironment?.runner?.rpc_proto || 'http',
    runnerRpcHost:
      droneDraft.runnerRpcHost || defaultDroneEnvironment?.runner?.rpc_host || 'drone-server',
    runnerRpcSecretEnv:
      droneDraft.runnerRpcSecretEnv ||
      defaultDroneEnvironment?.runner?.rpc_secret_env ||
      'DRONE_RPC_SECRET',
  };
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
  const updateSourceControlDraft = <TKey extends keyof SourceControlDraft>(
    key: TKey,
    value: SourceControlDraft[TKey]
  ) => {
    setSourceControlDraft((current) => ({ ...current, [key]: value }));
  };
  const updateSourceControlProvider = (provider: WorkspaceSourceControlProvider) => {
    setSourceControlDraft((current) => {
      const currentDefaults = sourceControlDefaultsForProvider(current.provider);
      const nextDefaults = sourceControlDefaultsForProvider(provider);
      return {
        ...current,
        provider,
        serverUrl:
          !current.serverUrl || current.serverUrl === currentDefaults.serverUrl
            ? nextDefaults.serverUrl
            : current.serverUrl,
        authTokenEnv:
          !current.authTokenEnv || current.authTokenEnv === currentDefaults.authTokenEnv
            ? nextDefaults.authTokenEnv
            : current.authTokenEnv,
        cloneUrl: '',
      };
    });
  };
  const updateDroneDraft = (key: keyof DroneEnvironmentDraft, value: string) => {
    setDroneDraft((current) => ({ ...current, [key]: value }));
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenantId || !projectId || !workspaceUseCase || !collaborationMode || !canCreate) {
      return;
    }

    setSubmitting(true);
    try {
      const droneConfig: WorkspaceDeliveryDroneConfig | undefined = needsCodeRoot
        ? {
            repo: droneForm.repo.trim(),
            branch: droneForm.branch.trim(),
            server_url_env: droneForm.serverUrlEnv.trim(),
            token_env: droneForm.tokenEnv.trim(),
            poll_interval_seconds: positiveInteger(droneForm.pollIntervalSeconds, 5),
            ...(normalizedSourceControl ? { source_control: normalizedSourceControl } : {}),
            environment: {
              api: {
                server_url_env: droneForm.serverUrlEnv.trim(),
                token_env: droneForm.tokenEnv.trim(),
              },
              server: {
                server_port: positiveInteger(droneForm.serverPort, 8080),
                server_host: droneForm.serverHost.trim(),
                server_proto: droneForm.serverProto.trim(),
                rpc_secret_env: droneForm.rpcSecretEnv.trim(),
                user_create: droneForm.userCreate.trim(),
                ...(normalizedSourceControl
                  ? {
                      source_provider: normalizedSourceControl.provider,
                      github_server:
                        normalizedSourceControl.provider === 'github'
                          ? normalizedSourceControl.server_url
                          : DEFAULT_GITHUB_SERVER_URL,
                      gitlab_server:
                        normalizedSourceControl.provider === 'gitlab'
                          ? normalizedSourceControl.server_url
                          : DEFAULT_GITLAB_SERVER_URL,
                    }
                  : {}),
                github_client_id_env: droneForm.githubClientIdEnv.trim(),
                github_client_secret_env: droneForm.githubClientSecretEnv.trim(),
                gitlab_client_id_env: droneForm.gitlabClientIdEnv.trim(),
                gitlab_client_secret_env: droneForm.gitlabClientSecretEnv.trim(),
                git_always_auth: false,
              },
              runner: {
                runner_port: positiveInteger(droneForm.runnerPort, 3001),
                runner_capacity: positiveInteger(droneForm.runnerCapacity, 2),
                runner_name: droneForm.runnerName.trim(),
                rpc_proto: droneForm.runnerRpcProto.trim(),
                rpc_host: droneForm.runnerRpcHost.trim(),
                rpc_secret_env: droneForm.runnerRpcSecretEnv.trim(),
              },
            },
          }
        : undefined;
      const workspace = await createWorkspace(
        tenantId,
        projectId,
        buildWorkspaceCreateRequest({
          name,
          description,
          useCase: workspaceUseCase,
          collaborationMode,
          sandboxCodeRoot: normalizedCodeRoot,
          ...(normalizedSourceControl ? { sourceControl: normalizedSourceControl } : {}),
          ...(droneConfig ? { droneConfig } : {}),
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

              {needsCodeRoot ? (
                <div className="grid gap-3 border-t border-border-light pt-4 dark:border-border-dark">
                  <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
                    {t('workspaceSettings.sourceControl.title', 'Source control')}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.sourceControl.provider', 'SCM provider')}
                      <Select
                        aria-label={t('workspaceSettings.sourceControl.provider', 'SCM provider')}
                        value={sourceControlForm.provider}
                        onChange={(value: WorkspaceSourceControlProvider) => {
                          updateSourceControlProvider(value);
                        }}
                        options={[
                          {
                            value: 'github',
                            label: t('workspaceSettings.sourceControl.providerGithub', 'GitHub'),
                          },
                          {
                            value: 'gitlab',
                            label: t('workspaceSettings.sourceControl.providerGitlab', 'GitLab'),
                          },
                        ]}
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.sourceControl.repo', 'Repository')}
                      <Input
                        prefix={<GitBranch size={14} className="text-text-muted" />}
                        value={sourceControlForm.repo}
                        onChange={(event) => {
                          updateSourceControlDraft('repo', event.target.value);
                        }}
                        placeholder="memstack/my-workspace"
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.sourceControl.defaultBranch', 'Default branch')}
                      <Input
                        value={sourceControlForm.defaultBranch}
                        onChange={(event) => {
                          updateSourceControlDraft('defaultBranch', event.target.value);
                        }}
                        placeholder="main"
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.sourceControl.serverUrl', 'Server URL')}
                      <Input
                        value={sourceControlForm.serverUrl}
                        onChange={(event) => {
                          updateSourceControlDraft('serverUrl', event.target.value);
                        }}
                        placeholder="https://github.com"
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.sourceControl.authTokenEnv', 'Auth token env')}
                      <Input
                        value={sourceControlForm.authTokenEnv}
                        onChange={(event) => {
                          updateSourceControlDraft('authTokenEnv', event.target.value);
                        }}
                        placeholder="GITHUB_TOKEN"
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted sm:col-span-2">
                      {t('workspaceSettings.sourceControl.cloneUrl', 'Clone URL')}
                      <Input
                        value={sourceControlForm.cloneUrl}
                        onChange={(event) => {
                          updateSourceControlDraft('cloneUrl', event.target.value);
                        }}
                        placeholder="https://github.com/memstack/my-workspace.git"
                        disabled={submitting}
                      />
                    </label>
                  </div>
                </div>
              ) : null}

              {needsCodeRoot ? (
                <div className="grid gap-3 border-t border-border-light pt-4 dark:border-border-dark">
                  <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
                    {t('workspaceSettings.delivery.droneEnvironment', 'Drone environment')}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.delivery.droneRepo', 'Drone repository')}
                      <Input
                        value={droneForm.repo}
                        onChange={(event) => {
                          updateDroneDraft('repo', event.target.value);
                        }}
                        placeholder="memstack/my-workspace"
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.delivery.droneBranch', 'Drone branch')}
                      <Input
                        value={droneForm.branch}
                        onChange={(event) => {
                          updateDroneDraft('branch', event.target.value);
                        }}
                        placeholder="main"
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.delivery.droneServerUrlEnv', 'Drone server URL env')}
                      <Input
                        value={droneForm.serverUrlEnv}
                        onChange={(event) => {
                          updateDroneDraft('serverUrlEnv', event.target.value);
                        }}
                        placeholder="DRONE_SERVER_URL"
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t('workspaceSettings.delivery.droneTokenEnv', 'Drone token env')}
                      <Input
                        value={droneForm.tokenEnv}
                        onChange={(event) => {
                          updateDroneDraft('tokenEnv', event.target.value);
                        }}
                        placeholder="DRONE_TOKEN"
                        disabled={submitting}
                      />
                    </label>
                    <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t(
                        'workspaceSettings.delivery.dronePollIntervalSeconds',
                        'Drone poll interval seconds'
                      )}
                      <Input
                        type="number"
                        min={1}
                        value={droneForm.pollIntervalSeconds}
                        onChange={(event) => {
                          updateDroneDraft('pollIntervalSeconds', event.target.value);
                        }}
                        disabled={submitting}
                      />
                    </label>
                  </div>

                  <div className="grid gap-3 border-t border-border-light pt-3 dark:border-border-dark">
                    <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t(
                        'workspaceSettings.delivery.droneServerEnvironment',
                        'Drone server environment'
                      )}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.delivery.droneServerPort', 'Drone server port')}
                        <Input
                          type="number"
                          min={1}
                          value={droneForm.serverPort}
                          onChange={(event) => {
                            updateDroneDraft('serverPort', event.target.value);
                          }}
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.delivery.droneServerHost', 'Drone server host')}
                        <Input
                          value={droneForm.serverHost}
                          onChange={(event) => {
                            updateDroneDraft('serverHost', event.target.value);
                          }}
                          placeholder="localhost:8080"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.delivery.droneServerProto', 'Drone server proto')}
                        <Input
                          value={droneForm.serverProto}
                          onChange={(event) => {
                            updateDroneDraft('serverProto', event.target.value);
                          }}
                          placeholder="http"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.delivery.droneRpcSecretEnv', 'Drone RPC secret env')}
                        <Input
                          value={droneForm.rpcSecretEnv}
                          onChange={(event) => {
                            updateDroneDraft('rpcSecretEnv', event.target.value);
                          }}
                          placeholder="DRONE_RPC_SECRET"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.delivery.droneUserCreate', 'Drone user create')}
                        <Input
                          value={droneForm.userCreate}
                          onChange={(event) => {
                            updateDroneDraft('userCreate', event.target.value);
                          }}
                          placeholder="username:memstack,admin:true"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t(
                          'workspaceSettings.delivery.droneGithubClientIdEnv',
                          'Drone GitHub client ID env'
                        )}
                        <Input
                          value={droneForm.githubClientIdEnv}
                          onChange={(event) => {
                            updateDroneDraft('githubClientIdEnv', event.target.value);
                          }}
                          placeholder="DRONE_GITHUB_CLIENT_ID"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t(
                          'workspaceSettings.delivery.droneGithubClientSecretEnv',
                          'Drone GitHub client secret env'
                        )}
                        <Input
                          value={droneForm.githubClientSecretEnv}
                          onChange={(event) => {
                            updateDroneDraft('githubClientSecretEnv', event.target.value);
                          }}
                          placeholder="DRONE_GITHUB_CLIENT_SECRET"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t(
                          'workspaceSettings.delivery.droneGitlabClientIdEnv',
                          'Drone GitLab client ID env'
                        )}
                        <Input
                          value={droneForm.gitlabClientIdEnv}
                          onChange={(event) => {
                            updateDroneDraft('gitlabClientIdEnv', event.target.value);
                          }}
                          placeholder="DRONE_GITLAB_CLIENT_ID"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t(
                          'workspaceSettings.delivery.droneGitlabClientSecretEnv',
                          'Drone GitLab client secret env'
                        )}
                        <Input
                          value={droneForm.gitlabClientSecretEnv}
                          onChange={(event) => {
                            updateDroneDraft('gitlabClientSecretEnv', event.target.value);
                          }}
                          placeholder="DRONE_GITLAB_CLIENT_SECRET"
                          disabled={submitting}
                        />
                      </label>
                    </div>
                  </div>

                  <div className="grid gap-3 border-t border-border-light pt-3 dark:border-border-dark">
                    <div className="text-xs font-semibold text-text-secondary dark:text-text-muted">
                      {t(
                        'workspaceSettings.delivery.droneRunnerEnvironment',
                        'Drone runner environment'
                      )}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.delivery.droneRunnerPort', 'Drone runner port')}
                        <Input
                          type="number"
                          min={1}
                          value={droneForm.runnerPort}
                          onChange={(event) => {
                            updateDroneDraft('runnerPort', event.target.value);
                          }}
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t(
                          'workspaceSettings.delivery.droneRunnerCapacity',
                          'Drone runner capacity'
                        )}
                        <Input
                          type="number"
                          min={1}
                          value={droneForm.runnerCapacity}
                          onChange={(event) => {
                            updateDroneDraft('runnerCapacity', event.target.value);
                          }}
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.delivery.droneRunnerName', 'Drone runner name')}
                        <Input
                          value={droneForm.runnerName}
                          onChange={(event) => {
                            updateDroneDraft('runnerName', event.target.value);
                          }}
                          placeholder="memstack-drone-runner"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t(
                          'workspaceSettings.delivery.droneRunnerRpcProto',
                          'Drone runner RPC proto'
                        )}
                        <Input
                          value={droneForm.runnerRpcProto}
                          onChange={(event) => {
                            updateDroneDraft('runnerRpcProto', event.target.value);
                          }}
                          placeholder="http"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t(
                          'workspaceSettings.delivery.droneRunnerRpcHost',
                          'Drone runner RPC host'
                        )}
                        <Input
                          value={droneForm.runnerRpcHost}
                          onChange={(event) => {
                            updateDroneDraft('runnerRpcHost', event.target.value);
                          }}
                          placeholder="drone-server"
                          disabled={submitting}
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t(
                          'workspaceSettings.delivery.droneRunnerRpcSecretEnv',
                          'Drone runner RPC secret env'
                        )}
                        <Input
                          value={droneForm.runnerRpcSecretEnv}
                          onChange={(event) => {
                            updateDroneDraft('runnerRpcSecretEnv', event.target.value);
                          }}
                          placeholder="DRONE_RPC_SECRET"
                          disabled={submitting}
                        />
                      </label>
                    </div>
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
