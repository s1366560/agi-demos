export type ModelRole = 'primary' | 'fast' | 'embedding' | 'rerank' | 'voice';

export type RoleReason =
  | 'ok'
  | 'not_a_chat_model'
  | 'audio_input_not_declared'
  | 'audio_declaration_unsupported';

export function boundaryForCapability(
  capability: 'chat' | 'embedding' | 'rerank',
  audioDeclared: boolean,
  audioAllowed: boolean
): { roles: ModelRole[]; reason: RoleReason } {
  if (capability === 'embedding' || capability === 'rerank') {
    return {
      roles: [capability === 'embedding' ? 'embedding' : 'rerank'],
      reason: 'not_a_chat_model',
    };
  }
  if (audioDeclared && audioAllowed) {
    return { roles: ['primary', 'fast', 'voice'], reason: 'ok' };
  }
  if (!audioAllowed) {
    return { roles: ['primary', 'fast'], reason: 'audio_declaration_unsupported' };
  }
  return { roles: ['primary', 'fast'], reason: 'audio_input_not_declared' };
}
