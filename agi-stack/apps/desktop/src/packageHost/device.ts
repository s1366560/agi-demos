import type { LocalPluginReference } from '../api/localPluginClient';
import type { DevicePageCall } from '../../../../packages/plugin-slots/src/richPage';

type Installed = {
  reference: LocalPluginReference;
  tools: string[];
  grant_id: string;
  grant_status: string;
  last_invoked_at: string | null;
  last_error: string | null;
  generation_id: string;
};
export type Catalog = {
  context_token: string;
  machine_id: string;
  device_fingerprint: string;
  generation_id: string;
  trust_configured: boolean;
  can_manage: boolean;
  installations: Installed[];
};

export function deviceRequest<T>(
  tenant: string,
  project: string,
  pluginId: string | undefined,
  operation: Record<string, unknown>,
  contextToken?: string,
): Promise<T> {
  const bridge = window.__MEMSTACK_DESKTOP__;
  if (bridge?.runtime !== 'electron' || !bridge.core?.invoke)
    throw new Error('device_plugin_native_required');
  return bridge.core.invoke<T>('device_plugin_manage_v2', {
    input: {
      tenant_id: tenant,
      project_id: project,
      ...(pluginId && { plugin_id: pluginId }),
      context_token: contextToken,
      operation,
    },
  });
}

export function devicePageCall(tenant: string, project: string): DevicePageCall {
  return async ({ pluginId, digest, tool, payload, signal }) => {
    signal.throwIfAborted();
    const catalog = await deviceRequest<Catalog>(tenant, project, pluginId, {
      action: 'list',
    });
    const item = catalog.installations.find(
      ({ reference }) =>
        reference.bundle_id === pluginId &&
        reference.digest.replace(/^sha256:/u, '') === digest.replace(/^sha256:/u, ''),
    );
    if (!item) throw new Error('device_plugin_installation_required');
    if (item.grant_status !== 'approved')
      throw new Error('device_plugin_grant_' + item.grant_status);
    if (catalog.generation_id !== item.generation_id)
      throw new Error('device_plugin_generation_changed');
    if (!item.tools.includes(tool)) throw new Error('device_plugin_tool_missing');
    signal.throwIfAborted();
    const output = await deviceRequest(
      tenant,
      project,
      pluginId,
      {
        action: 'invoke',
        reference: item.reference,
        grant_id: item.grant_id,
        tool,
        input: payload,
      },
      catalog.context_token,
    );
    signal.throwIfAborted();
    return output;
  };
}
