import type { NativeKnowledgeScope } from './nativeKnowledgeContracts';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';

export type NativeKnowledgeEmbeddingChoice = Readonly<{
  providerId: string;
  providerRevision: number;
  providerName: string;
  modelId: string;
}>;
export type NativeKnowledgeWorkspaceChoice = Readonly<{ id: string; name: string }>;
export type NativeKnowledgeInputDirectory<T> =
  | Readonly<{ availability: 'available'; items: readonly T[] }>
  | Readonly<{ availability: 'unavailable'; items: readonly [] }>;
export type NativeKnowledgeProcessingInputs = Readonly<{
  scope: NativeKnowledgeScope;
  embeddingModels: NativeKnowledgeInputDirectory<NativeKnowledgeEmbeddingChoice>;
  workspaces: NativeKnowledgeInputDirectory<NativeKnowledgeWorkspaceChoice>;
}>;
export interface NativeKnowledgeProcessingInputsClient {
  load(
    scope: ProjectKnowledgeScope,
    options: Readonly<{
      operation: 'configure_embedding' | 'process_one' | 'process_community_one';
      expectedScope: NativeKnowledgeScope;
      signal?: AbortSignal;
    }>,
  ): Promise<NativeKnowledgeProcessingInputs>;
}
