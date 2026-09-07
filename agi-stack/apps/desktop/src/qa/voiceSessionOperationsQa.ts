import type { DesktopVoiceSessionOperationsV2 } from '../plugins/desktopVoiceSessionAuthorityModuleV2';
import type { VoiceTranscriptionRuntime } from '../features/chat/voiceTranscriptionRuntime';
import type { VoiceCallRuntime } from '../features/chat/voiceCallRuntime';

/** Explicit presentation fixture; it does not claim native or generation authority. */
export function createVoiceSessionOperationsQa(runtimes: {
  transcription?: VoiceTranscriptionRuntime;
  call?: VoiceCallRuntime;
}): DesktopVoiceSessionOperationsV2 {
  return {
    async acquireTranscription({ signal }) {
      signal.throwIfAborted();
      if (!runtimes.transcription) throw new Error('QA transcription unavailable');
      return { runtime: runtimes.transcription, release: async () => {} };
    },
    async acquireCall({ signal }) {
      signal.throwIfAborted();
      if (!runtimes.call) throw new Error('QA call unavailable');
      return { runtime: runtimes.call, release: async () => {} };
    },
  };
}
export const unavailableVoiceSessionOperationsQa = createVoiceSessionOperationsQa({});
