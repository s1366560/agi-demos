/**
 * VoiceCallPanel - Floating draggable overlay for voice/video calls.
 *
 * Features:
 * - Draggable floating window (not full-screen modal)
 * - Minimize/expand capability
 * - Audio-only and video call modes
 * - Video rendering DOM elements for RTC SDK
 * - Device settings drawer (microphone, speaker, camera selection)
 */

import type React from 'react';
import { useEffect, useState, useCallback, useRef } from 'react';
import {
  PhoneOff,
  Mic,
  MicOff,
  Camera,
  CameraOff,
  Minimize2,
  Maximize2,
  Settings,
  X,
  GripHorizontal,
  Video,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useShallow } from 'zustand/react/shallow';

import { useVoiceCallStore } from '@/stores/voiceCallStore';
import { useVolcRTC } from '@/hooks/rtc/useVolcRTC';
import { VoiceWaveform } from './VoiceWaveform';

// ---- Drag Hook --------------------------------------------------------------

function useDrag(ref: React.RefObject<HTMLElement | null>) {
  const posRef = useRef({ x: 0, y: 0 });
  const draggingRef = useRef(false);
  const startRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Position bottom-right by default
    const initX = window.innerWidth - 420;
    const initY = window.innerHeight - 520;
    posRef.current = { x: Math.max(16, initX), y: Math.max(16, initY) };
    el.style.transform = `translate(${posRef.current.x}px, ${posRef.current.y}px)`;

    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('[data-drag-handle]')) return;
      draggingRef.current = true;
      startRef.current = { x: e.clientX - posRef.current.x, y: e.clientY - posRef.current.y };
      e.preventDefault();
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      const newX = Math.max(0, Math.min(window.innerWidth - 100, e.clientX - startRef.current.x));
      const newY = Math.max(0, Math.min(window.innerHeight - 60, e.clientY - startRef.current.y));
      posRef.current = { x: newX, y: newY };
      el.style.transform = `translate(${newX}px, ${newY}px)`;
    };

    const onMouseUp = () => {
      draggingRef.current = false;
    };

    el.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);

    return () => {
      el.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, [ref]);
}

// ---- Device Settings Panel --------------------------------------------------

const DeviceSettingsPanel: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const { t } = useTranslation();

  const {
    audioInputs,
    audioOutputs,
    videoInputs,
    selectedMicId,
    selectedSpeakerId,
    selectedCameraId,
    showDeviceSettings,
  } = useVoiceCallStore(
    useShallow((state) => ({
      audioInputs: state.audioInputs,
      audioOutputs: state.audioOutputs,
      videoInputs: state.videoInputs,
      selectedMicId: state.selectedMicId,
      selectedSpeakerId: state.selectedSpeakerId,
      selectedCameraId: state.selectedCameraId,
      showDeviceSettings: state.showDeviceSettings,
    })),
  );

  const { selectMicrophone, selectSpeaker, selectCamera } = useVoiceCallStore(
    useShallow((state) => ({
      selectMicrophone: state.selectMicrophone,
      selectSpeaker: state.selectSpeaker,
      selectCamera: state.selectCamera,
    })),
  );

  if (!showDeviceSettings) return null;

  const renderSelect = (
    labelText: string,
    devices: Array<{ deviceId: string; label: string }>,
    selectedId: string | null,
    onChange: (id: string) => void,
  ) => (
    <div className="mb-3">
      <label className="block text-xs text-slate-400 mb-1">
        {labelText}
        <select
          value={selectedId ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="mt-1 w-full px-2 py-1.5 bg-slate-700 border border-slate-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
        >
          {devices.length === 0 && (
            <option value="">{t('agent.voiceCall.noDevices', 'No devices found')}</option>
          )}
          {devices.map((d) => (
            <option key={d.deviceId} value={d.deviceId}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );

  return (
    <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg p-4 shadow-xl z-50">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-white">
          {t('agent.voiceCall.deviceSettings', 'Device Settings')}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="p-1 text-slate-400 hover:text-white transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      {renderSelect(
        t('agent.voiceCall.microphone', 'Microphone'),
        audioInputs,
        selectedMicId,
        selectMicrophone,
      )}

      {renderSelect(
        t('agent.voiceCall.speaker', 'Speaker'),
        audioOutputs,
        selectedSpeakerId,
        selectSpeaker,
      )}

      {renderSelect(
        t('agent.voiceCall.camera', 'Camera'),
        videoInputs,
        selectedCameraId,
        selectCamera,
      )}
    </div>
  );
};

// ---- Main Component ---------------------------------------------------------

export interface VoiceCallPanelProps {
  onClose: () => void;
}

export const VoiceCallPanel: React.FC<VoiceCallPanelProps> = ({ onClose }) => {
  const { t } = useTranslation();
  const [duration, setDuration] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);

  useDrag(panelRef);

  const {
    status,
    roomId,
    userId,
    appId,
    token,
    isMuted,
    isCameraOn,
    callStartTime,
    error,
    aiSpeaking,
    isMinimized,
    callMode,
    showDeviceSettings,
    selectedMicId,
    selectedCameraId,
  } = useVoiceCallStore(
    useShallow((state) => ({
      status: state.status,
      roomId: state.roomId,
      userId: state.userId,
      appId: state.appId,
      token: state.token,
      isMuted: state.isMuted,
      isCameraOn: state.isCameraOn,
      callStartTime: state.callStartTime,
      error: state.error,
      aiSpeaking: state.aiSpeaking,
      isMinimized: state.isMinimized,
      callMode: state.callMode,
      showDeviceSettings: state.showDeviceSettings,
      selectedMicId: state.selectedMicId,
      selectedCameraId: state.selectedCameraId,
    })),
  );

  const {
    toggleMute: storeToggleMute,
    toggleCamera: storeToggleCamera,
    endCall,
    setAiSpeaking,
    setMinimized,
    setShowDeviceSettings,
    setDevices,
  } = useVoiceCallStore(
    useShallow((state) => ({
      toggleMute: state.toggleMute,
      toggleCamera: state.toggleCamera,
      endCall: state.endCall,
      setAiSpeaking: state.setAiSpeaking,
      setMinimized: state.setMinimized,
      setShowDeviceSettings: state.setShowDeviceSettings,
      setDevices: state.setDevices,
    })),
  );

  const {
    joinRoom,
    leaveRoom,
    toggleMute: rtcToggleMute,
    startCamera,
    stopCamera,
    enumerateDevices,
    switchMicrophone,
    switchCamera,
  } = useVolcRTC({
    appId,
    roomId,
    userId,
    token,
    autoPublishAudio: !isMuted,
    selectedMicId,
    selectedCameraId,
    onAiSpeakingChange: setAiSpeaking,
    onError: (err) => useVoiceCallStore.setState({ status: 'error', error: err }),
  });

  // Join room when connected
  useEffect(() => {
    if (status === 'connected' && appId && token && roomId && userId) {
      joinRoom();
    }
  }, [status, appId, token, roomId, userId, joinRoom]);

  // Enumerate devices after joining
  useEffect(() => {
    if (status === 'connected') {
      enumerateDevices().then((devices) => {
        setDevices(devices);
      });
    }
  }, [status, enumerateDevices, setDevices]);

  // Duration timer
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (status === 'connected' && callStartTime) {
      interval = setInterval(() => {
        setDuration(Math.floor((Date.now() - callStartTime) / 1000));
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [status, callStartTime]);

  // Sync mute to RTC
  useEffect(() => {
    rtcToggleMute(isMuted);
  }, [isMuted, rtcToggleMute]);

  // Sync camera to RTC
  useEffect(() => {
    if (isCameraOn) {
      startCamera('rtc-local-video');
    } else {
      stopCamera();
    }
  }, [isCameraOn, startCamera, stopCamera]);

  // Sync device selection to RTC
  useEffect(() => {
    if (selectedMicId) {
      switchMicrophone(selectedMicId);
    }
  }, [selectedMicId, switchMicrophone]);

  useEffect(() => {
    if (selectedCameraId) {
      switchCamera(selectedCameraId);
    }
  }, [selectedCameraId, switchCamera]);

  const handleEndCall = useCallback(() => {
    leaveRoom();
    endCall();
    onClose();
  }, [leaveRoom, endCall, onClose]);

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60)
      .toString()
      .padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  // ---- Minimized view -------------------------------------------------------

  if (isMinimized) {
    return (
      <div
        ref={panelRef}
        className="fixed z-50 top-0 left-0"
        style={{ willChange: 'transform' }}
      >
        <div
          className="flex items-center gap-3 px-4 py-2 bg-slate-900/95 border border-slate-700/50 rounded-full shadow-2xl backdrop-blur-sm cursor-move"
          data-drag-handle
        >
          <div
            className={`w-3 h-3 rounded-full ${aiSpeaking ? 'bg-blue-500 animate-pulse' : 'bg-green-500'}`}
          />
          <span className="text-white text-sm font-mono">{formatDuration(duration)}</span>
          {isMuted && <MicOff size={14} className="text-red-400" />}
          <button
            type="button"
            onClick={() => setMinimized(false)}
            className="p-1 text-slate-400 hover:text-white transition-colors"
          >
            <Maximize2 size={14} />
          </button>
          <button
            type="button"
            onClick={handleEndCall}
            className="p-1 text-red-400 hover:text-red-300 transition-colors"
          >
            <PhoneOff size={14} />
          </button>
        </div>
      </div>
    );
  }

  // ---- Expanded view --------------------------------------------------------

  return (
    <div
      ref={panelRef}
      className="fixed z-50 top-0 left-0"
      style={{ willChange: 'transform' }}
    >
      <div className="relative flex flex-col bg-slate-900/95 border border-slate-700/50 rounded-2xl shadow-2xl backdrop-blur-sm w-[380px] overflow-hidden">
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
                    ? 'bg-yellow-500 animate-pulse'
                    : 'bg-red-500'
              }`}
            />
            <span className="text-sm text-white font-medium">
              {status === 'connecting' && t('agent.voiceCall.connecting', 'Connecting...')}
              {status === 'connected' && formatDuration(duration)}
              {status === 'error' && t('agent.voiceCall.error', 'Error')}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setMinimized(true)}
              className="p-1.5 text-slate-400 hover:text-white transition-colors rounded"
            >
              <Minimize2 size={14} />
            </button>
            <button
              type="button"
              onClick={handleEndCall}
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

        {/* Video Area */}
        {callMode === 'video' && (
          <div className="relative w-full h-[240px] bg-black">
            {/* Remote video (AI bot) - full area */}
            <div id="rtc-remote-video" className="absolute inset-0" />

            {/* Local video - picture-in-picture */}
            {isCameraOn && (
              <div
                id="rtc-local-video"
                className="absolute bottom-2 right-2 w-[100px] h-[75px] bg-slate-800 rounded-lg overflow-hidden border border-slate-600 z-10"
              />
            )}
          </div>
        )}

        {/* Audio-only Visualizer */}
        {callMode === 'audio' && (
          <div className="flex items-center justify-center py-8">
            <div className="relative w-32 h-32">
              {/* AI avatar circle */}
              <div
                className={`
                  absolute inset-0 rounded-full border-4 flex items-center justify-center bg-slate-800
                  transition-all duration-300
                  ${aiSpeaking ? 'border-blue-500 shadow-[0_0_30px_rgba(59,130,246,0.4)] scale-105' : 'border-slate-700'}
                `}
              >
                <div
                  className={`
                    w-16 h-16 rounded-full bg-blue-500/20
                    ${aiSpeaking ? 'animate-ping' : 'opacity-0'}
                  `}
                />
              </div>
              {/* Waveform under avatar */}
              <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 w-24 z-10">
                <VoiceWaveform active={!isMuted && status === 'connected'} />
              </div>
            </div>
          </div>
        )}

        {/* Controls */}
        <div className="flex items-center justify-center gap-4 px-4 py-4 border-t border-slate-700/30">
          {/* Mute */}
          <button
            type="button"
            onClick={storeToggleMute}
            title={isMuted ? 'Unmute' : 'Mute'}
            className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-all
              ${isMuted ? 'bg-red-500/20 text-red-500 hover:bg-red-500/30' : 'bg-slate-700 text-white hover:bg-slate-600'}
            `}
          >
            {isMuted ? <MicOff size={20} /> : <Mic size={20} />}
          </button>

          {/* Camera toggle */}
          <button
            type="button"
            onClick={storeToggleCamera}
            title={isCameraOn ? 'Turn off camera' : 'Turn on camera'}
            className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-all
              ${isCameraOn ? 'bg-blue-500/20 text-blue-500 hover:bg-blue-500/30' : 'bg-slate-700 text-white hover:bg-slate-600'}
            `}
          >
            {isCameraOn ? <Camera size={20} /> : <CameraOff size={20} />}
          </button>

          {/* Switch mode (audio <-> video) */}
          <button
            type="button"
            onClick={() => {
              const nextMode = callMode === 'audio' ? 'video' : 'audio';
              useVoiceCallStore.setState({ callMode: nextMode });
              if (nextMode === 'video' && !isCameraOn) {
                storeToggleCamera();
              }
              if (nextMode === 'audio' && isCameraOn) {
                storeToggleCamera();
              }
            }}
            title={callMode === 'audio' ? 'Switch to video' : 'Switch to audio'}
            className="w-11 h-11 rounded-full bg-slate-700 text-white hover:bg-slate-600 flex items-center justify-center transition-all"
          >
            <Video size={20} />
          </button>

          {/* Device settings */}
          <button
            type="button"
            onClick={() => setShowDeviceSettings(!showDeviceSettings)}
            title="Device settings"
            className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-all
              ${showDeviceSettings ? 'bg-slate-600 text-white' : 'bg-slate-700 text-white hover:bg-slate-600'}
            `}
          >
            <Settings size={20} />
          </button>

          {/* End call */}
          <button
            type="button"
            onClick={handleEndCall}
            title="End call"
            className="w-14 h-11 rounded-full bg-red-500 hover:bg-red-600 flex items-center justify-center text-white shadow-lg shadow-red-500/20 transition-all hover:scale-105"
          >
            <PhoneOff size={22} />
          </button>
        </div>

        {/* Device Settings Panel (positioned below controls) */}
        <div className="relative">
          <DeviceSettingsPanel onClose={() => setShowDeviceSettings(false)} />
        </div>
      </div>
    </div>
  );
};
