export type CloudSocketKind = 'agent' | 'terminal' | 'voice';

export type CloudSocketScope = Readonly<{
  tenant_id: string;
  project_id: string;
  workspace_id: string | null;
  conversation_id: string | null;
}>;

export type VaultBoundCloudSocketInput = Readonly<{
  kind: CloudSocketKind;
  url: string;
  scope: CloudSocketScope;
  terminal?: Readonly<{
    session_id: string;
    resume_token: string | null;
  }>;
}>;

export type AuthorizedCloudSocket = Readonly<{
  kind: CloudSocketKind;
  url: string;
  protocols: readonly string[];
  scope: CloudSocketScope;
  binary: Readonly<{
    client_to_server: boolean;
    server_to_client: boolean;
  }>;
  limits: Readonly<{
    max_frame_bytes: number;
    max_aggregate_bytes: number;
    connect_timeout_ms: number;
    idle_timeout_ms: number;
  }>;
}>;

export type CloudSocketFrameDirection = 'client_to_server' | 'server_to_client';

export type CloudSocketFrame = Readonly<{
  binary: boolean;
  byteLength: number;
  text?: string;
}>;

export type VaultBoundCloudSocketDependencies = Readonly<{
  loadTrustedSession(): Promise<unknown>;
  fetch(url: string, init: RequestInit): Promise<Response>;
  now?: () => number;
}>;

export type CloudSocketCloseDirective = Readonly<{
  code: number;
  reason: string;
}>;

export type CloudSocketExecutionLease = Readonly<{
  signal: AbortSignal;
  release(): void;
}>;

export type CloudSocketFrameReservation = Readonly<{
  release(): void;
}>;

type TrustedCloudSession = Readonly<{
  apiBaseUrl: string;
  credential: string;
}>;

type TimerScheduler = Readonly<{
  setTimeout(callback: () => void, delayMs: number): unknown;
  clearTimeout(handle: unknown): void;
}>;

export type CloudSocketExecutionRegistryOptions = Readonly<{
  perOwnerLimit: number;
  globalLimit: number;
  scheduler?: TimerScheduler;
}>;

type ActiveCloudSocket = {
  ownerId: number;
  policy: AuthorizedCloudSocket;
  controller: AbortController;
  onClose: (directive: CloudSocketCloseDirective) => void;
  phase: 'connecting' | 'open';
  timer: unknown;
  pendingBytes: number;
};

const INPUT_KEYS = new Set(['kind', 'url', 'scope', 'terminal']);
const SCOPE_KEYS = new Set(['tenant_id', 'project_id', 'workspace_id', 'conversation_id']);
const TERMINAL_KEYS = new Set(['session_id', 'resume_token']);
const SOCKET_ID = /^[A-Za-z0-9_-]{16,128}$/u;
const MAX_CONTEXT_RESPONSE_BYTES = 64 * 1024;

const SOCKET_LIMITS: Readonly<Record<CloudSocketKind, AuthorizedCloudSocket['limits']>> =
  Object.freeze({
    agent: Object.freeze({
      max_frame_bytes: 512 * 1024,
      max_aggregate_bytes: 2 * 1024 * 1024,
      connect_timeout_ms: 15_000,
      idle_timeout_ms: 75_000,
    }),
    terminal: Object.freeze({
      max_frame_bytes: 128 * 1024,
      max_aggregate_bytes: 256 * 1024,
      connect_timeout_ms: 15_000,
      idle_timeout_ms: 60_000,
    }),
    voice: Object.freeze({
      max_frame_bytes: 256 * 1024,
      max_aggregate_bytes: 2 * 1024 * 1024,
      connect_timeout_ms: 15_000,
      idle_timeout_ms: 30_000,
    }),
  });

const SOCKET_BINARY: Readonly<Record<CloudSocketKind, AuthorizedCloudSocket['binary']>> =
  Object.freeze({
    agent: Object.freeze({ client_to_server: false, server_to_client: false }),
    terminal: Object.freeze({ client_to_server: false, server_to_client: false }),
    voice: Object.freeze({ client_to_server: true, server_to_client: true }),
  });

const defaultScheduler: TimerScheduler = Object.freeze({
  setTimeout(callback, delayMs) {
    const handle = setTimeout(callback, delayMs);
    handle.unref?.();
    return handle;
  },
  clearTimeout(handle) {
    clearTimeout(handle as ReturnType<typeof setTimeout>);
  },
});

export async function authorizeVaultBoundCloudSocket(
  input: unknown,
  dependencies: VaultBoundCloudSocketDependencies
): Promise<AuthorizedCloudSocket> {
  const request = parseSocketInput(input);
  const session = parseTrustedCloudSession(
    await dependencies.loadTrustedSession(),
    dependencies.now?.() ?? Date.now()
  );
  const observedScope = await observeWorkspaceContext(session, dependencies);
  assertObservedScope(request.scope, observedScope);
  const target = authorizeSocketUrl(request, session);
  const protocols = ['memstack.auth', session.credential];
  if (request.kind === 'terminal' && request.terminal?.resume_token) {
    protocols.push('memstack.terminal-v2', request.terminal.resume_token);
  }
  return Object.freeze({
    kind: request.kind,
    url: target.toString(),
    protocols: Object.freeze(protocols),
    scope: request.scope,
    binary: SOCKET_BINARY[request.kind],
    limits: SOCKET_LIMITS[request.kind],
  });
}

export function assertCloudSocketFrame(
  policy: AuthorizedCloudSocket,
  direction: CloudSocketFrameDirection,
  frame: CloudSocketFrame
): void {
  if (direction !== 'client_to_server' && direction !== 'server_to_client') {
    throw new Error('cloud socket frame direction is invalid');
  }
  if (!Number.isSafeInteger(frame.byteLength) || frame.byteLength < 0) {
    throw new Error('cloud socket frame size is invalid');
  }
  if (frame.byteLength > policy.limits.max_frame_bytes) {
    throw new Error('cloud socket frame is too large');
  }
  if (frame.binary) {
    if (!policy.binary[direction]) {
      throw new Error('cloud socket binary frame is not allowed');
    }
    if (frame.text !== undefined) throw new Error('cloud socket binary frame is invalid');
    return;
  }
  if (typeof frame.text !== 'string') throw new Error('cloud socket text frame is invalid');
  if (new TextEncoder().encode(frame.text).byteLength !== frame.byteLength) {
    throw new Error('cloud socket frame size is invalid');
  }
  const protectedCredential = policy.protocols[1];
  if (protectedCredential && frame.text.includes(protectedCredential)) {
    throw new Error('cloud socket frame contains protected credential');
  }
  let value: unknown;
  try {
    value = JSON.parse(frame.text) as unknown;
  } catch {
    throw new Error('cloud socket text frame is invalid');
  }
  if (!isRecord(value)) throw new Error('cloud socket text frame is invalid');
  if (policy.kind === 'agent') assertStructuredFrameScope(value, policy.scope);
}

export class CloudSocketExecutionRegistry {
  readonly #perOwnerLimit: number;
  readonly #globalLimit: number;
  readonly #scheduler: TimerScheduler;
  readonly #connections = new Map<string, ActiveCloudSocket>();

  constructor(options: CloudSocketExecutionRegistryOptions) {
    if (!positiveInteger(options.perOwnerLimit) || !positiveInteger(options.globalLimit)) {
      throw new Error('cloud socket connection limits are invalid');
    }
    if (options.perOwnerLimit > options.globalLimit) {
      throw new Error('cloud socket connection limits are invalid');
    }
    this.#perOwnerLimit = options.perOwnerLimit;
    this.#globalLimit = options.globalLimit;
    this.#scheduler = options.scheduler ?? defaultScheduler;
  }

  get activeCount(): number {
    return this.#connections.size;
  }

  begin(
    ownerId: number,
    socketId: unknown,
    policy: AuthorizedCloudSocket,
    onClose: (directive: CloudSocketCloseDirective) => void
  ): CloudSocketExecutionLease {
    const id = validSocketId(socketId);
    validOwnerId(ownerId);
    validatePolicyLimits(policy);
    if (this.#connections.has(id)) throw new Error('cloud socket id is already active');
    if (this.#connections.size >= this.#globalLimit) {
      throw new Error('cloud socket global connection limit exceeded');
    }
    if (this.#ownerConnectionCount(ownerId) >= this.#perOwnerLimit) {
      throw new Error('cloud socket owner connection limit exceeded');
    }
    const controller = new AbortController();
    const connection: ActiveCloudSocket = {
      ownerId,
      policy,
      controller,
      onClose,
      phase: 'connecting',
      timer: null,
      pendingBytes: 0,
    };
    connection.timer = this.#scheduler.setTimeout(() => {
      this.#terminate(id, connection, 4000, 'cloud socket connect timed out');
    }, policy.limits.connect_timeout_ms);
    this.#connections.set(id, connection);
    let released = false;
    return Object.freeze({
      signal: controller.signal,
      release: () => {
        if (released) return;
        released = true;
        this.complete(ownerId, id);
      },
    });
  }

  markConnected(ownerId: number, socketId: unknown): boolean {
    const connection = this.#owned(ownerId, socketId);
    if (!connection) return false;
    connection.phase = 'open';
    this.#armIdleTimer(String(socketId), connection);
    return true;
  }

  touch(ownerId: number, socketId: unknown): boolean {
    const connection = this.#owned(ownerId, socketId);
    if (!connection || connection.phase !== 'open') return false;
    this.#armIdleTimer(String(socketId), connection);
    return true;
  }

  reserveFrame(
    ownerId: number,
    socketId: unknown,
    direction: CloudSocketFrameDirection,
    frame: CloudSocketFrame
  ): CloudSocketFrameReservation {
    const id = validSocketId(socketId);
    const connection = this.#connections.get(id);
    if (!connection || connection.ownerId !== ownerId || connection.phase !== 'open') {
      throw new Error('cloud socket is unavailable');
    }
    try {
      assertCloudSocketFrame(connection.policy, direction, frame);
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'cloud socket frame is invalid';
      const code = reason.includes('too large') ? 1009 : 1008;
      this.#terminate(id, connection, code, reason);
      throw error;
    }
    if (connection.pendingBytes + frame.byteLength > connection.policy.limits.max_aggregate_bytes) {
      const error = new Error('cloud socket aggregate is too large');
      this.#terminate(id, connection, 1009, error.message);
      throw error;
    }
    connection.pendingBytes += frame.byteLength;
    this.#armIdleTimer(id, connection);
    let released = false;
    return Object.freeze({
      release: () => {
        if (released) return;
        released = true;
        connection.pendingBytes = Math.max(0, connection.pendingBytes - frame.byteLength);
      },
    });
  }

  pendingBytes(ownerId: number, socketId: unknown): number {
    const connection = this.#owned(ownerId, socketId);
    return connection?.pendingBytes ?? 0;
  }

  close(ownerId: number, socketId: unknown, code = 1000, reason = ''): boolean {
    const id = validSocketId(socketId);
    const connection = this.#connections.get(id);
    if (!connection || connection.ownerId !== ownerId) return false;
    this.#terminate(id, connection, code, reason);
    return true;
  }

  complete(ownerId: number, socketId: unknown): boolean {
    const id = validSocketId(socketId);
    const connection = this.#connections.get(id);
    if (!connection || connection.ownerId !== ownerId) return false;
    this.#remove(id, connection, new Error('cloud socket completed'));
    return true;
  }

  cancelOwner(ownerId: number): number {
    validOwnerId(ownerId);
    let cancelled = 0;
    for (const [id, connection] of [...this.#connections]) {
      if (connection.ownerId !== ownerId) continue;
      this.#terminate(id, connection, 1001, 'cloud socket owner was destroyed');
      cancelled += 1;
    }
    return cancelled;
  }

  cancelAll(): number {
    let cancelled = 0;
    for (const [id, connection] of [...this.#connections]) {
      this.#terminate(id, connection, 1001, 'cloud socket broker is shutting down');
      cancelled += 1;
    }
    return cancelled;
  }

  #owned(ownerId: number, socketId: unknown): ActiveCloudSocket | null {
    validOwnerId(ownerId);
    const id = validSocketId(socketId);
    const connection = this.#connections.get(id);
    return connection?.ownerId === ownerId ? connection : null;
  }

  #ownerConnectionCount(ownerId: number): number {
    let count = 0;
    for (const connection of this.#connections.values()) {
      if (connection.ownerId === ownerId) count += 1;
    }
    return count;
  }

  #armIdleTimer(id: string, connection: ActiveCloudSocket): void {
    this.#scheduler.clearTimeout(connection.timer);
    connection.timer = this.#scheduler.setTimeout(() => {
      this.#terminate(id, connection, 4001, 'cloud socket idle timed out');
    }, connection.policy.limits.idle_timeout_ms);
  }

  #terminate(id: string, connection: ActiveCloudSocket, code: number, reason: string): void {
    if (this.#connections.get(id) !== connection) return;
    this.#remove(id, connection, new Error(reason));
    try {
      connection.onClose(Object.freeze({ code, reason }));
    } catch {}
  }

  #remove(id: string, connection: ActiveCloudSocket, reason: Error): void {
    if (this.#connections.get(id) !== connection) return;
    this.#connections.delete(id);
    this.#scheduler.clearTimeout(connection.timer);
    connection.controller.abort(reason);
  }
}

function parseSocketInput(input: unknown): VaultBoundCloudSocketInput {
  const record = exactRecord(input, INPUT_KEYS, 'cloud socket request is invalid');
  if (record.kind !== 'agent' && record.kind !== 'terminal' && record.kind !== 'voice') {
    throw new Error('cloud socket kind is invalid');
  }
  if (
    typeof record.url !== 'string' ||
    record.url.length > 4096 ||
    hasControlCharacter(record.url)
  ) {
    throw new Error('cloud socket URL is invalid');
  }
  const scope = parseScope(record.scope);
  const terminal = parseTerminal(record.terminal, record.kind);
  return Object.freeze({
    kind: record.kind,
    url: record.url,
    scope,
    ...(terminal === null ? {} : { terminal }),
  });
}

function parseScope(input: unknown): CloudSocketScope {
  const record = exactRecord(input, SCOPE_KEYS, 'cloud socket scope is invalid');
  return Object.freeze({
    tenant_id: identifier(record.tenant_id, 'cloud socket tenant scope is invalid'),
    project_id: identifier(record.project_id, 'cloud socket project scope is invalid'),
    workspace_id: nullableIdentifier(
      record.workspace_id,
      'cloud socket workspace scope is invalid'
    ),
    conversation_id: nullableIdentifier(
      record.conversation_id,
      'cloud socket conversation scope is invalid'
    ),
  });
}

function parseTerminal(
  input: unknown,
  kind: CloudSocketKind
): VaultBoundCloudSocketInput['terminal'] | null {
  if (kind !== 'terminal') {
    if (input !== undefined) throw new Error('cloud socket terminal authority is invalid');
    return null;
  }
  const record = exactRecord(input, TERMINAL_KEYS, 'cloud socket terminal authority is invalid');
  return Object.freeze({
    session_id: identifier(record.session_id, 'cloud socket terminal session is invalid'),
    resume_token: nullableIdentifier(
      record.resume_token,
      'cloud socket terminal resume authority is invalid'
    ),
  });
}

function parseTrustedCloudSession(input: unknown, nowMs: number): TrustedCloudSession {
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
  let base: URL;
  try {
    base = new URL(input.api_base_url);
  } catch {
    throw new Error('trusted cloud session origin is invalid');
  }
  if (
    !secureOrigin(base) ||
    base.username ||
    base.password ||
    base.pathname !== '/' ||
    base.search ||
    base.hash
  ) {
    throw new Error('trusted cloud session origin is invalid');
  }
  if (input.expires_at !== null) {
    const expiresAt = Date.parse(input.expires_at);
    if (!Number.isFinite(expiresAt) || expiresAt <= nowMs) {
      throw new Error('trusted cloud session is expired');
    }
  }
  return Object.freeze({
    apiBaseUrl: base.origin,
    credential: input.credential,
  });
}

async function observeWorkspaceContext(
  session: TrustedCloudSession,
  dependencies: VaultBoundCloudSocketDependencies
): Promise<Readonly<{ tenantId: string; projectId: string; workspaceId: string | null }>> {
  const response = await dependencies.fetch(`${session.apiBaseUrl}/api/v1/workspace-context`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${session.credential}`,
    },
    credentials: 'omit',
    redirect: 'manual',
  });
  if (!response.ok) throw new Error('cloud socket scope observation failed');
  const text = await boundedResponseText(response);
  if (text.includes(session.credential)) {
    throw new Error('cloud socket scope response contains protected credential');
  }
  if (!(response.headers.get('content-type') ?? '').toLowerCase().includes('application/json')) {
    throw new Error('cloud socket scope contract is invalid');
  }
  let value: unknown;
  try {
    value = JSON.parse(text) as unknown;
  } catch {
    throw new Error('cloud socket scope contract is invalid');
  }
  if (!isRecord(value) || !isRecord(value.context)) {
    throw new Error('cloud socket scope contract is invalid');
  }
  return Object.freeze({
    tenantId: identifier(value.context.tenant_id, 'cloud socket tenant scope is invalid'),
    projectId: identifier(value.context.project_id, 'cloud socket project scope is invalid'),
    workspaceId:
      value.context.workspace_id === undefined
        ? null
        : nullableIdentifier(
            value.context.workspace_id,
            'cloud socket workspace scope is invalid'
          ),
  });
}

async function boundedResponseText(response: Response): Promise<string> {
  const declared = response.headers.get('content-length');
  if (
    declared !== null &&
    (!/^\d+$/u.test(declared) || Number(declared) > MAX_CONTEXT_RESPONSE_BYTES)
  ) {
    await response.body?.cancel().catch(() => undefined);
    throw new Error('cloud socket scope response is too large');
  }
  if (!response.body) return '';
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let bytes = 0;
  let text = '';
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > MAX_CONTEXT_RESPONSE_BYTES) {
        await reader.cancel('cloud socket scope response is too large');
        throw new Error('cloud socket scope response is too large');
      }
      text += decoder.decode(chunk.value, { stream: true });
    }
    return text + decoder.decode();
  } catch (error) {
    await reader.cancel(error).catch(() => undefined);
    if (error instanceof TypeError) throw new Error('cloud socket scope contract is invalid');
    throw error;
  } finally {
    reader.releaseLock();
  }
}

function assertObservedScope(
  requested: CloudSocketScope,
  observed: Readonly<{
    tenantId: string;
    projectId: string;
    workspaceId: string | null;
  }>
): void {
  if (requested.tenant_id !== observed.tenantId) {
    throw new Error('cloud socket tenant scope mismatch');
  }
  if (requested.project_id !== observed.projectId) {
    throw new Error('cloud socket project scope mismatch');
  }
  if (requested.workspace_id !== observed.workspaceId) {
    throw new Error('cloud socket workspace scope mismatch');
  }
}

function authorizeSocketUrl(
  request: VaultBoundCloudSocketInput,
  session: TrustedCloudSession
): URL {
  let target: URL;
  try {
    target = new URL(request.url);
  } catch {
    throw new Error('cloud socket URL is invalid');
  }
  if (
    target.origin !== websocketOrigin(session.apiBaseUrl) ||
    target.username ||
    target.password ||
    target.hash
  ) {
    throw new Error('cloud socket origin mismatch');
  }
  if (request.kind === 'agent') authorizeAgentUrl(target);
  if (request.kind === 'voice') authorizeVoiceUrl(target, request.scope);
  if (request.kind === 'terminal') authorizeTerminalUrl(target, request);
  return target;
}

function authorizeAgentUrl(target: URL): void {
  if (
    target.pathname !== '/api/v1/agent/ws' ||
    !exactQuery(target.searchParams, ['session_id']) ||
    identifierOrNull(target.searchParams.get('session_id')) === null
  ) {
    throw new Error('cloud agent socket URL is invalid');
  }
}

function authorizeVoiceUrl(target: URL, scope: CloudSocketScope): void {
  if (
    target.pathname !== '/api/v1/voice/chat' ||
    !exactQuery(target.searchParams, ['project_id', 'conversation_id'])
  ) {
    throw new Error('cloud voice socket URL is invalid');
  }
  if (target.searchParams.get('project_id') !== scope.project_id) {
    throw new Error('cloud voice socket project scope mismatch');
  }
  if (
    scope.conversation_id === null ||
    target.searchParams.get('conversation_id') !== scope.conversation_id
  ) {
    throw new Error('cloud voice socket conversation scope mismatch');
  }
}

function authorizeTerminalUrl(target: URL, request: VaultBoundCloudSocketInput): void {
  const terminal = request.terminal;
  if (!terminal || request.scope.conversation_id === null) {
    throw new Error('cloud terminal socket scope is invalid');
  }
  const project = encodeURIComponent(request.scope.project_id);
  const session = encodeURIComponent(terminal.session_id);
  const legacyPath = `/api/v1/projects/${project}/sandbox/terminal/proxy/ws`;
  if (target.pathname === legacyPath) {
    if (
      terminal.resume_token !== null ||
      !exactQuery(target.searchParams, ['session_id']) ||
      target.searchParams.get('session_id') !== terminal.session_id
    ) {
      throw new Error('cloud terminal socket URL is invalid');
    }
    return;
  }
  const v2Path = `/api/v1/projects/${project}/sandbox/terminal/sessions/${session}/ws`;
  const afterSequence = target.searchParams.get('after_sequence');
  const validAfterSequence =
    afterSequence === null ||
    (/^[1-9]\d*$/u.test(afterSequence) && Number.isSafeInteger(Number(afterSequence)));
  if (
    target.pathname !== v2Path ||
    !terminal.resume_token ||
    !validAfterSequence ||
    !exactQuery(target.searchParams, afterSequence === null ? [] : ['after_sequence'])
  ) {
    throw new Error('cloud terminal socket URL is invalid');
  }
}

function assertStructuredFrameScope(value: Record<string, unknown>, scope: CloudSocketScope): void {
  const stack: unknown[] = [value];
  let inspected = 0;
  while (stack.length) {
    const candidate = stack.pop();
    if (!isRecord(candidate)) continue;
    inspected += 1;
    if (inspected > 256) throw new Error('cloud socket text frame is invalid');
    assertScopeField(candidate, ['tenant_id', 'tenantId'], scope.tenant_id, 'tenant');
    assertScopeField(candidate, ['project_id', 'projectId'], scope.project_id, 'project');
    assertScopeField(candidate, ['workspace_id', 'workspaceId'], scope.workspace_id, 'workspace');
    assertScopeField(
      candidate,
      ['conversation_id', 'conversationId'],
      scope.conversation_id,
      'conversation',
      true
    );
    for (const nested of Object.values(candidate)) {
      if (isRecord(nested)) stack.push(nested);
      if (Array.isArray(nested)) stack.push(...nested);
    }
  }
}

function assertScopeField(
  record: Record<string, unknown>,
  keys: readonly string[],
  expected: string | null,
  label: string,
  allowAnyWhenNull = false
): void {
  for (const key of keys) {
    if (!(key in record)) continue;
    if ((!allowAnyWhenNull && expected === null) || (expected !== null && record[key] !== expected)) {
      throw new Error(`cloud socket ${label} scope mismatch`);
    }
  }
}

function websocketOrigin(apiBaseUrl: string): string {
  const target = new URL(apiBaseUrl);
  target.protocol = target.protocol === 'https:' ? 'wss:' : 'ws:';
  return target.origin;
}

function exactQuery(query: URLSearchParams, expectedKeys: readonly string[]): boolean {
  const entries = [...query.entries()];
  return (
    entries.length === expectedKeys.length &&
    expectedKeys.every((key) => query.getAll(key).length === 1 && query.get(key) !== null)
  );
}

function validatePolicyLimits(policy: AuthorizedCloudSocket): void {
  const limits = policy?.limits;
  if (
    !limits ||
    !positiveInteger(limits.max_frame_bytes) ||
    !positiveInteger(limits.max_aggregate_bytes) ||
    limits.max_aggregate_bytes < limits.max_frame_bytes ||
    !positiveInteger(limits.connect_timeout_ms) ||
    !positiveInteger(limits.idle_timeout_ms)
  ) {
    throw new Error('cloud socket policy limits are invalid');
  }
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function validOwnerId(ownerId: number): void {
  if (!Number.isSafeInteger(ownerId) || ownerId < 0) {
    throw new Error('cloud socket owner is invalid');
  }
}

function validSocketId(value: unknown): string {
  if (typeof value !== 'string' || !SOCKET_ID.test(value)) {
    throw new Error('cloud socket id is invalid');
  }
  return value;
}

function identifier(value: unknown, reason: string): string {
  const result = identifierOrNull(value);
  if (result === null) throw new Error(reason);
  return result;
}

function nullableIdentifier(value: unknown, reason: string): string | null {
  if (value === null) return null;
  return identifier(value, reason);
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

function exactRecord(
  input: unknown,
  allowedKeys: ReadonlySet<string>,
  reason: string
): Record<string, unknown> {
  if (!isRecord(input) || Object.keys(input).some((key) => !allowedKeys.has(key))) {
    throw new Error(reason);
  }
  return input;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function secureOrigin(url: URL): boolean {
  return (
    url.protocol === 'https:' ||
    (url.protocol === 'http:' &&
      ['localhost', '127.0.0.1', '::1', '[::1]'].includes(url.hostname.toLowerCase()))
  );
}

function hasControlCharacter(value: string): boolean {
  return /[\u0000-\u001f\u007f]/u.test(value);
}
