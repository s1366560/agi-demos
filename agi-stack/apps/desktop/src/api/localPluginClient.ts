import type { DesktopRuntimeConfig } from '../types';

export type LocalPluginReference = Readonly<{
  bundle_id: string;
  version: string;
  digest: string;
  source: string;
}>;
export type LocalPluginScope = Readonly<{
  kind: 'project';
  tenant_id: string;
  project_id: string;
}>;
export type LocalPluginInstallation = Readonly<{
  reference: LocalPluginReference;
  scope: LocalPluginScope;
  enabled: boolean;
  authorization_status: 'approved' | 'revoked';
  activation_status: 'pending' | 'active' | 'failed' | 'inactive';
  activation_error: string | null;
  approved_permissions: readonly string[];
}>;
export type LocalPluginInspection = Readonly<{
  reference: LocalPluginReference;
  scope: LocalPluginScope;
  verified: true;
  declared_permissions: readonly string[];
  plugins: readonly Readonly<{ plugin_id: string; version: string }>[];
}>;
export type LocalPluginAction = 'enable' | 'disable' | 'revoke' | 'uninstall';
export type LocalPluginTransport = (
  path: string,
  options: {
    method?: 'GET' | 'POST';
    body?: unknown;
    signal?: AbortSignal;
  },
) => Promise<unknown>;
const ROOT = '/api/v1/local-plugins/v2/installations';

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalidResponse();
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== 'string' || !value || value.trim() !== value) throw invalidResponse();
  return value;
}
function strings(value: unknown): readonly string[] {
  if (!Array.isArray(value)) throw invalidResponse();
  const result = value.map(text);
  if (new Set(result).size !== result.length) throw invalidResponse();
  return Object.freeze(result);
}
function reference(value: unknown): LocalPluginReference {
  const item = record(value);
  const result = {
    bundle_id: text(item.bundle_id),
    version: text(item.version),
    digest: text(item.digest),
    source: text(item.source),
  };
  if (result.source !== `local-file://${result.bundle_id}/${result.version}`)
    throw invalidResponse();
  return Object.freeze(result);
}
function scope(value: unknown, expected: LocalPluginScope): LocalPluginScope {
  const item = record(value);
  if (
    item.kind !== expected.kind ||
    item.tenant_id !== expected.tenant_id ||
    item.project_id !== expected.project_id ||
    item.session_id != null
  )
    throw invalidResponse();
  return expected;
}
function sameReference(left: LocalPluginReference, right: LocalPluginReference): boolean {
  return (
    left.bundle_id === right.bundle_id &&
    left.version === right.version &&
    left.digest === right.digest &&
    left.source === right.source
  );
}
function invalidResponse(): Error {
  return new Error('local_plugin_response_invalid');
}

export function createLocalPluginClient(
  config: DesktopRuntimeConfig,
  transport: LocalPluginTransport,
) {
  if (config.mode !== 'local' || !config.tenantId || !config.projectId) {
    throw new Error('local_plugin_scope_unavailable');
  }
  const expected: LocalPluginScope = Object.freeze({
    kind: 'project',
    tenant_id: config.tenantId,
    project_id: config.projectId,
  });
  const bodyScope = {
    tenant_id: expected.tenant_id,
    project_id: expected.project_id,
  };
  async function mutation(
    action: 'import' | LocalPluginAction,
    target: LocalPluginReference,
    body: Record<string, unknown>,
    signal?: AbortSignal,
  ) {
    const path =
      action === 'import'
        ? `${ROOT}/import`
        : `${ROOT}/${encodeURIComponent(target.bundle_id)}/${action}`;
    const raw = record(
      await transport(path, {
        method: 'POST',
        body: { ...bodyScope, ...body },
        signal,
      }),
    );
    const resultReference = reference(raw.reference);
    scope(raw.scope, expected);
    const statuses = {
      import: 'installed',
      enable: 'enabled',
      disable: 'disabled',
      revoke: 'revoked',
      uninstall: 'uninstalled',
    };
    if (raw.status !== statuses[action] || !sameReference(resultReference, target))
      throw invalidResponse();
    return Object.freeze({
      reference: resultReference,
      scope: expected,
      status: statuses[action],
    });
  }
  return Object.freeze({
    async list(signal?: AbortSignal) {
      const query = new URLSearchParams(bodyScope);
      const raw = record(await transport(`${ROOT}?${query}`, { signal }));
      if (typeof raw.trust_configured !== 'boolean' || !Array.isArray(raw.installations))
        throw invalidResponse();
      const installations = raw.installations.map((value): LocalPluginInstallation => {
        const item = record(value);
        if (
          typeof item.enabled !== 'boolean' ||
          !['approved', 'revoked'].includes(String(item.authorization_status)) ||
          (item.authorization_status === 'revoked' && item.enabled) ||
          !['pending', 'active', 'failed', 'inactive'].includes(String(item.activation_status)) ||
          (item.enabled
            ? item.activation_status === 'inactive'
            : item.activation_status !== 'inactive') ||
          (item.activation_status === 'failed'
            ? typeof item.activation_error !== 'string' || !item.activation_error.trim()
            : item.activation_error !== null)
        )
          throw invalidResponse();
        return Object.freeze({
          reference: reference(item.reference),
          scope: scope(item.scope, expected),
          enabled: item.enabled,
          authorization_status: item.authorization_status as 'approved' | 'revoked',
          approved_permissions: strings(item.approved_permissions),
          activation_status: item.activation_status as LocalPluginInstallation['activation_status'],
          activation_error: item.activation_error as string | null,
        });
      });
      const keys = installations.map((item) => item.reference.bundle_id);
      if (new Set(keys).size !== keys.length) throw invalidResponse();
      return Object.freeze({
        installations: Object.freeze(installations),
        trustConfigured: raw.trust_configured,
      });
    },
    async inspect(archiveBase64: string, signal?: AbortSignal): Promise<LocalPluginInspection> {
      const raw = record(
        await transport(`${ROOT}/inspect`, {
          method: 'POST',
          body: { ...bodyScope, archive_base64: archiveBase64 },
          signal,
        }),
      );
      if (raw.verified !== true || !Array.isArray(raw.plugins)) throw invalidResponse();
      const plugins = raw.plugins.map((value) => {
        const item = record(value);
        return Object.freeze({
          plugin_id: text(item.plugin_id),
          version: text(item.version),
        });
      });
      if (!plugins.length || new Set(plugins.map((item) => item.plugin_id)).size !== plugins.length)
        throw invalidResponse();
      return Object.freeze({
        reference: reference(raw.reference),
        scope: scope(raw.scope, expected),
        verified: true,
        declared_permissions: strings(raw.declared_permissions),
        plugins: Object.freeze(plugins),
      });
    },
    async install(
      inspection: LocalPluginInspection,
      archiveBase64: string,
      approvedPermissions: readonly string[],
      signal?: AbortSignal,
    ) {
      scope(inspection.scope, expected);
      if (
        inspection.verified !== true ||
        approvedPermissions.length !== inspection.declared_permissions.length ||
        new Set(approvedPermissions).size !== approvedPermissions.length ||
        approvedPermissions.some(
          (permission) => !inspection.declared_permissions.includes(permission),
        )
      ) {
        throw new Error('local_plugin_permissions_invalid');
      }
      return mutation(
        'import',
        inspection.reference,
        {
          reference: inspection.reference,
          archive_base64: archiveBase64,
          approved_permissions: [...approvedPermissions],
        },
        signal,
      );
    },
    control(
      action: LocalPluginAction,
      installation: LocalPluginInstallation,
      signal?: AbortSignal,
    ) {
      scope(installation.scope, expected);
      if (action === 'enable' && installation.authorization_status !== 'approved') {
        throw new Error('local_plugin_authorization_required');
      }
      return mutation(
        action,
        installation.reference,
        { reference: installation.reference },
        signal,
      );
    },
  });
}
export type LocalPluginClient = ReturnType<typeof createLocalPluginClient>;

export async function pluginArchiveBase64(file: File): Promise<string> {
  if (!file.name.toLowerCase().endsWith('.mspkg') || file.size <= 0 || file.size > 64 * 1_048_576) {
    throw new Error('local_plugin_archive_invalid');
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.byteLength !== file.size) throw new Error('local_plugin_archive_invalid');
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary);
}
