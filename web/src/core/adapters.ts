/**
 * Adapter interfaces — the *ports* that `core/` declares and that
 * application code supplies implementations for.
 *
 * Any I/O that `core/` wants to perform must go through one of these.
 * This keeps `core/` testable with fakes and ready to extract.
 */
import type { ProjectId, ProjectRef } from './types/project';
import type { ConversationId } from './types/session';

export interface ProjectAdapter {
  list(tenantId: string): Promise<ProjectRef[]>;
  get(projectId: ProjectId): Promise<ProjectRef>;
}

export interface SessionAdapter {
  send(conversationId: ConversationId, message: string): Promise<void>;
  subscribe(conversationId: ConversationId, onEvent: (event: unknown) => void): () => void;
}
