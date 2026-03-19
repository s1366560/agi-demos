import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

export type CallStatus =
	| "idle"
	| "connecting"
	| "connected"
	| "reconnecting"
	| "error";
export type CallMode = "audio" | "video";

export interface DeviceInfo {
	deviceId: string;
	label: string;
	kind: "audioinput" | "audiooutput" | "videoinput";
}

export interface VoiceCallState {
	// Connection state
	status: CallStatus;
	conversationId: string | null;
	projectId: string | null;
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
	audioInputs: DeviceInfo[];
	audioOutputs: DeviceInfo[];
	videoInputs: DeviceInfo[];
	selectedMicId: string | null;
	selectedSpeakerId: string | null;
	selectedCameraId: string | null;

	// ASR / Agent transcript state
	asrInterimText: string;
	asrFinalText: string;
	agentResponseText: string;
	isAgentStreaming: boolean;

	// Actions
	startCall: (
		conversationId: string,
		projectId: string,
		mode?: CallMode,
	) => Promise<void>;
	endCall: () => Promise<void>;
	setConnected: () => void;
	toggleMute: () => void;
	toggleCamera: () => void;
	setAiSpeaking: (speaking: boolean) => void;
	setCallMode: (mode: CallMode) => void;
	setMinimized: (minimized: boolean) => void;
	setShowDeviceSettings: (show: boolean) => void;
	setDevices: (devices: {
		audioInputs: DeviceInfo[];
		audioOutputs: DeviceInfo[];
		videoInputs: DeviceInfo[];
	}) => void;
	selectMicrophone: (deviceId: string) => void;
	selectSpeaker: (deviceId: string) => void;
	selectCamera: (deviceId: string) => void;
	setAsrInterimText: (text: string) => void;
	setAsrFinalText: (text: string) => void;
	appendAgentToken: (token: string) => void;
	setAgentComplete: (content: string) => void;
	setAgentStreaming: (streaming: boolean) => void;
	clearTranscript: () => void;
	reset: () => void;
}

const initialState = {
	status: "idle" as CallStatus,
	conversationId: null as string | null,
	projectId: null as string | null,
	isMuted: false,
	isCameraOn: false,
	callStartTime: null as number | null,
	error: null as string | null,
	aiSpeaking: false,
	callMode: "audio" as CallMode,
	isMinimized: false,
	showDeviceSettings: false,
	audioInputs: [] as DeviceInfo[],
	audioOutputs: [] as DeviceInfo[],
	videoInputs: [] as DeviceInfo[],
	selectedMicId: null as string | null,
	selectedSpeakerId: null as string | null,
	selectedCameraId: null as string | null,
	asrInterimText: "",
	asrFinalText: "",
	agentResponseText: "",
	isAgentStreaming: false,
};

export const useVoiceCallStore = create<VoiceCallState>()(
	devtools(
		(set) => ({
			...initialState,

			startCall: async (
				conversationId: string,
				projectId: string,
				mode: CallMode,
			) => {
				set({
					status: "connecting",
					error: null,
					callMode: mode,
					isMinimized: false,
					conversationId,
					projectId,
					asrInterimText: "",
					asrFinalText: "",
					agentResponseText: "",
				});
				// Actual WS connection is handled by useVoiceChat hook in the component.
				// The hook reads conversationId/projectId from the store.
				// We just set status to 'connecting' and let the hook take over.
			},

			endCall: async () => {
				// Just reset state. The useVoiceChat hook watches status and disconnects.
				set({ ...initialState });
			},

			setConnected: () =>
				{ set({
					status: "connected",
					callStartTime: Date.now(),
				}); },

			toggleMute: () => { set((state) => ({ isMuted: !state.isMuted })); },
			toggleCamera: () => { set((state) => ({ isCameraOn: !state.isCameraOn })); },
			setAiSpeaking: (speaking: boolean) => { set({ aiSpeaking: speaking }); },
			setCallMode: (mode: CallMode) => { set({ callMode: mode }); },
			setMinimized: (minimized: boolean) => { set({ isMinimized: minimized }); },
			setShowDeviceSettings: (show: boolean) =>
				{ set({ showDeviceSettings: show }); },

			setDevices: (devices) =>
				{ set({
					audioInputs: devices.audioInputs,
					audioOutputs: devices.audioOutputs,
					videoInputs: devices.videoInputs,
				}); },

			selectMicrophone: (deviceId: string) => { set({ selectedMicId: deviceId }); },
			selectSpeaker: (deviceId: string) => { set({ selectedSpeakerId: deviceId }); },
			selectCamera: (deviceId: string) => { set({ selectedCameraId: deviceId }); },

			setAsrInterimText: (text: string) => { set({ asrInterimText: text }); },
			setAsrFinalText: (text: string) => { set({ asrFinalText: text }); },
			appendAgentToken: (token: string) =>
				{ set((state) => ({
					agentResponseText: state.agentResponseText + token,
				})); },
			setAgentComplete: (content: string) =>
				{ set({ agentResponseText: content, isAgentStreaming: false }); },
			setAgentStreaming: (streaming: boolean) =>
				{ set({ isAgentStreaming: streaming }); },
			clearTranscript: () =>
				{ set({
					asrInterimText: "",
					asrFinalText: "",
					agentResponseText: "",
					isAgentStreaming: false,
				}); },

			reset: () => { set({ ...initialState }); },
		}),
		{ name: "voice-call-store" },
	),
);

// Single-value selectors
export const useVoiceCallStatus = () =>
	useVoiceCallStore((state) => state.status);
export const useVoiceCallError = () =>
	useVoiceCallStore((state) => state.error);
export const useVoiceCallIsMuted = () =>
	useVoiceCallStore((state) => state.isMuted);
export const useVoiceCallIsCameraOn = () =>
	useVoiceCallStore((state) => state.isCameraOn);
export const useVoiceCallAiSpeaking = () =>
	useVoiceCallStore((state) => state.aiSpeaking);
export const useVoiceCallStartTime = () =>
	useVoiceCallStore((state) => state.callStartTime);
export const useVoiceCallIsMinimized = () =>
	useVoiceCallStore((state) => state.isMinimized);
export const useVoiceCallMode = () =>
	useVoiceCallStore((state) => state.callMode);

// Action selectors
export const useVoiceCallActions = () =>
	useVoiceCallStore(
		useShallow((state) => ({
			startCall: state.startCall,
			endCall: state.endCall,
			setConnected: state.setConnected,
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
			setAsrInterimText: state.setAsrInterimText,
			setAsrFinalText: state.setAsrFinalText,
			appendAgentToken: state.appendAgentToken,
			setAgentComplete: state.setAgentComplete,
			setAgentStreaming: state.setAgentStreaming,
			clearTranscript: state.clearTranscript,
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

// Transcript selectors
export const useVoiceCallTranscript = () =>
	useVoiceCallStore(
		useShallow((state) => ({
			asrInterimText: state.asrInterimText,
			asrFinalText: state.asrFinalText,
			agentResponseText: state.agentResponseText,
			isAgentStreaming: state.isAgentStreaming,
		})),
	);

// Connection selectors
export const useVoiceCallConnection = () =>
	useVoiceCallStore(
		useShallow((state) => ({
			conversationId: state.conversationId,
			projectId: state.projectId,
		})),
	);
