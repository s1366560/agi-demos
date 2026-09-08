import type { DesktopRuntimeConfig } from '../types';
import type * as K from '../features/project-administration/nativeProjectSchemaGenerated';
import {
  NATIVE_PROJECT_SCHEMA_ACTIONS as actions,
  NATIVE_PROJECT_SCHEMA_CAPABILITIES as capabilities,
} from '../features/project-administration/nativeProjectSchemaSchemaGenerated';
import {
  prepareNativeProjectSchemaRequest,
  requireNativeProjectSchemaResponse,
  requireNativeProjectSchemaCapabilities,
} from '../features/project-administration/nativeProjectSchemaValidation';
import {
  freezeSchemaJson,
  schemaAssert,
  plainSchemaObject,
  matchesSchemaDefinition,
} from '../features/project-administration/nativeProjectSchemaShape';
import { sameJson } from '../features/project-knowledge/nativeKnowledgeRelationships';
import {
  projectKnowledgeError,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import { requireNativeKnowledgeScope } from '../features/project-knowledge/nativeKnowledgeValidation';
import { requireNativeKnowledgeTransportV2 } from './desktopNativeKnowledgeSyncHttpV2';
import { requestNativeProjectSchemaJsonV2 } from './desktopNativeProjectSchemaTransportV2';

export type NativeProjectSchemaOptions = Readonly<{
  expectedScope: K.NativeProjectSchemaScope;
  expectedActorId: string;
  signal?: AbortSignal;
}>;
type Command<A extends K.NativeProjectSchemaAction> = Omit<
  K.NativeProjectSchemaRequestMap[A],
  'scope'
>;
export type NativeProjectSchemaCapabilityGetter =
  () => K.NativeProjectSchemaCapabilitiesResponse | null;
export interface DesktopNativeProjectSchemaHttpV2 {
  read(options: NativeProjectSchemaOptions): Promise<K.NativeProjectSchemaReadResponse>;
  bootstrap(
    command: Command<'schema_bootstrap'>,
    options: NativeProjectSchemaOptions,
  ): Promise<K.NativeProjectSchemaBootstrapResponse>;
  replace(
    command: Command<'schema_replace'>,
    options: NativeProjectSchemaOptions,
  ): Promise<K.NativeProjectSchemaReplaceResponse>;
  receipt(
    command: Command<'schema_receipt'>,
    options: NativeProjectSchemaOptions,
  ): Promise<K.NativeProjectSchemaReceiptResponse>;
  history(
    command: Command<'schema_history'>,
    options: NativeProjectSchemaOptions,
  ): Promise<K.NativeProjectSchemaHistoryResponse>;
}
function prepareOptions(input: NativeProjectSchemaOptions): NativeProjectSchemaOptions {
  schemaAssert(plainSchemaObject(input));
  const descriptors = Object.getOwnPropertyDescriptors(input);
  schemaAssert(
    Object.getOwnPropertySymbols(input).length === 0 &&
      Object.keys(descriptors).every(
        (key) =>
          ['expectedScope', 'expectedActorId', 'signal'].includes(key) &&
          'value' in descriptors[key]!,
      ),
  );
  const frozen = freezeSchemaJson({
    expectedScope: input.expectedScope,
    expectedActorId: input.expectedActorId,
  });
  schemaAssert(matchesSchemaDefinition('NativeProjectSchemaScope', frozen.expectedScope));
  schemaAssert(typeof frozen.expectedActorId === 'string' && frozen.expectedActorId.length > 0);
  schemaAssert(input.signal === undefined || input.signal instanceof AbortSignal);
  return Object.freeze({ ...frozen, signal: input.signal });
}
function requireBinding(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  options: NativeProjectSchemaOptions,
): void {
  requireNativeKnowledgeTransportV2(config);
  if (
    scope.authority !== 'local' ||
    config.tenantId !== scope.tenantId ||
    config.projectId !== scope.projectId ||
    options.expectedScope.tenant_id !== scope.tenantId ||
    options.expectedScope.project_id !== scope.projectId
  )
    throw projectKnowledgeError('native_project_schema_scope_conflict', 409);
}
async function observeContext(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  options: NativeProjectSchemaOptions,
  current: () => void,
): Promise<void> {
  const actor = await requestNativeProjectSchemaJsonV2(
    config,
    '/api/v1/auth/me',
    { method: 'GET', signal: options.signal },
    current,
  );
  current();
  if (
    !plainSchemaObject(actor) ||
    actor.user_id !== options.expectedActorId ||
    actor.is_active !== true
  )
    throw projectKnowledgeError('native_project_schema_scope_conflict', 409);
  const context = requireNativeKnowledgeScope(
    await requestNativeProjectSchemaJsonV2(
      config,
      '/api/v1/knowledge/context',
      { method: 'GET', signal: options.signal },
      current,
    ),
    scope,
  );
  current();
  if (!sameJson(context, options.expectedScope))
    throw projectKnowledgeError('native_project_schema_scope_conflict', 409);
}
/** No runtime config alone grants this authority: both callbacks are mandatory. */
export function createDesktopNativeProjectSchemaHttpV2(
  inputConfig: DesktopRuntimeConfig,
  inputScope: ProjectKnowledgeScope,
  getCapability: NativeProjectSchemaCapabilityGetter,
  requireCurrent: () => void,
): DesktopNativeProjectSchemaHttpV2 {
  schemaAssert(typeof getCapability === 'function' && typeof requireCurrent === 'function');
  const config = Object.freeze({ ...inputConfig }),
    scope = Object.freeze({ ...inputScope });
  const invoke = async <A extends K.NativeProjectSchemaAction>(
    action: A,
    input: Command<A>,
    inputOptions: NativeProjectSchemaOptions,
  ): Promise<K.NativeProjectSchemaResponseMap[A]> => {
    const options = prepareOptions(inputOptions);
    const command = freezeSchemaJson(input);
    schemaAssert(plainSchemaObject(command) && !Object.hasOwn(command, 'scope'));
    const request = prepareNativeProjectSchemaRequest(action, {
      scope: options.expectedScope,
      ...command,
    } as K.NativeProjectSchemaRequestMap[A]);
    const current = () => {
      requireCurrent();
      options.signal?.throwIfAborted();
      requireBinding(config, scope, options);
      const cap = requireNativeProjectSchemaCapabilities(
        getCapability(),
        options.expectedScope,
        options.expectedActorId,
      );
      if (!cap.result.allowed_actions.includes(action))
        throw projectKnowledgeError('native_project_schema_unavailable', 503);
    };
    current();
    await observeContext(config, scope, options, current);
    current();
    const payload = await requestNativeProjectSchemaJsonV2(
      config,
      actions[action].path,
      { method: actions[action].method, body: request, signal: options.signal },
      current,
    );
    current();
    const response = requireNativeProjectSchemaResponse(
      action,
      payload,
      request,
      options.expectedActorId,
    );
    await observeContext(config, scope, options, current);
    current();
    return response;
  };
  return Object.freeze({
    read: (options: NativeProjectSchemaOptions) => invoke('schema_read', {}, options),
    bootstrap: (command: Command<'schema_bootstrap'>, options: NativeProjectSchemaOptions) =>
      invoke('schema_bootstrap', command, options),
    replace: (command: Command<'schema_replace'>, options: NativeProjectSchemaOptions) =>
      invoke('schema_replace', command, options),
    receipt: (command: Command<'schema_receipt'>, options: NativeProjectSchemaOptions) =>
      invoke('schema_receipt', command, options),
    history: (command: Command<'schema_history'>, options: NativeProjectSchemaOptions) =>
      invoke('schema_history', command, options),
  });
}
/** Discovery is observed with actor, scope and generation checks on both sides of its request. */
export async function observeDesktopNativeProjectSchemaCapabilitiesV2(
  inputConfig: DesktopRuntimeConfig,
  inputScope: ProjectKnowledgeScope,
  inputOptions: NativeProjectSchemaOptions,
  requireCurrent: () => void,
): Promise<K.NativeProjectSchemaCapabilitiesResponse> {
  schemaAssert(typeof requireCurrent === 'function');
  const config = Object.freeze({ ...inputConfig }),
    scope = Object.freeze({ ...inputScope }),
    options = prepareOptions(inputOptions);
  const current = () => {
    requireCurrent();
    options.signal?.throwIfAborted();
    requireBinding(config, scope, options);
  };
  current();
  await observeContext(config, scope, options, current);
  current();
  const response = requireNativeProjectSchemaCapabilities(
    await requestNativeProjectSchemaJsonV2(
      config,
      capabilities.path,
      { method: capabilities.method, signal: options.signal },
      current,
    ),
    options.expectedScope,
    options.expectedActorId,
  );
  current();
  await observeContext(config, scope, options, current);
  current();
  return response;
}
