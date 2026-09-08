import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopCapabilitySnapshotEntry } from '../runtime/capabilitySnapshot';
import { requireNativeKnowledgeTransportV2 } from '../../plugins/desktopNativeKnowledgeSyncHttpV2';
import { requireNativeKnowledgeScope } from './nativeKnowledgeValidation';
import { definitions } from './nativeKnowledgeProcessingSchemaGenerated';
import { sameJson } from './nativeKnowledgeRelationships';
import * as s from './nativeKnowledgeSchema';
import { PROJECT_MEMORIES_LOCAL_REASON } from './projectMemoriesClient';
import type { NativeKnowledgeCapabilitiesResponse } from './nativeKnowledgeContracts';
import {
  requestProjectKnowledgeJson,
  type ProjectKnowledgeScope,
  projectKnowledgeError,
} from './projectKnowledgeClient';

/** Only an authenticated, stable sidecar observation becomes an observed entry. */
export async function loadNativeKnowledgeCapability(
  inputConfig: DesktopRuntimeConfig,
  inputScope: ProjectKnowledgeScope,
  signal?: AbortSignal,
): Promise<DesktopCapabilitySnapshotEntry> {
  const config = Object.freeze({ ...inputConfig });
  const scope = Object.freeze({ ...inputScope });
  try {
    signal?.throwIfAborted();
    requireNativeKnowledgeTransportV2(config);
    if (
      !s.object({ authority: s.literal('local'), tenantId: s.identifier, projectId: s.identifier })(
        scope,
      ) ||
      config.tenantId !== scope.tenantId ||
      config.projectId !== scope.projectId
    )
      throw invalid();
    const before = await observe(config, scope, signal);
    const payload = await requestProjectKnowledgeJson(config, '/api/v1/knowledge/capabilities', {
      signal,
    });
    signal?.throwIfAborted();
    if (!s.jsonValue(payload) || !definitions.NativeKnowledgeCapabilitiesResponse!(payload))
      throw invalid();
    const response = payload as NativeKnowledgeCapabilitiesResponse;
    const native = requireNativeKnowledgeScope(
      { contract_version: response.contract_version, scope: response.scope },
      scope,
    );
    if (response.actor_id !== before.actorId || !sameJson(native, before.scope)) throw invalid();
    const result = response.result;
    if (
      result.provenance !== 'observed' ||
      result.authority_source !== 'sidecar' ||
      result.supporting_authority_sources.length !== 0 ||
      result.scope.tenant_id !== scope.tenantId ||
      result.scope.project_id !== scope.projectId ||
      result.scope.workspace_id !== null ||
      result.scope.instance_id !== null ||
      result.authority_revision !== native.context_revision ||
      result.contract_version !== '1.0.0' ||
      !s.identifier(result.service_version) ||
      new Set(result.allowed_actions).size !== result.allowed_actions.length ||
      (result.availability === 'available'
        ? result.reason_code !== null
        : !s.identifier(result.reason_code)) ||
      (result.availability === 'unavailable' && result.allowed_actions.length !== 0) ||
      result.availability === 'not_applicable'
    )
      throw invalid();
    const after = await observe(config, scope, signal);
    if (after.actorId !== before.actorId || !sameJson(after.scope, before.scope)) throw invalid();
    return s.frozenClone(result);
  } catch (error) {
    signal?.throwIfAborted();
    return Object.freeze({
      availability: 'unavailable',
      reason_code: PROJECT_MEMORIES_LOCAL_REASON,
      service_version: null,
      contract_version: null,
      allowed_actions: Object.freeze([]),
      scope: Object.freeze({
        tenant_id: scope.tenantId,
        project_id: scope.projectId,
        workspace_id: null,
        instance_id: null,
      }),
      authority_revision: null,
      retryable: false,
      authority_source: 'renderer',
      supporting_authority_sources: Object.freeze([]),
      provenance: 'declared',
    });
  }
}

async function observe(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  const [actor, context] = await Promise.all([
    requestProjectKnowledgeJson(config, '/api/v1/auth/me', { signal }),
    requestProjectKnowledgeJson(config, '/api/v1/knowledge/context', { signal }),
  ]);
  signal?.throwIfAborted();
  if (!s.object({ user_id: s.identifier, is_active: s.literal(true) }, {}, true)(actor))
    throw invalid();
  return Object.freeze({
    actorId: (actor as { user_id: string }).user_id,
    scope: requireNativeKnowledgeScope(context, scope),
  });
}
const invalid = () => projectKnowledgeError('native_knowledge_capability_invalid');
