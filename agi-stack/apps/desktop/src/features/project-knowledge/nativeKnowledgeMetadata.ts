import type { NativeKnowledgeJson } from './nativeKnowledgeContracts';
import { jsonObject } from './nativeKnowledgeSchema';

export type NativeKnowledgeMetadata = Readonly<Record<string, NativeKnowledgeJson>>;

export function isNativeKnowledgeMetadata(value: unknown): value is NativeKnowledgeMetadata {
  return jsonObject(value) && new TextEncoder().encode(JSON.stringify(value)).length <= 65_536;
}

export function parseNativeKnowledgeMetadata(text: string): NativeKnowledgeMetadata | null {
  try {
    const value: unknown = JSON.parse(text);
    return isNativeKnowledgeMetadata(value) ? value : null;
  } catch {
    return null;
  }
}
