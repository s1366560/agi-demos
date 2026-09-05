/** Streaming playback remains a child of the voice session that produced it. */
import { useState, useRef, useCallback, useEffect } from 'react';

import {
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';

export interface UseAudioQueueReturn {
  enqueueChunk: (audioData: ArrayBuffer, operation: WebOperationContextV2) => Promise<void>;
  stop: () => Promise<void>;
  clear: () => Promise<void>;
  isPlaying: boolean;
}

interface PlaybackSession {
  parent: WebOperationContextV2;
  active: boolean;
  stop: () => void;
  ready: Promise<void>;
  drained: Promise<void>;
  tail: Promise<void>;
  audio: AudioContext | undefined;
  operation: WebOperationContextV2 | undefined;
  sources: Set<AudioBufferSourceNode>;
  nextStart: number;
  cleanupErrors: unknown[];
}

const cancelled = () => new DOMException('Voice playback retired', 'AbortError');
const isCancelled = (error: unknown) =>
  error instanceof DOMException && error.name === 'AbortError';

export const useAudioQueue = (): UseAudioQueueReturn => {
  const [isPlaying, setIsPlaying] = useState(false);
  const current = useRef<PlaybackSession | null>(null);
  const sessions = useRef(new Set<PlaybackSession>());
  const mounted = useRef(true);

  const createSession = useCallback((parent: WebOperationContextV2): PlaybackSession => {
    parent.check();
    let resolveReady!: () => void;
    let resolveStopped!: () => void;
    const stopped = new Promise<void>((resolve) => {
      resolveStopped = resolve;
    });
    const session: PlaybackSession = {
      parent,
      active: true,
      ready: new Promise<void>((resolve) => {
        resolveReady = resolve;
      }),
      drained: Promise.resolve(),
      tail: Promise.resolve(),
      audio: undefined,
      operation: undefined,
      sources: new Set(),
      nextStart: 0,
      cleanupErrors: [],
      stop: () => {
        if (!session.active) return;
        session.active = false;
        for (const source of session.sources) {
          source.onended = null;
          try {
            source.disconnect();
          } catch (error) {
            session.cleanupErrors.push(error);
          }
          try {
            source.stop();
          } catch (error) {
            // Web Audio reports InvalidStateError when a source never started.
            if (!(error instanceof DOMException && error.name === 'InvalidStateError')) {
              session.cleanupErrors.push(error);
            }
          }
        }
        session.sources.clear();
        if (mounted.current && current.current === session) setIsPlaying(false);
        resolveStopped();
      },
    };
    session.drained = parent
      .runChild(async (operation) => {
        session.operation = operation;
        operation.signal.addEventListener('abort', session.stop, { once: true });
        let failure: { error: unknown } | undefined;
        try {
          operation.check();
          if (!session.active) throw cancelled();
          session.audio = new AudioContext();
          resolveReady();
          await stopped;
        } catch (error) {
          failure = { error };
        }
        session.stop();
        resolveReady();
        // decodeAudioData and resume cannot be cancelled. Drain before closing/releasing.
        await session.tail;
        try {
          if (session.audio && session.audio.state !== 'closed') await session.audio.close();
        } catch (error) {
          session.cleanupErrors.push(error);
        } finally {
          operation.signal.removeEventListener('abort', session.stop);
        }
        if (session.cleanupErrors.length) {
          throw new WebOperationCleanupErrorV2(
            [...(failure ? [failure.error] : []), ...session.cleanupErrors],
            'Voice audio resources failed to close'
          );
        }
        if (failure) throw failure.error;
      })
      .catch((error: unknown) => {
        if (!isCancelled(error)) throw error;
      });
    sessions.current.add(session);
    // Observe without changing the promise returned to explicit stop callers.
    void session.drained.catch(() => undefined);
    return session;
  }, []);

  const enqueueChunk = useCallback(
    (audioData: ArrayBuffer, parent: WebOperationContextV2) => {
      try {
        if (!mounted.current) throw cancelled();
        parent.check();
        let session = current.current;
        if (!session || !session.active || session.parent !== parent) {
          session?.stop();
          session = createSession(parent);
          current.current = session;
        }
        const playback = session;
        const check = () => {
          parent.check();
          playback.operation?.check();
          if (!playback.active || current.current !== playback || !mounted.current)
            throw cancelled();
        };
        const job = playback.tail.then(async () => {
          // Admission can reject before the callback supplies an AudioContext.
          await Promise.race([
            playback.ready,
            playback.drained.then(() => {
              throw cancelled();
            }),
          ]);
          check();
          const audio = playback.audio!;
          if (audio.state === 'suspended') {
            await audio.resume();
            check();
          }
          const buffer = await audio.decodeAudioData(audioData.slice(0));
          check();
          const source = audio.createBufferSource();
          source.buffer = buffer;
          source.connect(audio.destination);
          source.onended = () => {
            if (!playback.sources.has(source)) return;
            try {
              source.disconnect();
            } catch (error) {
              playback.cleanupErrors.push(error);
            }
            playback.sources.delete(source);
            if (mounted.current && current.current === playback && playback.sources.size === 0) {
              setIsPlaying(false);
            }
          };
          playback.sources.add(source);
          playback.nextStart = Math.max(playback.nextStart, audio.currentTime + 0.05);
          source.start(playback.nextStart);
          playback.nextStart += buffer.duration;
          setIsPlaying(true);
        });
        playback.tail = job.catch(() => undefined);
        return job;
      } catch (error) {
        return Promise.reject(error);
      }
    },
    [createSession]
  );

  const stop = useCallback(async () => {
    const retiring = [...sessions.current];
    for (const session of retiring) session.stop();
    current.current = null;
    const results = await Promise.allSettled(retiring.map((session) => session.drained));
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') sessions.current.delete(retiring[index]!);
    });
    const failures = results.filter(
      (result): result is PromiseRejectedResult => result.status === 'rejected'
    );
    if (failures.length)
      throw new AggregateError(
        failures.map((result) => result.reason),
        'Voice playback cleanup failed'
      );
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      void stop().catch((error: unknown) => {
        console.error('Voice playback cleanup failed', error);
      });
    };
  }, [stop]);

  return { enqueueChunk, stop, clear: stop, isPlaying };
};
