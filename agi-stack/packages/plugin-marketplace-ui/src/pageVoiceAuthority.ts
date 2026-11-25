import {
  runPageVoice,
  type OpenVoiceSocket,
  type VoiceMode,
} from '../../plugin-slots/src/pageVoice';
import { approveVoice } from './voicePermission';

type Authorized = { principal_id: string; conversation_id: string; ticket: string };
type VoiceAuthorityOptions = {
  projectId: string | null;
  tenantId: string;
  pluginId: string;
  locale: string;
  open?: OpenVoiceSocket | undefined;
  authorize(conversation: string, signal: AbortSignal): Promise<Authorized>;
};
type ActiveVoice = { id: string; controller: AbortController; mute?: (value: boolean) => void };
export function createPageVoiceAuthority(options: VoiceAuthorityOptions) {
  let session: ActiveVoice | undefined;
  async function start(
    mode: VoiceMode,
    conversation: string,
    caller: AbortSignal,
    emit: (event: unknown) => void
  ) {
    if (!options.open || !options.projectId) throw new Error('voice_unavailable');
    if (session) throw new Error('voice_session_active');
    caller.throwIfAborted();
    const controller = new AbortController();
    const { signal } = controller;
    const active: ActiveVoice = { id: crypto.randomUUID(), controller };
    session = active;
    const abort = () => controller.abort();
    caller.addEventListener('abort', abort, { once: true });
    let timer: ReturnType<typeof setTimeout> | undefined;
    let revoked = false;
    try {
      const grant = await options.authorize(conversation, signal);
      if (!grant.principal_id || grant.conversation_id !== conversation)
        throw new Error('voice_scope_invalid');
      signal.throwIfAborted();
      await approveVoice(options.pluginId, conversation, options.locale, signal);
      async function validate() {
        const current = await options.authorize(conversation, signal);
        if (current.principal_id !== grant.principal_id || current.conversation_id !== conversation)
          throw new Error('voice_scope_changed');
        return current;
      }
      const admission=await validate();
      if (!admission.ticket) throw new Error('voice_grant_unavailable');
      signal.throwIfAborted();
      const refresh = () => {
        timer = setTimeout(() => {
          void validate().then(
            () => {
              if (!signal.aborted) refresh();
            },
            () => {
              revoked = true;
              abort();
            }
          );
        }, 3000);
      };
      refresh();
      const socket = await options.open(
        {
          tenantId: options.tenantId,
          projectId: options.projectId,
          conversationId: conversation,
          principalId: grant.principal_id,
        },
        signal
      );
      emit({ type: 'handle', id: active.id });
      await runPageVoice({
        socket,
        ticket: admission.ticket,
        mode,
        signal,
        event: emit,
        workletUrl: new URL(
          'audio-processor.js',
          document.baseURI.startsWith('file:') ? document.baseURI : location.origin + '/'
        ).href,
        bindMute(handler) {
          active.mute = handler;
        },
      });
      if (revoked) throw new Error('voice_grant_revoked');
    } finally {
      controller.abort();
      clearTimeout(timer);
      caller.removeEventListener('abort', abort);
      if (session === active) session = undefined;
    }
  }
  return {
    start,
    mute(id: string, muted: boolean) {
      if (!session || session.id !== id || session.controller.signal.aborted || !session.mute)
        throw new Error('voice_session_unavailable');
      session.mute(muted);
    },
    stop() {
      session?.controller.abort();
    },
  };
}
