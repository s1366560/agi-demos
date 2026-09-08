import type { ProjectMemory } from './projectMemoriesClient';
import {
  isRecord,
  optionalText,
  projectKnowledgeError,
  requireNonnegativeInteger,
  requireText,
  type ProjectKnowledgeScope,
} from './projectKnowledgeClient';

export function parseMemoryV2(payload: unknown, scope: ProjectKnowledgeScope): ProjectMemory {
  if (!isRecord(payload)) {
    throw projectKnowledgeError('project_memory_contract_invalid');
  }
  const projectId = responseIdentifier(payload.project_id);
  if (projectId !== scope.projectId) {
    throw projectKnowledgeError('project_memory_scope_conflict', 409);
  }
  return Object.freeze({
    id: responseIdentifier(payload.id),
    projectId: scope.projectId,
    title: responseIdentifier(payload.title),
    content: requireText(payload.content, 'project_memory_contract_invalid'),
    contentType: responseIdentifier(payload.content_type),
    version: requireNonnegativeInteger(payload.version, 'project_memory_contract_invalid'),
    status: responseIdentifier(payload.status),
    processingStatus: responseIdentifier(payload.processing_status),
    createdAt: responseIdentifier(payload.created_at),
    updatedAt: optionalText(payload.updated_at, 'project_memory_contract_invalid'),
  });
}

function responseIdentifier(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) {
    throw projectKnowledgeError('project_memory_contract_invalid');
  }
  return value;
}
