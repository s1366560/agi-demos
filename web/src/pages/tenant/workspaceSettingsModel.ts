import {
  DEFAULT_DRONE_GITLAB_CLIENT_ID_ENV,
  DEFAULT_DRONE_GITLAB_CLIENT_SECRET_ENV,
  DEFAULT_GITHUB_SERVER_URL,
  DEFAULT_GITLAB_SERVER_URL,
  buildDefaultSourceControlConfig,
  buildDefaultDroneDeliveryConfig,
  isWorkspaceDroneDeployMode,
  getSandboxCodeRoot,
  getWorkspaceCollaborationMode,
  getWorkspaceUseCase,
  isWorkspaceSourceControlProvider,
  normaliseSandboxCodeRoot,
  normaliseWorkspaceSourceControlConfig,
  workspaceTypeForUseCase,
} from '@/utils/workspaceConfig';

import type {
  Workspace,
  WorkspaceCollaborationMode,
  WorkspaceDroneDeployMode,
  WorkspaceDeliveryCicdConfig,
  WorkspaceDeliveryServiceConfig,
  WorkspaceMemberRole,
  WorkspaceMetadata,
  WorkspaceSourceControlConfig,
  WorkspaceSourceControlProvider,
  WorkspaceUseCase,
  WorkspaceVerificationGrade,
} from '@/types/workspace';

export const ROLE_OPTIONS: Array<{ value: WorkspaceMemberRole; labelKey: string }> = [
  { value: 'owner', labelKey: 'workspaceSettings.members.owner' },
  { value: 'editor', labelKey: 'workspaceSettings.members.editor' },
  { value: 'viewer', labelKey: 'workspaceSettings.members.viewer' },
];

export const USE_CASE_OPTIONS: Array<{
  value: WorkspaceUseCase;
  labelKey: string;
  descriptionKey: string;
}> = [
  {
    value: 'general',
    labelKey: 'tenant.workspaceList.typeGeneral',
    descriptionKey: 'tenant.workspaceList.typeGeneralDescription',
  },
  {
    value: 'programming',
    labelKey: 'tenant.workspaceList.typeProgramming',
    descriptionKey: 'tenant.workspaceList.typeProgrammingDescription',
  },
  {
    value: 'conversation',
    labelKey: 'tenant.workspaceList.typeConversation',
    descriptionKey: 'tenant.workspaceList.typeConversationDescription',
  },
  {
    value: 'research',
    labelKey: 'tenant.workspaceList.typeResearch',
    descriptionKey: 'tenant.workspaceList.typeResearchDescription',
  },
  {
    value: 'operations',
    labelKey: 'tenant.workspaceList.typeOperations',
    descriptionKey: 'tenant.workspaceList.typeOperationsDescription',
  },
];

export const COLLABORATION_MODE_OPTIONS: Array<{
  value: WorkspaceCollaborationMode;
  labelKey: string;
  descriptionKey: string;
}> = [
  {
    value: 'single_agent',
    labelKey: 'tenant.workspaceList.modeSingle',
    descriptionKey: 'tenant.workspaceList.modeSingleDescription',
  },
  {
    value: 'multi_agent_shared',
    labelKey: 'tenant.workspaceList.modeShared',
    descriptionKey: 'tenant.workspaceList.modeSharedDescription',
  },
  {
    value: 'multi_agent_isolated',
    labelKey: 'tenant.workspaceList.modeIsolated',
    descriptionKey: 'tenant.workspaceList.modeIsolatedDescription',
  },
  {
    value: 'autonomous',
    labelKey: 'tenant.workspaceList.modeAutonomous',
    descriptionKey: 'tenant.workspaceList.modeAutonomousDescription',
  },
];

export const VERIFICATION_GRADE_OPTIONS: WorkspaceVerificationGrade[] = ['pass', 'warn', 'fail'];

export const SOURCE_CONTROL_PROVIDER_OPTIONS: Array<{
  value: WorkspaceSourceControlProvider;
  labelKey: string;
}> = [
  { value: 'github', labelKey: 'workspaceSettings.sourceControl.providerGithub' },
  { value: 'gitlab', labelKey: 'workspaceSettings.sourceControl.providerGitlab' },
];

export interface SettingsDraft {
  name: string;
  description: string;
  isArchived: boolean;
  workspaceUseCase: WorkspaceUseCase;
  collaborationMode: WorkspaceCollaborationMode;
  sandboxCodeRoot: string;
  sourceControlProvider: WorkspaceSourceControlProvider;
  sourceControlRepo: string;
  sourceControlDefaultBranch: string;
  sourceControlServerUrl: string;
  sourceControlCloneUrl: string;
  sourceControlAuthTokenEnv: string;
  allowInternalTaskArtifacts: boolean;
  requiresExternalArtifact: boolean;
  minimumVerificationGrade: WorkspaceVerificationGrade;
  requiredArtifactPrefixes: string;
  deliveryProvider: string;
  deliveryAgentManaged: boolean;
  deliveryContractSource: string;
  deliveryContractConfidence: number;
  deliveryTimeoutSeconds: number;
  deliveryAutoDeploy: boolean;
  deliveryPreviewPort: number;
  deliveryHealthUrl: string;
  deliveryHealthCommand: string;
  deliveryInstallCommand: string;
  deliveryLintCommand: string;
  deliveryTestCommand: string;
  deliveryBuildCommand: string;
  deliveryDeployCommand: string;
  deliveryServices: WorkspaceDeliveryServiceConfig[];
  deliveryDroneRepo: string;
  deliveryDroneBranch: string;
  deliveryDroneServerUrlEnv: string;
  deliveryDroneTokenEnv: string;
  deliveryDronePollIntervalSeconds: number;
  deliveryDroneServerPort: number;
  deliveryDroneServerHost: string;
  deliveryDroneServerProto: string;
  deliveryDroneRpcSecretEnv: string;
  deliveryDroneUserCreate: string;
  deliveryDroneGithubClientIdEnv: string;
  deliveryDroneGithubClientSecretEnv: string;
  deliveryDroneGitlabClientIdEnv: string;
  deliveryDroneGitlabClientSecretEnv: string;
  deliveryDroneGitAlwaysAuth: boolean;
  deliveryDroneRunnerPort: number;
  deliveryDroneRunnerCapacity: number;
  deliveryDroneRunnerName: string;
  deliveryDroneRunnerRpcProto: string;
  deliveryDroneRunnerRpcHost: string;
  deliveryDroneRunnerRpcSecretEnv: string;
  deliveryDroneDeployEnabled: boolean;
  deliveryDroneDeployMode: WorkspaceDroneDeployMode;
  deliveryDroneDeployTarget: string;
  deliveryDroneDeployStage: string;
  deliveryDroneDeployRequired: boolean;
  deliveryDroneDeployDockerRegistry: string;
  deliveryDroneDeployDockerImage: string;
  deliveryDroneDeployDockerContext: string;
  deliveryDroneDeployDockerfile: string;
  deliveryDroneDeployDockerTags: string;
  deliveryDroneDeployDockerUsernameSecret: string;
  deliveryDroneDeployDockerPasswordSecret: string;
  deliveryDroneDeployKubernetesNamespace: string;
  deliveryDroneDeployKubernetesManifestPaths: string;
  deliveryDroneDeployKubeconfigSecret: string;
  deliveryDroneDeployKubernetesContext: string;
  deliveryDroneDeployKubectlImage: string;
  deliveryDroneDeployCliImage: string;
  deliveryDroneDeployCliCommands: string;
  rawMetadata: string;
}

export function syncDraftFromWorkspace(workspace: Workspace): SettingsDraft {
  const metadata = workspace.metadata ?? {};
  const profile = metadata.autonomy_profile ?? {};
  const policy = profile.completion_policy ?? {};
  const workspaceUseCase = getWorkspaceUseCase(workspace);
  const sandboxCodeRoot = getSandboxCodeRoot(workspace) ?? '';
  const delivery = metadata.delivery_cicd ?? {};
  const defaultDelivery =
    workspaceUseCase === 'programming' && sandboxCodeRoot
      ? buildDefaultDroneDeliveryConfig(workspace.name, normaliseSandboxCodeRoot(sandboxCodeRoot))
      : null;
  const defaultDrone = defaultDelivery?.drone;
  const drone = asRecord(delivery.drone);
  const defaultEnvironment = defaultDrone?.environment;
  const defaultDeploy = defaultDrone?.deploy;
  const environment = asRecord(drone.environment);
  const apiEnvironment = asRecord(environment.api);
  const serverEnvironment = asRecord(environment.server);
  const runnerEnvironment = asRecord(environment.runner);
  const deploy = asRecord(drone.deploy);
  const deployDocker = asRecord(deploy.docker);
  const deployKubernetes = asRecord(deploy.kubernetes);
  const deployCli = asRecord(deploy.cli);
  const explicitDroneRepo = asString(drone.repo ?? drone.repository);
  const explicitDroneBranch = asString(drone.branch);
  const sourceControlSeed = {
    ...asRecord(drone.source_control),
    ...asRecord(metadata.source_control),
  } as WorkspaceSourceControlConfig;
  if (!sourceControlSeed.repo && explicitDroneRepo) {
    sourceControlSeed.repo = explicitDroneRepo;
  }
  if (!sourceControlSeed.default_branch && explicitDroneBranch) {
    sourceControlSeed.default_branch = explicitDroneBranch;
  }
  if (
    !isWorkspaceSourceControlProvider(sourceControlSeed.provider) &&
    isWorkspaceSourceControlProvider(serverEnvironment.source_provider)
  ) {
    sourceControlSeed.provider = serverEnvironment.source_provider;
  }
  const sourceControl =
    workspaceUseCase === 'programming'
      ? normaliseWorkspaceSourceControlConfig(sourceControlSeed, workspace.name)
      : buildDefaultSourceControlConfig(workspace.name);
  const deliveryDroneRepo = explicitDroneRepo || sourceControl.repo || defaultDrone?.repo || '';
  const deliveryDroneBranch =
    explicitDroneBranch || sourceControl.default_branch || defaultDrone?.branch || 'main';

  return {
    name: workspace.name,
    description: workspace.description ?? '',
    isArchived: workspace.is_archived ?? false,
    workspaceUseCase,
    collaborationMode: getWorkspaceCollaborationMode(workspace),
    sandboxCodeRoot,
    sourceControlProvider: sourceControl.provider ?? 'github',
    sourceControlRepo: sourceControl.repo ?? '',
    sourceControlDefaultBranch: sourceControl.default_branch ?? 'main',
    sourceControlServerUrl: sourceControl.server_url ?? DEFAULT_GITHUB_SERVER_URL,
    sourceControlCloneUrl: sourceControl.clone_url ?? '',
    sourceControlAuthTokenEnv: sourceControl.auth_token_env ?? 'GITHUB_TOKEN',
    allowInternalTaskArtifacts: policy.allow_internal_task_artifacts ?? false,
    requiresExternalArtifact: policy.requires_external_artifact ?? false,
    minimumVerificationGrade: policy.minimum_verification_grade ?? 'warn',
    requiredArtifactPrefixes: formatPrefixDraft(policy.required_artifact_prefixes),
    deliveryProvider: asString(delivery.provider) || defaultDelivery?.provider || 'sandbox_native',
    deliveryAgentManaged: delivery.agent_managed ?? defaultDelivery?.agent_managed ?? true,
    deliveryContractSource:
      asString(delivery.contract_source) || defaultDelivery?.contract_source || 'metadata',
    deliveryContractConfidence:
      delivery.contract_confidence === undefined
        ? (defaultDelivery?.contract_confidence ?? 0)
        : clampConfidence(delivery.contract_confidence),
    deliveryTimeoutSeconds: asNumber(
      delivery.timeout_seconds,
      defaultDelivery?.timeout_seconds ?? 600
    ),
    deliveryAutoDeploy: delivery.auto_deploy ?? defaultDelivery?.auto_deploy ?? true,
    deliveryPreviewPort: asNumber(delivery.preview_port, 3000),
    deliveryHealthUrl: asString(delivery.health_url),
    deliveryHealthCommand: asString(delivery.health_command),
    deliveryInstallCommand: asString(delivery.install_command),
    deliveryLintCommand: asString(delivery.lint_command),
    deliveryTestCommand: asString(delivery.test_command),
    deliveryBuildCommand: asString(delivery.build_command),
    deliveryDeployCommand: asString(delivery.deploy_command),
    deliveryServices: normaliseDeliveryServices(delivery.services),
    deliveryDroneRepo,
    deliveryDroneBranch,
    deliveryDroneServerUrlEnv:
      asString(apiEnvironment.server_url_env) ||
      asString(drone.server_url_env) ||
      defaultEnvironment?.api?.server_url_env ||
      defaultDrone?.server_url_env ||
      'DRONE_SERVER_URL',
    deliveryDroneTokenEnv:
      asString(apiEnvironment.token_env) ||
      asString(drone.token_env) ||
      defaultEnvironment?.api?.token_env ||
      defaultDrone?.token_env ||
      'DRONE_TOKEN',
    deliveryDronePollIntervalSeconds: asNumber(
      drone.poll_interval_seconds,
      defaultDrone?.poll_interval_seconds ?? 5
    ),
    deliveryDroneServerPort: asNumber(
      serverEnvironment.server_port,
      defaultEnvironment?.server?.server_port ?? 8080
    ),
    deliveryDroneServerHost:
      asString(serverEnvironment.server_host) ||
      defaultEnvironment?.server?.server_host ||
      'localhost:8080',
    deliveryDroneServerProto:
      asString(serverEnvironment.server_proto) ||
      defaultEnvironment?.server?.server_proto ||
      'http',
    deliveryDroneRpcSecretEnv:
      asString(serverEnvironment.rpc_secret_env) ||
      asString(runnerEnvironment.rpc_secret_env) ||
      defaultEnvironment?.server?.rpc_secret_env ||
      'DRONE_RPC_SECRET',
    deliveryDroneUserCreate:
      asString(serverEnvironment.user_create) ||
      defaultEnvironment?.server?.user_create ||
      'username:memstack,admin:true',
    deliveryDroneGithubClientIdEnv:
      asString(serverEnvironment.github_client_id_env) ||
      defaultEnvironment?.server?.github_client_id_env ||
      'DRONE_GITHUB_CLIENT_ID',
    deliveryDroneGithubClientSecretEnv:
      asString(serverEnvironment.github_client_secret_env) ||
      defaultEnvironment?.server?.github_client_secret_env ||
      'DRONE_GITHUB_CLIENT_SECRET',
    deliveryDroneGitlabClientIdEnv:
      asString(serverEnvironment.gitlab_client_id_env) ||
      defaultEnvironment?.server?.gitlab_client_id_env ||
      DEFAULT_DRONE_GITLAB_CLIENT_ID_ENV,
    deliveryDroneGitlabClientSecretEnv:
      asString(serverEnvironment.gitlab_client_secret_env) ||
      defaultEnvironment?.server?.gitlab_client_secret_env ||
      DEFAULT_DRONE_GITLAB_CLIENT_SECRET_ENV,
    deliveryDroneGitAlwaysAuth: asBoolean(
      serverEnvironment.git_always_auth,
      defaultEnvironment?.server?.git_always_auth ?? false
    ),
    deliveryDroneRunnerPort: asNumber(
      runnerEnvironment.runner_port,
      defaultEnvironment?.runner?.runner_port ?? 3001
    ),
    deliveryDroneRunnerCapacity: asNumber(
      runnerEnvironment.runner_capacity,
      defaultEnvironment?.runner?.runner_capacity ?? 2
    ),
    deliveryDroneRunnerName:
      asString(runnerEnvironment.runner_name) ||
      defaultEnvironment?.runner?.runner_name ||
      'memstack-drone-runner',
    deliveryDroneRunnerRpcProto:
      asString(runnerEnvironment.rpc_proto) || defaultEnvironment?.runner?.rpc_proto || 'http',
    deliveryDroneRunnerRpcHost:
      asString(runnerEnvironment.rpc_host) ||
      defaultEnvironment?.runner?.rpc_host ||
      'drone-server',
    deliveryDroneRunnerRpcSecretEnv:
      asString(runnerEnvironment.rpc_secret_env) ||
      asString(serverEnvironment.rpc_secret_env) ||
      defaultEnvironment?.runner?.rpc_secret_env ||
      'DRONE_RPC_SECRET',
    deliveryDroneDeployEnabled: asBoolean(deploy.enabled, defaultDeploy?.enabled ?? false),
    deliveryDroneDeployMode: isWorkspaceDroneDeployMode(deploy.mode)
      ? deploy.mode
      : (defaultDeploy?.mode ?? 'cli'),
    deliveryDroneDeployTarget: asString(deploy.target),
    deliveryDroneDeployStage: asString(deploy.stage) || defaultDeploy?.stage || 'deploy',
    deliveryDroneDeployRequired: asBoolean(deploy.required, defaultDeploy?.required ?? true),
    deliveryDroneDeployDockerRegistry: asString(deployDocker.registry),
    deliveryDroneDeployDockerImage: asString(deployDocker.image),
    deliveryDroneDeployDockerContext:
      asString(deployDocker.context) || defaultDeploy?.docker?.context || '.',
    deliveryDroneDeployDockerfile:
      asString(deployDocker.dockerfile) || defaultDeploy?.docker?.dockerfile || 'Dockerfile',
    deliveryDroneDeployDockerTags: formatListDraft(
      deployDocker.tags || defaultDeploy?.docker?.tags
    ),
    deliveryDroneDeployDockerUsernameSecret: asString(deployDocker.username_secret),
    deliveryDroneDeployDockerPasswordSecret: asString(deployDocker.password_secret),
    deliveryDroneDeployKubernetesNamespace:
      asString(deployKubernetes.namespace) || defaultDeploy?.kubernetes?.namespace || 'default',
    deliveryDroneDeployKubernetesManifestPaths: formatListDraft(
      deployKubernetes.manifest_paths || defaultDeploy?.kubernetes?.manifest_paths
    ),
    deliveryDroneDeployKubeconfigSecret:
      asString(deployKubernetes.kubeconfig_secret) ||
      defaultDeploy?.kubernetes?.kubeconfig_secret ||
      'kubeconfig',
    deliveryDroneDeployKubernetesContext: asString(deployKubernetes.context),
    deliveryDroneDeployKubectlImage:
      asString(deployKubernetes.kubectl_image) ||
      defaultDeploy?.kubernetes?.kubectl_image ||
      'bitnami/kubectl:latest',
    deliveryDroneDeployCliImage:
      asString(deployCli.image) || defaultDeploy?.cli?.image || 'alpine:3.20',
    deliveryDroneDeployCliCommands: formatListDraft(
      deployCli.commands || defaultDeploy?.cli?.commands
    ),
    rawMetadata: prettyJson(metadata),
  };
}

export function buildWorkspaceMetadataDraft(draft: SettingsDraft): {
  metadata: WorkspaceMetadata;
  error: string | null;
} {
  const parsed = parseMetadataDraft(draft.rawMetadata);
  if (parsed.error) {
    return parsed;
  }

  const metadata: WorkspaceMetadata = { ...parsed.metadata };
  const workspaceType = workspaceTypeForUseCase(draft.workspaceUseCase);
  const normalizedCodeRoot = normaliseSandboxCodeRoot(draft.sandboxCodeRoot);
  const existingProfile =
    metadata.autonomy_profile && typeof metadata.autonomy_profile === 'object'
      ? metadata.autonomy_profile
      : {};
  const existingPolicy =
    existingProfile.completion_policy && typeof existingProfile.completion_policy === 'object'
      ? existingProfile.completion_policy
      : {};

  metadata.workspace_use_case = draft.workspaceUseCase;
  metadata.workspace_type = workspaceType;
  metadata.collaboration_mode = draft.collaborationMode;
  metadata.agent_conversation_mode = draft.collaborationMode;
  metadata.autonomy_profile = {
    ...existingProfile,
    workspace_type: workspaceType,
    completion_policy: {
      ...existingPolicy,
      allow_internal_task_artifacts: draft.allowInternalTaskArtifacts,
      requires_external_artifact: draft.requiresExternalArtifact,
      minimum_verification_grade: draft.minimumVerificationGrade,
      required_artifact_prefixes: parsePrefixDraft(draft.requiredArtifactPrefixes),
    },
  };

  if (normalizedCodeRoot) {
    metadata.sandbox_code_root = normalizedCodeRoot;
    metadata.code_context = {
      ...(metadata.code_context ?? {}),
      sandbox_code_root: normalizedCodeRoot,
    };
  } else {
    delete metadata.sandbox_code_root;
    if (metadata.code_context) {
      const nextCodeContext = { ...metadata.code_context };
      delete nextCodeContext.sandbox_code_root;
      metadata.code_context = nextCodeContext;
    }
  }

  const sourceControl = normaliseWorkspaceSourceControlConfig(
    {
      provider: draft.sourceControlProvider,
      repo: draft.sourceControlRepo,
      default_branch: draft.sourceControlDefaultBranch,
      server_url: draft.sourceControlServerUrl,
      clone_url: draft.sourceControlCloneUrl,
      auth_token_env: draft.sourceControlAuthTokenEnv,
    },
    draft.name
  );
  if (draft.workspaceUseCase === 'programming' || draft.sourceControlRepo.trim()) {
    metadata.source_control = sourceControl;
  } else {
    delete metadata.source_control;
  }

  const deliveryCicd: WorkspaceDeliveryCicdConfig = {
    ...(metadata.delivery_cicd ?? {}),
    provider: draft.deliveryProvider || 'sandbox_native',
    code_root: normalizedCodeRoot || undefined,
    agent_managed: draft.deliveryAgentManaged,
    contract_source: draft.deliveryContractSource || 'metadata',
    contract_confidence: draft.deliveryContractConfidence,
    timeout_seconds: Math.max(1, draft.deliveryTimeoutSeconds || 600),
    auto_deploy: draft.deliveryAutoDeploy,
    preview_port: Math.max(1, draft.deliveryPreviewPort || 3000),
    health_url: draft.deliveryHealthUrl.trim() || undefined,
    health_command: draft.deliveryHealthCommand.trim() || undefined,
    install_command: draft.deliveryInstallCommand.trim() || undefined,
    lint_command: draft.deliveryLintCommand.trim() || undefined,
    test_command: draft.deliveryTestCommand.trim() || undefined,
    build_command: draft.deliveryBuildCommand.trim() || undefined,
    deploy_command: draft.deliveryDeployCommand.trim() || undefined,
    services: normaliseDeliveryServices(draft.deliveryServices),
  };
  if (draft.deliveryProvider === 'drone' || metadata.delivery_cicd?.drone) {
    const sourceProvider = sourceControl.provider ?? 'github';
    const githubServer =
      sourceProvider === 'github'
        ? sourceControl.server_url || DEFAULT_GITHUB_SERVER_URL
        : DEFAULT_GITHUB_SERVER_URL;
    const gitlabServer =
      sourceProvider === 'gitlab'
        ? sourceControl.server_url || DEFAULT_GITLAB_SERVER_URL
        : DEFAULT_GITLAB_SERVER_URL;
    deliveryCicd.drone = {
      ...asRecord(metadata.delivery_cicd?.drone),
      repo: sourceControl.repo || draft.deliveryDroneRepo.trim() || undefined,
      branch: sourceControl.default_branch || draft.deliveryDroneBranch.trim() || undefined,
      server_url_env: draft.deliveryDroneServerUrlEnv.trim() || undefined,
      token_env: draft.deliveryDroneTokenEnv.trim() || undefined,
      poll_interval_seconds: Math.max(1, draft.deliveryDronePollIntervalSeconds || 5),
      source_control: sourceControl,
      environment: {
        api: {
          server_url_env: draft.deliveryDroneServerUrlEnv.trim() || undefined,
          token_env: draft.deliveryDroneTokenEnv.trim() || undefined,
        },
        server: {
          server_port: Math.max(1, draft.deliveryDroneServerPort || 8080),
          server_host: draft.deliveryDroneServerHost.trim() || undefined,
          server_proto: draft.deliveryDroneServerProto.trim() || undefined,
          rpc_secret_env: draft.deliveryDroneRpcSecretEnv.trim() || undefined,
          user_create: draft.deliveryDroneUserCreate.trim() || undefined,
          source_provider: sourceProvider,
          github_server: githubServer,
          github_client_id_env: draft.deliveryDroneGithubClientIdEnv.trim() || undefined,
          github_client_secret_env: draft.deliveryDroneGithubClientSecretEnv.trim() || undefined,
          gitlab_server: gitlabServer,
          gitlab_client_id_env: draft.deliveryDroneGitlabClientIdEnv.trim() || undefined,
          gitlab_client_secret_env: draft.deliveryDroneGitlabClientSecretEnv.trim() || undefined,
          git_always_auth: draft.deliveryDroneGitAlwaysAuth,
        },
        runner: {
          runner_port: Math.max(1, draft.deliveryDroneRunnerPort || 3001),
          runner_capacity: Math.max(1, draft.deliveryDroneRunnerCapacity || 2),
          runner_name: draft.deliveryDroneRunnerName.trim() || undefined,
          rpc_proto: draft.deliveryDroneRunnerRpcProto.trim() || undefined,
          rpc_host: draft.deliveryDroneRunnerRpcHost.trim() || undefined,
          rpc_secret_env: draft.deliveryDroneRunnerRpcSecretEnv.trim() || undefined,
        },
      },
      deploy: {
        enabled: draft.deliveryDroneDeployEnabled,
        mode: draft.deliveryDroneDeployMode,
        target: draft.deliveryDroneDeployTarget.trim() || undefined,
        stage: draft.deliveryDroneDeployStage.trim() || 'deploy',
        required: draft.deliveryDroneDeployRequired,
        docker: {
          registry: draft.deliveryDroneDeployDockerRegistry.trim() || undefined,
          image: draft.deliveryDroneDeployDockerImage.trim() || undefined,
          context: draft.deliveryDroneDeployDockerContext.trim() || '.',
          dockerfile: draft.deliveryDroneDeployDockerfile.trim() || 'Dockerfile',
          tags: parseListDraft(draft.deliveryDroneDeployDockerTags),
          username_secret: draft.deliveryDroneDeployDockerUsernameSecret.trim() || undefined,
          password_secret: draft.deliveryDroneDeployDockerPasswordSecret.trim() || undefined,
        },
        kubernetes: {
          namespace: draft.deliveryDroneDeployKubernetesNamespace.trim() || 'default',
          manifest_paths: parseListDraft(draft.deliveryDroneDeployKubernetesManifestPaths),
          kubeconfig_secret: draft.deliveryDroneDeployKubeconfigSecret.trim() || undefined,
          context: draft.deliveryDroneDeployKubernetesContext.trim() || undefined,
          kubectl_image: draft.deliveryDroneDeployKubectlImage.trim() || 'bitnami/kubectl:latest',
        },
        cli: {
          image: draft.deliveryDroneDeployCliImage.trim() || 'alpine:3.20',
          commands: parseListDraft(draft.deliveryDroneDeployCliCommands),
        },
      },
    };
  }
  metadata.delivery_cicd = deliveryCicd;

  return { metadata, error: null };
}

export function getOptionLabel<TValue extends string>(
  value: TValue,
  options: Array<{ value: TValue; labelKey: string }>,
  t: (key: string) => string
): string {
  const option = options.find((item) => item.value === value);
  return option ? t(option.labelKey) : value;
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseMetadataDraft(value: string): { metadata: WorkspaceMetadata; error: string | null } {
  try {
    const parsed: unknown = value.trim() ? JSON.parse(value) : {};
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { metadata: {}, error: 'metadata_object_required' };
    }
    return { metadata: parsed as WorkspaceMetadata, error: null };
  } catch {
    return { metadata: {}, error: 'metadata_invalid_json' };
  }
}

function parsePrefixDraft(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatPrefixDraft(value: unknown): string {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string').join(', ')
    : '';
}

function formatListDraft(value: unknown): string {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string').join('\n')
    : '';
}

function parseListDraft(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asNumber(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
}

function clampConfidence(value: unknown): number {
  const parsed = asNumber(value, 0);
  return Math.max(0, Math.min(1, parsed));
}

export function createBlankDeliveryService(index: number): WorkspaceDeliveryServiceConfig {
  const suffix = Math.max(1, index);
  const suffixLabel = String(suffix);
  return {
    service_id: suffix === 1 ? 'default' : `service-${suffixLabel}`,
    name: suffix === 1 ? 'Preview' : `Service ${suffixLabel}`,
    start_command: '',
    internal_port: suffix === 1 ? 3000 : 3000 + suffix - 1,
    internal_scheme: 'http',
    path_prefix: '/',
    health_path: '/',
    required: true,
    auto_open: suffix === 1,
  };
}

export function normaliseDeliveryServices(value: unknown): WorkspaceDeliveryServiceConfig[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item, index): WorkspaceDeliveryServiceConfig | null => {
      if (!item || typeof item !== 'object') {
        return null;
      }
      const record = item as Record<string, unknown>;
      const serviceId = asServiceId(record.service_id ?? record.id, index + 1);
      const startCommand = asString(record.start_command ?? record.deploy_command).trim();
      const port = Math.max(1, Math.trunc(asNumber(record.internal_port ?? record.port, 0)));
      if (!startCommand || port <= 0) {
        return null;
      }
      const scheme = asString(record.internal_scheme ?? record.scheme) || 'http';
      return {
        service_id: serviceId,
        name: asString(record.name) || serviceId,
        start_command: startCommand,
        internal_port: port,
        internal_scheme: scheme === 'https' ? 'https' : 'http',
        path_prefix: normalizePath(asString(record.path_prefix) || '/'),
        health_path: normalizePath(asString(record.health_path) || '/'),
        health_command: asString(record.health_command).trim() || undefined,
        required: asBoolean(record.required, true),
        auto_open: asBoolean(record.auto_open, true),
      };
    })
    .filter((item): item is WorkspaceDeliveryServiceConfig => item !== null);
}

function asServiceId(value: unknown, index: number): string {
  const indexLabel = String(index);
  const raw = asString(value) || `service-${indexLabel}`;
  const normalized = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return normalized || `service-${indexLabel}`;
}

function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return '/';
  }
  return trimmed.startsWith('/') || trimmed.startsWith('http://') || trimmed.startsWith('https://')
    ? trimmed
    : `/${trimmed}`;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (['1', 'true', 'yes', 'on'].includes(normalized)) {
      return true;
    }
    if (['0', 'false', 'no', 'off'].includes(normalized)) {
      return false;
    }
  }
  return fallback;
}
