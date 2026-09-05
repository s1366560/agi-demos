import { memo, useEffect, useRef } from 'react';

import type { WebOperationContextV2 } from '../../../plugins/webOperationAdmissionV2';

interface VoiceWaveformProps {
  active: boolean;
  analyser: AnalyserNode | null;
  operation: WebOperationContextV2 | null;
  barCount?: number | undefined;
  className?: string | undefined;
}

/** Displays the session's microphone analyser without owning a second capture stream. */
export const VoiceWaveform = memo<VoiceWaveformProps>(
  ({ active, analyser, operation, barCount = 5, className = '' }) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    useEffect(() => {
      if (!active || !analyser || !operation) return;
      let cancelled = false;
      let animationId = 0;
      const stop = () => {
        cancelled = true;
        cancelAnimationFrame(animationId);
      };
      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const draw = () => {
        if (cancelled) return;
        try {
          operation.check();
        } catch {
          stop();
          return;
        }
        const canvas = canvasRef.current;
        const ctx = canvas?.getContext('2d');
        if (!canvas || !ctx) return;
        analyser.getByteFrequencyData(dataArray);
        const { width, height } = canvas;
        ctx.clearRect(0, 0, width, height);
        const barWidth = Math.floor(width / barCount);
        const step = Math.floor(dataArray.length / barCount);
        for (let i = 0; i < barCount; i++) {
          const value = (dataArray[i * step] ?? 0) / 255;
          const barHeight = Math.max(4, value * height * 0.9);
          ctx.fillStyle = `rgba(239, 68, 68, ${String(0.6 + value * 0.4)})`;
          ctx.beginPath();
          ctx.roundRect(i * barWidth + 1, (height - barHeight) / 2, barWidth - 2, barHeight, 2);
          ctx.fill();
        }
        animationId = requestAnimationFrame(draw);
      };
      operation.signal.addEventListener('abort', stop, { once: true });
      draw();
      return () => {
        stop();
        operation.signal.removeEventListener('abort', stop);
      };
    }, [active, analyser, operation, barCount]);
    return active ? (
      <canvas
        ref={canvasRef}
        width={barCount * 8}
        height={24}
        className={`inline-block ${className}`}
        aria-hidden="true"
      />
    ) : null;
  }
);
VoiceWaveform.displayName = 'VoiceWaveform';
