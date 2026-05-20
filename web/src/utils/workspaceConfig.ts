import type {
  Workspace,
  WorkspaceCollaborationMode,
  WorkspaceCreateRequest,
  WorkspaceDeliveryCicdConfig,
  WorkspaceDeliveryDroneDeployConfig,
  WorkspaceDeliveryDroneConfig,
  WorkspaceDeliveryDroneEnvironmentConfig,
  WorkspaceDroneDeployMode,
  WorkspaceSourceControlConfig,
  WorkspaceSourceControlProvider,
  WorkspaceType,
  WorkspaceUseCase,
} from '@/types/workspace';

export const DEFAULT_WORKSPACE_USE_CASE: WorkspaceUseCase = 'general';
export const DEFAULT_COLLABORATION_MODE: WorkspaceCollaborationMode = 'multi_agent_shared';
export const MIN_WORKSPACE_DESCRIPTION_LENGTH = 12;
export const DEFAULT_SOURCE_CONTROL_PROVIDER: WorkspaceSourceControlProvider = 'github';
export const DEFAULT_SOURCE_CONTROL_REPO_OWNER = 'memstack';
export const DEFAULT_SOURCE_CONTROL_BRANCH = 'main';
export const DEFAULT_GITHUB_SERVER_URL = 'https://github.com';
export const DEFAULT_GITLAB_SERVER_URL = 'https://gitlab.com';
export const DEFAULT_GITHUB_TOKEN_ENV = 'GITHUB_TOKEN';
export const DEFAULT_GITLAB_TOKEN_ENV = 'GITLAB_TOKEN';
export const DEFAULT_DRONE_REPO_OWNER = 'memstack';
export const DEFAULT_DRONE_BRANCH = 'main';
export const DEFAULT_DRONE_SERVER_URL_ENV = 'DRONE_SERVER_URL';
export const DEFAULT_DRONE_TOKEN_ENV = 'DRONE_TOKEN';
export const DEFAULT_DRONE_POLL_INTERVAL_SECONDS = 5;
export const DEFAULT_DRONE_TIMEOUT_SECONDS = 600;
export const DEFAULT_DRONE_SERVER_PORT = 8080;
export const DEFAULT_DRONE_SERVER_HOST = 'localhost:8080';
export const DEFAULT_DRONE_SERVER_PROTO = 'http';
export const DEFAULT_DRONE_RPC_SECRET_ENV = 'DRONE_RPC_SECRET';
export const DEFAULT_DRONE_USER_CREATE = 'username:memstack,admin:true';
export const DEFAULT_DRONE_GITHUB_SERVER = DEFAULT_GITHUB_SERVER_URL;
export const DEFAULT_DRONE_GITHUB_CLIENT_ID_ENV = 'DRONE_GITHUB_CLIENT_ID';
export const DEFAULT_DRONE_GITHUB_CLIENT_SECRET_ENV = 'DRONE_GITHUB_CLIENT_SECRET';
export const DEFAULT_DRONE_GITLAB_SERVER = DEFAULT_GITLAB_SERVER_URL;
export const DEFAULT_DRONE_GITLAB_CLIENT_ID_ENV = 'DRONE_GITLAB_CLIENT_ID';
export const DEFAULT_DRONE_GITLAB_CLIENT_SECRET_ENV = 'DRONE_GITLAB_CLIENT_SECRET';
export const DEFAULT_DRONE_RUNNER_PORT = 3001;
export const DEFAULT_DRONE_RUNNER_CAPACITY = 2;
export const DEFAULT_DRONE_RUNNER_NAME = 'memstack-drone-runner';
export const DEFAULT_DRONE_RUNNER_RPC_PROTO = 'http';
export const DEFAULT_DRONE_RUNNER_RPC_HOST = 'drone-server';
export const DEFAULT_DRONE_DEPLOY_MODE: WorkspaceDroneDeployMode = 'cli';
export const DEFAULT_DRONE_DEPLOY_STAGE = 'deploy';
export const DEFAULT_DRONE_DEPLOY_CLI_IMAGE = 'alpine:3.20';
export const DEFAULT_DRONE_DEPLOY_DOCKER_CONTEXT = '.';
export const DEFAULT_DRONE_DEPLOY_DOCKERFILE = 'Dockerfile';
export const DEFAULT_DRONE_DEPLOY_DOCKER_TAGS = ['latest'];
export const DEFAULT_DRONE_DEPLOY_DOCKER_STRATEGY = 'local_build';
export const DEFAULT_DRONE_DEPLOY_DOCKER_ALLOW_DAEMON_REGISTRY_PULL = false;
export const DEFAULT_DRONE_DEPLOY_DOCKER_HOST_PORT = 18080;
export const DEFAULT_DRONE_DEPLOY_DOCKER_RESERVED_HOST_PORTS = [
  3000, 3001, 5001, 5432, 6379, 7474, 7687, 8000, 8080,
];
export const DEFAULT_DRONE_DEPLOY_KUBERNETES_NAMESPACE = 'default';
export const DEFAULT_DRONE_DEPLOY_KUBERNETES_MANIFEST_PATHS = ['k8s/*.yaml'];
export const DEFAULT_DRONE_DEPLOY_KUBECONFIG_SECRET = 'kubeconfig';
export const DEFAULT_DRONE_DEPLOY_KUBECTL_IMAGE = 'bitnami/kubectl:latest';

export function workspaceTypeForUseCase(useCase: WorkspaceUseCase): WorkspaceType {
  if (useCase === 'programming') return 'software_development';
  if (useCase === 'research') return 'research';
  if (useCase === 'operations') return 'operations';
  return 'general';
}

export function isWorkspaceUseCase(value: unknown): value is WorkspaceUseCase {
  return (
    value === 'programming' ||
    value === 'conversation' ||
    value === 'research' ||
    value === 'operations' ||
    value === 'general'
  );
}

export function isWorkspaceCollaborationMode(value: unknown): value is WorkspaceCollaborationMode {
  return (
    value === 'single_agent' ||
    value === 'multi_agent_shared' ||
    value === 'multi_agent_isolated' ||
    value === 'autonomous'
  );
}

export function isWorkspaceSourceControlProvider(
  value: unknown
): value is WorkspaceSourceControlProvider {
  return value === 'github' || value === 'gitlab';
}

export function isWorkspaceDroneDeployMode(value: unknown): value is WorkspaceDroneDeployMode {
  return value === 'docker' || value === 'kubernetes' || value === 'cli';
}

export function getWorkspaceUseCase(workspace: Workspace): WorkspaceUseCase {
  const direct = workspace.metadata?.workspace_use_case;
  if (isWorkspaceUseCase(direct)) {
    return direct;
  }
  const type = workspace.metadata?.workspace_type;
  if (type === 'software_development') {
    return 'programming';
  }
  if (type === 'research' || type === 'operations' || type === 'general') {
    return type;
  }
  return DEFAULT_WORKSPACE_USE_CASE;
}

export function getWorkspaceCollaborationMode(workspace: Workspace): WorkspaceCollaborationMode {
  const direct = workspace.metadata?.collaboration_mode;
  if (isWorkspaceCollaborationMode(direct)) {
    return direct;
  }
  const legacy = workspace.metadata?.agent_conversation_mode;
  if (isWorkspaceCollaborationMode(legacy)) {
    return legacy;
  }
  return DEFAULT_COLLABORATION_MODE;
}

export function normaliseSandboxCodeRoot(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('/workspace/')) return trimmed.replace(/\/+$/, '');
  if (!trimmed.startsWith('/')) return `/workspace/${trimmed.replace(/^\/+/, '')}`;
  return trimmed.replace(/\/+$/, '');
}

export function isIsolatedSandboxCodeRoot(value: string): boolean {
  const normalised = normaliseSandboxCodeRoot(value);
  return normalised.startsWith('/workspace/') && normalised.length > '/workspace/'.length;
}

export function getSandboxCodeRoot(workspace: Workspace): string | null {
  const direct = workspace.metadata?.sandbox_code_root;
  if (typeof direct === 'string' && direct.trim()) return direct.trim();
  const codeContext = workspace.metadata?.code_context;
  if (
    codeContext &&
    typeof codeContext === 'object' &&
    'sandbox_code_root' in codeContext &&
    typeof codeContext.sandbox_code_root === 'string' &&
    codeContext.sandbox_code_root.trim()
  ) {
    return codeContext.sandbox_code_root.trim();
  }
  return null;
}

export function workspaceNameSlug(name: string): string {
  return (
    name
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'workspace'
  );
}

export function sourceControlDefaultsForProvider(provider: WorkspaceSourceControlProvider): {
  serverUrl: string;
  authTokenEnv: string;
} {
  if (provider === 'gitlab') {
    return {
      serverUrl: DEFAULT_GITLAB_SERVER_URL,
      authTokenEnv: DEFAULT_GITLAB_TOKEN_ENV,
    };
  }
  return {
    serverUrl: DEFAULT_GITHUB_SERVER_URL,
    authTokenEnv: DEFAULT_GITHUB_TOKEN_ENV,
  };
}

export function buildSourceCloneUrl(
  provider: WorkspaceSourceControlProvider,
  serverUrl: string,
  repo: string
): string {
  const defaults = sourceControlDefaultsForProvider(provider);
  const baseUrl = (serverUrl.trim() || defaults.serverUrl).replace(/\/+$/, '');
  const repoPath =
    repo.trim().replace(/^\/+|\/+$/g, '') || `${DEFAULT_SOURCE_CONTROL_REPO_OWNER}/workspace`;
  return `${baseUrl}/${repoPath}${repoPath.endsWith('.git') ? '' : '.git'}`;
}

export function buildDefaultSourceControlConfig(
  name: string,
  provider: WorkspaceSourceControlProvider = DEFAULT_SOURCE_CONTROL_PROVIDER
): WorkspaceSourceControlConfig {
  const defaults = sourceControlDefaultsForProvider(provider);
  const repo = `${DEFAULT_SOURCE_CONTROL_REPO_OWNER}/${workspaceNameSlug(name)}`;
  return {
    provider,
    repo,
    default_branch: DEFAULT_SOURCE_CONTROL_BRANCH,
    server_url: defaults.serverUrl,
    clone_url: buildSourceCloneUrl(provider, defaults.serverUrl, repo),
    auth_token_env: defaults.authTokenEnv,
  };
}

export function normaliseWorkspaceSourceControlConfig(
  sourceControl: WorkspaceSourceControlConfig | undefined,
  name: string
): WorkspaceSourceControlConfig {
  const sourceProvider = sourceControl?.provider;
  const provider = isWorkspaceSourceControlProvider(sourceProvider)
    ? sourceProvider
    : DEFAULT_SOURCE_CONTROL_PROVIDER;
  const defaults = buildDefaultSourceControlConfig(name, provider);
  const repo =
    sourceControl?.repo?.trim() ||
    defaults.repo ||
    `${DEFAULT_SOURCE_CONTROL_REPO_OWNER}/workspace`;
  const serverUrl =
    sourceControl?.server_url?.trim() || defaults.server_url || DEFAULT_GITHUB_SERVER_URL;
  return {
    provider,
    repo,
    default_branch: sourceControl?.default_branch?.trim() || defaults.default_branch,
    server_url: serverUrl,
    clone_url: sourceControl?.clone_url?.trim() || buildSourceCloneUrl(provider, serverUrl, repo),
    auth_token_env: sourceControl?.auth_token_env?.trim() || defaults.auth_token_env,
  };
}

export function buildDefaultDroneEnvironmentConfig(
  sourceControl?: WorkspaceSourceControlConfig
): WorkspaceDeliveryDroneEnvironmentConfig {
  const sourceProviderValue = sourceControl?.provider;
  const sourceProvider = isWorkspaceSourceControlProvider(sourceProviderValue)
    ? sourceProviderValue
    : DEFAULT_SOURCE_CONTROL_PROVIDER;
  const sourceServerUrl = sourceControl?.server_url?.trim();
  return {
    api: {
      server_url_env: DEFAULT_DRONE_SERVER_URL_ENV,
      token_env: DEFAULT_DRONE_TOKEN_ENV,
    },
    server: {
      server_port: DEFAULT_DRONE_SERVER_PORT,
      server_host: DEFAULT_DRONE_SERVER_HOST,
      server_proto: DEFAULT_DRONE_SERVER_PROTO,
      rpc_secret_env: DEFAULT_DRONE_RPC_SECRET_ENV,
      user_create: DEFAULT_DRONE_USER_CREATE,
      source_provider: sourceProvider,
      github_server:
        sourceProvider === 'github' && sourceServerUrl
          ? sourceServerUrl
          : DEFAULT_DRONE_GITHUB_SERVER,
      github_client_id_env: DEFAULT_DRONE_GITHUB_CLIENT_ID_ENV,
      github_client_secret_env: DEFAULT_DRONE_GITHUB_CLIENT_SECRET_ENV,
      gitlab_server:
        sourceProvider === 'gitlab' && sourceServerUrl
          ? sourceServerUrl
          : DEFAULT_DRONE_GITLAB_SERVER,
      gitlab_client_id_env: DEFAULT_DRONE_GITLAB_CLIENT_ID_ENV,
      gitlab_client_secret_env: DEFAULT_DRONE_GITLAB_CLIENT_SECRET_ENV,
      git_always_auth: false,
    },
    runner: {
      runner_port: DEFAULT_DRONE_RUNNER_PORT,
      runner_capacity: DEFAULT_DRONE_RUNNER_CAPACITY,
      runner_name: DEFAULT_DRONE_RUNNER_NAME,
      rpc_proto: DEFAULT_DRONE_RUNNER_RPC_PROTO,
      rpc_host: DEFAULT_DRONE_RUNNER_RPC_HOST,
      rpc_secret_env: DEFAULT_DRONE_RPC_SECRET_ENV,
    },
  };
}

export function buildDefaultDroneDeployConfig(): WorkspaceDeliveryDroneDeployConfig {
  return {
    enabled: false,
    mode: DEFAULT_DRONE_DEPLOY_MODE,
    stage: DEFAULT_DRONE_DEPLOY_STAGE,
    required: true,
    cli: {
      image: DEFAULT_DRONE_DEPLOY_CLI_IMAGE,
      commands: [],
    },
    docker: {
      trusted: true,
      context: DEFAULT_DRONE_DEPLOY_DOCKER_CONTEXT,
      dockerfile: DEFAULT_DRONE_DEPLOY_DOCKERFILE,
      tags: [...DEFAULT_DRONE_DEPLOY_DOCKER_TAGS],
      deploy_strategy: DEFAULT_DRONE_DEPLOY_DOCKER_STRATEGY,
      deploy_host_port: DEFAULT_DRONE_DEPLOY_DOCKER_HOST_PORT,
      reserved_host_ports: [...DEFAULT_DRONE_DEPLOY_DOCKER_RESERVED_HOST_PORTS],
      allow_daemon_registry_pull: DEFAULT_DRONE_DEPLOY_DOCKER_ALLOW_DAEMON_REGISTRY_PULL,
    },
    kubernetes: {
      namespace: DEFAULT_DRONE_DEPLOY_KUBERNETES_NAMESPACE,
      manifest_paths: [...DEFAULT_DRONE_DEPLOY_KUBERNETES_MANIFEST_PATHS],
      kubeconfig_secret: DEFAULT_DRONE_DEPLOY_KUBECONFIG_SECRET,
      kubectl_image: DEFAULT_DRONE_DEPLOY_KUBECTL_IMAGE,
    },
  };
}

function mergeSourceControlConfig(
  base: WorkspaceSourceControlConfig | undefined,
  override: WorkspaceSourceControlConfig | undefined
): WorkspaceSourceControlConfig | undefined {
  if (!base && !override) return undefined;
  return {
    ...(base ?? {}),
    ...(override ?? {}),
  };
}

function mergeDroneEnvironmentConfig(
  base: WorkspaceDeliveryDroneEnvironmentConfig | undefined,
  override: WorkspaceDeliveryDroneEnvironmentConfig | undefined
): WorkspaceDeliveryDroneEnvironmentConfig | undefined {
  if (!base && !override) return undefined;
  return {
    api: {
      ...(base?.api ?? {}),
      ...(override?.api ?? {}),
    },
    server: {
      ...(base?.server ?? {}),
      ...(override?.server ?? {}),
    },
    runner: {
      ...(base?.runner ?? {}),
      ...(override?.runner ?? {}),
    },
  };
}

function mergeDroneDeployConfig(
  base: WorkspaceDeliveryDroneDeployConfig | undefined,
  override: WorkspaceDeliveryDroneDeployConfig | undefined
): WorkspaceDeliveryDroneDeployConfig | undefined {
  if (!base && !override) return undefined;
  return {
    ...(base ?? {}),
    ...(override ?? {}),
    docker: {
      ...(base?.docker ?? {}),
      ...(override?.docker ?? {}),
    },
    kubernetes: {
      ...(base?.kubernetes ?? {}),
      ...(override?.kubernetes ?? {}),
    },
    cli: {
      ...(base?.cli ?? {}),
      ...(override?.cli ?? {}),
    },
  };
}

export function mergeDroneConfig(
  base: WorkspaceDeliveryDroneConfig | undefined,
  override: WorkspaceDeliveryDroneConfig | undefined
): WorkspaceDeliveryDroneConfig | undefined {
  if (!base && !override) return undefined;
  const sourceControl = mergeSourceControlConfig(base?.source_control, override?.source_control);
  return {
    ...(base ?? {}),
    ...(override ?? {}),
    ...(sourceControl ? { source_control: sourceControl } : {}),
    environment: mergeDroneEnvironmentConfig(base?.environment, override?.environment),
    deploy: mergeDroneDeployConfig(base?.deploy, override?.deploy),
  };
}

export function buildDefaultDroneDeliveryConfig(
  name: string,
  codeRoot: string,
  sourceControl?: WorkspaceSourceControlConfig
): WorkspaceDeliveryCicdConfig {
  const normalizedSourceControl = normaliseWorkspaceSourceControlConfig(sourceControl, name);
  return {
    provider: 'drone',
    code_root: codeRoot,
    agent_managed: false,
    contract_source: 'workspace_defaults',
    contract_confidence: 1,
    timeout_seconds: DEFAULT_DRONE_TIMEOUT_SECONDS,
    auto_deploy: false,
    drone: {
      repo: normalizedSourceControl.repo,
      branch: normalizedSourceControl.default_branch,
      server_url_env: DEFAULT_DRONE_SERVER_URL_ENV,
      token_env: DEFAULT_DRONE_TOKEN_ENV,
      poll_interval_seconds: DEFAULT_DRONE_POLL_INTERVAL_SECONDS,
      source_control: normalizedSourceControl,
      environment: buildDefaultDroneEnvironmentConfig(normalizedSourceControl),
      deploy: buildDefaultDroneDeployConfig(),
    },
  };
}

export function buildWorkspaceCreateRequest({
  name,
  description,
  useCase,
  collaborationMode,
  sandboxCodeRoot,
  sourceControl,
  droneConfig,
}: {
  name: string;
  description: string;
  useCase: WorkspaceUseCase;
  collaborationMode: WorkspaceCollaborationMode;
  sandboxCodeRoot: string;
  sourceControl?: WorkspaceSourceControlConfig;
  droneConfig?: WorkspaceDeliveryDroneConfig;
}): WorkspaceCreateRequest {
  const workspaceType = workspaceTypeForUseCase(useCase);
  const workspaceName = name.trim();
  const normalizedCodeRoot = normaliseSandboxCodeRoot(sandboxCodeRoot);
  const sourceControlConfig =
    useCase === 'programming'
      ? normaliseWorkspaceSourceControlConfig(sourceControl, workspaceName)
      : undefined;
  const deliveryCicd =
    useCase === 'programming'
      ? buildDefaultDroneDeliveryConfig(workspaceName, normalizedCodeRoot, sourceControlConfig)
      : undefined;
  if (deliveryCicd) {
    deliveryCicd.drone = mergeDroneConfig(deliveryCicd.drone, droneConfig);
  }

  return {
    name: workspaceName,
    description: description.trim(),
    use_case: useCase,
    collaboration_mode: collaborationMode,
    ...(useCase === 'programming' ? { sandbox_code_root: normalizedCodeRoot } : {}),
    ...(sourceControlConfig ? { source_control: sourceControlConfig } : {}),
    metadata: {
      workspace_use_case: useCase,
      workspace_type: workspaceType,
      collaboration_mode: collaborationMode,
      agent_conversation_mode: collaborationMode,
      autonomy_profile: { workspace_type: workspaceType },
      ...(useCase === 'programming'
        ? {
            sandbox_code_root: normalizedCodeRoot,
            code_context: { sandbox_code_root: normalizedCodeRoot },
            source_control: sourceControlConfig,
            ...(deliveryCicd ? { delivery_cicd: deliveryCicd } : {}),
          }
        : {}),
    },
  };
}
