import type { NativeKnowledgeCapabilitiesResponse } from './nativeKnowledgeContracts';
import { definitions } from './nativeKnowledgeProcessingSchemaGenerated';
import { identifier } from './nativeKnowledgeSchema';

/** Structural read prerequisites of the native route implementations. */
export const NATIVE_KNOWLEDGE_ROUTE_READ_ACTIONS = Object.freeze({
  'project-project-memories': Object.freeze([]),
  'project-project-communities': Object.freeze([
    'community_active',
    'community_build',
    'community_builds',
    'community_audit',
  ]),
  'project-project-graph': Object.freeze(['entities', 'graph_source']),
});

/** The knowledge service has its own V1 contract, independent of the snapshot envelope. */
export function supportsNativeKnowledgeCapabilityV1(
  capabilityName: string,
  runtimeState: string,
  input: unknown,
): boolean {
  if (
    !Object.hasOwn(NATIVE_KNOWLEDGE_ROUTE_READ_ACTIONS, capabilityName) ||
    (runtimeState !== 'local_online' && runtimeState !== 'local_offline') ||
    !definitions.NativeKnowledgeCapabilityEntry!(input)
  ) {
    return false;
  }
  const entry = input as NativeKnowledgeCapabilitiesResponse['result'];
  return (
    entry.contract_version === '1.0.0' &&
    entry.authority_source === 'sidecar' &&
    entry.provenance === 'observed' &&
    entry.supporting_authority_sources.length === 0 &&
    identifier(entry.scope.tenant_id) &&
    identifier(entry.scope.project_id) &&
    entry.scope.workspace_id === null &&
    entry.scope.instance_id === null &&
    entry.availability !== 'not_applicable'
  );
}
