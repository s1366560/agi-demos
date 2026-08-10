import { authorizeCloudProductEndpoint } from './cloudProductEndpointPolicy';

export type VaultBoundCloudRequestInput = Readonly<{
  path: string;
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: Readonly<Record<string, unknown>>;
  form?: readonly VaultBoundCloudFormPart[];
  mutation?: VaultBoundCloudMutation;
  response?: VaultBoundCloudResponsePolicy;
}>;

type VaultBoundCloudMutation =
  | Readonly<{
      expected_revision: number;
      idempotency_key: string;
    }>
  | Readonly<{
      kind: 'idempotency-only';
      idempotency_key: string;
    }>;

type VaultBoundCloudFormPart =
  | Readonly<{ kind: 'text'; name: string; value: string }>
  | Readonly<{
      kind: 'file';
      name: string;
      filename: string;
      mime_type: string;
      bytes_base64: string;
    }>;

type VaultBoundCloudResponsePolicy =
  | Readonly<{
      kind: 'binary';
      max_bytes: number;
    }>
  | Readonly<{
      kind: 'event-stream';
      max_bytes: number;
    }>;

export type VaultBoundCloudRequestResult = Readonly<{
  status: number;
  body: unknown;
}>;

export type VaultBoundCloudSessionProjection = Readonly<{
  status: 'authenticated';
  api_base_url: string;
  expires_at: string | null;
  user: Readonly<Record<string, unknown>>;
  workspace_context: Readonly<Record<string, unknown>>;
  tenants: readonly Readonly<Record<string, unknown>>[];
  projects: readonly Readonly<Record<string, unknown>>[];
}>;

type TrustedCloudSession = Readonly<{
  version: 1;
  api_base_url: string;
  runtime_mode: 'cloud';
  credential_kind: 'cloud_bearer';
  credential: string;
  expires_at: string | null;
}>;

export type VaultBoundCloudRequestDependencies = Readonly<{
  loadTrustedSession(): Promise<unknown>;
  fetch(url: string, init: RequestInit): Promise<Response>;
  signal?: AbortSignal;
}>;

export type CloudRequestExecutionLease = Readonly<{
  signal: AbortSignal;
  release(): void;
}>;

export type CloudRequestExecutionRegistryOptions = Readonly<{
  timeoutMs: number;
}>;

type AuthorizedEndpoint = Readonly<{
  kind:
    | 'identity'
    | 'identity-catalog'
    | 'tenant-admin'
    | 'workspace-context'
    | 'backend-stores'
    | 'project-playbooks'
    | 'project'
    | 'workspace';
  tenantId: string | null;
  projectId: string | null;
  workspaceId?: string | null;
}>;

const REQUEST_KEYS = new Set(['path', 'method', 'body', 'form', 'mutation', 'response']);
const MUTATION_KEYS = new Set(['expected_revision', 'idempotency_key']);
const IDEMPOTENCY_MUTATION_KEYS = new Set(['kind', 'idempotency_key']);
const FORM_TEXT_KEYS = new Set(['kind', 'name', 'value']);
const FORM_FILE_KEYS = new Set(['kind', 'name', 'filename', 'mime_type', 'bytes_base64']);
const RESPONSE_KEYS = new Set(['kind', 'max_bytes']);
const MAX_REQUEST_BYTES = 512 * 1024;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_BINARY_RESPONSE_BYTES = 16 * 1024 * 1024;
const MAX_EVENT_STREAM_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_FORM_PARTS = 32;
const MAX_FORM_TEXT_BYTES = 64 * 1024;
const IDENTITY_CATALOG_PAGE_SIZE = 100;
const IDENTITY_CATALOG_MAX_PAGES = 100;
const CATALOG_PAGE_KEYS = new Set(['total', 'page', 'page_size']);
const BACKEND_ROOTS = new Set(['graph-stores', 'retrieval-stores']);
const METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);
const REQUEST_ID = /^[A-Za-z0-9_-]{16,128}$/u;
const FORM_NAME = /^[A-Za-z0-9_.-]{1,128}$/u;
const MIME_TYPE = /^[A-Za-z0-9!#$&^_.+-]+\/[A-Za-z0-9!#$&^_.+-]+$/u;

type CloudRequestExecution = Readonly<{
  ownerId: number;
  controller: AbortController;
  timeout: ReturnType<typeof setTimeout>;
}>;

export class CloudRequestExecutionRegistry {
  readonly #timeoutMs: number;
  readonly #executions = new Map<string, CloudRequestExecution>();

  constructor(options: CloudRequestExecutionRegistryOptions) {
    if (!Number.isSafeInteger(options.timeoutMs) || options.timeoutMs < 1) {
      throw new Error('cloud request timeout is invalid');
    }
    this.#timeoutMs = options.timeoutMs;
  }

  begin(ownerId: number, requestId: unknown): CloudRequestExecutionLease {
    const id = validRequestId(requestId);
    if (!Number.isSafeInteger(ownerId) || ownerId < 0) {
      throw new Error('cloud request owner is invalid');
    }
    if (this.#executions.has(id)) throw new Error('cloud request id is already active');

    const controller = new AbortController();
    const timeout = setTimeout(() => {
      const execution = this.#executions.get(id);
      if (!execution || execution.controller !== controller) return;
      this.#executions.delete(id);
      controller.abort(new Error('cloud request timed out'));
    }, this.#timeoutMs);
    const execution = Object.freeze({ ownerId, controller, timeout });
    this.#executions.set(id, execution);

    let released = false;
    return Object.freeze({
      signal: controller.signal,
      release: () => {
        if (released) return;
        released = true;
        const current = this.#executions.get(id);
        if (!current || current.controller !== controller) return;
        this.#executions.delete(id);
        clearTimeout(current.timeout);
      },
    });
  }

  cancel(ownerId: number, requestId: unknown): boolean {
    const id = validRequestId(requestId);
    const execution = this.#executions.get(id);
    if (!execution || execution.ownerId !== ownerId) return false;
    this.#executions.delete(id);
    clearTimeout(execution.timeout);
    execution.controller.abort(new Error('cloud request was cancelled'));
    return true;
  }

  cancelOwner(ownerId: number): number {
    let cancelled = 0;
    for (const [requestId, execution] of this.#executions) {
      if (execution.ownerId !== ownerId) continue;
      this.#executions.delete(requestId);
      clearTimeout(execution.timeout);
      execution.controller.abort(new Error('cloud request owner was destroyed'));
      cancelled += 1;
    }
    return cancelled;
  }

  cancelAll(): number {
    let cancelled = 0;
    for (const [requestId, execution] of this.#executions) {
      this.#executions.delete(requestId);
      clearTimeout(execution.timeout);
      execution.controller.abort(new Error('cloud request broker is shutting down'));
      cancelled += 1;
    }
    return cancelled;
  }
}

export async function executeVaultBoundCloudRequest(
  input: unknown,
  dependencies: VaultBoundCloudRequestDependencies,
): Promise<VaultBoundCloudRequestResult> {
  dependencies.signal?.throwIfAborted();
  const request = parseRequest(input);
  const endpoint = authorizeEndpoint(request);
  const session = parseTrustedCloudSession(await dependencies.loadTrustedSession());
  dependencies.signal?.throwIfAborted();
  const contextResponse = await authorizedFetch(
    session,
    dependencies,
    Object.freeze({ path: '/api/v1/workspace-context', method: 'GET' }),
  );
  const contextBody = await boundedJson(contextResponse, false, session.credential);
  if (!contextResponse.ok) throw new Error('cloud request scope observation failed');
  const context = parseObservedContext(contextBody);
  assertEndpointScope(endpoint, context);
  if (endpoint.kind === 'workspace-context') {
    return Object.freeze({ status: contextResponse.status, body: contextBody });
  }
  const response = await authorizedFetch(session, dependencies, request);
  if (request.response?.kind === 'binary' && response.ok) {
    return Object.freeze({
      status: response.status,
      body: await boundedBinary(
        response,
        request.response.max_bytes,
        session.credential,
        request.path,
      ),
    });
  }
  if (request.response?.kind === 'event-stream' && response.ok) {
    return Object.freeze({
      status: response.status,
      body: await boundedEventStream(
        response,
        request.response.max_bytes,
        session.credential,
      ),
    });
  }
  return Object.freeze({
    status: response.status,
    body: await boundedJson(response, true, session.credential),
  });
}

export async function projectVaultBoundCloudSession(
  dependencies: VaultBoundCloudRequestDependencies,
): Promise<VaultBoundCloudSessionProjection | null> {
  dependencies.signal?.throwIfAborted();
  const storedSession = await dependencies.loadTrustedSession();
  if (storedSession === null || storedSession === undefined) return null;
  const session = parseTrustedCloudSession(storedSession);
  dependencies.signal?.throwIfAborted();

  const contextResponse = await authorizedFetch(
    session,
    dependencies,
    Object.freeze({ path: '/api/v1/workspace-context', method: 'GET' }),
  );
  const contextBody = await boundedJson(contextResponse, false, session.credential);
  if (!contextResponse.ok || !isRecord(contextBody)) {
    throw new Error('cloud session scope observation failed');
  }
  const context = parseObservedContext(contextBody);

  const identityResponse = await authorizedFetch(
    session,
    dependencies,
    Object.freeze({ path: '/api/v1/auth/me', method: 'GET' }),
  );
  const identityBody = await boundedJson(identityResponse, false, session.credential);
  if (!identityResponse.ok || !isRecord(identityBody)) {
    throw new Error('cloud session identity observation failed');
  }

  const tenants = await loadProjectedIdentityCatalog(
    session,
    dependencies,
    'tenants',
    (page) => `/api/v1/tenants?page=${page}&page_size=${IDENTITY_CATALOG_PAGE_SIZE}`,
    projectTenant,
  );
  if (!tenants.some((tenant) => tenant.id === context.tenantId)) {
    throw new Error('cloud session tenant catalog scope mismatch');
  }
  const projects = await loadProjectedIdentityCatalog(
    session,
    dependencies,
    'projects',
    (page) =>
      `/api/v1/projects?page=${page}&page_size=${IDENTITY_CATALOG_PAGE_SIZE}&tenant_id=${encodeURIComponent(context.tenantId)}`,
    (value) => projectProject(value, context.tenantId),
  );
  if (context.projectId !== null && !projects.some((project) => project.id === context.projectId)) {
    throw new Error('cloud session project catalog scope mismatch');
  }

  return Object.freeze({
    status: 'authenticated',
    api_base_url: session.api_base_url,
    expires_at: session.expires_at,
    user: Object.freeze({ ...identityBody }),
    workspace_context: Object.freeze({ ...contextBody }),
    tenants,
    projects,
  });
}

async function loadProjectedIdentityCatalog(
  session: TrustedCloudSession,
  dependencies: VaultBoundCloudRequestDependencies,
  itemKey: 'tenants' | 'projects',
  pathForPage: (page: number) => string,
  projectItem: (value: unknown) => Readonly<Record<string, unknown>>,
): Promise<readonly Readonly<Record<string, unknown>>[]> {
  const responseKeys = new Set([...CATALOG_PAGE_KEYS, itemKey]);
  const items: Readonly<Record<string, unknown>>[] = [];
  const seenIds = new Set<string>();
  let expectedTotal: number | null = null;
  for (let page = 1; page <= IDENTITY_CATALOG_MAX_PAGES; page += 1) {
    dependencies.signal?.throwIfAborted();
    const response = await authorizedFetch(
      session,
      dependencies,
      Object.freeze({ path: pathForPage(page), method: 'GET' }),
    );
    const body = await boundedJson(response, false, session.credential);
    if (!response.ok) throw new Error('cloud session identity catalog request failed');
    const record = exactRecord(body, responseKeys, 'cloud session identity catalog is invalid');
    if (
      !Array.isArray(record[itemKey]) ||
      !Number.isSafeInteger(record.total) ||
      (record.total as number) < 0 ||
      record.page !== page ||
      record.page_size !== IDENTITY_CATALOG_PAGE_SIZE ||
      record[itemKey].length > IDENTITY_CATALOG_PAGE_SIZE
    ) {
      throw new Error('cloud session identity catalog is invalid');
    }
    if (expectedTotal === null) expectedTotal = record.total as number;
    if (record.total !== expectedTotal) {
      throw new Error('cloud session identity catalog revision drift');
    }
    for (const value of record[itemKey]) {
      const item = projectItem(value);
      const id = item.id as string;
      if (seenIds.has(id)) throw new Error('cloud session identity catalog is invalid');
      seenIds.add(id);
      items.push(item);
    }
    if (items.length === expectedTotal) {
      if (new TextEncoder().encode(JSON.stringify(items)).byteLength > MAX_RESPONSE_BYTES) {
        throw new Error('cloud session identity catalog is too large');
      }
      return Object.freeze(items);
    }
    if (
      items.length > expectedTotal ||
      record[itemKey].length === 0 ||
      record[itemKey].length < IDENTITY_CATALOG_PAGE_SIZE
    ) {
      throw new Error('cloud session identity catalog is invalid');
    }
  }
  throw new Error('cloud session identity catalog page limit exceeded');
}

function projectTenant(value: unknown): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw new Error('cloud session tenant catalog is invalid');
  const id = identifier(value.id, 'cloud session tenant scope is invalid');
  const name = displayString(value.name, 'cloud session tenant name is invalid');
  const slug = optionalDisplayString(value.slug, 'cloud session tenant slug is invalid');
  const description = optionalNullableDisplayString(
    value.description,
    'cloud session tenant description is invalid',
  );
  return Object.freeze({
    id,
    name,
    ...(slug === undefined ? {} : { slug }),
    ...(description === undefined ? {} : { description }),
  });
}

function projectProject(value: unknown, tenantId: string): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw new Error('cloud session project catalog is invalid');
  const id = identifier(value.id, 'cloud session project scope is invalid');
  const observedTenantId = identifier(
    value.tenant_id,
    'cloud session project tenant scope is invalid',
  );
  if (observedTenantId !== tenantId) throw new Error('cloud session project scope mismatch');
  const name = displayString(value.name, 'cloud session project name is invalid');
  const description = optionalNullableDisplayString(
    value.description,
    'cloud session project description is invalid',
  );
  if (value.is_public !== undefined && typeof value.is_public !== 'boolean') {
    throw new Error('cloud session project visibility is invalid');
  }
  return Object.freeze({
    id,
    tenant_id: observedTenantId,
    name,
    ...(description === undefined ? {} : { description }),
    ...(value.is_public === undefined ? {} : { is_public: value.is_public }),
  });
}

function displayString(value: unknown, reason: string): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 1024 ||
    value !== value.trim() ||
    hasControlCharacter(value)
  ) {
    throw new Error(reason);
  }
  return value;
}

function optionalDisplayString(value: unknown, reason: string): string | undefined {
  return value === undefined ? undefined : displayString(value, reason);
}

function optionalNullableDisplayString(
  value: unknown,
  reason: string,
): string | null | undefined {
  return value === undefined || value === null ? value : displayString(value, reason);
}

function parseRequest(input: unknown): VaultBoundCloudRequestInput {
  const record = exactRecord(input, REQUEST_KEYS, 'cloud request is invalid');
  const path = record.path;
  if (
    typeof path !== 'string' ||
    !path.startsWith('/api/v1/') ||
    path.length > 2048 ||
    path.includes('#') ||
    path.includes('://') ||
    hasControlCharacter(path)
  ) {
    throw new Error('cloud request path is invalid');
  }
  const method = record.method ?? 'GET';
  if (typeof method !== 'string' || !METHODS.has(method)) {
    throw new Error('cloud request method is invalid');
  }
  const body = record.body;
  if (body !== undefined && !isRecord(body)) {
    throw new Error('cloud request body is invalid');
  }
  if (method === 'GET' && body !== undefined) {
    throw new Error('cloud request body is not allowed');
  }
  if (
    body !== undefined &&
    new TextEncoder().encode(JSON.stringify(body)).byteLength > MAX_REQUEST_BYTES
  ) {
    throw new Error('cloud request body is too large');
  }
  const form = parseForm(record.form, method);
  if (body !== undefined && form !== null) {
    throw new Error('cloud request body is invalid');
  }
  const mutation = parseMutation(record.mutation, method);
  const response = parseResponsePolicy(record.response);
  return Object.freeze({
    path,
    method: method as VaultBoundCloudRequestInput['method'],
    ...(body === undefined ? {} : { body: Object.freeze({ ...body }) }),
    ...(form === null ? {} : { form }),
    ...(mutation === null ? {} : { mutation }),
    ...(response === null ? {} : { response }),
  });
}

function parseForm(
  input: unknown,
  method: string,
): readonly VaultBoundCloudFormPart[] | null {
  if (input === undefined) return null;
  if (
    method === 'GET' ||
    !Array.isArray(input) ||
    input.length === 0 ||
    input.length > MAX_FORM_PARTS
  ) {
    throw new Error('cloud request form is invalid');
  }
  const parts: VaultBoundCloudFormPart[] = [];
  let totalBytes = 0;
  for (const inputPart of input) {
    if (!isRecord(inputPart) || !FORM_NAME.test(String(inputPart.name ?? ''))) {
      throw new Error('cloud request form is invalid');
    }
    const name = String(inputPart.name);
    totalBytes += utf8Length(name);
    if (inputPart.kind === 'text') {
      const part = exactRecord(inputPart, FORM_TEXT_KEYS, 'cloud request form is invalid');
      if (typeof part.value !== 'string' || utf8Length(part.value) > MAX_FORM_TEXT_BYTES) {
        throw new Error('cloud request form is invalid');
      }
      totalBytes += utf8Length(part.value);
      parts.push(Object.freeze({ kind: 'text', name, value: part.value }));
    } else if (inputPart.kind === 'file') {
      const part = exactRecord(inputPart, FORM_FILE_KEYS, 'cloud request form is invalid');
      const filename = validFilename(part.filename, 'cloud request filename is invalid');
      const mimeType = validMimeType(part.mime_type, 'cloud request MIME type is invalid');
      const bytes = decodeCanonicalBase64(
        part.bytes_base64,
        'cloud request file body is invalid',
      );
      totalBytes += utf8Length(filename) + utf8Length(mimeType) + bytes.byteLength;
      parts.push(
        Object.freeze({
          kind: 'file',
          name,
          filename,
          mime_type: mimeType,
          bytes_base64: String(part.bytes_base64),
        }),
      );
    } else {
      throw new Error('cloud request form is invalid');
    }
    if (totalBytes > MAX_REQUEST_BYTES) throw new Error('cloud request body is too large');
  }
  return Object.freeze(parts);
}

function parseResponsePolicy(input: unknown): VaultBoundCloudResponsePolicy | null {
  if (input === undefined) return null;
  const response = exactRecord(input, RESPONSE_KEYS, 'cloud request response is invalid');
  const maxAllowed = response.kind === 'binary'
    ? MAX_BINARY_RESPONSE_BYTES
    : response.kind === 'event-stream'
      ? MAX_EVENT_STREAM_RESPONSE_BYTES
      : null;
  if (
    maxAllowed === null ||
    !Number.isSafeInteger(response.max_bytes) ||
    Number(response.max_bytes) < 1 ||
    Number(response.max_bytes) > maxAllowed
  ) {
    throw new Error('cloud request response is invalid');
  }
  return Object.freeze({
    kind: response.kind as VaultBoundCloudResponsePolicy['kind'],
    max_bytes: Number(response.max_bytes),
  });
}

function parseMutation(
  input: unknown,
  method: string,
): VaultBoundCloudRequestInput['mutation'] | null {
  if (input === undefined) return null;
  if (isRecord(input) && input.kind === 'idempotency-only') {
    const mutation = exactRecord(
      input,
      IDEMPOTENCY_MUTATION_KEYS,
      'cloud request mutation is invalid',
    );
    if (method === 'GET') throw new Error('cloud request mutation is invalid');
    return Object.freeze({
      kind: 'idempotency-only',
      idempotency_key: identifier(
        mutation.idempotency_key,
        'cloud request mutation is invalid',
      ),
    });
  }
  const mutation = exactRecord(input, MUTATION_KEYS, 'cloud request mutation is invalid');
  if (
    method === 'GET' ||
    !Number.isSafeInteger(mutation.expected_revision) ||
    Number(mutation.expected_revision) < 0
  ) {
    throw new Error('cloud request mutation is invalid');
  }
  return Object.freeze({
    expected_revision: Number(mutation.expected_revision),
    idempotency_key: identifier(
      mutation.idempotency_key,
      'cloud request mutation is invalid',
    ),
  });
}

function authorizeEndpoint(request: VaultBoundCloudRequestInput): AuthorizedEndpoint {
  const target = new URL(request.path, 'https://desktop.invalid');
  const segments = target.pathname.split('/');
  if (
    target.origin !== 'https://desktop.invalid' ||
    target.username ||
    target.password ||
    target.hash
  ) {
    throw new Error('cloud request endpoint is not allowed');
  }
  if (request.form !== undefined || request.response !== undefined) {
    const specializedEndpoint = authorizeCloudProductEndpoint(request, target);
    if (specializedEndpoint) return specializedEndpoint;
    throw new Error('cloud request endpoint is not allowed');
  }
  if (
    target.pathname === '/api/v1/workspace-context' &&
    request.method === 'GET' &&
    request.form === undefined &&
    request.response === undefined &&
    [...target.searchParams].length === 0
  ) {
    return Object.freeze({
      kind: 'workspace-context',
      tenantId: null,
      projectId: null,
    });
  }
  if (
    target.pathname === '/api/v1/auth/me' &&
    request.method === 'GET' &&
    request.form === undefined &&
    request.response === undefined &&
    [...target.searchParams].length === 0
  ) {
    return Object.freeze({
      kind: 'identity',
      tenantId: null,
      projectId: null,
    });
  }
  if (segments[1] === 'api' && segments[2] === 'v1' && BACKEND_ROOTS.has(segments[3] ?? '')) {
    return authorizeBackendEndpoint(request, target, segments);
  }
  if (
    segments.length === 6 &&
    segments[1] === 'api' &&
    segments[2] === 'v1' &&
    segments[3] === 'projects' &&
    (segments[5] === 'playbooks' || segments[5] === 'reflection-verdicts') &&
    request.method === 'GET' &&
    exactQuery(target.searchParams, [['limit', '200']])
  ) {
    return Object.freeze({
      kind: 'project-playbooks',
      tenantId: null,
      projectId: identifier(segments[4], 'cloud request project scope is invalid'),
    });
  }
  const productEndpoint = authorizeCloudProductEndpoint(request, target);
  if (productEndpoint) return productEndpoint;
  throw new Error('cloud request endpoint is not allowed');
}

function authorizeBackendEndpoint(
  request: VaultBoundCloudRequestInput,
  target: URL,
  segments: readonly string[],
): AuthorizedEndpoint {
  if (
    segments.length === 5 &&
    segments[4] === 'types' &&
    request.method === 'GET' &&
    [...target.searchParams].length === 0
  ) {
    return Object.freeze({
      kind: 'backend-stores',
      tenantId: null,
      projectId: null,
    });
  }
  const tenantId = exactTenantQuery(target.searchParams);
  const baseCollection =
    segments.length === 4 && (request.method === 'GET' || request.method === 'POST');
  const rawTest = segments.length === 5 && segments[4] === 'test' && request.method === 'POST';
  const storedResource =
    segments.length === 5 &&
    identifierOrNull(segments[4]) !== null &&
    (request.method === 'PUT' || request.method === 'DELETE');
  const storedTest =
    segments.length === 6 &&
    identifierOrNull(segments[4]) !== null &&
    segments[5] === 'test' &&
    request.method === 'POST';
  if (!baseCollection && !rawTest && !storedResource && !storedTest) {
    throw new Error('cloud request endpoint is not allowed');
  }
  return Object.freeze({ kind: 'backend-stores', tenantId, projectId: null });
}

function parseTrustedCloudSession(input: unknown): TrustedCloudSession {
  if (
    !isRecord(input) ||
    input.version !== 1 ||
    input.runtime_mode !== 'cloud' ||
    input.credential_kind !== 'cloud_bearer' ||
    typeof input.api_base_url !== 'string' ||
    typeof input.credential !== 'string' ||
    !input.credential ||
    input.credential !== input.credential.trim() ||
    (input.expires_at !== null && typeof input.expires_at !== 'string')
  ) {
    throw new Error('trusted cloud session is unavailable');
  }
  const baseUrl = new URL(input.api_base_url);
  if (
    !secureOrigin(baseUrl) ||
    baseUrl.username ||
    baseUrl.password ||
    baseUrl.pathname !== '/' ||
    baseUrl.search ||
    baseUrl.hash
  ) {
    throw new Error('trusted cloud session origin is invalid');
  }
  if (input.expires_at !== null) {
    const expiresAt = Date.parse(input.expires_at);
    if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      throw new Error('trusted cloud session is expired');
    }
  }
  return Object.freeze({
    version: 1,
    api_base_url: baseUrl.origin,
    runtime_mode: 'cloud',
    credential_kind: 'cloud_bearer',
    credential: input.credential,
    expires_at: input.expires_at,
  });
}

async function authorizedFetch(
  session: TrustedCloudSession,
  dependencies: VaultBoundCloudRequestDependencies,
  request: VaultBoundCloudRequestInput,
): Promise<Response> {
  const target = new URL(request.path, `${session.api_base_url}/`);
  if (target.origin !== session.api_base_url) throw new Error('cloud request origin mismatch');
  const headers = new Headers({
    Accept: request.response?.kind === 'binary'
      ? 'application/octet-stream'
      : request.response?.kind === 'event-stream'
        ? 'text/event-stream'
        : 'application/json',
    Authorization: `Bearer ${session.credential}`,
  });
  if (request.body !== undefined) headers.set('Content-Type', 'application/json');
  if (request.mutation) {
    if ('expected_revision' in request.mutation) {
      headers.set('X-Expected-Revision', String(request.mutation.expected_revision));
    }
    headers.set('Idempotency-Key', request.mutation.idempotency_key);
  }
  const form = request.form === undefined ? undefined : reconstructFormData(request.form);
  return dependencies.fetch(target.toString(), {
    method: request.method ?? 'GET',
    headers,
    credentials: 'omit',
    redirect: 'manual',
    body: form ?? (request.body === undefined ? undefined : JSON.stringify(request.body)),
    signal: dependencies.signal,
  });
}

function reconstructFormData(parts: readonly VaultBoundCloudFormPart[]): FormData {
  const form = new FormData();
  for (const part of parts) {
    if (part.kind === 'text') {
      form.append(part.name, part.value);
      continue;
    }
    const bytes = decodeCanonicalBase64(part.bytes_base64, 'cloud request file body is invalid');
    const body = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(body).set(bytes);
    form.append(part.name, new Blob([body], { type: part.mime_type }), part.filename);
  }
  return form;
}

async function boundedBinary(
  response: Response,
  maxBytes: number,
  protectedCredential: string,
  requestPath: string,
): Promise<Readonly<Record<string, unknown>>> {
  const declaredLengthHeader = response.headers.get('content-length');
  const declaredLength = Number(declaredLengthHeader ?? '0');
  if (
    declaredLengthHeader !== null &&
    (!/^\d+$/u.test(declaredLengthHeader) || !Number.isSafeInteger(declaredLength))
  ) {
    await cancelResponseBody(response);
    throw new Error('cloud binary response contract is invalid');
  }
  if (declaredLength > maxBytes) {
    await cancelResponseBody(response);
    throw new Error('cloud binary response is too large');
  }
  const mimeType = response.headers.get('content-type')?.split(';', 1)[0]?.trim();
  validMimeType(mimeType, 'cloud binary response MIME type is invalid');
  const filename = binaryFilename(response.headers.get('content-disposition'), requestPath);
  const bytes = await readBoundedResponseBytes(response, maxBytes);
  if (containsBytes(bytes, new TextEncoder().encode(protectedCredential))) {
    throw new Error('cloud response contains protected credential');
  }
  return Object.freeze({
    kind: 'binary',
    bytes_base64: Buffer.from(bytes).toString('base64'),
    size_bytes: bytes.byteLength,
    mime_type: mimeType,
    filename,
  });
}

async function boundedEventStream(
  response: Response,
  maxBytes: number,
  protectedCredential: string,
): Promise<Readonly<Record<string, unknown>>> {
  const declaredLengthHeader = response.headers.get('content-length');
  const declaredLength = Number(declaredLengthHeader ?? '0');
  if (
    declaredLengthHeader !== null &&
    (!/^\d+$/u.test(declaredLengthHeader) || !Number.isSafeInteger(declaredLength))
  ) {
    await cancelResponseBody(response);
    throw new Error('cloud event stream response contract is invalid');
  }
  if (declaredLength > maxBytes) {
    await cancelResponseBody(response);
    throw new Error('cloud event stream response is too large');
  }
  const mimeType = response.headers.get('content-type')?.split(';', 1)[0]?.trim();
  if (mimeType !== 'text/event-stream') {
    await cancelResponseBody(response);
    throw new Error('cloud event stream response MIME type is invalid');
  }
  const bytes = await readBoundedResponseBytes(
    response,
    maxBytes,
    'cloud event stream response is too large',
  );
  if (containsBytes(bytes, new TextEncoder().encode(protectedCredential))) {
    throw new Error('cloud response contains protected credential');
  }
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    throw new Error('cloud event stream response encoding is invalid');
  }
  return Object.freeze({
    kind: 'event-stream',
    text,
    size_bytes: bytes.byteLength,
    mime_type: 'text/event-stream',
  });
}

async function readBoundedResponseBytes(
  response: Response,
  maxBytes: number,
  tooLargeReason = 'cloud binary response is too large',
): Promise<Uint8Array> {
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let receivedBytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      receivedBytes += chunk.value.byteLength;
      if (receivedBytes > maxBytes) {
        await reader.cancel(tooLargeReason);
        throw new Error(tooLargeReason);
      }
      chunks.push(chunk.value);
    }
  } catch (error) {
    await reader.cancel(error).catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(receivedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function binaryFilename(contentDisposition: string | null, requestPath: string): string {
  if (contentDisposition !== null) {
    const tokens = contentDisposition.split(';').map((token) => token.trim());
    if (tokens.shift()?.toLowerCase() !== 'attachment') {
      throw new Error('cloud binary response filename is invalid');
    }
    let filename: string | null = null;
    let encodedFilename: string | null = null;
    for (const token of tokens) {
      const separator = token.indexOf('=');
      if (separator < 1) throw new Error('cloud binary response filename is invalid');
      const key = token.slice(0, separator).trim().toLowerCase();
      const value = token.slice(separator + 1).trim();
      if (key === 'filename' && filename === null) {
        filename = value.startsWith('"') && value.endsWith('"')
          ? value.slice(1, -1)
          : value;
      } else if (key === 'filename*' && encodedFilename === null) {
        encodedFilename = decodeRfc5987Filename(value);
      } else {
        throw new Error('cloud binary response filename is invalid');
      }
    }
    const preferred = encodedFilename ?? filename;
    if (preferred !== null) {
      return validFilename(preferred, 'cloud binary response filename is invalid');
    }
  }
  const target = new URL(requestPath, 'https://desktop.invalid');
  const segments = target.pathname.split('/');
  const fallback = segments[3] === 'artifacts' ? segments[4] : 'download';
  return validFilename(fallback, 'cloud binary response filename is invalid');
}

function decodeRfc5987Filename(value: string): string {
  if (!value.toUpperCase().startsWith("UTF-8''")) {
    throw new Error('cloud binary response filename is invalid');
  }
  try {
    return decodeURIComponent(value.slice(7));
  } catch {
    throw new Error('cloud binary response filename is invalid');
  }
}

function containsBytes(haystack: Uint8Array, needle: Uint8Array): boolean {
  if (needle.byteLength === 0 || needle.byteLength > haystack.byteLength) return false;
  const body = Buffer.from(haystack.buffer, haystack.byteOffset, haystack.byteLength);
  const protectedValue = Buffer.from(needle.buffer, needle.byteOffset, needle.byteLength);
  return body.includes(protectedValue);
}

async function boundedJson(
  response: Response,
  allowNoContent = false,
  protectedCredential: string | null = null,
): Promise<unknown> {
  const declaredLengthHeader = response.headers.get('content-length');
  const declaredLength = Number(declaredLengthHeader ?? '0');
  if (
    declaredLengthHeader !== null &&
    (!/^\d+$/u.test(declaredLengthHeader) || !Number.isSafeInteger(declaredLength))
  ) {
    await cancelResponseBody(response);
    throw new Error('cloud response contract is invalid');
  }
  if (declaredLength > MAX_RESPONSE_BYTES) {
    await cancelResponseBody(response);
    throw new Error('cloud response is too large');
  }
  const text = await readBoundedResponseText(response);
  if (!text && allowNoContent && response.status === 204) return null;
  if (!(response.headers.get('content-type') ?? '').toLowerCase().includes('application/json')) {
    throw new Error('cloud response contract is invalid');
  }
  if (protectedCredential && text.includes(protectedCredential)) {
    throw new Error('cloud response contains protected credential');
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error('cloud response contract is invalid');
  }
}

async function readBoundedResponseText(response: Response): Promise<string> {
  if (!response.body) return '';
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let receivedBytes = 0;
  let text = '';
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      receivedBytes += chunk.value.byteLength;
      if (receivedBytes > MAX_RESPONSE_BYTES) {
        await reader.cancel('cloud response is too large');
        throw new Error('cloud response is too large');
      }
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    return text;
  } catch (error) {
    await reader.cancel(error).catch(() => undefined);
    if (error instanceof TypeError) throw new Error('cloud response contract is invalid');
    throw error;
  } finally {
    reader.releaseLock();
  }
}

async function cancelResponseBody(response: Response): Promise<void> {
  await response.body?.cancel().catch(() => undefined);
}

function parseObservedContext(
  input: unknown,
): Readonly<{ tenantId: string; projectId: string | null; workspaceId: string | null }> {
  if (!isRecord(input) || !isRecord(input.context)) {
    throw new Error('cloud request scope contract is invalid');
  }
  return Object.freeze({
    tenantId: identifier(input.context.tenant_id, 'cloud request tenant scope is invalid'),
    projectId: identifierOrNull(input.context.project_id),
    workspaceId: identifierOrNull(input.context.workspace_id),
  });
}

function assertEndpointScope(
  endpoint: AuthorizedEndpoint,
  context: Readonly<{ tenantId: string; projectId: string | null; workspaceId: string | null }>,
): void {
  if (endpoint.tenantId !== null && endpoint.tenantId !== context.tenantId) {
    throw new Error('cloud request tenant scope mismatch');
  }
  if (endpoint.projectId !== null && endpoint.projectId !== context.projectId) {
    throw new Error('cloud request project scope mismatch');
  }
  if (endpoint.workspaceId != null && endpoint.workspaceId !== context.workspaceId) {
    throw new Error('cloud request workspace scope mismatch');
  }
}

function exactTenantQuery(query: URLSearchParams): string {
  const values = query.getAll('tenant_id');
  if (values.length !== 1 || [...query].length !== 1) {
    throw new Error('cloud request tenant scope is invalid');
  }
  return identifier(values[0], 'cloud request tenant scope is invalid');
}

function exactQuery(
  query: URLSearchParams,
  expected: readonly (readonly [string, string])[],
): boolean {
  const entries = [...query.entries()];
  return (
    entries.length === expected.length &&
    entries.every(
      ([key, value], index) => key === expected[index]?.[0] && value === expected[index]?.[1],
    )
  );
}

function identifier(value: unknown, reason: string): string {
  const parsed = identifierOrNull(value);
  if (parsed === null) throw new Error(reason);
  return parsed;
}

function identifierOrNull(value: unknown): string | null {
  return typeof value === 'string' &&
    value.length > 0 &&
    value.length <= 256 &&
    value === value.trim() &&
    !hasControlCharacter(value)
    ? value
    : null;
}

function validFilename(value: unknown, reason: string): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value !== value.trim() ||
    utf8Length(value) > 255 ||
    value === '.' ||
    value === '..' ||
    value.includes('/') ||
    value.includes('\\') ||
    hasControlCharacter(value)
  ) {
    throw new Error(reason);
  }
  return value;
}

function validMimeType(value: unknown, reason: string): string {
  if (
    typeof value !== 'string' ||
    value.length > 127 ||
    value !== value.trim() ||
    !MIME_TYPE.test(value)
  ) {
    throw new Error(reason);
  }
  return value;
}

function decodeCanonicalBase64(value: unknown, reason: string): Uint8Array {
  if (typeof value !== 'string') throw new Error(reason);
  const bytes = Buffer.from(value, 'base64');
  if (bytes.toString('base64') !== value) throw new Error(reason);
  return bytes;
}

function utf8Length(value: string): number {
  return Buffer.byteLength(value, 'utf8');
}

function secureOrigin(url: URL): boolean {
  return (
    url.protocol === 'https:' ||
    (url.protocol === 'http:' &&
      ['localhost', '127.0.0.1', '::1', '[::1]'].includes(url.hostname.toLowerCase()))
  );
}

function exactRecord(
  input: unknown,
  allowedKeys: ReadonlySet<string>,
  reason: string,
): Record<string, unknown> {
  if (!isRecord(input) || Object.keys(input).some((key) => !allowedKeys.has(key))) {
    throw new Error(reason);
  }
  return input;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasControlCharacter(value: string): boolean {
  return /[\u0000-\u001f\u007f]/u.test(value);
}

function validRequestId(value: unknown): string {
  if (typeof value !== 'string' || !REQUEST_ID.test(value)) {
    throw new Error('cloud request id is invalid');
  }
  return value;
}
