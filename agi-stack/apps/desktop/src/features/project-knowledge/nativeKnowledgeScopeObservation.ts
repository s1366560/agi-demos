import type { NativeKnowledgeScopeObservationOptions } from './nativeKnowledgeContracts';
import { projectKnowledgeError } from './projectKnowledgeClient';
import { identifier, plain } from './nativeKnowledgeSchema';

export function prepareNativeKnowledgeScopeObservationOptions(
  input: NativeKnowledgeScopeObservationOptions,
): NativeKnowledgeScopeObservationOptions {
  if (
    !plain(input) ||
    !Object.hasOwn(input, 'expectedActorId') ||
    !identifier(input.expectedActorId) ||
    Object.keys(input).some((key) => key !== 'expectedActorId' && key !== 'signal') ||
    (input.signal !== undefined && !(input.signal instanceof AbortSignal))
  ) {
    throw projectKnowledgeError('native_knowledge_scope_observation_invalid', 422);
  }
  return Object.freeze({
    expectedActorId: input.expectedActorId,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
