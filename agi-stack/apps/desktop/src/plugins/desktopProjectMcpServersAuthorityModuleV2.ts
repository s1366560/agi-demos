import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopProjectMcpServersHttpProjectionV2 } from './desktopProjectMcpServersHttpProjectionV2';
import {
  MCP_SERVERS_METHODS_V2,
  freezeMcpServersConfigV2,
  prepareMcpServersInputV2,
  mcpServersErrorV2,
  mcpServersRecordV2,
  type McpServersArgumentsV2,
  type McpServersInputV2,
  type McpServersMethodV2,
  type McpServersResultsV2,
  type DesktopProjectMcpServersAuthorityV2,
} from './desktopProjectMcpServersOperationContractV2';
import { requireMcpServersResultV2 } from './desktopProjectMcpServersResponseContractV2';
export const DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-mcp-servers-authority';
export const DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-mcp-servers-authority';
export const DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopProjectMcpServersAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopProjectMcpServersAuthorityV2;
}
export type DesktopProjectMcpServersOperationsV2 = {
  readonly [K in McpServersMethodV2]: (
    input: McpServersInputV2<K>,
  ) => Promise<McpServersResultsV2[K]>;
};
export type DesktopProjectMcpServersClientV2 = {
  readonly [K in McpServersMethodV2]: (
    ...args: [...McpServersArgumentsV2[K], signal?: AbortSignal]
  ) => Promise<McpServersResultsV2[K]>;
};
export function applyDesktopProjectMcpServersAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_project_mcp_serverss_authority_config_invalid',
      'invalid MCP servers authority config',
    );
  context.provide(
    DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopProjectMcpServersHttpProjectionV2 }),
  );
}
export const desktopProjectMcpServersAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopProjectMcpServersAuthorityV2,
});
export function createDesktopProjectMcpServersOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectMcpServersOperationsV2 {
  const run = async <K extends McpServersMethodV2>(
    method: K,
    input: McpServersInputV2<K>,
  ): Promise<McpServersResultsV2[K]> => {
    const p = prepareMcpServersInputV2(method, input);
    const actions = resolve();
    if (!actions) throw mcpServersErrorV2('desktop_renderer_generation_actions_unavailable', 503);
    const lease =
      await actions.acquireServiceOperationLease<DesktopProjectMcpServersAuthorityServiceV2>({
        service: DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_SERVICE_V2,
        version: DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: 'project',
          tenant_id: p.scope.tenantId,
          project_id: p.scope.projectId,
        }),
      });
    if (lease.status !== 'accepted') throw mcpServersErrorV2(lease.reasonCode, 503);
    let active = true;
    let failed = false;
    const check = () => {
      if (!active)
        throw new RuntimeV2Error(
          'project_mcp_servers_operation_released',
          'MCP server operation released',
        );
      if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    };
    try {
      return await lease.useService(async (candidate) => {
        check();
        if (
          !mcpServersRecordV2(candidate) ||
          Object.keys(candidate).length !== 1 ||
          typeof candidate.bindOperation !== 'function'
        )
          throw mcpServersErrorV2('project_mcp_servers_service_invalid', 502);
        const authority = candidate.bindOperation(p.config);
        if (
          !mcpServersRecordV2(authority) ||
          Object.keys(authority).length !== 1 ||
          typeof authority.execute !== 'function'
        )
          throw mcpServersErrorV2('project_mcp_servers_service_invalid', 502);
        check();
        const raw = await authority.execute(method, p);
        check();
        return requireMcpServersResultV2(method, raw, p);
      });
    } catch (error) {
      failed = true;
      throw error;
    } finally {
      active = false;
      try {
        await lease.release();
      } catch (error) {
        if (!failed) throw error;
      }
    }
  };
  return createMcpServersOperationsTableV2(run);
}
export function createMcpServersOperationsTableV2(
  run: <K extends McpServersMethodV2>(
    method: K,
    input: McpServersInputV2<K>,
  ) => Promise<McpServersResultsV2[K]>,
): DesktopProjectMcpServersOperationsV2 {
  return Object.freeze(
    Object.fromEntries(
      MCP_SERVERS_METHODS_V2.map((method) => [
        method,
        (input: McpServersInputV2) => run(method, input),
      ]),
    ),
  ) as DesktopProjectMcpServersOperationsV2;
}
export function createDesktopProjectMcpServersClientV2(
  operations: DesktopProjectMcpServersOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopProjectMcpServersClientV2 {
  const runtime = freezeMcpServersConfigV2(config);
  const scope = Object.freeze({
    authority: runtime.mode,
    tenantId: runtime.tenantId,
    projectId: runtime.projectId,
  });
  const call = <K extends McpServersMethodV2>(
    method: K,
    args: McpServersArgumentsV2[K],
    signal?: AbortSignal,
  ) => operations[method]({ config: runtime, scope, args, signal });
  const client: DesktopProjectMcpServersClientV2 = {
    listMCPServers: (projectId, signal) => call('listMCPServers', [projectId], signal),
    provisionMCPServerCredential: (input, signal) =>
      call('provisionMCPServerCredential', [input], signal),
    createMCPServer: (input, signal) => call('createMCPServer', [input], signal),
    updateMCPServer: (id, input, signal) => call('updateMCPServer', [id, input], signal),
    setMCPServerEnabled: (id, input, signal) => call('setMCPServerEnabled', [id, input], signal),
    deleteMCPServer: (id, input, signal) => call('deleteMCPServer', [id, input], signal),
    testMCPServer: (id, signal) => call('testMCPServer', [id], signal),
  };
  return Object.freeze(client);
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_project_mcp_serverss_authority_catalog_missing',
      'MCP servers authority absent from catalog',
    );
  return entry.contract_digest;
}
