export type DeviceMcpOperationV2 = Readonly<{
  action: 'list' | 'get' | 'create' | 'update' | 'delete' | 'test' | 'provision_credential';
  server_id?: string;
  body?: Readonly<Record<string, unknown>>;
}>;
export type DeviceMcpRequestV2 = Readonly<{
  input: Readonly<{
    tenant_id: string;
    project_id: string;
    context_token?: string;
    operation: DeviceMcpOperationV2;
  }>;
}>;
export type DeviceMcpEnvelopeV2 = Readonly<{
  context: Readonly<{ tenant_id: string; project_id: string; location: 'device'; token: string }>;
  result: unknown;
}>;

function invalid(): never {
  throw new Error('device_mcp_request_invalid');
}
function record(value: unknown): value is Record<string, unknown> {
  return (
    value !== null &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value))
  );
}
function fields(
  value: unknown,
  allowed: readonly string[],
): asserts value is Record<string, unknown> {
  if (!record(value) || Object.keys(value).some((key) => !allowed.includes(key))) invalid();
}
function identifier(value: unknown): asserts value is string {
  if (
    typeof value !== 'string' ||
    !value ||
    value !== value.trim() ||
    /[\u0000-\u001f\u007f]/u.test(value)
  )
    invalid();
}
function idempotency(value: unknown): void {
  identifier(value);
  if (value.length > 200) invalid();
}
function transport(type: unknown, value: unknown, provisioning: boolean): void {
  if (!['stdio', 'http', 'sse', 'websocket'].includes(String(type))) invalid();
  fields(value, [
    'command',
    'args',
    'cwd',
    'url',
    'credential_env_names',
    'credential_header_names',
  ]);
  if (type === 'stdio') {
    const command = value.command;
    if (
      !(typeof command === 'string' && command.length > 0) &&
      !(
        Array.isArray(command) &&
        command.length > 0 &&
        command.every((item) => typeof item === 'string' && item.length > 0)
      )
    )
      invalid();
  } else identifier(value.url);
  if (value.cwd !== undefined && value.cwd !== null && typeof value.cwd !== 'string') invalid();
  for (const key of ['args', 'credential_env_names', 'credential_header_names']) {
    if (
      value[key] !== undefined &&
      (!Array.isArray(value[key]) || value[key].some((item) => typeof item !== 'string'))
    )
      invalid();
  }
  if (
    provisioning &&
    ['credential_env_names', 'credential_header_names'].some(
      (key) => Array.isArray(value[key]) && value[key].length > 0,
    )
  )
    invalid();
}

// Shared by preload and main. Authority, credentials, and the vault namespace are
// selected by the trusted sidecar; renderer input can only select a workspace.
export function requireDeviceMcpRequestV2(value: unknown): DeviceMcpRequestV2 {
  fields(value, ['input']);
  const input = value.input;
  fields(input, ['tenant_id', 'project_id', 'context_token', 'operation']);
  identifier(input.tenant_id);
  identifier(input.project_id);
  const operation = input.operation;
  fields(operation, ['action', 'server_id', 'body']);
  const action = operation.action;
  if (
    !['list', 'get', 'create', 'update', 'delete', 'test', 'provision_credential'].includes(
      String(action),
    )
  )
    invalid();
  if (action === 'list') {
    if (
      input.context_token !== undefined ||
      operation.server_id !== undefined ||
      operation.body !== undefined
    )
      invalid();
  } else identifier(input.context_token);
  const item = ['get', 'update', 'delete', 'test'].includes(String(action));
  if (item) identifier(operation.server_id);
  else if (operation.server_id !== undefined) invalid();
  const mutation = ['create', 'update', 'delete', 'provision_credential'].includes(String(action));
  if (!mutation) {
    if (operation.body !== undefined) invalid();
    return value as DeviceMcpRequestV2;
  }
  const body = operation.body;
  const common = ['project_id', 'idempotency_key'];
  fields(
    body,
    action === 'provision_credential'
      ? [
          ...common,
          'server_name',
          'server_type',
          'transport_config',
          'credential_kind',
          'credential_name',
          'secret',
          'mutation_idempotency_key',
        ]
      : action === 'delete'
        ? [...common, 'expected_revision']
        : [
            ...common,
            'name',
            'description',
            'server_type',
            'transport_config',
            'enabled',
            ...(action === 'update' ? ['expected_revision'] : []),
          ],
  );
  if (body.project_id !== input.project_id) invalid();
  idempotency(body.idempotency_key);
  if (
    ['update', 'delete'].includes(String(action)) &&
    (!Number.isSafeInteger(body.expected_revision) || Number(body.expected_revision) < 1)
  )
    invalid();
  if (action === 'provision_credential') {
    identifier(body.server_name);
    identifier(body.credential_name);
    if (
      !['env', 'header'].includes(String(body.credential_kind)) ||
      typeof body.secret !== 'string' ||
      !body.secret
    )
      invalid();
    if ((body.server_type === 'stdio') !== (body.credential_kind === 'env')) invalid();
    if (body.mutation_idempotency_key !== undefined) idempotency(body.mutation_idempotency_key);
    transport(body.server_type, body.transport_config, true);
  } else if (action !== 'delete') {
    if (action === 'create' || body.name !== undefined) identifier(body.name);
    if (
      body.description !== undefined &&
      body.description !== null &&
      typeof body.description !== 'string'
    )
      invalid();
    if (body.enabled !== undefined && typeof body.enabled !== 'boolean') invalid();
    if (action === 'create' && body.enabled !== false) invalid();
    if (
      action === 'create' ||
      body.server_type !== undefined ||
      body.transport_config !== undefined
    )
      transport(body.server_type, body.transport_config, false);
    if (
      action === 'update' &&
      !['name', 'description', 'server_type', 'transport_config', 'enabled'].some(
        (key) => body[key] !== undefined,
      )
    )
      invalid();
  }
  return value as DeviceMcpRequestV2;
}

export function requireDeviceMcpEnvelopeV2(
  value: unknown,
  tenantId: string,
  projectId: string,
): DeviceMcpEnvelopeV2 {
  if (
    !record(value) ||
    Object.keys(value).length !== 2 ||
    !record(value.context) ||
    Object.keys(value.context).length !== 4 ||
    value.context.tenant_id !== tenantId ||
    value.context.project_id !== projectId ||
    value.context.location !== 'device' ||
    typeof value.context.token !== 'string' ||
    !value.context.token ||
    !('result' in value)
  )
    throw new Error('device_mcp_response_scope_invalid');
  return value as DeviceMcpEnvelopeV2;
}
