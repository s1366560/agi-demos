export type ModelRole = 'primary' | 'fast' | 'embedding' | 'rerank' | 'voice';

export type RoleReason =
  | 'ok'
  | 'unknown_assumed_chat'
  | 'not_a_chat_model'
  | 'embedding_capability_required'
  | 'rerank_capability_required'
  | 'llm_scoring_rerank'
  | 'audio_input_not_declared'
  | 'audio_declaration_unsupported'
  | 'deprecated'
  | 'provider_has_no_embedding_models'
  | 'provider_has_no_rerank_models';

export interface ModelSignals {
  capabilities: readonly string[];
  modalities?: readonly string[];
  known: boolean;
  deprecated?: boolean;
  audioDeclared?: boolean;
  audioDeclarationAllowed?: boolean;
  providerType?: string;
}

export interface RoleAssessment {
  supported: boolean;
  reason: RoleReason;
}

const CHAT = new Set(['chat', 'completion']);
const EMBEDDING = new Set(['embedding']);
const RERANK = new Set(['rerank', 'reranking']);
const VOICE = new Set(['tts', 'asr', 'voice_cloning', 'realtime_voice']);
const NATIVE_RERANK = new Set(['cohere']);

const AUDIO_PROVIDERS = new Set(['openai', 'openrouter', 'lmstudio', 'kimi', 'volcengine']);

export const providerAllowsAudioDeclaration = (providerType: string): boolean => {
  const family = providerType.replace(/_(coding|embedding|reranker)$/, '');
  return AUDIO_PROVIDERS.has(family);
};

const hasAny = (values: ReadonlySet<string>, expected: ReadonlySet<string>): boolean => {
  for (const value of expected) {
    if (values.has(value)) return true;
  }
  return false;
};

export function assessModelRole(role: ModelRole, signals: ModelSignals): RoleAssessment {
  const capabilities = new Set(signals.capabilities.map((item) => item.toLowerCase()));
  const modalities = new Set((signals.modalities ?? []).map((item) => item.toLowerCase()));
  const deprecated = Boolean(signals.deprecated);

  if (role === 'primary' || role === 'fast') {
    if (!signals.known) return { supported: true, reason: 'unknown_assumed_chat' };
    if (hasAny(capabilities, CHAT)) {
      return { supported: true, reason: deprecated ? 'deprecated' : 'ok' };
    }
    return { supported: false, reason: 'not_a_chat_model' };
  }

  if (role === 'embedding') {
    const supported = hasAny(capabilities, EMBEDDING) || modalities.has('embedding');
    if (!supported) return { supported: false, reason: 'embedding_capability_required' };
    return { supported: true, reason: deprecated ? 'deprecated' : 'ok' };
  }

  if (role === 'rerank') {
    if (hasAny(capabilities, RERANK)) {
      return { supported: true, reason: deprecated ? 'deprecated' : 'ok' };
    }
    const family = (signals.providerType ?? '').replace(/_(coding|embedding|reranker)$/, '');
    if (NATIVE_RERANK.has(family)) {
      if (!signals.known) return { supported: true, reason: 'unknown_assumed_chat' };
      return { supported: false, reason: 'rerank_capability_required' };
    }
    if (!signals.known) return { supported: true, reason: 'unknown_assumed_chat' };
    if (hasAny(capabilities, CHAT)) {
      return { supported: true, reason: deprecated ? 'deprecated' : 'llm_scoring_rerank' };
    }
    return { supported: false, reason: 'rerank_capability_required' };
  }

  const voiceCapability = hasAny(capabilities, VOICE);
  if (voiceCapability && signals.audioDeclarationAllowed) {
    return { supported: true, reason: deprecated ? 'deprecated' : 'ok' };
  }
  if (signals.audioDeclared && signals.audioDeclarationAllowed) {
    return { supported: true, reason: 'ok' };
  }
  if (!signals.audioDeclarationAllowed) {
    return { supported: false, reason: 'audio_declaration_unsupported' };
  }
  return { supported: false, reason: 'audio_input_not_declared' };
}

export function roleForOperation(operation: string): ModelRole {
  if (operation === 'embedding') return 'embedding';
  if (operation === 'rerank') return 'rerank';
  return 'primary';
}

export function preferredListedModel(
  models: readonly string[],
  preferred: string | null | undefined,
  excluded = ''
): string {
  if (preferred && models.includes(preferred) && preferred !== excluded) return preferred;
  return models.find((model) => model !== excluded) ?? preferred ?? '';
}
