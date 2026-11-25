import { createPortal } from 'react-dom';
/**
 * VoiceCallPanel - Floating draggable overlay for voice/video calls.
 *
 * Features:
 * - Draggable floating window (not full-screen modal)
 * - Minimize/expand capability
 * - Audio-only and video call modes
 * - ASR transcript display (interim + final + agent response)
 * - Device settings drawer (microphone, speaker, camera selection)
 */

import type React from 'react';
import { useCallback, useEffect, useLayoutEffect, useRef, useSyncExternalStore } from 'react';

import { VoiceCallPanelView } from '@business/agent/ui/web/chat/VoiceCallPanelView';
import { useTranslation } from 'react-i18next';

import { Camera, CameraOff, Settings, Video, X } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useVoiceCallStore } from '@/stores/voiceCallStore';

import { useAudioQueue } from '@/hooks/useAudioQueue';
import { useVoiceChat } from '@/hooks/useVoiceChat';

import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
} from '../../../plugins/webOperationAdmissionV2';

import { useVoiceSessionMediaV2 } from './useVoiceSessionMediaV2';
import { VoiceWaveform } from './VoiceWaveform';

// ---- Drag Hook --------------------------------------------------------------

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
    }))
  );

  const { selectMicrophone, selectSpeaker, selectCamera } = useVoiceCallStore(
    useShallow((state) => ({
      selectMicrophone: state.selectMicrophone,
      selectSpeaker: state.selectSpeaker,
      selectCamera: state.selectCamera,
    }))
  );

  if (!showDeviceSettings) return null;

  const renderSelect = (
    labelText: string,
    devices: Array<{ deviceId: string; label: string }>,
    selectedId: string | null,
    onChange: (id: string) => void
  ) => (
    <div className="mb-3">
      <label className="block text-xs text-slate-400 mb-1">
        {labelText}
        <select
          value={selectedId ?? ''}
          onChange={(e) => {
            onChange(e.target.value);
          }}
          className="mt-1 w-full rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-slate-100 focus:border-blue-500 focus:outline-none"
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
    <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-lg border border-slate-700 bg-slate-800 p-4 shadow-md">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-50">
          {t('agent.voiceCall.deviceSettings', 'Device Settings')}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('agent.voiceCall.closeDeviceSettings', 'Close device settings')}
          title={t('agent.voiceCall.closeDeviceSettings', 'Close device settings')}
          className="p-1 text-slate-400 transition-colors hover:text-slate-50"
        >
          <X size={14} />
        </button>
      </div>

      {renderSelect(
        t('agent.voiceCall.microphone', 'Microphone'),
        audioInputs,
        selectedMicId,
        selectMicrophone
      )}

      {renderSelect(
        t('agent.voiceCall.speaker', 'Speaker'),
        audioOutputs,
        selectedSpeakerId,
        selectSpeaker
      )}

      {renderSelect(
        t('agent.voiceCall.camera', 'Camera'),
        videoInputs,
        selectedCameraId,
        selectCamera
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
  const localVideoRef = useRef<HTMLVideoElement>(null);
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );

  const {
    status,
    callId,
    owner,
    conversationId,
    projectId,
    isMuted,
    isCameraOn,
    callStartTime,
    error,
    aiSpeaking,
    isMinimized,
    callMode,
    showDeviceSettings,
    asrInterimText,
    asrFinalText,
    agentResponseText,
    isAgentStreaming,
  } = useVoiceCallStore(
    useShallow((state) => ({
      status: state.status,
      callId: state.callId,
      owner: state.owner,
      conversationId: state.conversationId,
      projectId: state.projectId,
      isMuted: state.isMuted,
      isCameraOn: state.isCameraOn,
      callStartTime: state.callStartTime,
      error: state.error,
      aiSpeaking: state.aiSpeaking,
      isMinimized: state.isMinimized,
      callMode: state.callMode,
      showDeviceSettings: state.showDeviceSettings,
      asrInterimText: state.asrInterimText,
      asrFinalText: state.asrFinalText,
      agentResponseText: state.agentResponseText,
      isAgentStreaming: state.isAgentStreaming,
    }))
  );

  const {
    toggleMute: storeToggleMute,
    toggleCamera: storeToggleCamera,
    endCall,
    setAiSpeaking,
    setConnected,
    setMinimized,
    setShowDeviceSettings,
    setDevices,
    setAsrInterimText,
    setAsrFinalText,
    appendAgentToken,
    setAgentComplete,
    setAgentStreaming,
  } = useVoiceCallStore(
    useShallow((state) => ({
      toggleMute: state.toggleMute,
      toggleCamera: state.toggleCamera,
      endCall: state.endCall,
      setAiSpeaking: state.setAiSpeaking,
      setConnected: state.setConnected,
      setMinimized: state.setMinimized,
      setShowDeviceSettings: state.setShowDeviceSettings,
      setDevices: state.setDevices,
      setAsrInterimText: state.setAsrInterimText,
      setAsrFinalText: state.setAsrFinalText,
      appendAgentToken: state.appendAgentToken,
      setAgentComplete: state.setAgentComplete,
      setAgentStreaming: state.setAgentStreaming,
    }))
  );

  // Voice chat hook (WebSocket-based pipeline)
  const { enqueueChunk, stop: stopAudio } = useAudioQueue();
  const current = () => {
    const state = useVoiceCallStore.getState();
    return (
      state.callId === callId &&
      state.owner === owner &&
      getWebOperationAvailabilityV2().owner === owner &&
      getWebOperationAvailabilityV2().available
    );
  };
  const {
    isConnected,
    isRecording,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    operation,
    analyser,
    session,
  } = useVoiceChat({
    projectId: projectId || '',
    conversationId: conversationId || '',
    onAsrInterim: (text) => {
      if (current()) setAsrInterimText(text);
    },
    onAsrFinal: (text) => {
      if (current()) setAsrFinalText(text);
    },
    onAgentToken: (text) => {
      if (current()) {
        appendAgentToken(text);
        setAgentStreaming(true);
      }
    },
    onAgentComplete: (text) => {
      if (current()) setAgentComplete(text);
    },
    onTtsStart: () => {
      if (current()) setAiSpeaking(true);
    },
    onTtsEnd: () => {
      if (current()) setAiSpeaking(false);
    },
    onTtsAudio: (data, voiceOperation) => {
      if (!current()) return;
      void enqueueChunk(data, voiceOperation).catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError'))
          console.warn('Voice playback failed');
      });
    },
    onError: (error) => {
      if (current()) useVoiceCallStore.setState({ status: 'error', error });
    },
  });
  const close = useCallback(async () => {
    const results = await Promise.allSettled([disconnect(), stopAudio()]);
    const failed = results.find((result) => result.status === 'rejected');
    if (failed?.status === 'rejected') throw failed.reason;
  }, [disconnect, stopAudio]);
  useLayoutEffect(() => {
    const unbind = useVoiceCallStore.getState().bindCallCleanup(callId, close);
    return () => {
      unbind();
      void close().catch(() => {
        console.warn('Voice cleanup failed');
      });
    };
  }, [callId, close]);
  useEffect(() => {
    if (!availability.available || availability.owner !== owner) {
      void endCall(callId).catch(() => {
        console.warn('Voice cleanup failed');
      });
    }
  }, [availability, owner, callId, endCall]);
  useVoiceSessionMediaV2(session, isCameraOn && callMode === 'video', localVideoRef, setDevices);

  // Connect when status becomes 'connecting'
  useEffect(() => {
    if (
      status === 'connecting' &&
      conversationId &&
      projectId &&
      availability.available &&
      availability.owner === owner
    ) {
      void connect().catch(() => {
        console.warn('Voice connection failed');
      });
    }
  }, [status, conversationId, projectId, connect, availability, owner]);

  // When connected, update store and start recording
  useEffect(() => {
    if (isConnected && operation && !operation.signal.aborted) {
      operation.check();
      setConnected();
    }
  }, [isConnected, operation, setConnected]);

  // Mute sync: stop/start recording when mute state changes
  useEffect(() => {
    if (!isConnected || !operation || operation.signal.aborted) return;
    if (isMuted) {
      void stopRecording().catch(() => {
        console.warn('Voice capture cleanup failed');
      });
    } else if (!isRecording) {
      void startRecording().catch(() => {
        console.warn('Voice capture failed');
      });
    }
  }, [isMuted, isConnected, isRecording, stopRecording, startRecording, operation]);

  const handleEndCall = useCallback(() => {
    void endCall(callId).catch(() => {
      console.warn('Voice cleanup failed');
    });
    onClose();
  }, [endCall, callId, onClose]);

  return (
    <VoiceCallPanelView
      createPortal={createPortal}
      {...{
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
      }}
      waveform={
        <VoiceWaveform
          active={!isMuted && status === 'connected'}
          analyser={analyser}
          operation={operation}
        />
      }
      video={
        callMode === 'video' && (
          <div className="relative w-full h-[240px] bg-black">
            {/* Local camera preview */}
            <div
              className={`absolute bottom-2 right-2 w-[100px] h-[75px] bg-slate-800 rounded-lg overflow-hidden border border-slate-600 z-10 ${isCameraOn ? '' : 'hidden'}`}
            >
              <video
                ref={localVideoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover"
              />
            </div>
          </div>
        )
      }
      deviceControls={
        <>
          {' '}
          {/* Camera toggle */}
          <button
            type="button"
            onClick={storeToggleCamera}
            title={
              isCameraOn
                ? t('agent.voiceCall.turnOffCamera', { defaultValue: 'Turn off camera' })
                : t('agent.voiceCall.turnOnCamera', { defaultValue: 'Turn on camera' })
            }
            aria-label={
              isCameraOn
                ? t('agent.voiceCall.turnOffCamera', { defaultValue: 'Turn off camera' })
                : t('agent.voiceCall.turnOnCamera', { defaultValue: 'Turn on camera' })
            }
            className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform]
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
            title={
              callMode === 'audio'
                ? t('agent.voiceCall.switchToVideo', { defaultValue: 'Switch to video' })
                : t('agent.voiceCall.switchToAudio', { defaultValue: 'Switch to audio' })
            }
            aria-label={
              callMode === 'audio'
                ? t('agent.voiceCall.switchToVideo', { defaultValue: 'Switch to video' })
                : t('agent.voiceCall.switchToAudio', { defaultValue: 'Switch to audio' })
            }
            className="w-11 h-11 rounded-full bg-slate-700 text-white hover:bg-slate-600 flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform]"
          >
            <Video size={20} />
          </button>
          {/* Device settings */}
          <button
            type="button"
            onClick={() => {
              setShowDeviceSettings(!showDeviceSettings);
            }}
            title={t('agent.voiceCall.deviceSettings', { defaultValue: 'Device settings' })}
            aria-label={t('agent.voiceCall.deviceSettings', { defaultValue: 'Device settings' })}
            aria-expanded={showDeviceSettings}
            className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform]
              ${showDeviceSettings ? 'bg-slate-600 text-white' : 'bg-slate-700 text-white hover:bg-slate-600'}
            `}
          >
            <Settings size={20} />
          </button>
        </>
      }
      deviceSettings={
        <div className="relative">
          <DeviceSettingsPanel
            onClose={() => {
              setShowDeviceSettings(false);
            }}
          />
        </div>
      }
    />
  );
};
