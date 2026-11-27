/** The cloud/web project list. The package-kernel picker is a different client. */

/** Full-host marketplace follows the web hub: no projectId means the whole tenant. */
export function fullMarketProjectId(search: string): string | null {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  const values = params.getAll('projectId');
  if (values.length !== 1 || !values[0]) return null;
  return values[0];
}

export const PROJECT_CATALOG_PAGE_SIZE = 100;
const MAX_PAGES = 20;

export type CatalogProject = {
  id: string;
  tenant_id: string;
  name: string;
};

export type ProjectCatalogPage = {
  projects: CatalogProject[];
  total: number;
  page: number;
};

/**
 * One broker-allowed read of every project the user can open.
 * `/api/v1/projects/?tenant_id=` is limited to the saved workspace tenant.
 */
export const PACKAGE_PROJECT_CATALOG_PATH = '/api/v1/project-packages/projects/';

export type PackageCatalogProject = CatalogProject & { tenant_name: string };

export function readPackageProjectCatalog(payload: unknown): PackageCatalogProject[] {
  if (!Array.isArray(payload)) throw new Error('project_catalog_invalid');
  return payload.map((item) => {
    if (!item || typeof item !== 'object') throw new Error('project_catalog_invalid');
    const row = item as {
      project_id?: unknown;
      tenant_id?: unknown;
      project_name?: unknown;
      tenant_name?: unknown;
    };
    if (typeof row.project_id !== 'string' || !row.project_id) {
      throw new Error('project_catalog_invalid');
    }
    if (typeof row.tenant_id !== 'string' || !row.tenant_id) {
      throw new Error('project_catalog_invalid');
    }
    if (typeof row.project_name !== 'string' || !row.project_name) {
      throw new Error('project_catalog_invalid');
    }
    if (typeof row.tenant_name !== 'string' || !row.tenant_name) {
      throw new Error('project_catalog_invalid');
    }
    return {
      id: row.project_id,
      tenant_id: row.tenant_id,
      name: row.project_name,
      tenant_name: row.tenant_name,
    };
  });
}

export function projectCatalogPath(tenantId: string, page = 1): string {
  const query = new URLSearchParams({
    tenant_id: tenantId,
    page: String(page),
    page_size: String(PROJECT_CATALOG_PAGE_SIZE),
  });
  return `/api/v1/projects/?${query.toString()}`;
}

export function readProjectCatalogPage(payload: unknown): ProjectCatalogPage {
  if (!payload || typeof payload !== 'object') throw new Error('project_catalog_invalid');
  const body = payload as { projects?: unknown; total?: unknown; page?: unknown };
  if (!Array.isArray(body.projects) || typeof body.total !== 'number' || body.total < 0) {
    throw new Error('project_catalog_invalid');
  }
  const projects = body.projects.map((item) => {
    if (!item || typeof item !== 'object') throw new Error('project_catalog_invalid');
    const row = item as { id?: unknown; tenant_id?: unknown; name?: unknown };
    if (
      typeof row.id !== 'string' ||
      !row.id ||
      typeof row.tenant_id !== 'string' ||
      !row.tenant_id
    ) {
      throw new Error('project_catalog_invalid');
    }
    if (typeof row.name !== 'string' || !row.name) throw new Error('project_catalog_invalid');
    return { id: row.id, tenant_id: row.tenant_id, name: row.name };
  });
  return {
    projects,
    total: body.total,
    page: typeof body.page === 'number' ? body.page : 1,
  };
}

type CatalogRequest = <T>(path: string, init: { signal?: AbortSignal }) => Promise<T>;

/** Follows the web project service: `/api/v1/projects/?tenant_id=`, one tenant at a time. */
export async function loadTenantProjects(
  request: CatalogRequest,
  tenantId: string,
  signal?: AbortSignal,
): Promise<CatalogProject[]> {
  const projects: CatalogProject[] = [];
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const parsed = readProjectCatalogPage(
      await request<unknown>(projectCatalogPath(tenantId, page), { signal }),
    );
    if (parsed.page !== page) throw new Error('project_catalog_invalid');
    for (const project of parsed.projects) {
      if (project.tenant_id === tenantId) projects.push(project);
    }
    if (!parsed.projects.length || projects.length >= parsed.total) return projects;
  }
  return projects;
}
