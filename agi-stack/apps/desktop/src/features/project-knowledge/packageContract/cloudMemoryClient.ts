import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectMemory } from './projectMemoriesClient';

export type CloudMemoryEditableFields = Readonly<{
  title?: string;
  content?: string;
  tags?: readonly string[];
  metadata?: Readonly<Record<string, unknown>>;
}>;
export type CloudMemoryCommand =
  | Readonly<{ operation: 'get'; id: string }>
  | Readonly<{
      operation: 'create';
      idempotencyKey: string;
      memory: CloudMemoryEditableFields &
        Readonly<{
          title: string;
          content: string;
          contentType?: string;
        }>;
    }>
  | Readonly<{
      operation: 'update';
      id: string;
      expectedRevision: number;
      idempotencyKey: string;
      patch: CloudMemoryEditableFields;
    }>
  | Readonly<{
      operation: 'delete';
      id: string;
      expectedRevision: number;
      idempotencyKey: string;
    }>;
export type CloudMemoryOptions = Readonly<{
  signal?: AbortSignal;
  expectedActorId: string;
  expectedContextRevision: number;
}>;
export type CloudMemoryResultMap = Readonly<{
  get: ProjectMemory;
  create: ProjectMemory;
  update: ProjectMemory;
  delete: Readonly<{ memoryId: string; deleted: true }>;
}>;
export type CloudMemoryResponse<C extends CloudMemoryCommand = CloudMemoryCommand> = Readonly<{
  operation: C['operation'];
  result: CloudMemoryResultMap[C['operation']];
}>;
export interface CloudMemoryClient {
  execute<C extends CloudMemoryCommand>(
    scope: ProjectKnowledgeScope,
    command: C,
    options: CloudMemoryOptions,
  ): Promise<CloudMemoryResponse<C>>;
}
