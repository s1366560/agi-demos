import type { ProjectSummary, TenantSummary } from '../types';

type DesktopInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

const PROJECTION_KEYS = new Set([
  'status',
  'api_base_url',
  'expires_at',
  'user',
  'workspace_context',
  'tenants',
  'projects',
]);
const USER_KEYS = new Set([
  'user_id',
  'email',
  'name',
  'roles',
  'global_roles',
  'is_active',
  'is_superuser',
  'created_at',
  'profile',
  'preferred_language',
]);
const WORKSPACE_CONTEXT_KEYS = new Set(['context', 'membership_role']);
const WORKSPACE_SCOPE_KEYS = new Set([
  'tenant_id',
  'project_id',
  'revision',
  'updated_at',
]);
const TENANT_KEYS = new Set(['id', 'name', 'slug', 'description']);
const PROJECT_KEYS = new Set(['id', 'tenant_id', 'name', 'description', 'is_public']);

export type CloudSessionIdentityProjection = Readonly<{
  userId: string;
  email: string;
  name: string;
  roles: readonly string[];
  globalRoles: readonly string[];
  active: boolean;
  superuser: boolean;
  createdAt: string;
  preferredLanguage: 'en-US' | 'zh-CN' | null;
}>;

export type CloudSessionWorkspaceProjection = Readonly<{
  tenantId: string;
  projectId: string | null;
  revision: number;
  updatedAt: string;
  membershipRole: string;
}>;

export type CloudSessionProjection = Readonly<{
  status: 'authenticated';
  apiBaseUrl: string;
  expiresAt: string | null;
  user: CloudSessionIdentityProjection;
  workspaceContext: CloudSessionWorkspaceProjection;
  tenants: readonly TenantSummary[];
  projects: readonly ProjectSummary[];
}>;

export type CloudSessionProjectionClient = Readonly<{
  load(signal?: AbortSignal): Promise<CloudSessionProjection | null>;
}>;

export function decodeCloudSessionProjection(value: unknown): CloudSessionProjection | null {
  if (!isExactRecord(value, PROJECTION_KEYS) || value.status !== 'authenticated') return null;
  const apiBaseUrl = secureOrigin(value.api_base_url);
  const expiresAt = nullableTimestamp(value.expires_at);
  const user = decodeIdentity(value.user);
  const workspaceContext = decodeWorkspaceContext(value.workspace_context);
  const tenants = decodeTenants(value.tenants);
  const projects = workspaceContext
    ? decodeProjects(value.projects, workspaceContext.tenantId)
    : null;
  if (
    !apiBaseUrl ||
    expiresAt === undefined ||
    !user ||
    !workspaceContext ||
    !tenants ||
    !projects ||
    !tenants.some((tenant) => tenant.id === workspaceContext.tenantId) ||
    (workspaceContext.projectId !== null &&
      !projects.some((project) => project.id === workspaceContext.projectId))
  ) {
    return null;
  }
  return Object.freeze({
    status: 'authenticated',
    apiBaseUrl,
    expiresAt,
    user,
    workspaceContext,
    tenants,
    projects,
  });
}

function decodeTenants(value: unknown): readonly TenantSummary[] | null {
  if (!Array.isArray(value)) return null;
  const tenants: TenantSummary[] = [];
  const ids = new Set<string>();
  for (const candidate of value) {
    if (!isAllowedRecord(candidate, TENANT_KEYS)) return null;
    const id = identifier(candidate.id);
    const name = displayString(candidate.name);
    const slug = candidate.slug === undefined ? undefined : displayString(candidate.slug);
    const description =
      candidate.description === undefined || candidate.description === null
        ? candidate.description
        : displayString(candidate.description);
    if (
      !id ||
      !name ||
      (candidate.slug !== undefined && !slug) ||
      (candidate.description !== undefined && candidate.description !== null && !description) ||
      ids.has(id)
    ) {
      return null;
    }
    ids.add(id);
    tenants.push(
      Object.freeze({
        id,
        name,
        ...(typeof slug === 'string' ? { slug } : {}),
        ...(description === undefined ? {} : { description }),
      }),
    );
  }
  return Object.freeze(tenants);
}

function decodeProjects(value: unknown, tenantId: string): readonly ProjectSummary[] | null {
  if (!Array.isArray(value)) return null;
  const projects: ProjectSummary[] = [];
  const ids = new Set<string>();
  for (const candidate of value) {
    if (!isAllowedRecord(candidate, PROJECT_KEYS)) return null;
    const id = identifier(candidate.id);
    const observedTenantId = identifier(candidate.tenant_id);
    const name = displayString(candidate.name);
    const description =
      candidate.description === undefined || candidate.description === null
        ? candidate.description
        : displayString(candidate.description);
    if (
      !id ||
      observedTenantId !== tenantId ||
      !name ||
      (candidate.description !== undefined && candidate.description !== null && !description) ||
      (candidate.is_public !== undefined && typeof candidate.is_public !== 'boolean') ||
      ids.has(id)
    ) {
      return null;
    }
    ids.add(id);
    projects.push(
      Object.freeze({
        id,
        tenant_id: observedTenantId,
        name,
        ...(description === undefined ? {} : { description }),
        ...(candidate.is_public === undefined ? {} : { is_public: candidate.is_public }),
      }),
    );
  }
  return Object.freeze(projects);
}

export function desktopCloudSessionProjectionClient(): CloudSessionProjectionClient | null {
  if (typeof window === 'undefined') return null;
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) return null;
  return Object.freeze({
    async load(signal?: AbortSignal): Promise<CloudSessionProjection | null> {
      if (signal?.aborted) throw abortError();
      const requestId = globalThis.crypto.randomUUID();
      const request = invoke('cloud_session_projection', { requestId });
      const value = signal
        ? await waitForProjection(invoke, requestId, request, signal)
        : await request;
      if (value === null || value === undefined) return null;
      const projection = decodeCloudSessionProjection(value);
      if (!projection) throw new Error('cloud_session_projection_contract_invalid');
      return projection;
    },
  });
}

function decodeIdentity(value: unknown): CloudSessionIdentityProjection | null {
  if (!isExactRecord(value, USER_KEYS)) return null;
  const userId = identifier(value.user_id);
  const email = boundedString(value.email, 320, false);
  const name = boundedString(value.name, 512, true);
  const roles = stringList(value.roles);
  const globalRoles = stringList(value.global_roles);
  const createdAt = timestamp(value.created_at);
  const preferredLanguage =
    value.preferred_language === null ||
    value.preferred_language === 'en-US' ||
    value.preferred_language === 'zh-CN'
      ? value.preferred_language
      : undefined;
  if (
    !userId ||
    email === null ||
    name === null ||
    !roles ||
    !globalRoles ||
    typeof value.is_active !== 'boolean' ||
    typeof value.is_superuser !== 'boolean' ||
    !createdAt ||
    !isRecord(value.profile) ||
    preferredLanguage === undefined
  ) {
    return null;
  }
  return Object.freeze({
    userId,
    email,
    name,
    roles: Object.freeze(roles),
    globalRoles: Object.freeze(globalRoles),
    active: value.is_active,
    superuser: value.is_superuser,
    createdAt,
    preferredLanguage,
  });
}

function decodeWorkspaceContext(value: unknown): CloudSessionWorkspaceProjection | null {
  if (!isExactRecord(value, WORKSPACE_CONTEXT_KEYS)) return null;
  if (!isExactRecord(value.context, WORKSPACE_SCOPE_KEYS)) return null;
  const tenantId = identifier(value.context.tenant_id);
  const observedProjectId = value.context.project_id;
  const projectId = observedProjectId === null ? null : identifier(observedProjectId);
  const updatedAt = timestamp(value.context.updated_at);
  const membershipRole = identifier(value.membership_role);
  if (
    !tenantId ||
    (observedProjectId !== null && !projectId) ||
    !updatedAt ||
    !membershipRole ||
    !unsignedSafeInteger(value.context.revision)
  ) {
    return null;
  }
  return Object.freeze({
    tenantId,
    projectId,
    revision: value.context.revision,
    updatedAt,
    membershipRole,
  });
}

async function waitForProjection(
  invoke: DesktopInvoke,
  requestId: string,
  request: Promise<unknown>,
  signal: AbortSignal,
): Promise<unknown> {
  let rejectAbort: ((reason: Error) => void) | null = null;
  const aborted = new Promise<never>((_resolve, reject) => {
    rejectAbort = reject;
  });
  const handleAbort = (): void => {
    void invoke('cloud_request_cancel', { requestId }).catch(() => undefined);
    rejectAbort?.(abortError());
  };
  signal.addEventListener('abort', handleAbort, { once: true });
  try {
    if (signal.aborted) handleAbort();
    return await Promise.race([request, aborted]);
  } finally {
    signal.removeEventListener('abort', handleAbort);
  }
}

function secureOrigin(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    const loopback =
      url.protocol === 'http:' &&
      ['localhost', '127.0.0.1', '::1', '[::1]'].includes(url.hostname.toLowerCase());
    if (
      (url.protocol !== 'https:' && !loopback) ||
      url.username ||
      url.password ||
      url.pathname !== '/' ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url.origin;
  } catch {
    return null;
  }
}

function nullableTimestamp(value: unknown): string | null | undefined {
  if (value === null) return null;
  return timestamp(value) ?? undefined;
}

function timestamp(value: unknown): string | null {
  return typeof value === 'string' && value.length <= 64 && Number.isFinite(Date.parse(value))
    ? value
    : null;
}

function identifier(value: unknown): string | null {
  return boundedString(value, 256, false);
}

function boundedString(value: unknown, maxLength: number, allowEmpty: boolean): string | null {
  if (
    typeof value !== 'string' ||
    value.length > maxLength ||
    value !== value.trim() ||
    (!allowEmpty && value.length === 0) ||
    hasControlCharacter(value)
  ) {
    return null;
  }
  return value;
}

function displayString(value: unknown): string | null {
  return boundedString(value, 1024, false);
}

function stringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.map(identifier);
  if (items.some((item) => item === null)) return null;
  const strings = items as string[];
  return new Set(strings).size === strings.length ? strings : null;
}

function unsignedSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function isExactRecord(value: unknown, keys: ReadonlySet<string>): value is Record<string, unknown> {
  return isRecord(value) && Object.keys(value).every((key) => keys.has(key));
}

function isAllowedRecord(value: unknown, keys: ReadonlySet<string>): value is Record<string, unknown> {
  return isExactRecord(value, keys);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasControlCharacter(value: string): boolean {
  return [...value].some((character) => {
    const code = character.charCodeAt(0);
    return code <= 0x1f || code === 0x7f;
  });
}

function abortError(): Error {
  return new DOMException('The Cloud session projection was aborted.', 'AbortError');
}
