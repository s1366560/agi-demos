/**
 * Sandbox/workspace path → artifact resolution helpers.
 *
 * Agent-authored content (markdown links, images) often references generated files
 * by their sandbox path (e.g. `/workspace/output/report.png`) or bare filename.
 * Those paths are not directly fetchable from the web origin — the real bytes live
 * in object storage and are exposed through an artifact presigned/preview URL.
 *
 * These helpers map such a path to the matching {@link Artifact} so callers can
 * render or open it with a working URL. Shared by the chat message bubble (file
 * links) and the markdown image renderer (Canvas + chat).
 */

import { useTimelineStore } from '@/stores/agent/timelineStore';
import { useProjectStore } from '@/stores/project';
import { useSandboxStore } from '@/stores/sandbox';

import { artifactService } from '@/services/artifactService';

import type { Artifact, TimelineEvent } from '@/types/agent';

/** Normalize a sandbox path, expanding the `~/` home shortcut to `/workspace/`. */
export function normalizeSandboxPath(path: string): string {
  if (path.startsWith('~/')) return `/workspace/${path.slice(2)}`;
  return path;
}

/** Whether a sandbox path (or bare filename) refers to the given artifact. */
export function pathMatchesArtifact(path: string, artifact: Artifact): boolean {
  const normalized = normalizeSandboxPath(path);
  const sourcePath = artifact.sourcePath ? normalizeSandboxPath(artifact.sourcePath) : '';
  const filename = artifact.filename;
  return (
    sourcePath === normalized ||
    sourcePath.endsWith(`/${path}`) ||
    normalized.endsWith(`/${filename}`) ||
    path === filename
  );
}

/** Read the last active project id persisted in localStorage (survives refresh). */
function decodePersistedProjectId(rawValue: string | null): string | null {
  if (!rawValue) return null;

  try {
    const parsed = JSON.parse(rawValue) as unknown;
    return typeof parsed === 'string' && parsed.trim().length > 0 ? parsed : null;
  } catch {
    return rawValue.trim().length > 0 ? rawValue : null;
  }
}

function getPersistedProjectId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const tenantId = getTenantIdFromPath();
    if (tenantId) {
      const scoped = decodePersistedProjectId(
        window.localStorage.getItem(`agent:${tenantId}:lastProjectId`)
      );
      if (scoped) return scoped;
      return null;
    }

    const legacy = decodePersistedProjectId(window.localStorage.getItem('agent:lastProjectId'));
    if (legacy) return legacy;

    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (key && key.endsWith(':lastProjectId')) {
        const value = decodePersistedProjectId(window.localStorage.getItem(key));
        if (value) return value;
      }
    }
  } catch {
    // Ignore storage access errors (private mode, disabled storage, etc.).
  }
  return null;
}

function getTenantIdFromPath(): string | null {
  const match = /^\/tenant\/([^/?#]+)/.exec(window.location.pathname);
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/**
 * Resolve the project id of the current agent/canvas context.
 *
 * Checks every source that may hold it, in order of reliability: the live sandbox
 * connection, the project store, the URL query, and finally the persisted
 * `lastProjectId`. The localStorage fallback is essential after a hard refresh,
 * when the canvas restores persisted tabs before any store/URL state is populated.
 */
function getCurrentProjectId(): string | null {
  const activeProjectId = useSandboxStore.getState().activeProjectId;
  if (activeProjectId) return activeProjectId;

  const currentProjectId = useProjectStore.getState().currentProject?.id;
  if (currentProjectId) return currentProjectId;

  if (typeof window !== 'undefined') {
    const urlProjectId = new URLSearchParams(window.location.search).get('projectId');
    if (urlProjectId) return urlProjectId;
  }

  return getPersistedProjectId();
}

/**
 * Resolve a sandbox path to its artifact, preferring already-loaded artifacts in the
 * sandbox store before falling back to a project-scoped artifact list request.
 */
export async function findArtifactForSandboxPath(path: string): Promise<Artifact | undefined> {
  const storeArtifacts = Array.from(useSandboxStore.getState().artifacts.values());
  const storeArtifact = storeArtifacts.find((item) => pathMatchesArtifact(path, item));
  if (storeArtifact) return storeArtifact;

  const projectId = getCurrentProjectId();
  if (!projectId) return undefined;

  const { artifacts } = await artifactService.list(projectId, { limit: 500 });
  return artifacts.find((item) => pathMatchesArtifact(path, item));
}

interface TimelineArtifactLike {
  filename?: string | undefined;
  sourcePath?: string | undefined;
  url?: string | undefined;
  previewUrl?: string | undefined;
}

/** Whether a timeline artifact event (by filename/sourcePath) refers to a path. */
function timelineArtifactMatchesPath(path: string, event: TimelineArtifactLike): boolean {
  const normalized = normalizeSandboxPath(path);
  const sourcePath = event.sourcePath ? normalizeSandboxPath(event.sourcePath) : '';
  const filename = event.filename ?? '';
  return (
    (!!sourcePath && (sourcePath === normalized || sourcePath.endsWith(`/${path}`))) ||
    (!!filename && (normalized.endsWith(`/${filename}`) || path === filename))
  );
}

/**
 * Scan the loaded conversation timeline for an artifact event matching the given
 * sandbox path and return its usable URL. This is the most reliable source after a
 * hard refresh: the timeline is reloaded from the backend with real presigned URLs,
 * so no project lookup or live sandbox connection is required.
 */
function findArtifactUrlInTimeline(path: string): string | null {
  const { timeline, agentTimeline } = useTimelineStore.getState();
  const events = [...timeline, ...agentTimeline] as TimelineEvent[];
  for (const event of events) {
    if (event.type === 'artifact_created' || event.type === 'artifact_ready') {
      const candidate = event as unknown as TimelineArtifactLike;
      if (!timelineArtifactMatchesPath(path, candidate)) continue;
      const url = candidate.url || candidate.previewUrl;
      if (url && isSafeArtifactUrl(url)) return url;
    } else if (event.type === 'artifacts_batch') {
      const batch = event as unknown as { artifacts?: TimelineArtifactLike[] | undefined };
      for (const candidate of batch.artifacts ?? []) {
        if (!timelineArtifactMatchesPath(path, candidate)) continue;
        const url = candidate.url || candidate.previewUrl;
        if (url && isSafeArtifactUrl(url)) return url;
      }
    }
  }
  return null;
}

/**
 * Resolve a sandbox/workspace path (or bare filename) to a directly-loadable
 * artifact URL, or `null` when it cannot be resolved.
 *
 * Resolution order: the conversation timeline (reliable after refresh) first, then
 * the sandbox store / project-scoped artifact list via {@link findArtifactForSandboxPath}.
 */
export async function resolveSandboxArtifactUrl(path: string): Promise<string | null> {
  const timelineUrl = findArtifactUrlInTimeline(path);
  if (timelineUrl) return timelineUrl;

  try {
    const artifact = await findArtifactForSandboxPath(path);
    const url = artifact?.url || artifact?.previewUrl;
    if (url && isSafeArtifactUrl(url)) return url;
  } catch {
    // Ignore lookup failures; caller renders nothing rather than a broken image.
  }
  return null;
}

/**
 * Whether an image/media `src` already points at a directly-loadable resource
 * (absolute http(s) URL, blob/data URI, or an app-relative API path).
 * Anything else — most importantly a sandbox/workspace path like
 * `/workspace/output/chart.png` or a bare `chart.png` — must be resolved to
 * the matching artifact URL before it can be rendered.
 */
export function isDirectlyLoadableImageSrc(src: string): boolean {
  const lower = src.toLowerCase();
  if (lower.startsWith('http://') || lower.startsWith('https://')) return true;
  if (lower.startsWith('blob:') || lower.startsWith('data:')) return true;
  // App-relative artifact/API endpoints are served by our own origin.
  if (src.startsWith('/api/') || src.startsWith('/artifacts/')) return true;
  return false;
}

const SANDBOX_IMAGE_PATH_PATTERN = /(?:^\/|^~\/|^\.{0,2}\/)|\.[A-Za-z0-9]{1,12}$/;

/**
 * Whether a media `src` looks like a sandbox/workspace file path or bare
 * filename that should be resolved to an artifact URL before rendering.
 */
export function looksLikeSandboxImagePath(src: string): boolean {
  if (isDirectlyLoadableImageSrc(src)) return false;
  return SANDBOX_IMAGE_PATH_PATTERN.test(src);
}

/** Whether a resolved artifact URL is safe to use as a resource `src`/`href`. */
export function isSafeArtifactUrl(src: string): boolean {
  if (!src) return false;
  if (src.startsWith('/')) return true;
  const lower = src.toLowerCase();
  if (lower.startsWith('data:application/pdf')) return true;
  if (lower.startsWith('data:')) return false;
  try {
    const url = new URL(src, window.location.origin);
    return url.protocol === 'http:' || url.protocol === 'https:' || url.protocol === 'blob:';
  } catch {
    return false;
  }
}
