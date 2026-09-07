import { useEffect } from 'react';
import type { RefObject } from 'react';

import type { WebVoiceSessionV2 } from '../../../services/voiceRetainedSessionV2';
import type { DeviceInfo } from '../../../stores/voiceCallStore';

type VoiceSession = WebVoiceSessionV2;
type Devices = { audioInputs: DeviceInfo[]; audioOutputs: DeviceInfo[]; videoInputs: DeviceInfo[] };

/** Camera and device discovery belong to the already-admitted voice session. */
export function useVoiceSessionMediaV2(
  session: VoiceSession | null,
  cameraEnabled: boolean,
  video: RefObject<HTMLVideoElement | null>,
  setDevices: (devices: Devices) => void
): void {
  useEffect(() => {
    const operation = session?.operation;
    if (!session || !operation) return;
    let active = true;
    void operation
      .runChild(async (child) => {
        child.check();
        const devices = await navigator.mediaDevices.enumerateDevices();
        child.check();
        if (!active) return;
        const select = (kind: MediaDeviceKind, label: string): DeviceInfo[] =>
          devices
            .filter((device) => device.kind === kind)
            .map((device) => ({
              deviceId: device.deviceId,
              label: device.label || `${label} ${device.deviceId.slice(0, 4)}`,
              kind,
            }));
        setDevices({
          audioInputs: select('audioinput', 'Mic'),
          audioOutputs: select('audiooutput', 'Speaker'),
          videoInputs: select('videoinput', 'Camera'),
        });
      })
      .catch(() => {
        if (!active || operation.signal.aborted) return;
        try {
          operation.check();
        } catch {
          return;
        }
        setDevices({ audioInputs: [], audioOutputs: [], videoInputs: [] });
      });
    return () => {
      active = false;
    };
  }, [session, setDevices]);

  useEffect(() => {
    const operation = session?.operation;
    if (!session || !operation || !cameraEnabled) return;
    let active = true;
    let capture: Awaited<ReturnType<VoiceSession['capture']>> | undefined;
    let element: HTMLVideoElement | null = null;
    const clear = () => {
      active = false;
      if (element?.srcObject === capture?.stream && element) element.srcObject = null;
      if (capture) {
        const current = capture;
        capture = undefined;
        void current.release().catch(() => {
          console.warn('Voice camera cleanup failed');
        });
      }
    };
    operation.signal.addEventListener('abort', clear, { once: true });
    void session
      .capture({ video: true })
      .then(async (resource) => {
        if (!active || operation.signal.aborted) {
          await resource.release();
          return;
        }
        capture = resource;
        operation.check();
        element = video.current;
        if (element) element.srcObject = resource.stream;
      })
      .catch(() => {
        clear();
      });
    return () => {
      clear();
      operation.signal.removeEventListener('abort', clear);
    };
  }, [session, cameraEnabled, video]);
}
