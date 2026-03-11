import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { volcengineRTCService } from '@/services/volcengineRTCService';

import type { RTCDeviceInfo } from '@/hooks/rtc/useVolcRTC';

export type CallStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error';
export type CallMode = 'audio' | 'video';

export interface VoiceCallState {
  // Connection state
  status: CallStatus;
  roomId: string | null;
  userId: string | null;
  appId: string | null;
  token: string | null;
  isMuted: boolean;
  isCameraOn: boolean;
  callStartTime: number | null;
  error: string | null;
  aiSpeaking: boolean;

  // Call mode
  callMode: CallMode;

  // UI state
  isMinimized: boolean;
  showDeviceSettings: boolean;

  // Device state
  audioInputs: RTCDeviceInfo[];
  audioOutputs: RTCDeviceInfo[];
  videoInputs: RTCDeviceInfo[];
  selectedMicId: string | null;
  selectedSpeakerId: string | null;
  selectedCameraId: string | null;

  // Actions
  startCall: (conversationId: string, userId: string, mode?: CallMode) => Promise<void>;
  endCall: () => Promise<void>;
  toggleMute: () => void;
  toggleCamera: () => void;
  setAiSpeaking: (speaking: boolean) => void;
  setCallMode: (mode: CallMode) => void;
  setMinimized: (minimized: boolean) => void;
  setShowDeviceSettings: (show: boolean) => void;
  setDevices: (devices: {
    audioInputs: RTCDeviceInfo[];
    audioOutputs: RTCDeviceInfo[];
    videoInputs: RTCDeviceInfo[];
  }) => void;
  selectMicrophone: (deviceId: string) => void;
  selectSpeaker: (deviceId: string) => void;
  selectCamera: (deviceId: string) => void;
  reset: () => void;
}

const initialState = {
  status: 'idle' as CallStatus,
  roomId: null as string | null,
  userId: null as string | null,
  appId: null as string | null,
  token: null as string | null,
  isMuted: false,
  isCameraOn: false,
  callStartTime: null as number | null,
  error: null as string | null,
  aiSpeaking: false,
  callMode: 'audio' as CallMode,
  isMinimized: false,
  showDeviceSettings: false,
  audioInputs: [] as RTCDeviceInfo[],
  audioOutputs: [] as RTCDeviceInfo[],
  videoInputs: [] as RTCDeviceInfo[],
  selectedMicId: null as string | null,
  selectedSpeakerId: null as string | null,
  selectedCameraId: null as string | null,
};

export const useVoiceCallStore = create<VoiceCallState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      startCall: async (conversationId: string, userId: string, mode: CallMode = 'audio') => {
        set({ status: 'connecting', error: null, callMode: mode, isMinimized: false });
        const roomId = `rtc_${conversationId}`;

        try {
          // 1. Get token
          const tokenRes = await volcengineRTCService.getToken({
            room_id: roomId,
            user_id: userId,
          });

          // 2. Start AI bot
          await volcengineRTCService.startVoiceChat({
            room_id: roomId,
            user_id: userId,
          });

          set({
            status: 'connected',
            roomId,
            userId,
            appId: tokenRes.app_id,
            token: tokenRes.token,
            callStartTime: Date.now(),
          });
        } catch (error: unknown) {
          const errorMessage =
            error instanceof Error ? error.message : 'Failed to start call';
          set({ status: 'error', error: errorMessage });
        }
      },

      endCall: async () => {
        const { roomId, userId } = get();
        if (roomId && userId) {
          try {
            await volcengineRTCService.stopVoiceChat({
              room_id: roomId,
              user_id: userId,
            });
          } catch (error) {
            console.error('Error stopping voice chat:', error);
          }
        }
        set({ ...initialState });
      },

      toggleMute: () => set((state) => ({ isMuted: !state.isMuted })),
      toggleCamera: () => set((state) => ({ isCameraOn: !state.isCameraOn })),
      setAiSpeaking: (speaking: boolean) => set({ aiSpeaking: speaking }),
      setCallMode: (mode: CallMode) => set({ callMode: mode }),
      setMinimized: (minimized: boolean) => set({ isMinimized: minimized }),
      setShowDeviceSettings: (show: boolean) => set({ showDeviceSettings: show }),

      setDevices: (devices) =>
        set({
          audioInputs: devices.audioInputs,
          audioOutputs: devices.audioOutputs,
          videoInputs: devices.videoInputs,
        }),

      selectMicrophone: (deviceId: string) => set({ selectedMicId: deviceId }),
      selectSpeaker: (deviceId: string) => set({ selectedSpeakerId: deviceId }),
      selectCamera: (deviceId: string) => set({ selectedCameraId: deviceId }),

      reset: () => set({ ...initialState }),
    }),
    { name: 'voice-call-store' },
  ),
);

// Single-value selectors
export const useVoiceCallStatus = () => useVoiceCallStore((state) => state.status);
export const useVoiceCallError = () => useVoiceCallStore((state) => state.error);
export const useVoiceCallIsMuted = () => useVoiceCallStore((state) => state.isMuted);
export const useVoiceCallIsCameraOn = () => useVoiceCallStore((state) => state.isCameraOn);
export const useVoiceCallAiSpeaking = () => useVoiceCallStore((state) => state.aiSpeaking);
export const useVoiceCallStartTime = () => useVoiceCallStore((state) => state.callStartTime);
export const useVoiceCallIsMinimized = () => useVoiceCallStore((state) => state.isMinimized);
export const useVoiceCallMode = () => useVoiceCallStore((state) => state.callMode);

// Action selectors
export const useVoiceCallActions = () =>
  useVoiceCallStore(
    useShallow((state) => ({
      startCall: state.startCall,
      endCall: state.endCall,
      toggleMute: state.toggleMute,
      toggleCamera: state.toggleCamera,
      setAiSpeaking: state.setAiSpeaking,
      setCallMode: state.setCallMode,
      setMinimized: state.setMinimized,
      setShowDeviceSettings: state.setShowDeviceSettings,
      setDevices: state.setDevices,
      selectMicrophone: state.selectMicrophone,
      selectSpeaker: state.selectSpeaker,
      selectCamera: state.selectCamera,
      reset: state.reset,
    })),
  );

// Device selectors
export const useVoiceCallDevices = () =>
  useVoiceCallStore(
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
