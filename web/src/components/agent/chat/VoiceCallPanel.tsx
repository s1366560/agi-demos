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

import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import {
	Camera,
	CameraOff,
	GripHorizontal,
	Maximize2,
	Mic,
	MicOff,
	Minimize2,
	PhoneOff,
	Settings,
	Video,
	X,
} from "lucide-react";
import { useShallow } from "zustand/react/shallow";

import { type DeviceInfo, useVoiceCallStore } from "@/stores/voiceCallStore";

import { useAudioQueue } from "@/hooks/useAudioQueue";
import { useVoiceChat } from "@/hooks/useVoiceChat";

import { VoiceWaveform } from "./VoiceWaveform";

// ---- Drag Hook --------------------------------------------------------------

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
			el.style.transform = `translate(${posRef.current.x}px, ${posRef.current.y}px)`;
		});

		const onMouseDown = (e: MouseEvent) => {
			const target = e.target as HTMLElement;
			if (!target.closest("[data-drag-handle]")) return;
			draggingRef.current = true;
			startRef.current = {
				x: e.clientX - posRef.current.x,
				y: e.clientY - posRef.current.y,
			};
			e.preventDefault();
		};

		const onMouseMove = (e: MouseEvent) => {
			if (!draggingRef.current) return;
			const newX = Math.max(
				0,
				Math.min(window.innerWidth - 100, e.clientX - startRef.current.x),
			);
			const newY = Math.max(
				0,
				Math.min(window.innerHeight - 60, e.clientY - startRef.current.y),
			);
			posRef.current = { x: newX, y: newY };
			el.style.transform = `translate(${newX}px, ${newY}px)`;
		};

		const onMouseUp = () => {
			draggingRef.current = false;
		};

		el.addEventListener("mousedown", onMouseDown);
		document.addEventListener("mousemove", onMouseMove);
		document.addEventListener("mouseup", onMouseUp);

		return () => {
			cancelAnimationFrame(raf);
			el.removeEventListener("mousedown", onMouseDown);
			document.removeEventListener("mousemove", onMouseMove);
			document.removeEventListener("mouseup", onMouseUp);
		};
	}, [ref]);
}

// ---- Device Settings Panel --------------------------------------------------

const DeviceSettingsPanel: React.FC<{ onClose: () => void }> = ({
	onClose,
}) => {
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
					value={selectedId ?? ""}
					onChange={(e) => { onChange(e.target.value); }}
					className="mt-1 w-full px-2 py-1.5 bg-slate-700 border border-slate-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
				>
					{devices.length === 0 && (
						<option value="">
							{t("agent.voiceCall.noDevices", "No devices found")}
						</option>
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
					{t("agent.voiceCall.deviceSettings", "Device Settings")}
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
				t("agent.voiceCall.microphone", "Microphone"),
				audioInputs,
				selectedMicId,
				selectMicrophone,
			)}

			{renderSelect(
				t("agent.voiceCall.speaker", "Speaker"),
				audioOutputs,
				selectedSpeakerId,
				selectSpeaker,
			)}

			{renderSelect(
				t("agent.voiceCall.camera", "Camera"),
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
	const localVideoRef = useRef<HTMLVideoElement>(null);
	const localStreamRef = useRef<MediaStream | null>(null);

	useDrag(panelRef);

	const {
		status,
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
		})),
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
		})),
	);

	// Voice chat hook (WebSocket-based pipeline)
	const { enqueueChunk, stop: stopAudio, clear: clearAudio } = useAudioQueue();

	// Keep a ref to disconnect for the unmount cleanup.
	// This ensures the WebSocket is torn down if the panel is unmounted
	// without an explicit handleEndCall (e.g., parent navigates away).
	const disconnectRef = useRef<() => void>(() => {});

	const {
		isConnected,
		isRecording,
		connect,
		disconnect,
		startRecording,
		stopRecording,
	} = useVoiceChat({
		projectId: projectId || "",
		conversationId: conversationId || "",
		onAsrInterim: (text) => { setAsrInterimText(text); },
		onAsrFinal: (text) => { setAsrFinalText(text); },
		onAgentToken: (token) => {
			appendAgentToken(token);
			setAgentStreaming(true);
		},
		onAgentComplete: (content) => { setAgentComplete(content); },
		onTtsStart: () => { setAiSpeaking(true); },
		onTtsEnd: () => { setAiSpeaking(false); },
		onTtsAudio: (data) => enqueueChunk(data),
		onError: (err) =>
			{ useVoiceCallStore.setState({ status: "error", error: err }); },
	});

	// Keep disconnectRef in sync so the cleanup effect always calls the latest version.
	useEffect(() => {
		disconnectRef.current = disconnect;
	});

	// Cleanup: when VoiceCallPanel is truly unmounted (not StrictMode), tear down WS.
	useEffect(() => {
		return () => {
			disconnectRef.current();
		};
	}, []);

	// Connect when status becomes 'connecting'
	useEffect(() => {
		if (status === "connecting" && conversationId && projectId) {
			connect();
		}
	}, [status, conversationId, projectId, connect]);

	// When connected, update store and start recording
	useEffect(() => {
		if (isConnected) {
			setConnected();
			startRecording();
		}
	}, [isConnected, setConnected, startRecording]);

	// Disconnect on endCall (status reset to 'idle')
	useEffect(() => {
		if (status === "idle") {
			disconnect();
			stopAudio();
		}
	}, [status, disconnect, stopAudio]);

	// Enumerate devices on connect
	useEffect(() => {
		if (isConnected) {
			navigator.mediaDevices.enumerateDevices().then((devices) => {
				const audioInputs: DeviceInfo[] = devices
					.filter((d) => d.kind === "audioinput")
					.map((d) => ({
						deviceId: d.deviceId,
						label: d.label || `Mic ${d.deviceId.slice(0, 4)}`,
						kind: "audioinput" as const,
					}));
				const audioOutputs: DeviceInfo[] = devices
					.filter((d) => d.kind === "audiooutput")
					.map((d) => ({
						deviceId: d.deviceId,
						label: d.label || `Speaker ${d.deviceId.slice(0, 4)}`,
						kind: "audiooutput" as const,
					}));
				const videoInputs: DeviceInfo[] = devices
					.filter((d) => d.kind === "videoinput")
					.map((d) => ({
						deviceId: d.deviceId,
						label: d.label || `Camera ${d.deviceId.slice(0, 4)}`,
						kind: "videoinput" as const,
					}));
				setDevices({ audioInputs, audioOutputs, videoInputs });
			});
		}
	}, [isConnected, setDevices]);

	// Mute sync: stop/start recording when mute state changes
	useEffect(() => {
		if (!isConnected) return;
		if (isMuted) {
			stopRecording();
		} else if (!isRecording) {
			startRecording();
		}
	}, [isMuted, isConnected, isRecording, stopRecording, startRecording]);

	// Local camera preview
	useEffect(() => {
		if (isCameraOn && callMode === "video") {
			navigator.mediaDevices
				.getUserMedia({ video: true })
				.then((stream) => {
					localStreamRef.current = stream;
					if (localVideoRef.current) {
						localVideoRef.current.srcObject = stream;
					}
				})
				.catch(() => {
					// Camera access denied or unavailable
				});
		} else {
			if (localStreamRef.current) {
				for (const track of localStreamRef.current.getTracks()) {
					track.stop();
				}
				localStreamRef.current = null;
			}
			if (localVideoRef.current) {
				localVideoRef.current.srcObject = null;
			}
		}

		return () => {
			if (localStreamRef.current) {
				for (const track of localStreamRef.current.getTracks()) {
					track.stop();
				}
				localStreamRef.current = null;
			}
		};
	}, [isCameraOn, callMode]);

	// Duration timer
	useEffect(() => {
		let interval: ReturnType<typeof setInterval>;
		if (status === "connected" && callStartTime) {
			interval = setInterval(() => {
				setDuration(Math.floor((Date.now() - callStartTime) / 1000));
			}, 1000);
		}
		return () => { clearInterval(interval); };
	}, [status, callStartTime]);

	const handleEndCall = useCallback(() => {
		disconnect();
		stopAudio();
		clearAudio();
		endCall();
		onClose();
	}, [disconnect, stopAudio, clearAudio, endCall, onClose]);

	const formatDuration = (seconds: number) => {
		const m = Math.floor(seconds / 60)
			.toString()
			.padStart(2, "0");
		const s = (seconds % 60).toString().padStart(2, "0");
		return `${m}:${s}`;
	};

	// ---- Minimized view -------------------------------------------------------

	if (isMinimized) {
		return createPortal(
			<div
				ref={panelRef}
				className="fixed z-50 top-0 left-0"
				style={{ willChange: "transform" }}
			>
				<div
					className="flex items-center gap-3 px-4 py-2 bg-slate-900/95 border border-slate-700/50 rounded-full shadow-2xl backdrop-blur-sm cursor-move"
					data-drag-handle
				>
					<div
						className={`w-3 h-3 rounded-full ${aiSpeaking ? "bg-blue-500 animate-pulse motion-reduce:animate-none" : "bg-green-500"}`}
					/>
					<span className="text-white text-sm font-mono">
						{formatDuration(duration)}
					</span>
					{isMuted && <MicOff size={14} className="text-red-400" />}
					<button
						type="button"
						onClick={() => { setMinimized(false); }}
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
			</div>,
			document.body,
		);
	}

	// ---- Expanded view --------------------------------------------------------

	return createPortal(
		<div
			ref={panelRef}
			className="fixed z-50 top-0 left-0"
			style={{ willChange: "transform" }}
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
								status === "connected"
									? "bg-green-500"
									: status === "connecting"
										? "bg-yellow-500 animate-pulse motion-reduce:animate-none"
										: "bg-red-500"
							}`}
						/>
						<span className="text-sm text-white font-medium">
							{status === "connecting" &&
								t("agent.voiceCall.connecting", "Connecting...")}
							{status === "connected" && formatDuration(duration)}
							{status === "error" && t("agent.voiceCall.error", "Error")}
						</span>
					</div>
					<div className="flex items-center gap-1">
						<button
							type="button"
							onClick={() => { setMinimized(true); }}
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
				{status === "error" && error && (
					<div className="px-4 py-2 bg-red-500/10 text-red-400 text-xs">
						{error}
					</div>
				)}

				{/* Video Area - local camera preview */}
				{callMode === "video" && (
					<div className="relative w-full h-[240px] bg-black">
						{/* Local camera preview */}
						<div
							className={`absolute bottom-2 right-2 w-[100px] h-[75px] bg-slate-800 rounded-lg overflow-hidden border border-slate-600 z-10 ${isCameraOn ? "" : "hidden"}`}
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
				)}

				{/* Audio-only Visualizer */}
				{callMode === "audio" && (
					<div className="flex items-center justify-center py-8">
						<div className="relative w-32 h-32">
							{/* AI avatar circle */}
							<div
								className={`
                  absolute inset-0 rounded-full border-4 flex items-center justify-center bg-slate-800
                  transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300
                  ${aiSpeaking ? "border-blue-500 shadow-[0_0_30px_rgba(59,130,246,0.4)] scale-105" : "border-slate-700"}
                `}
							>
								<div
									className={`
                    w-16 h-16 rounded-full bg-blue-500/20
                    ${aiSpeaking ? "animate-ping" : "opacity-0"}
                  `}
								/>
							</div>
							{/* Waveform under avatar */}
							<div className="absolute -bottom-6 left-1/2 -translate-x-1/2 w-24 z-10">
								<VoiceWaveform active={!isMuted && status === "connected"} />
							</div>
						</div>
					</div>
				)}

				{/* ASR Transcript */}
				<div className="px-4 py-2 min-h-[60px] max-h-[120px] overflow-y-auto">
					{asrFinalText && (
						<p className="text-sm text-slate-300 mb-1">{asrFinalText}</p>
					)}
					{asrInterimText && (
						<p className="text-sm text-slate-400 italic">{asrInterimText}</p>
					)}
					{agentResponseText && (
						<p className="text-sm text-blue-300 mt-1">
							{agentResponseText}
							{isAgentStreaming && <span className="animate-pulse motion-reduce:animate-none">|</span>}
						</p>
					)}
				</div>

				{/* Controls */}
				<div className="flex items-center justify-center gap-4 px-4 py-4 border-t border-slate-700/30">
					{/* Mute */}
					<button
						type="button"
						onClick={storeToggleMute}
						title={isMuted ? "Unmute" : "Mute"}
						className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform]
              ${isMuted ? "bg-red-500/20 text-red-500 hover:bg-red-500/30" : "bg-slate-700 text-white hover:bg-slate-600"}
            `}
					>
						{isMuted ? <MicOff size={20} /> : <Mic size={20} />}
					</button>

					{/* Camera toggle */}
					<button
						type="button"
						onClick={storeToggleCamera}
						title={isCameraOn ? "Turn off camera" : "Turn on camera"}
						className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform]
              ${isCameraOn ? "bg-blue-500/20 text-blue-500 hover:bg-blue-500/30" : "bg-slate-700 text-white hover:bg-slate-600"}
            `}
					>
						{isCameraOn ? <Camera size={20} /> : <CameraOff size={20} />}
					</button>

					{/* Switch mode (audio <-> video) */}
					<button
						type="button"
						onClick={() => {
							const nextMode = callMode === "audio" ? "video" : "audio";
							useVoiceCallStore.setState({ callMode: nextMode });
							if (nextMode === "video" && !isCameraOn) {
								storeToggleCamera();
							}
							if (nextMode === "audio" && isCameraOn) {
								storeToggleCamera();
							}
						}}
						title={callMode === "audio" ? "Switch to video" : "Switch to audio"}
						className="w-11 h-11 rounded-full bg-slate-700 text-white hover:bg-slate-600 flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform]"
					>
						<Video size={20} />
					</button>

					{/* Device settings */}
					<button
						type="button"
						onClick={() => { setShowDeviceSettings(!showDeviceSettings); }}
						title="Device settings"
						className={`
              w-11 h-11 rounded-full flex items-center justify-center transition-[color,background-color,border-color,box-shadow,opacity,transform]
              ${showDeviceSettings ? "bg-slate-600 text-white" : "bg-slate-700 text-white hover:bg-slate-600"}
            `}
					>
						<Settings size={20} />
					</button>

					{/* End call */}
					<button
						type="button"
						onClick={handleEndCall}
						title="End call"
						className="w-14 h-11 rounded-full bg-red-500 hover:bg-red-600 flex items-center justify-center text-white shadow-lg shadow-red-500/20 transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:scale-105"
					>
						<PhoneOff size={22} />
					</button>
				</div>

				{/* Device Settings Panel (positioned below controls) */}
				<div className="relative">
					<DeviceSettingsPanel onClose={() => { setShowDeviceSettings(false); }} />
				</div>
			</div>
		</div>,
		document.body,
	);
};
