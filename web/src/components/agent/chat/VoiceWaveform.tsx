/**
 * VoiceWaveform - Real-time audio frequency visualization
 *
 * Uses Web Audio API (AudioContext + AnalyserNode) to render
 * frequency bars from the microphone stream.
 */

import { useEffect, useRef, memo } from 'react';

interface VoiceWaveformProps {
  active: boolean;
  barCount?: number;
  className?: string;
}

export const VoiceWaveform = memo<VoiceWaveformProps>(
  ({ active, barCount = 5, className = '' }) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const contextRef = useRef<{
      audioContext: AudioContext;
      analyser: AnalyserNode;
      source: MediaStreamAudioSourceNode;
      stream: MediaStream;
      animationId: number;
    } | null>(null);

    useEffect(() => {
      if (!active) {
        if (contextRef.current) {
          cancelAnimationFrame(contextRef.current.animationId);
          contextRef.current.source.disconnect();
          contextRef.current.audioContext.close();
          contextRef.current.stream.getTracks().forEach((t) => t.stop());
          contextRef.current = null;
        }
        return;
      }

      let cancelled = false;

      const start = async () => {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          if (cancelled) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }

          const audioContext = new AudioContext();
          const analyser = audioContext.createAnalyser();
          analyser.fftSize = 64;
          const source = audioContext.createMediaStreamSource(stream);
          source.connect(analyser);

          const bufferLength = analyser.frequencyBinCount;
          const dataArray = new Uint8Array(bufferLength);

          const draw = () => {
            if (cancelled) return;
            const canvas = canvasRef.current;
            if (!canvas) return;

            const ctx = canvas.getContext('2d');
            if (!ctx) return;

            analyser.getByteFrequencyData(dataArray);

            const w = canvas.width;
            const h = canvas.height;
            ctx.clearRect(0, 0, w, h);

            const barWidth = Math.floor(w / barCount);
            const gap = 2;
            const step = Math.floor(bufferLength / barCount);

            for (let i = 0; i < barCount; i++) {
              const value = dataArray[i * step] / 255;
              const barHeight = Math.max(4, value * h * 0.9);
              const x = i * barWidth + gap / 2;
              const y = (h - barHeight) / 2;

              ctx.fillStyle = `rgba(239, 68, 68, ${0.6 + value * 0.4})`;
              ctx.beginPath();
              ctx.roundRect(x, y, barWidth - gap, barHeight, 2);
              ctx.fill();
            }

            const animationId = requestAnimationFrame(draw);
            if (contextRef.current) {
              contextRef.current.animationId = animationId;
            }
          };

          contextRef.current = {
            audioContext,
            analyser,
            source,
            stream,
            animationId: requestAnimationFrame(draw),
          };
        } catch {
          // Microphone permission denied or unavailable
        }
      };

      start();

      return () => {
        cancelled = true;
        if (contextRef.current) {
          cancelAnimationFrame(contextRef.current.animationId);
          contextRef.current.source.disconnect();
          contextRef.current.audioContext.close();
          contextRef.current.stream.getTracks().forEach((t) => t.stop());
          contextRef.current = null;
        }
      };
    }, [active, barCount]);

    if (!active) return null;

    return (
      <canvas
        ref={canvasRef}
        width={barCount * 8}
        height={24}
        className={`inline-block ${className}`}
        aria-hidden="true"
      />
    );
  }
);
VoiceWaveform.displayName = 'VoiceWaveform';
