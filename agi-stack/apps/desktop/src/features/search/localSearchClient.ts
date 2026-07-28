import type {
  DesktopSearchRequest,
  DesktopSearchResponse,
} from '../../api/searchContract';

export type LocalSearchCapability = {
  service_version: string;
  contract_version: string;
  mode: 'full' | 'keyword_degraded' | 'unavailable';
  reason_code: string | null;
  tenant_id: string;
  project_id: string;
  projection_revision: number | null;
  backfill_cursor: string | null;
  supported_search_types: string[];
  unavailable_search_types: string[];
};

export type LocalSearchClient = {
  getCapability(signal?: AbortSignal): Promise<LocalSearchCapability>;
  search(
    request: DesktopSearchRequest,
    scope: {
      tenantId: string;
      projectId: string;
      signal?: AbortSignal;
    },
  ): Promise<DesktopSearchResponse>;
};

export function createLocalSearchClient(authority: LocalSearchClient): LocalSearchClient {
  return Object.freeze({
    getCapability: (signal?: AbortSignal) => authority.getCapability(signal),
    search: (
      request: DesktopSearchRequest,
      scope: {
        tenantId: string;
        projectId: string;
        signal?: AbortSignal;
      },
    ) => authority.search(request, scope),
  });
}
