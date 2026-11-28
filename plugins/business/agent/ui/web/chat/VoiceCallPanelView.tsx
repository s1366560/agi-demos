import type React from 'react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { GripHorizontal, Maximize2, Mic, MicOff, Minimize2, PhoneOff, X } from 'lucide-react';
import { formatCallDuration } from '../../../../../../web/src/utils/format';

function useDrag(ref: React.RefObject<HTMLElement | null>) {
  const posRef = useRef({ x: 0, y: 0 });
  const draggingRef = useRef(false);
  const startRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Defer initial positioning to ensure portal DOM is attached
    const raf = requestAnimationFrame(() => {
      const initX = window.innerWidth - 420;
      const initY = window.innerHeight - 520;
      posRef.current = { x: Math.max(16, initX), y: Math.max(16, initY) };
      el.style.transform = `translate(${String(posRef.current.x)}px, ${String(posRef.current.y)}px)`;
    });

    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('[data-drag-handle]')) return;
      draggingRef.current = true;
      startRef.current = {
        x: e.clientX - posRef.current.x,
        y: e.clientY - posRef.current.y,
      };
      e.preventDefault();
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      const newX = Math.max(0, Math.min(window.innerWidth - 100, e.clientX - startRef.current.x));
      const newY = Math.max(0, Math.min(window.innerHeight - 60, e.clientY - startRef.current.y));
      posRef.current = { x: newX, y: newY };
      el.style.transform = `translate(${String(newX)}px, ${String(newY)}px)`;
    };

    const onMouseUp = () => {
      draggingRef.current = false;
    };

    el.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);

    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, [ref]);
}

interface Props {
  createPortal(children: ReactNode, container: Element): React.ReactPortal;
  status: string;
  callStartTime: number | null;
  error: string | null;
  isMuted: boolean;
  aiSpeaking: boolean;
  isMinimized: boolean;
  asrFinalText: string;
  asrInterimText: string;
  agentResponseText: string;
  isAgentStreaming: boolean;
  setMinimized(value: boolean): void;
  storeToggleMute(): void;
  handleEndCall(): void;
  waveform: ReactNode;
  video?: ReactNode;
  deviceSettings?: ReactNode;
  deviceControls?: ReactNode;
}
export function VoiceCallPanelView({
  createPortal,
  status,
  callStartTime,
  error,
  isMuted,
  aiSpeaking,
  isMinimized,
  asrFinalText,
  asrInterimText,
  agentResponseText,
  isAgentStreaming,
  setMinimized,
  storeToggleMute,
  handleEndCall,
  video,
  waveform,
  deviceSettings,
  deviceControls,
}: Props) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  useDrag(panelRef);
  const [duration, setDuration] = useState(0);
  // Duration timer
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (status === 'connected' && callStartTime) {
      interval = setInterval(() => {
        setDuration(Math.floor((Date.now() - callStartTime) / 1000));
      }, 1000);
    }
    return () => {
      clearInterval(interval);
    };
  }, [status, callStartTime]);

  // ---- Minimized view -------------------------------------------------------

  if (isMinimized) {
    return createPortal(
      <div ref={panelRef} className="fixed z-50 top-0 left-0" style={{ willChange: 'transform' }}>
        <div
          className="flex cursor-move items-center gap-3 rounded-lg border border-slate-700 bg-slate-900 px-4 py-2 shadow-md"
          data-drag-handle
        >
          <div
            role="status"
            aria-label={
              aiSpeaking
                ? t('agent.voiceCall.aiSpeaking', 'AI is speaking')
                : t('agent.voiceCall.connected', 'Connected')
            }
            title={
              aiSpeaking
                ? t('agent.voiceCall.aiSpeaking', 'AI is speaking')
                : t('agent.voiceCall.connected', 'Connected')
            }
            className={`w-3 h-3 rounded-full ${aiSpeaking ? 'bg-blue-500 animate-pulse motion-reduce:animate-none' : 'bg-green-500'}`}
          />
          <span className="text-xs text-slate-300">
            {aiSpeaking
              ? t('agent.voiceCall.aiSpeaking', 'AI is speaking')
              : t('agent.voiceCall.connected', 'Connected')}
          </span>
          <span className="font-mono text-sm text-slate-50">{formatCallDuration(duration)}</span>
          {isMuted && <MicOff size={14} className="text-red-400" />}
          <button
            type="button"
            onClick={() => {
              setMinimized(false);
            }}
            aria-label={t('agent.voiceCall.expandPanel', 'Expand voice call panel')}
            title={t('agent.voiceCall.expandPanel', 'Expand voice call panel')}
            className="p-1 text-slate-400 transition-colors hover:text-slate-50"
          >
            <Maximize2 size={14} />
          </button>
          <button
            type="button"
            onClick={handleEndCall}
            aria-label={t('agent.voiceCall.endCall', 'End call')}
            title={t('agent.voiceCall.endCall', 'End call')}
            className="p-1 text-red-400 hover:text-red-300 transition-colors"
          >
            <PhoneOff size={14} />
          </button>
        </div>
      </div>,
      document.body
    );
  }

  // ---- Expanded view --------------------------------------------------------

  return createPortal(
    <div ref={panelRef} className="fixed z-50 top-0 left-0" style={{ willChange: 'transform' }}>
      <div className="relative flex w-[380px] flex-col overflow-hidden rounded-lg border border-slate-700 bg-slate-900 shadow-lg">
        {/* Drag Handle + Header */}
        <div
          className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50 cursor-move"
          data-drag-handle
        >
          <div className="flex items-center gap-2">
            <GripHorizontal size={16} className="text-slate-500" />
            <div
              className={`w-2.5 h-2.5 rounded-full ${
                status === 'connected'
                  ? 'bg-green-500'
                  : status === 'connecting'
                    ? 'bg-yellow-500 animate-pulse motion-reduce:animate-none'
                    : 'bg-red-500'
              }`}
            />
            <span className="text-sm text-white font-medium">
              {status === 'connecting' && t('agent.voiceCall.connecting', 'Connecting…')}
              {status === 'connected' && formatCallDuration(duration)}
              {status === 'error' && t('agent.voiceCall.error', 'Error')}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => {
                setMinimized(true);
              }}
              aria-label={t('agent.voiceCall.minimizePanel', 'Minimize voice call panel')}
              title={t('agent.voiceCall.minimizePanel', 'Minimize voice call panel')}
              className="p-1.5 text-slate-400 hover:text-white transition-colors rounded"
            >
              <Minimize2 size={14} />
            </button>
            <button
              type="button"
              onClick={handleEndCall}
              aria-label={t('agent.voiceCall.endCall', 'End call')}
              title={t('agent.voiceCall.endCall', 'End call')}
              className="p-1.5 text-slate-400 hover:text-red-400 transition-colors rounded"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Error message */}
        {status === 'error' && error && (
          <div className="px-4 py-2 bg-red-500/10 text-red-400 text-xs">{error}</div>
        )}

        {video}
        {/* Audio-only Visualizer */}
        {!video && (
          <div className="flex items-center justify-center py-8">
            <div className="relative w-32 h-32">
              {/* AI avatar circle */}
              <div
                className={`
                  absolute inset-0 rounded-full border-4 flex items-center justify-center bg-slate-800
                  transition-[color,background-color,border-color,box-shadow,opacity] duration-300
                  ${aiSpeaking ? 'border-blue-500 shadow-xl shadow-blue-500/30' : 'border-slate-700'}
                `}
              >
                <div
                  className={`
                    w-16 h-16 rounded-full bg-blue-500/20
                    ${aiSpeaking ? 'animate-pulse motion-reduce:animate-none' : 'opacity-0'}
                  `}
                />
              </div>
              {/* Waveform under avatar */}
              <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 w-24 z-10">
                {waveform}
              </div>
            </div>
          </div>
        )}

        {/* ASR Transcript */}
        <div className="px-4 py-2 min-h-[60px] max-h-[120px] overflow-y-auto">
          {asrFinalText && <p className="text-sm text-slate-300 mb-1">{asrFinalText}</p>}
          {asrInterimText && <p className="text-sm text-slate-400 italic">{asrInterimText}</p>}
          {agentResponseText && (
            <p className="text-sm text-blue-300 mt-1">
              {agentResponseText}
              {isAgentStreaming && (
                <span className="animate-pulse motion-reduce:animate-none">|</span>
              )}
            </p>
          )}
        </div>

        {/* Controls */}
        <div className="flex items-center justify-center gap-4 px-4 py-4 border-t border-slate-700/30">
          {/* Mute */}
          <button
            type="button"
            onClick={storeToggleMute}
            title={
              isMuted
                ? t('agent.voiceCall.unmute', { defaultValue: 'Unmute' })
                : t('agent.voiceCall.mute', { defaultValue: 'Mute' })
            }
            aria-label={
              isMuted
                ? t('agent.voiceCall.unmute', { defaultValue: 'Unmute' })
                : t('agent.voiceCall.mute', { defaultValue: 'Mute' })
            }
            className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform]
              ${isMuted ? 'bg-red-500/20 text-red-500 hover:bg-red-500/30' : 'bg-slate-700 text-white hover:bg-slate-600'}
            `}
          >
            {isMuted ? <MicOff size={20} /> : <Mic size={20} />}
          </button>

          {deviceControls}
          {/* End call */}
          <button
            type="button"
            onClick={handleEndCall}
            title={t('agent.voiceCall.endCall', { defaultValue: 'End call' })}
            aria-label={t('agent.voiceCall.endCall', { defaultValue: 'End call' })}
            className="w-14 h-11 rounded-full bg-red-500 hover:bg-red-600 flex items-center justify-center text-white shadow-lg shadow-red-500/20 transition-[color,background-color,border-color,box-shadow,opacity]"
          >
            <PhoneOff size={22} />
          </button>
        </div>

        {deviceSettings}
      </div>
    </div>,
    document.body
  );
}
