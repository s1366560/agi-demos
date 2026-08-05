import type { RunInputDelivery } from '../../types';

export type SessionComposerDispatch =
  | { kind: 'run_input'; delivery: RunInputDelivery }
  | { kind: 'conversation_message' }
  | {
      kind: 'blocked';
      reason:
        | 'run_input_authority_stale'
        | 'run_input_delivery_required'
        | 'composer_authority_unavailable';
    };

export function resolveSessionComposerDispatch(input: {
  requestedDelivery: RunInputDelivery | null;
  availableDeliveries: readonly RunInputDelivery[];
  hasActiveRun: boolean;
  canSendConversationMessage: boolean;
  canSendRunInput: boolean;
}): SessionComposerDispatch {
  if (input.requestedDelivery) {
    if (
      input.hasActiveRun &&
      input.canSendRunInput &&
      input.availableDeliveries.includes(input.requestedDelivery)
    ) {
      return {
        kind: 'run_input',
        delivery: input.requestedDelivery,
      };
    }
    return {
      kind: 'blocked',
      reason: 'run_input_authority_stale',
    };
  }

  if (input.hasActiveRun || input.availableDeliveries.length > 0) {
    return {
      kind: 'blocked',
      reason: 'run_input_delivery_required',
    };
  }

  if (input.canSendConversationMessage) {
    return { kind: 'conversation_message' };
  }

  return {
    kind: 'blocked',
    reason: 'composer_authority_unavailable',
  };
}
