import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopProjectMcpAppsHttpProjectionV2 } from './desktopProjectMcpAppsHttpProjectionV2';
import {
  MCP_APPS_METHODS_V2,
  freezeMcpAppsConfigV2,
  prepareMcpAppsInputV2,
  mcpAppsErrorV2,
  mcpAppsRecordV2,
  type McpAppsArgumentsV2,
  type McpAppsInputV2,
  type McpAppsMethodV2,
  type McpAppsResultsV2,
  type DesktopProjectMcpAppsAuthorityV2,
} from './desktopProjectMcpAppsOperationContractV2';
import { requireMcpAppsResultV2 } from './desktopProjectMcpAppsResponseContractV2';
export const DESKTOP_PROJECT_MCP_APPS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-mcp-apps-authority';
export const DESKTOP_PROJECT_MCP_APPS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-mcp-apps-authority';
export const DESKTOP_PROJECT_MCP_APPS_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopProjectMcpAppsAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopProjectMcpAppsAuthorityV2;
}
export type DesktopProjectMcpAppsOperationsV2 = {
  readonly [K in McpAppsMethodV2]: (input: McpAppsInputV2<K>) => Promise<McpAppsResultsV2[K]>;
};
export type DesktopProjectMcpAppsClientV2 = {
  readonly [K in McpAppsMethodV2]: (
    ...args: [...McpAppsArgumentsV2[K], signal?: AbortSignal]
  ) => Promise<McpAppsResultsV2[K]>;
};
export function applyDesktopProjectMcpAppsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_project_mcp_apps_authority_config_invalid',
      'invalid MCP apps authority config',
    );
  context.provide(
    DESKTOP_PROJECT_MCP_APPS_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopProjectMcpAppsHttpProjectionV2 }),
  );
}
export const desktopProjectMcpAppsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_MCP_APPS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopProjectMcpAppsAuthorityV2,
});
export function createDesktopProjectMcpAppsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectMcpAppsOperationsV2 {
  const run = async <K extends McpAppsMethodV2>(
    method: K,
    input: McpAppsInputV2<K>,
  ): Promise<McpAppsResultsV2[K]> => {
    const p = prepareMcpAppsInputV2(method, input);
    const actions = resolve();
    if (!actions) throw mcpAppsErrorV2('desktop_renderer_generation_actions_unavailable', 503);
    const lease =
      await actions.acquireServiceOperationLease<DesktopProjectMcpAppsAuthorityServiceV2>({
        service: DESKTOP_PROJECT_MCP_APPS_AUTHORITY_SERVICE_V2,
        version: DESKTOP_PROJECT_MCP_APPS_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: 'project',
          tenant_id: p.scope.tenantId,
          project_id: p.scope.projectId,
        }),
      });
    if (lease.status !== 'accepted') throw mcpAppsErrorV2(lease.reasonCode, 503);
    let active = true;
    let failed = false;
    const check = () => {
      if (!active)
        throw new RuntimeV2Error(
          'project_mcp_apps_operation_released',
          'MCP app operation released',
        );
      if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    };
    try {
      return await lease.useService(async (candidate) => {
        check();
        if (
          !mcpAppsRecordV2(candidate) ||
          Object.keys(candidate).length !== 1 ||
          typeof candidate.bindOperation !== 'function'
        )
          throw mcpAppsErrorV2('project_mcp_apps_service_invalid', 502);
        const authority = candidate.bindOperation(p.config);
        if (
          !mcpAppsRecordV2(authority) ||
          Object.keys(authority).length !== 1 ||
          typeof authority.execute !== 'function'
        )
          throw mcpAppsErrorV2('project_mcp_apps_service_invalid', 502);
        check();
        const raw = await authority.execute(method, p);
        check();
        return requireMcpAppsResultV2(method, raw, p);
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
  return createMcpAppsOperationsTableV2(run);
}
export function createMcpAppsOperationsTableV2(
  run: <K extends McpAppsMethodV2>(
    method: K,
    input: McpAppsInputV2<K>,
  ) => Promise<McpAppsResultsV2[K]>,
): DesktopProjectMcpAppsOperationsV2 {
  return Object.freeze(
    Object.fromEntries(
      MCP_APPS_METHODS_V2.map((method) => [method, (input: McpAppsInputV2) => run(method, input)]),
    ),
  ) as DesktopProjectMcpAppsOperationsV2;
}
export function createDesktopProjectMcpAppsClientV2(
  operations: DesktopProjectMcpAppsOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopProjectMcpAppsClientV2 {
  const runtime = freezeMcpAppsConfigV2(config);
  const scope = Object.freeze({
    authority: runtime.mode,
    tenantId: runtime.tenantId,
    projectId: runtime.projectId,
  });
  const call = <K extends McpAppsMethodV2>(
    method: K,
    args: McpAppsArgumentsV2[K],
    signal?: AbortSignal,
  ) => operations[method]({ config: runtime, scope, args, signal });
  const client: DesktopProjectMcpAppsClientV2 = {
    listMCPApps: (projectId, signal) => call('listMCPApps', [projectId], signal),
    callMCPAppTool: (id, tool, args, key, signal) =>
      call('callMCPAppTool', [id, tool, args, key], signal),
    callMCPToolByServerId: (id, tool, args, key, signal) =>
      call('callMCPToolByServerId', [id, tool, args, key], signal),
    callMCPAppToolDirect: (projectId, server, tool, args, key, signal) =>
      call('callMCPAppToolDirect', [projectId, server, tool, args, key], signal),
    readMCPAppResource: (projectId, uri, server, signal) =>
      call('readMCPAppResource', [projectId, uri, server ?? null], signal),
    listMCPAppResources: (projectId, server, signal) =>
      call('listMCPAppResources', [projectId, server ?? null], signal),
  };
  return Object.freeze(client);
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_PROJECT_MCP_APPS_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_project_mcp_apps_authority_catalog_missing',
      'MCP apps authority absent from catalog',
    );
  return entry.contract_digest;
}
