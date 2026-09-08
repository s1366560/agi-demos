import type { DesktopRuntimeConfig } from '../types';
import type {
  NativeKnowledgeScope,
  NativeKnowledgeScopeObservationOptions,
} from '../features/project-knowledge/nativeKnowledgeContracts';
import {
  requestProjectKnowledgeJson,
  projectKnowledgeError,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import { requireNativeKnowledgeScope } from '../features/project-knowledge/nativeKnowledgeValidation';
import { sameJson } from '../features/project-knowledge/nativeKnowledgeRelationships';
import { identifier, literal, object } from '../features/project-knowledge/nativeKnowledgeSchema';
import { prepareNativeKnowledgeScopeObservationOptions } from '../features/project-knowledge/nativeKnowledgeScopeObservation';

/** Authenticated discovery is independent of permission to synchronize content. */
export async function observeDesktopNativeKnowledgeScopeV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  inputOptions: NativeKnowledgeScopeObservationOptions,
  requireCurrent: () => void = () => undefined,
): Promise<NativeKnowledgeScope> {
  const options = prepareNativeKnowledgeScopeObservationOptions(inputOptions);
  const current = () => {
    requireCurrent();
    options.signal?.throwIfAborted();
  };
  const actor = async () => {
    current();
    const response = await requestProjectKnowledgeJson(config, '/api/v1/auth/me', options);
    current();
    if (
      !object({ user_id: identifier, is_active: literal(true) }, {}, true)(response) ||
      (response as { user_id: string }).user_id !== options.expectedActorId
    ) {
      throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
    }
  };
  const context = async () => {
    current();
    const response = await requestProjectKnowledgeJson(
      config,
      '/api/v1/knowledge/context',
      options,
    );
    current();
    return requireNativeKnowledgeScope(response, scope);
  };
  await actor();
  current();
  const before = await context();
  current();
  await actor();
  current();
  const after = await context();
  current();
  if (!sameJson(before, after))
    throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
  return after;
}
