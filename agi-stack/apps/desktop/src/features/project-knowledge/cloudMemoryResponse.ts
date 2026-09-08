import type { CloudMemoryCommand, CloudMemoryResponse } from './cloudMemoryClient';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import { isRecord, projectKnowledgeError } from './projectKnowledgeClient';
import { parseMemoryV2 } from './cloudMemoryProjection';

export function requireCloudMemoryResponse<C extends CloudMemoryCommand>(
  value: unknown,
  command: C,
  scope: ProjectKnowledgeScope,
): CloudMemoryResponse<C> {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== 2 ||
    value.operation !== command.operation ||
    !isRecord(value.result)
  )
    throw invalid();
  const result = value.result;
  if (command.operation === 'delete') {
    if (
      Object.keys(result).length !== 2 ||
      result.memoryId !== command.id ||
      result.deleted !== true
    )
      throw invalid();
    return Object.freeze({
      operation: command.operation,
      result: Object.freeze({ memoryId: command.id, deleted: true }),
    }) as CloudMemoryResponse<C>;
  }
  const keys = [
    'id',
    'projectId',
    'title',
    'content',
    'contentType',
    'version',
    'status',
    'processingStatus',
    'createdAt',
    'updatedAt',
  ];
  if (
    Object.keys(result).length !== keys.length ||
    Object.keys(result).some((key) => !keys.includes(key))
  )
    throw invalid();
  const memory = parseMemoryV2(
    {
      id: result.id,
      project_id: result.projectId,
      title: result.title,
      content: result.content,
      content_type: result.contentType,
      version: result.version,
      status: result.status,
      processing_status: result.processingStatus,
      created_at: result.createdAt,
      updated_at: result.updatedAt,
    },
    scope,
  );
  if (
    (command.operation !== 'create' && memory.id !== command.id) ||
    (command.operation === 'create' && memory.version !== 1) ||
    (command.operation === 'update' && memory.version !== command.expectedRevision + 1) ||
    memory.version < 1
  )
    throw invalid();
  return Object.freeze({ operation: command.operation, result: memory }) as CloudMemoryResponse<C>;
}
function invalid(): Error {
  return projectKnowledgeError('cloud_memory_response_invalid');
}
