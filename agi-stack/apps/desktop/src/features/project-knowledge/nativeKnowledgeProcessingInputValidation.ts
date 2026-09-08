import type {
  NativeKnowledgeProcessingInputs,
  NativeKnowledgeEmbeddingChoice,
} from './nativeKnowledgeProcessingInputs';

const identifier = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0 && value === value.trim();
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

export function validateNativeKnowledgeProcessingInputs(
  value: unknown,
): NativeKnowledgeProcessingInputs {
  if (!record(value) || !record(value.scope)) throw Error('knowledge_inputs_invalid');
  if (
    Object.keys(value).some((key) => !['scope', 'embeddingModels', 'workspaces'].includes(key)) ||
    Object.keys(value.scope).some(
      (key) =>
        ![
          'tenant_id',
          'project_id',
          'context_revision',
          'profile_id',
          'generation',
          'digest',
        ].includes(key),
    )
  )
    throw Error('knowledge_inputs_invalid');
  for (const name of ['embeddingModels', 'workspaces'] as const) {
    const directory = value[name];
    if (
      !record(directory) ||
      !Array.isArray(directory.items) ||
      !['available', 'unavailable'].includes(String(directory.availability)) ||
      (directory.availability === 'unavailable' && directory.items.length > 0)
    )
      throw Error('knowledge_inputs_invalid');
    if (Object.keys(directory).some((key) => !['availability', 'items'].includes(key)))
      throw Error('knowledge_inputs_invalid');
    const keys = new Set<string>();
    for (const item of directory.items) {
      if (!record(item)) throw Error('knowledge_inputs_invalid');
      const allowedKeys =
        name === 'embeddingModels'
          ? ['providerId', 'providerRevision', 'providerName', 'modelId']
          : ['id', 'name'];
      if (Object.keys(item).some((key) => !allowedKeys.includes(key)))
        throw Error('knowledge_inputs_invalid');
      let key: string;
      if (name === 'embeddingModels') {
        if (
          !identifier(item.providerId) ||
          !identifier(item.providerName) ||
          !identifier(item.modelId) ||
          !Number.isSafeInteger(item.providerRevision) ||
          Number(item.providerRevision) < 0
        )
          throw Error('knowledge_inputs_invalid');
        key = JSON.stringify([item.providerId, item.modelId]);
      } else {
        if (!identifier(item.id) || !identifier(item.name)) throw Error('knowledge_inputs_invalid');
        key = item.id;
      }
      if (keys.has(key)) throw Error('knowledge_inputs_invalid');
      keys.add(key);
    }
  }
  const cloned = structuredClone(value) as NativeKnowledgeProcessingInputs;
  for (const directory of [cloned.embeddingModels, cloned.workspaces]) {
    directory.items.forEach(Object.freeze);
    Object.freeze(directory.items);
    Object.freeze(directory);
  }
  Object.freeze(cloned.scope);
  return Object.freeze(cloned);
}

export function sameNativeKnowledgeEmbeddingChoice(
  left: NativeKnowledgeEmbeddingChoice,
  right: NativeKnowledgeEmbeddingChoice,
): boolean {
  return (
    left.providerId === right.providerId &&
    left.providerRevision === right.providerRevision &&
    left.modelId === right.modelId
  );
}
