import { useEffect, useRef, useCallback } from 'react';
import VERTC, {
  MediaType,
  RoomProfileType,
  StreamIndex,
  type IRTCEngine,
  type NetworkQuality,
} from '@volcengine/rtc';

export interface RTCDeviceInfo {
  deviceId: string;
  label: string;
  kind: 'audioinput' | 'audiooutput' | 'videoinput';
}

export interface UseVolcRTCOptions {
  appId: string | null;
  roomId: string | null;
  userId: string | null;
  token: string | null;
  autoPublishAudio?: boolean;
  selectedMicId?: string | null;
  selectedCameraId?: string | null;
  onAiSpeakingChange?: (speaking: boolean) => void;
  onRemoteUserJoined?: (uid: string) => void;
  onRemoteUserLeft?: (uid: string) => void;
  onAutoplayFailed?: () => void;
  onNetworkQuality?: (quality: { uplinkQuality: number; downlinkQuality: number }) => void;
  onError?: (error: string) => void;
}

export interface UseVolcRTCReturn {
  isJoined: boolean;
  joinRoom: () => Promise<void>;
  leaveRoom: () => void;
  toggleMute: (muted: boolean) => void;
  startCamera: (containerId?: string) => Promise<void>;
  stopCamera: () => void;
  setRemoteVideoPlayer: (uid: string, containerId: string) => void;
  removeRemoteVideoPlayer: (uid: string) => void;
  enumerateDevices: () => Promise<{
    audioInputs: RTCDeviceInfo[];
    audioOutputs: RTCDeviceInfo[];
    videoInputs: RTCDeviceInfo[];
  }>;
  switchMicrophone: (deviceId: string) => Promise<void>;
  switchCamera: (deviceId: string) => Promise<void>;
  engineRef: React.MutableRefObject<IRTCEngine | null>;
}

export const useVolcRTC = ({
  appId,
  roomId,
  userId,
  token,
  autoPublishAudio = true,
  selectedMicId,
  selectedCameraId,
  onAiSpeakingChange,
  onRemoteUserJoined,
  onRemoteUserLeft,
  onAutoplayFailed,
  onNetworkQuality,
  onError,
}: UseVolcRTCOptions): UseVolcRTCReturn => {
  const engineRef = useRef<IRTCEngine | null>(null);
  const isJoinedRef = useRef(false);

  // Store callbacks in refs to avoid engine recreation when callbacks change
  const onAiSpeakingChangeRef = useRef(onAiSpeakingChange);
  const onRemoteUserJoinedRef = useRef(onRemoteUserJoined);
  const onRemoteUserLeftRef = useRef(onRemoteUserLeft);
  const onAutoplayFailedRef = useRef(onAutoplayFailed);
  const onNetworkQualityRef = useRef(onNetworkQuality);
  const onErrorRef = useRef(onError);

  useEffect(() => { onAiSpeakingChangeRef.current = onAiSpeakingChange; }, [onAiSpeakingChange]);
  useEffect(() => { onRemoteUserJoinedRef.current = onRemoteUserJoined; }, [onRemoteUserJoined]);
  useEffect(() => { onRemoteUserLeftRef.current = onRemoteUserLeft; }, [onRemoteUserLeft]);
  useEffect(() => { onAutoplayFailedRef.current = onAutoplayFailed; }, [onAutoplayFailed]);
  useEffect(() => { onNetworkQualityRef.current = onNetworkQuality; }, [onNetworkQuality]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  const initEngine = useCallback(() => {
    if (!appId) return null;
    if (engineRef.current) return engineRef.current;

    const engine = VERTC.createEngine(appId);
    engineRef.current = engine;

    engine.on(VERTC.events.onError, (evt) => {
      console.error('[RTC] Engine error:', evt.errorCode);
      onErrorRef.current?.(`RTC Error [${evt.errorCode}]`);
    });

    engine.on(
      VERTC.events.onUserJoined,
      (evt: { userInfo: { userId: string } }) => {
        console.log('[RTC] User joined:', evt.userInfo.userId);
        onRemoteUserJoinedRef.current?.(evt.userInfo.userId);
      },
    );

    engine.on(
      VERTC.events.onUserLeave,
      (evt: { userInfo: { userId: string } }) => {
        console.log('[RTC] User left:', evt.userInfo.userId);
        onAiSpeakingChangeRef.current?.(false);
        onRemoteUserLeftRef.current?.(evt.userInfo.userId);
      },
    );

    engine.on(
      VERTC.events.onUserPublishStream,
      ({ userId: remoteUid, mediaType }: { userId: string; mediaType: MediaType }) => {
        console.log('[RTC] Remote publish:', remoteUid, 'mediaType:', mediaType);
        if (mediaType & MediaType.AUDIO) {
          onAiSpeakingChangeRef.current?.(true);
        }
      },
    );

    engine.on(
      VERTC.events.onUserUnpublishStream,
      ({ mediaType }: { mediaType: MediaType }) => {
        if (mediaType & MediaType.AUDIO) {
          onAiSpeakingChangeRef.current?.(false);
        }
      },
    );

    engine.on(VERTC.events.onTrackEnded, ({ kind }: { kind: string }) => {
      console.warn('[RTC] Track ended:', kind);
    });

    engine.on(
      VERTC.events.onRemoteAudioPropertiesReport,
      (infos: Array<{ streamKey: { userId: string }; audioPropertiesInfo: { linearVolume: number } }>) => {
        const hasAiAudio = infos.some(
          (info) => (info.audioPropertiesInfo?.linearVolume ?? 0) > 0.01,
        );
        onAiSpeakingChangeRef.current?.(hasAiAudio);
      },
    );

    engine.on(VERTC.events.onAutoplayFailed, () => {
      console.warn('[RTC] Autoplay failed - user interaction needed');
      onAutoplayFailedRef.current?.();
    });

    engine.on(
      VERTC.events.onNetworkQuality,
      (uplink: NetworkQuality, downlink: NetworkQuality) => {
        onNetworkQualityRef.current?.({
          uplinkQuality: uplink,
          downlinkQuality: downlink,
        });
      },
    );

    engine.on(VERTC.events.onPlayerEvent, (evt: unknown) => {
      console.debug('[RTC] Player event:', evt);
    });

    return engine;
  }, [appId]);

  // ---- Room Operations ------------------------------------------------------
  const joinRoom = useCallback(async () => {
    if (!appId || !roomId || !userId || !token) {
      onErrorRef.current?.('Missing required connection parameters');
      return;
    }

    const engine = initEngine();
    if (!engine) return;

    try {
      // Step 1: Request device permissions (reference: useCommon.ts)
      await VERTC.enableDevices({ video: false, audio: true });

      // Step 2: Join room with extraInfo (reference: RtcClient.ts)
      await engine.joinRoom(
        token,
        roomId,
        {
          userId,
          extraInfo: JSON.stringify({
            call_scene: 'RTC-AIGC',
            user_name: userId,
            user_id: userId,
          }),
        },
        {
          isAutoPublish: false, // We publish manually after startAudioCapture
          isAutoSubscribeAudio: true,
          isAutoSubscribeVideo: true,
          roomProfileType: RoomProfileType.chat,
        },
      );

      isJoinedRef.current = true;

      // Step 3: Start audio capture with selected device (reference: RtcClient.ts)
      if (autoPublishAudio) {
        await engine.startAudioCapture(selectedMicId ?? undefined);
        await engine.publishStream(MediaType.AUDIO);
      }
    } catch (err: unknown) {
      const errorMessage =
        err instanceof Error ? err.message : 'Failed to join room';
      onErrorRef.current?.(errorMessage);
    }
  }, [
    appId,
    roomId,
    userId,
    token,
    autoPublishAudio,
    selectedMicId,
    initEngine,
  ]);

  const leaveRoom = useCallback(() => {
    if (engineRef.current) {
      try {
        engineRef.current.stopAudioCapture();
      } catch {
        // ignore if not capturing
      }
      try {
        engineRef.current.stopVideoCapture();
      } catch {
        // ignore if not capturing
      }
      engineRef.current.leaveRoom();
      VERTC.destroyEngine(engineRef.current);
      engineRef.current = null;
    }
    isJoinedRef.current = false;
    onAiSpeakingChangeRef.current?.(false);
  }, []);

  // ---- Mute (reference: uses startAudioCapture/stopAudioCapture) ----------

  const toggleMute = useCallback(
    (muted: boolean) => {
      if (!engineRef.current || !isJoinedRef.current) return;
      if (muted) {
        engineRef.current.stopAudioCapture();
      } else {
        engineRef.current.startAudioCapture(selectedMicId ?? undefined);
      }
    },
    [selectedMicId],
  );

  // ---- Camera ---------------------------------------------------------------

  const startCamera = useCallback(
    async (containerId?: string) => {
      if (!engineRef.current || !isJoinedRef.current) return;
      try {
        await engineRef.current.startVideoCapture(
          selectedCameraId ?? undefined,
        );
        await engineRef.current.publishStream(MediaType.VIDEO);

        // Attach local video to DOM element
        if (containerId) {
          const container = document.getElementById(containerId);
          if (container) {
            engineRef.current.setLocalVideoPlayer(StreamIndex.STREAM_INDEX_MAIN, {
              renderDom: container,
              userId: userId ?? '',
              renderMode: 1, // FIT
            });
          }
        }
      } catch (err: unknown) {
        const errorMessage =
          err instanceof Error ? err.message : 'Failed to start camera';
        onErrorRef.current?.(errorMessage);
      }
    },
    [selectedCameraId, userId],
  );

  const stopCamera = useCallback(() => {
    if (!engineRef.current || !isJoinedRef.current) return;
    engineRef.current.stopVideoCapture();
    try {
      engineRef.current.unpublishStream(MediaType.VIDEO);
    } catch {
      // ignore
    }
  }, []);

  // ---- Remote video rendering -----------------------------------------------

  const setRemoteVideoPlayer = useCallback(
    (uid: string, containerId: string) => {
      if (!engineRef.current) return;
      const container = document.getElementById(containerId);
      if (!container) return;
      engineRef.current.setRemoteVideoPlayer(StreamIndex.STREAM_INDEX_MAIN, {
        renderDom: container,
        userId: uid,
        renderMode: 1,
      });
    },
    [],
  );

  const removeRemoteVideoPlayer = useCallback((uid: string) => {
    if (!engineRef.current) return;
    engineRef.current.setRemoteVideoPlayer(StreamIndex.STREAM_INDEX_MAIN, {
      userId: uid,
    });
  }, []);
  // ---- Device Enumeration & Switching ---------------------------------------

  const enumerateDevices = useCallback(async (): Promise<{
    audioInputs: RTCDeviceInfo[];
    audioOutputs: RTCDeviceInfo[];
    videoInputs: RTCDeviceInfo[];
  }> => {
    try {
      // Request permissions first to get labeled devices
      await VERTC.enableDevices({ video: true, audio: true });
    } catch {
      // may fail if camera not available, still try to enumerate
    }

    try {
      const [mics, speakers, cameras] = await Promise.all([
        VERTC.enumerateAudioCaptureDevices(),
        VERTC.enumerateAudioPlaybackDevices(),
        VERTC.enumerateVideoCaptureDevices(),
      ]);

      const mapDevices = (
        devices: Array<{ deviceId: string; label: string }>,
        kind: 'audioinput' | 'audiooutput' | 'videoinput',
      ): RTCDeviceInfo[] =>
        devices.map((d) => ({
          deviceId: d.deviceId,
          label: d.label || `${kind} (${d.deviceId.slice(0, 8)})`,
          kind,
        }));

      return {
        audioInputs: mapDevices(mics, 'audioinput'),
        audioOutputs: mapDevices(speakers, 'audiooutput'),
        videoInputs: mapDevices(cameras, 'videoinput'),
      };
    } catch (err) {
      console.error('[RTC] Failed to enumerate devices:', err);
      return { audioInputs: [], audioOutputs: [], videoInputs: [] };
    }
  }, []);

  const switchMicrophone = useCallback(async (deviceId: string) => {
    if (!engineRef.current) return;
    try {
      await engineRef.current.setAudioCaptureDevice(deviceId);
    } catch (err) {
      console.error('[RTC] Failed to switch microphone:', err);
    }
  }, []);

  const switchCamera = useCallback(async (deviceId: string) => {
    if (!engineRef.current) return;
    try {
      await engineRef.current.setVideoCaptureDevice(deviceId);
    } catch (err) {
      console.error('[RTC] Failed to switch camera:', err);
    }
  }, []);

  // ---- Cleanup on unmount ---------------------------------------------------

  useEffect(() => {
    return () => {
      leaveRoom();
    };
  }, [leaveRoom]);

  // ---- Return ---------------------------------------------------------------

  return {
    get isJoined() {
      return isJoinedRef.current;
    },
    joinRoom,
    leaveRoom,
    toggleMute,
    startCamera,
    stopCamera,
    setRemoteVideoPlayer,
    removeRemoteVideoPlayer,
    enumerateDevices,
    switchMicrophone,
    switchCamera,
    engineRef,
  };
};
