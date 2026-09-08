import type { ProjectMemory } from './projectMemoriesClient';
import {
  isRecord,
  optionalText,
  projectKnowledgeError,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  type ProjectKnowledgeScope,
} from './projectKnowledgeClient';

export function parseMemoryV2(payload: unknown, scope: ProjectKnowledgeScope): ProjectMemory {
  if (!isRecord(payload) || payload.project_id !== scope.projectId) {
    throw projectKnowledgeError('project_memory_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(payload.id, 'project_memory_contract_invalid'),
    projectId: scope.projectId,
    title: requireIdentifier(payload.title, 'project_memory_contract_invalid'),
    content: requireText(payload.content, 'project_memory_contract_invalid'),
    contentType: requireIdentifier(payload.content_type, 'project_memory_contract_invalid'),
    version: requireNonnegativeInteger(payload.version, 'project_memory_contract_invalid'),
    status: requireIdentifier(payload.status, 'project_memory_contract_invalid'),
    processingStatus: requireIdentifier(
      payload.processing_status,
      'project_memory_contract_invalid',
    ),
    createdAt: requireIdentifier(payload.created_at, 'project_memory_contract_invalid'),
    updatedAt: optionalText(payload.updated_at, 'project_memory_contract_invalid'),
  });
}
