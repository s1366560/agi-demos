/**
 * useVoiceTranscribe - WebSocket-based voice-to-text transcription hook.
 *
 * A lightweight wrapper around the backend Volcengine ASR streaming pipeline,
 * designed for dictating text into a chat input field. Unlike useVoiceChat
 * (which handles the full voice call lifecycle including TTS and agent
 * responses), this hook only performs:
 *
 *   1. WebSocket connection to the backend /voice/chat endpoint
 *   2. Microphone capture via AudioWorklet (raw PCM Int16 at 16kHz)
 *   3. ASR interim/final text callbacks for inserting into a text field
 *
 * The backend voice endpoint already supports ASR-only usage -- it simply
 * won't produce TTS/agent responses unless the client sends silence long
 * enough to trigger the agent bridge.
 *
 * Usage:
 *   const { isListening, toggle } = useVoiceTranscribe({
 *     projectId, conversationId,
 *     onInterim: (text) => setContent(prev => prev + text),
 *     onFinal: (text) => setContent(prev => prev + text),
 *   });
 */

import { useState, useRef, useCallback, useEffect } from 'react';

import { createWebSocketUrl } from '@/services/client/urlUtils';

import { getAuthToken } from '@/utils/tokenResolver';

export interface UseVoiceTranscribeOptions {
  /** Active project ID (required for the voice endpoint). */
  projectId: string | undefined;
  /** Active conversation ID (required for the voice endpoint). */
  conversationId: string | undefined;
  /** Called with interim (in-progress) ASR text while the user speaks. */
  onInterim?: ((text: string) => void) | undefined;
  /** Called with final ASR text once a sentence/phrase is confirmed. */
  onFinal?: ((text: string) => void) | undefined;
  /** Called on connection or recording errors. */
  onError?: ((error: string) => void) | undefined;
}

export interface UseVoiceTranscribeReturn {
  /** Whether the microphone is currently capturing and streaming. */
  isListening: boolean;
  /** Toggle listening on/off. Returns false if preconditions not met. */
  toggle: () => Promise<boolean>;
  /** Explicitly stop listening and tear down resources. */
  stop: () => void;
}

interface VoiceTextMessage {
  type: string;
  text?: string;
  message?: string;
}

const DEFAULT_SPEAKER = 'zh_female_tianmeixiaoyuan_moon_bigtts';

export const useVoiceTranscribe = (
  options: UseVoiceTranscribeOptions
): UseVoiceTranscribeReturn => {
  const [isListening, setIsListening] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const isMountedRef = useRef(true);
  const connectionIdRef = useRef(0);

  // Keep latest options in a ref to avoid re-creating callbacks
  const optionsRef = useRef(options);
  optionsRef.current = options;

  /**
   * Handle incoming JSON messages from the WebSocket.
   * We only care about asr_interim, asr_final, and error.
   */
  const handleTextMessage = useCallback((data: string) => {
    const opts = optionsRef.current;
    let parsed: VoiceTextMessage;
    try {
      parsed = JSON.parse(data) as VoiceTextMessage;
    } catch {
      return;
    }

    switch (parsed.type) {
      case 'asr_interim':
        if (parsed.text !== undefined) {
          opts.onInterim?.(parsed.text);
        }
        break;
      case 'asr_final':
        if (parsed.text !== undefined) {
          opts.onFinal?.(parsed.text);
        }
        break;
      case 'error':
        if (parsed.message !== undefined) {
          opts.onError?.(parsed.message);
        }
        break;
      default:
        // Ignore agent_token, agent_complete, tts_start, tts_end, etc.
        break;
    }
  }, []);

  /**
   * Tear down audio capture resources (mic, worklet, context).
   */
  const teardownAudio = useCallback(() => {
    if (workletNodeRef.current) {
      workletNodeRef.current.port.onmessage = null;
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }

    if (sourceNodeRef.current) {
      sourceNodeRef.current.disconnect();
      sourceNodeRef.current = null;
    }

    if (mediaStreamRef.current) {
      for (const track of mediaStreamRef.current.getTracks()) {
        track.stop();
      }
      mediaStreamRef.current = null;
    }

    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {
        // Ignore close errors during teardown
      });
      audioContextRef.current = null;
    }
  }, []);

  /**
   * Fully stop: tear down audio + close WebSocket + reset state.
   */
  const stop = useCallback(() => {
    connectionIdRef.current++;

    teardownAudio();

    if (wsRef.current) {
      const ws = wsRef.current;
      wsRef.current = null;
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    }

    if (isMountedRef.current) {
      setIsListening(false);
    }
  }, [teardownAudio]);

  /**
   * Start the full pipeline: WebSocket → AudioWorklet → streaming PCM.
   */
  const start = useCallback(async (): Promise<boolean> => {
    const opts = optionsRef.current;

    if (!opts.projectId || !opts.conversationId) {
      opts.onError?.('Missing projectId or conversationId');
      return false;
    }

    const token = getAuthToken();
    if (!token) {
      opts.onError?.('No auth token available');
      return false;
    }

    // Bump connection ID for stale event protection
    const connId = ++connectionIdRef.current;

    // 1. Open WebSocket
    const wsUrl = createWebSocketUrl('/voice/chat', {
      token,
      project_id: opts.projectId,
      conversation_id: opts.conversationId,
    });

    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    // Wrap the WS open/error/close in a promise so we can await connection
    const connected = await new Promise<boolean>((resolve) => {
      ws.onopen = () => {
        if (connId !== connectionIdRef.current) {
          ws.close();
          resolve(false);
          return;
        }

        // Send voice configuration
        ws.send(
          JSON.stringify({
            type: 'voice_config',
            sample_rate: 16000,
            speaker: DEFAULT_SPEAKER,
          })
        );
        resolve(true);
      };

      ws.onerror = () => {
        if (connId !== connectionIdRef.current) {
          resolve(false);
          return;
        }
        opts.onError?.('WebSocket connection error');
        resolve(false);
      };

      // If the WS closes before opening, also resolve false
      ws.onclose = () => {
        if (connId !== connectionIdRef.current) {
          resolve(false);
          return;
        }
        resolve(false);
      };
    });

    if (!connected || connId !== connectionIdRef.current) {
      // Clean up on failure
      wsRef.current = null;
      return false;
    }

    // Set up ongoing message handler
    ws.onmessage = (event: MessageEvent) => {
      if (connId !== connectionIdRef.current) return;
      if (!isMountedRef.current) return;
      if (typeof event.data === 'string') {
        handleTextMessage(event.data);
      }
      // Ignore binary frames (TTS audio) -- we don't need them for dictation
    };

    ws.onerror = () => {
      if (connId !== connectionIdRef.current) return;
      if (!isMountedRef.current) return;
      opts.onError?.('WebSocket error');
      stop();
    };

    ws.onclose = () => {
      if (connId !== connectionIdRef.current) return;
      if (!isMountedRef.current) return;
      stop();
    };

    // 2. Start AudioWorklet capture
    try {
      const ctx = new AudioContext();
      audioContextRef.current = ctx;

      await ctx.audioWorklet.addModule('/audio-processor.js');

      const workletNode = new AudioWorkletNode(ctx, 'audio-processor');
      workletNode.port.postMessage({ type: 'config', sampleRate: ctx.sampleRate });
      workletNodeRef.current = workletNode;

      // Forward PCM chunks to WebSocket
      workletNode.port.onmessage = (event: MessageEvent) => {
        const wsConn = wsRef.current;
        if (wsConn && wsConn.readyState === WebSocket.OPEN && event.data instanceof Int16Array) {
          wsConn.send(event.data.buffer);
        }
      };

      // Acquire microphone
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;

      // Connect: mic → worklet
      const source = ctx.createMediaStreamSource(stream);
      sourceNodeRef.current = source;
      source.connect(workletNode);

      if (isMountedRef.current) {
        setIsListening(true);
      }
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to start recording';
      opts.onError?.(message);
      stop();
      return false;
    }
  }, [handleTextMessage, stop]);

  /**
   * Toggle listening on/off.
   */
  const toggle = useCallback(async (): Promise<boolean> => {
    if (isListening) {
      stop();
      return true;
    }
    return start();
  }, [isListening, start, stop]);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      connectionIdRef.current++;
      // Do NOT call stop() here -- React StrictMode double-mounts in dev.
      // The parent component is responsible for calling stop() on unmount
      // or when the component is no longer needed.
    };
  }, []);

  return { isListening, toggle, stop };
};
