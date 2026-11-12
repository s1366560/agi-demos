import { httpClient } from '@/services/client/httpClient';

const BASE_URL = '/platform-plugins/v2/optional-business';

export interface OptionalBusinessPackageFileV2 {
  plugin_id: string;
  version: string;
  digest: string;
  wasm_base64: string;
  contribution: Record<string, unknown>;
  ui_files?: Record<string, string>;
  approved_permissions: string[];
}

export interface OptionalBusinessProjectionV2 {
  plugin_id: string;
  version: string;
  package_recorded: boolean;
  desired_enabled: boolean;
  runtime_phase: string;
  actual_digest: string | null;
  failure: string | null;
  retention: string;
}

export interface OptionalBusinessUiV2 {
  digest: string;
  bytes_base64: string;
  source: string;
  module_ref: string;
}

interface Scope {
  tenantId: string;
  projectId: string;
}

const scopeBody = ({ tenantId, projectId }: Scope) => ({
  tenant_id: tenantId,
  project_id: projectId,
});

export const optionalBusinessService = {
  projection(pluginId: string, scope: Scope): Promise<OptionalBusinessProjectionV2> {
    return httpClient.get(`${BASE_URL}/${encodeURIComponent(pluginId)}`, {
      params: scopeBody(scope),
    });
  },
  install(
    scope: Scope,
    file: OptionalBusinessPackageFileV2,
    onProgress?: (percent: number) => void
  ): Promise<{ status: string }> {
    return httpClient.post(
      `${BASE_URL}/install`,
      {
        ...scopeBody(scope),
        ...file,
        ui_files: file.ui_files ?? {},
      },
      {
        onUploadProgress: (event) => {
          if (!onProgress || !event.total) return;
          onProgress(Math.round((event.loaded / event.total) * 100));
        },
      }
    );
  },
  enable(pluginId: string, scope: Scope): Promise<{ status: string }> {
    return httpClient.post(`${BASE_URL}/${encodeURIComponent(pluginId)}/enable`, scopeBody(scope));
  },
  disable(pluginId: string, scope: Scope): Promise<{ status: string }> {
    return httpClient.post(`${BASE_URL}/${encodeURIComponent(pluginId)}/disable`, scopeBody(scope));
  },
  rollback(pluginId: string, scope: Scope): Promise<{ status: string }> {
    return httpClient.post(
      `${BASE_URL}/${encodeURIComponent(pluginId)}/rollback`,
      scopeBody(scope)
    );
  },
  uninstall(pluginId: string, scope: Scope): Promise<{ status: string }> {
    return httpClient.post(
      `${BASE_URL}/${encodeURIComponent(pluginId)}/uninstall`,
      scopeBody(scope)
    );
  },
  ui(pluginId: string, scope: Scope): Promise<OptionalBusinessUiV2> {
    return httpClient.get(`${BASE_URL}/${encodeURIComponent(pluginId)}/ui`, {
      params: { ...scopeBody(scope), target: 'web' },
    });
  },
};
