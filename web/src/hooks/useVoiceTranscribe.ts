import { useCallback, useLayoutEffect, useRef } from 'react';

import { useVoiceChat, type UseVoiceChatReturn } from './useVoiceChat';

export interface UseVoiceTranscribeOptions {
  projectId: string | undefined;
  conversationId: string | undefined;
  onInterim?: ((text: string) => void) | undefined;
  onFinal?: ((text: string) => void) | undefined;
  onError?: ((error: string) => void) | undefined;
}
export interface UseVoiceTranscribeReturn extends Pick<
  UseVoiceChatReturn,
  'session' | 'operation' | 'stream' | 'analyser'
> {
  isListening: boolean;
  toggle: () => Promise<boolean>;
  stop: () => Promise<void>;
}
export const useVoiceTranscribe = (
  options: UseVoiceTranscribeOptions
): UseVoiceTranscribeReturn => {
  const voice = useVoiceChat({
    projectId: options.projectId ?? '',
    conversationId: options.conversationId ?? '',
    onAsrInterim: options.onInterim,
    onAsrFinal: options.onFinal,
    onError: options.onError,
  });
  const { connect, disconnect, startRecording, isRecording } = voice;
  const intent = useRef(0);
  const pending = useRef<Promise<boolean> | null>(null);
  useLayoutEffect(() => {
    intent.current++;
    pending.current = null;
    return () => {
      intent.current++;
      pending.current = null;
    };
  }, [disconnect]);
  const stop = useCallback(() => {
    intent.current++;
    pending.current = null;
    return disconnect();
  }, [disconnect]);
  const toggle = useCallback((): Promise<boolean> => {
    if (isRecording) return stop().then(() => true);
    if (pending.current) return pending.current;
    const epoch = ++intent.current;
    const task = (async () => {
      try {
        await connect();
        if (epoch !== intent.current) return false;
        await startRecording();
        return epoch === intent.current;
      } catch {
        if (epoch === intent.current) await disconnect();
        return false;
      }
    })();
    pending.current = task;
    void task
      .finally(() => {
        if (pending.current === task) pending.current = null;
      })
      .catch(() => undefined);
    return task;
  }, [connect, disconnect, startRecording, isRecording, stop]);
  return {
    isListening: isRecording,
    toggle,
    stop,
    session: voice.session,
    operation: voice.operation,
    stream: voice.stream,
    analyser: voice.analyser,
  };
};
