import type { Project } from '@/types/memory';

export const LEGACY_LAST_PROJECT_ID_KEY = 'agent:lastProjectId';
export const MANUAL_PROJECT_SELECTION_SOURCE = 'manual';
export const DEFAULT_PROJECT_NAMES = new Set(['default project', '\u9ED8\u8BA4\u9879\u76EE']);

export type ProjectSelectionSource = typeof MANUAL_PROJECT_SELECTION_SOURCE;

export function lastProjectIdStorageKey(tenantId: string | undefined): string | null {
  return tenantId ? `agent:${tenantId}:lastProjectId` : null;
}

export function lastProjectSelectionSourceStorageKey(tenantId: string | undefined): string | null {
  return tenantId ? `agent:${tenantId}:lastProjectSelectionSource` : null;
}

export function isDefaultProject(project: Project | null | undefined): project is Project {
  const normalizedName = project?.name.trim().toLocaleLowerCase();
  return !!normalizedName && DEFAULT_PROJECT_NAMES.has(normalizedName);
}

export function getDefaultProject(projects: Project[]): Project | null {
  return projects.find(isDefaultProject) ?? null;
}

export function persistLastProjectId(
  tenantId: string | undefined,
  projectId: string,
  source: ProjectSelectionSource = MANUAL_PROJECT_SELECTION_SOURCE
): void {
  const storageKey = lastProjectIdStorageKey(tenantId);
  if (!storageKey) {
    return;
  }

  try {
    localStorage.setItem(storageKey, JSON.stringify(projectId));
    const sourceKey = lastProjectSelectionSourceStorageKey(tenantId);
    if (sourceKey) {
      localStorage.setItem(sourceKey, JSON.stringify(source));
    }
    localStorage.removeItem(LEGACY_LAST_PROJECT_ID_KEY);
  } catch {
    // Storage may be unavailable in private mode or restricted browser contexts.
  }
}
