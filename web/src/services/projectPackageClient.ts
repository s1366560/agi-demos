import type { kernelHttpClient } from './client/kernelHttpClient';

export type PackageClient = Pick<typeof kernelHttpClient, 'get' | 'post'>;

const BASE_URL = '/platform-plugins/v2/optional-business';

export interface OptionalBusinessPackageFileV2 {
  plugin_id: string;
  kind?: 'business' | 'adapter' | null;
  targets?: readonly string[];
  version: string;
  digest: string;
  permissions: string[];
  requires?: readonly { alias: string; service: string; version: string }[];
  provides?: readonly { service: string; version: string }[];
  archive_base64: string;
}

export interface OptionalBusinessProjectionV2 {
  plugin_id: string;
  kind?: 'business' | 'adapter' | null;
  targets?: readonly string[];
  version: string;
  package_recorded: boolean;
  installed_version: string | null;
  desired_revision: number;
  running_version: string | null;
  desired_enabled: boolean;
  has_web_ui: boolean;
  commands: readonly string[];
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

export function createOptionalBusinessService(httpClient: PackageClient) {
  return {
    list(scope: Scope): Promise<{
      items: { plugin_id: string; version: string; running_version: string | null }[];
    }> {
      return httpClient.get(BASE_URL + '/', { params: scopeBody(scope) });
    },
    projection(pluginId: string, scope: Scope): Promise<OptionalBusinessProjectionV2> {
      return httpClient.get(`${BASE_URL}/${encodeURIComponent(pluginId)}`, {
        params: scopeBody(scope),
      });
    },
    async inspect(file: File, scope: Scope): Promise<OptionalBusinessPackageFileV2> {
      if (file.size > 12 * 1024 * 1024) throw new RangeError('archive too large');
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => {
          reject(reader.error ?? new Error('Cannot read package'));
        };
        reader.onload = () => {
          if (typeof reader.result === 'string') resolve(reader.result.split(',')[1] ?? '');
          else reject(new Error('Invalid package file'));
        };
        reader.readAsDataURL(file);
      });
      const verified = await httpClient.post<Omit<OptionalBusinessPackageFileV2, 'archive_base64'>>(
        `${BASE_URL}/inspect`,
        { ...scopeBody(scope), archive_base64: encoded }
      );
      return { ...verified, archive_base64: encoded };
    },
    resolveNpm(
      scope: Scope,
      name: string,
      version: string
    ): Promise<OptionalBusinessPackageFileV2> {
      return httpClient.post(BASE_URL + '/npm/resolve', {
        ...scopeBody(scope),
        package_name: name,
        version,
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
          archive_base64: file.archive_base64,
          approved_permissions: file.permissions,
        },
        {
          onUploadProgress: (event) => {
            if (!onProgress || !event.total) return;
            onProgress(Math.round((event.loaded / event.total) * 100));
          },
        }
      );
    },
    command(
      pluginId: string,
      scope: Scope,
      commandId: string,
      digest: string,
      payload?: Record<string, unknown>
    ): Promise<Record<string, unknown>> {
      return httpClient.post(`${BASE_URL}/${encodeURIComponent(pluginId)}/commands`, {
        ...scopeBody(scope),
        command_id: commandId,
        ...(payload !== undefined ? { payload } : {}),
        expected_digest: digest,
      });
    },
    mutate(
      pluginId: string,
      scope: Scope,
      action: 'enable' | 'disable' | 'rollback' | 'uninstall',
      revision: number
    ): Promise<{ status: string }> {
      return httpClient.post(`${BASE_URL}/${encodeURIComponent(pluginId)}/${action}`, {
        ...scopeBody(scope),
        expected_revision: revision,
      });
    },
    ui(pluginId: string, scope: Scope, digest: string): Promise<OptionalBusinessUiV2> {
      return httpClient.get(`${BASE_URL}/${encodeURIComponent(pluginId)}/ui`, {
        params: { ...scopeBody(scope), target: 'web', expected_digest: digest },
      });
    },
  };
}

export type OptionalBusinessService = ReturnType<typeof createOptionalBusinessService>;
