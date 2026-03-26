/**
 * useAudioQueue - Audio playback queue for streaming TTS chunks.
 *
 * Manages a sequential playback queue of MP3 audio chunks received from the
 * TTS server. Creates an AudioContext lazily on first enqueue, decodes each
 * chunk, and schedules them for gapless playback using precise timing.
 */

import { useState, useRef, useCallback, useEffect } from 'react';

export interface UseAudioQueueReturn {
  /** Decode and schedule an MP3 audio chunk for playback. */
  enqueueChunk: (audioData: ArrayBuffer) => Promise<void>;
  /** Stop all currently playing and scheduled sources. */
  stop: () => void;
  /** Stop all sources and reset the time pointer. */
  clear: () => void;
  /** True when audio sources are scheduled and playing. */
  isPlaying: boolean;
}

export const useAudioQueue = (): UseAudioQueueReturn => {
  const [isPlaying, setIsPlaying] = useState(false);

  const audioContextRef = useRef<AudioContext | null>(null);
  const nextStartTimeRef = useRef<number>(0);
  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const isClosedRef = useRef(false);

  /**
   * Lazily create the AudioContext. Returns the existing context if already
   * created, or creates a new one.
   */
  const getOrCreateContext = useCallback((): AudioContext => {
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      return audioContextRef.current;
    }
    const ctx = new AudioContext();
    audioContextRef.current = ctx;
    return ctx;
  }, []);

  /**
   * Remove a source from the active set. When no sources remain, set
   * isPlaying to false.
   */
  const removeSource = useCallback((source: AudioBufferSourceNode) => {
    activeSourcesRef.current.delete(source);
    if (activeSourcesRef.current.size === 0) {
      setIsPlaying(false);
    }
  }, []);

  /**
   * Disconnect and stop all active sources, then clear the set.
   */
  const disconnectAllSources = useCallback(() => {
    for (const source of activeSourcesRef.current) {
      try {
        // Disconnect first to prevent onended from firing after stop
        source.disconnect();
        source.stop();
      } catch {
        // Source may already be stopped or disconnected
      }
    }
    activeSourcesRef.current.clear();
    setIsPlaying(false);
  }, []);

  const enqueueChunk = useCallback(
    async (audioData: ArrayBuffer): Promise<void> => {
      if (isClosedRef.current) {
        return;
      }

      const ctx = getOrCreateContext();

      // Resume context if suspended (browsers require user gesture)
      if (ctx.state === 'suspended') {
        await ctx.resume();
      }

      let buffer: AudioBuffer;
      try {
        // decodeAudioData requires ownership of the ArrayBuffer in some
        // browsers, so pass a copy to avoid detached buffer errors.
        buffer = await ctx.decodeAudioData(audioData.slice(0));
      } catch (err) {
        console.error('Failed to decode audio chunk:', err);
        return;
      }

      // Determine when to schedule this chunk
      const now = ctx.currentTime;
      if (nextStartTimeRef.current < now) {
        // Queue is idle -- start with a small lead-in to prevent glitches
        nextStartTimeRef.current = now + 0.05;
      }

      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);

      source.onended = () => {
        removeSource(source);
      };

      activeSourcesRef.current.add(source);
      setIsPlaying(true);

      source.start(nextStartTimeRef.current);
      nextStartTimeRef.current += buffer.duration;
    },
    [getOrCreateContext, removeSource]
  );

  const stop = useCallback(() => {
    disconnectAllSources();
    // Reset the schedule pointer so the next enqueue starts fresh
    nextStartTimeRef.current = 0;
  }, [disconnectAllSources]);

  const clear = useCallback(() => {
    disconnectAllSources();
    nextStartTimeRef.current = 0;
  }, [disconnectAllSources]);

  // Cleanup on unmount: close the AudioContext
  useEffect(() => {
    isClosedRef.current = false;

    return () => {
      isClosedRef.current = true;
      disconnectAllSources();
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close().catch(() => {
          // Ignore close errors during teardown
        });
        audioContextRef.current = null;
      }
    };
  }, [disconnectAllSources]);

  return { enqueueChunk, stop, clear, isPlaying };
};
