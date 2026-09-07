import type { TenantAdminRole } from "./tenantAdminHttp";
import type {
  TenantManagementAuthoritySnapshot,
  TenantManagementRequestOptions,
  TenantManagementScope,
} from "./tenantManagementHttp";

export const TENANT_ACP_ROUTE_ID = "tenant-tenant-acp" as const;
export const TENANT_ACP_LOCAL_REASON =
  "local_external_acp_not_applicable" as const;
export type TenantAcpTransport = "stdio" | "websocket";
export type TenantAcpAgent = Readonly<{
  id: string;
  agentKey: string;
  name: string;
  transport: TenantAcpTransport;
  command: string | null;
  url: string | null;
  enabled: boolean;
  available: boolean;
  missingEnv: readonly string[];
}>;
export type TenantAcpRunnerPool = Readonly<{
  id: string;
  poolKey: string;
  name: string;
  enabled: boolean;
  runnerCount: number;
  readyRunnerCount: number;
}>;
export type TenantAcpStatus = Readonly<{
  enabled: boolean;
  websocketEnabled: boolean;
  httpBaseUrl: string;
  agentCount: number;
  availableCount: number;
  activeSessionCount: number;
  agents: readonly TenantAcpAgent[];
  sessions: readonly Readonly<Record<string, unknown>>[];
}>;
export type TenantAcpAgentInput = Readonly<{
  agentKey?: string;
  name: string;
  transport: TenantAcpTransport;
  command?: string | null;
  args?: readonly string[];
  url?: string | null;
  env?: Readonly<Record<string, unknown>>;
  headers?: Readonly<Record<string, unknown>>;
  runnerPoolKey?: string | null;
  requiredLabels?: Readonly<Record<string, string>>;
  cwdPolicy?: Readonly<Record<string, unknown>>;
  enabled?: boolean;
}>;
export type TenantAcpTestInput = Readonly<{
  cwd: string;
  projectId?: string;
  prompt: string;
  timeoutSeconds?: number;
}>;
export type TenantAcpData = Readonly<{
  membershipRole: TenantAdminRole;
  status: TenantAcpStatus;
  runnerPools: readonly TenantAcpRunnerPool[];
}>;
export type TenantAcpSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantAcpData
> &
  TenantAcpData;
export type TenantAcpClient = Readonly<{
  load(
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ): Promise<TenantAcpSnapshot>;
  createAgent(
    scope: TenantManagementScope,
    input: TenantAcpAgentInput & Readonly<{ agentKey: string }>,
    options?: TenantManagementRequestOptions,
  ): Promise<TenantAcpAgent>;
  updateAgent(
    scope: TenantManagementScope,
    agentKey: string,
    input: TenantAcpAgentInput,
    options?: TenantManagementRequestOptions,
  ): Promise<TenantAcpAgent>;
  deleteAgent(
    scope: TenantManagementScope,
    agentKey: string,
    options?: TenantManagementRequestOptions,
  ): Promise<void>;
  testAgent(
    scope: TenantManagementScope,
    agentKey: string,
    input: TenantAcpTestInput,
    options?: TenantManagementRequestOptions,
  ): Promise<Readonly<Record<string, unknown>>>;
}>;
