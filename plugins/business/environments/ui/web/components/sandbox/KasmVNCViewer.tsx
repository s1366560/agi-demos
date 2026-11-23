/**
 * KasmVNCViewer - Direct KasmVNC RFB client for desktop access
 *
 * Uses KasmVNC's own noVNC fork (vendored) which supports KasmVNC's
 * proprietary protocol extensions (WebP encoding, QOI, etc.).
 * Standard noVNC cannot handle these extensions and disconnects.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';

import { useTranslation } from 'react-i18next';

import { Button, Select, Space, Tooltip } from 'antd';
import {
  VolumeX,
  Volume2,
  Monitor,
  Unplug,
  Maximize2,
  Minimize,
  Maximize,
  Loader2,
  RefreshCw,
} from 'lucide-react';

import { KasmRetainedSessionV2, type KasmAttemptContextV2 } from '@/services/kasmRetainedSessionV2';

import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
  WebOperationCleanupErrorV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';

// vendored KasmVNC noVNC fork
import MouseButtonMapper, { XVNC_BUTTONS } from '@/vendor/kasmvnc/core/mousebuttonmapper.js';
// vendored KasmVNC noVNC fork (ES modules, no TS declarations)
import RFB, { RfbInitializationError, type RFBEventDetail } from '@/vendor/kasmvnc/core/rfb.js';

import type { TFunction } from 'i18next';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'error';

const RESOLUTION_PRESETS = [
  { label: 'Auto (fit panel)', value: 'auto' },
  { label: '1280x720 (HD)', value: '1280x720' },
  { label: '1600x900', value: '1600x900' },
  { label: '1920x1080 (FHD)', value: '1920x1080' },
  { label: '2560x1440 (QHD)', value: '2560x1440' },
];

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

export interface KasmVNCViewerProps {
  projectId: string;
  sandboxId: string;
  /** WebSocket URL to the KasmVNC proxy endpoint */
  wsUrl: string;
  /** Current resolution */
  resolution?: string | undefined;
  /** Whether audio is enabled */
  audioEnabled?: boolean | undefined;
  /** Whether dynamic resize is supported */
  dynamicResize?: boolean | undefined;
  /** Called when connection is established */
  onConnect?: (() => void) | undefined;
  /** Called when connection is lost */
  onDisconnect?: ((reason?: string) => void) | undefined;
  /** Called on connection error */
  onError?: ((error: string) => void) | undefined;
  /** Called to change resolution */
  onResolutionChange?: ((resolution: string) => void) | undefined;
  /** Show toolbar */
  showToolbar?: boolean | undefined;
}

export function KasmVNCViewer({
  projectId,
  sandboxId,
  wsUrl,
  resolution = 'auto',
  audioEnabled = false,
  dynamicResize = true,
  onConnect,
  onDisconnect,
  onError,
  onResolutionChange,
  showToolbar = true,
}: KasmVNCViewerProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<{
    rfb: InstanceType<typeof RFB>;
    operation: WebOperationContextV2;
    attempt: KasmAttemptContextV2;
  } | null>(null);
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );
  const [retryNonce, setRetryNonce] = useState(0);
  const identity = useMemo(
    () => ({
      owner: availability.owner,
      projectId,
      sandboxId,
      wsUrl,
      retryNonce,
      available: availability.available,
    }),
    [availability.owner, availability.available, projectId, sandboxId, wsUrl, retryNonce]
  );
  const [connectionSnapshot, setConnectionSnapshot] = useState<{
    identity: object;
    state: ConnectionState;
  } | null>(null);
  const connectionState =
    connectionSnapshot?.identity === identity ? connectionSnapshot.state : 'disconnected';
  const [fullscreenSnapshot, setFullscreenSnapshot] = useState<{
    identity: object;
    value: boolean;
  } | null>(null);
  const isFullscreen = fullscreenSnapshot?.identity === identity && fullscreenSnapshot.value;
  const [isMuted, setIsMuted] = useState(!audioEnabled);
  const [currentResolution, setCurrentResolution] = useState(resolution);
  const muteAudioLabel = tFallback(t, 'components.kasmVNC.muteAudio', 'Mute audio');
  const unmuteAudioLabel = tFallback(t, 'components.kasmVNC.unmuteAudio', 'Unmute audio');
  const reconnectLabel = tFallback(t, 'components.kasmVNC.reconnect', 'Reconnect');
  const fullscreenLabel = tFallback(t, 'components.kasmVNC.fullscreen', 'Fullscreen');
  const exitFullscreenLabel = tFallback(t, 'components.kasmVNC.exitFullscreen', 'Exit fullscreen');
  const connectingToDesktopLabel = tFallback(
    t,
    'components.kasmVNC.connectingToDesktop',
    'Connecting to desktop…'
  );
  const failedToConnectLabel = tFallback(
    t,
    'components.kasmVNC.failedToConnect',
    'Failed to connect'
  );

  const settings = useRef({
    currentResolution,
    dynamicResize,
    onConnect,
    onDisconnect,
    onError,
    t,
  });
  useLayoutEffect(() => {
    settings.current = { currentResolution, dynamicResize, onConnect, onDisconnect, onError, t };
  });
  useLayoutEffect(() => {
    const target = canvasContainerRef.current;
    if (!target || !availability.available || !projectId || !sandboxId || !wsUrl) return;
    let active = true;
    const owner = availability.owner;
    const captured = settings.current;
    const current = () =>
      active &&
      getWebOperationAvailabilityV2().owner === owner &&
      getWebOperationAvailabilityV2().available;
    const session = new KasmRetainedSessionV2({
      projectId,
      sandboxId,
      wsUrl,
      onAdmitted() {
        const fullscreenTarget = containerRef.current;
        return async () => {
          if (fullscreenTarget && document.fullscreenElement === fullscreenTarget) {
            try {
              await document.exitFullscreen();
            } catch (error) {
              throw new WebOperationCleanupErrorV2([error], 'Kasm fullscreen cleanup failed');
            }
          }
        };
      },
      onStateChange(state) {
        if (current()) setConnectionSnapshot({ identity, state });
      },
      onError() {
        if (current())
          captured.onError?.(
            tFallback(captured.t, 'components.kasmVNC.failedToConnect', 'Failed to connect')
          );
      },
      onDisconnect(reason) {
        if (current()) captured.onDisconnect?.(reason);
      },
      createAttempt(socket, operation, attempt) {
        attempt.check();
        const touchInput = document.createElement('textarea');
        touchInput.style.cssText =
          'position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;';
        touchInput.setAttribute('autocapitalize', 'off');
        touchInput.setAttribute('autocomplete', 'off');
        touchInput.setAttribute('spellcheck', 'false');
        touchInput.setAttribute('tabindex', '-1');
        target.appendChild(touchInput);
        let owned: InstanceType<typeof RFB> | undefined;
        let initializationCleanup: Promise<void> | undefined;
        const removers: Array<() => void> = [];
        let disposed = false;
        const dispose = async () => {
          if (disposed) return;
          disposed = true;
          const errors: unknown[] = [];
          for (const remove of removers) {
            try {
              remove();
            } catch (error) {
              errors.push(error);
            }
          }
          if (viewRef.current?.attempt === attempt) viewRef.current = null;
          try {
            await owned?.dispose();
            await initializationCleanup;
          } catch (error) {
            errors.push(error);
          }
          touchInput.remove();
          if (errors.length) throw new WebOperationCleanupErrorV2(errors, 'Kasm UI cleanup failed');
        };
        try {
          owned = new RFB(target, touchInput, socket, { shared: true });
          const rfb = owned;
          const check = () => {
            if (!current() || disposed) throw new DOMException('Kasm view retired', 'AbortError');
            attempt.check();
          };
          const listen = (name: string, callback: (event: RFBEventDetail) => void) => {
            const guarded = (event: RFBEventDetail) => {
              try {
                check();
              } catch {
                return;
              }
              callback(event);
            };
            rfb.addEventListener(name, guarded);
            removers.push(() => {
              rfb.removeEventListener(name, guarded);
            });
          };
          rfb.scaleViewport = true;
          rfb.resizeSession =
            settings.current.currentResolution === 'auto' && settings.current.dynamicResize;
          rfb.clipViewport = false;
          rfb.background = '#000000';
          rfb.qualityLevel = 8;
          const mapper = new MouseButtonMapper();
          mapper.set(0, XVNC_BUTTONS.LEFT_BUTTON);
          mapper.set(1, XVNC_BUTTONS.MIDDLE_BUTTON);
          mapper.set(2, XVNC_BUTTONS.RIGHT_BUTTON);
          mapper.set(3, XVNC_BUTTONS.BACK_BUTTON);
          mapper.set(4, XVNC_BUTTONS.FORWARD_BUTTON);
          rfb.mouseButtonMapper = mapper;
          listen('connect', () => {
            attempt.connected();
            check();
            captured.onConnect?.();
          });
          listen('disconnect', (event) => {
            const detail = event.detail;
            const reason =
              detail &&
              typeof detail === 'object' &&
              'reason' in detail &&
              typeof detail.reason === 'string'
                ? detail.reason
                : undefined;
            attempt.disconnected(reason);
          });
          listen('credentialsrequired', () => {
            rfb.sendCredentials({ password: '' });
          });
          listen('clipboard', (event) => {
            const detail = event.detail;
            const text =
              detail && typeof detail === 'object' && 'text' in detail ? detail.text : undefined;
            if (typeof text !== 'string') return;
            void attempt
              .runChild(async (child) => {
                child.check();
                check();
                await navigator.clipboard.writeText(text);
                child.check();
                check();
              })
              .catch(() => {
                /* Clipboard access can be denied by the browser. */
              });
          });
          const fullscreen = () => {
            try {
              check();
            } catch {
              return;
            }
            setFullscreenSnapshot({
              identity,
              value: document.fullscreenElement === containerRef.current,
            });
          };
          document.addEventListener('fullscreenchange', fullscreen);
          removers.push(() => {
            document.removeEventListener('fullscreenchange', fullscreen);
          });
          viewRef.current = { rfb, operation, attempt };
          return { dispose };
        } catch (error) {
          // Resource construction failure still has to return its cleanup to the parent drain.
          if (error instanceof RfbInitializationError) initializationCleanup = error.disposal;
          attempt.fail(error instanceof Error ? error : new Error('Kasm initialization failed'));
          return { dispose };
        }
      },
    });
    // Cancel the discarded StrictMode mount before it admits a socket or constructs RFB.
    const connectTimer = setTimeout(() => {
      void session.connect().catch(() => {
        /* Session callbacks report non-retirement failures. */
      });
    }, 0);
    return () => {
      clearTimeout(connectTimer);
      active = false;
      void session.disconnect().catch(() => {
        console.warn('Kasm cleanup failed');
      });
    };
  }, [
    projectId,
    sandboxId,
    wsUrl,
    availability.owner,
    availability.available,
    retryNonce,
    identity,
  ]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    try {
      view.attempt.check();
    } catch {
      return;
    }
    view.rfb.resizeSession = currentResolution === 'auto' && dynamicResize;
    view.rfb.scaleViewport = true;
  }, [currentResolution, dynamicResize]);
  const toggleFullscreen = useCallback(async () => {
    const view = viewRef.current;
    const target = containerRef.current;
    if (!view || !target) return;
    try {
      view.attempt.check();
      await view.attempt.runChild(async (child) => {
        child.check();
        view.attempt.check();
        let failed = false;
        let primary: unknown;
        try {
          if (!document.fullscreenElement) await target.requestFullscreen();
          else await document.exitFullscreen();
          child.check();
          view.attempt.check();
          setFullscreenSnapshot({ identity, value: document.fullscreenElement === target });
        } catch (error) {
          failed = true;
          primary = error;
        }
        if (child.signal.aborted && document.fullscreenElement === target) {
          try {
            await document.exitFullscreen();
          } catch (error) {
            throw new WebOperationCleanupErrorV2([error], 'Kasm fullscreen cleanup failed');
          }
        }
        if (failed) throw primary;
      });
    } catch {
      /* Fullscreen can be denied without a user gesture. */
    }
  }, [identity]);
  const handleResolutionChange = useCallback(
    (value: string) => {
      const view = viewRef.current;
      if (!view) return;
      try {
        view.attempt.check();
      } catch {
        return;
      }
      setCurrentResolution(value);
      onResolutionChange?.(value);
    },
    [onResolutionChange]
  );
  const handleReconnect = useCallback(() => {
    if (!getWebOperationAvailabilityV2().available) return;
    setRetryNonce((value) => value + 1);
  }, []);

  const containerStyle: React.CSSProperties = isFullscreen
    ? { position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', zIndex: 50 }
    : { height: '100%', position: 'relative', width: '100%' };

  const resolutionOptions = useMemo(
    () =>
      RESOLUTION_PRESETS.map((option) =>
        option.value === 'auto'
          ? {
              ...option,
              label: tFallback(t, 'components.kasmVNC.autoResolution', 'Auto (fit panel)'),
            }
          : option
      ),
    [t]
  );

  const statusConfig: Record<ConnectionState, { color: string; text: string }> = {
    disconnected: {
      color: '#888',
      text: tFallback(t, 'components.kasmVNC.status.disconnected', 'Disconnected'),
    },
    connecting: {
      color: '#faad14',
      text: tFallback(t, 'components.kasmVNC.status.connecting', 'Connecting…'),
    },
    connected: {
      color: '#52c41a',
      text: tFallback(t, 'components.kasmVNC.status.connected', 'Connected'),
    },
    error: {
      color: '#ff4d4f',
      text: tFallback(t, 'components.kasmVNC.status.error', 'Error'),
    },
  };

  const status = statusConfig[connectionState];

  return (
    <div
      ref={containerRef}
      className={`flex flex-col bg-gray-900 ${isFullscreen ? 'fixed inset-0 z-50' : ''}`}
      style={containerStyle}
    >
      {/* Toolbar */}
      {showToolbar && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700 shrink-0">
          <div className="flex items-center gap-2">
            <Monitor size={16} className="text-gray-400" />
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ backgroundColor: status.color }}
            />
            <span className="text-xs text-gray-400">{status.text}</span>
          </div>

          <Space size="small">
            {/* Resolution selector */}
            {dynamicResize && (
              <Select
                size="small"
                value={currentResolution}
                onChange={handleResolutionChange}
                options={resolutionOptions}
                className="w-36"
                popupMatchSelectWidth={false}
                suffix={<Maximize2 size={16} className="text-gray-400" />}
              />
            )}

            {/* Audio toggle */}
            <Tooltip title={isMuted ? unmuteAudioLabel : muteAudioLabel}>
              <Button
                type="text"
                size="small"
                icon={isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
                onClick={() => {
                  setIsMuted((prev) => !prev);
                }}
                className={`text-gray-400 hover:text-white ${!isMuted ? '!text-blue-400' : ''}`}
                aria-label={isMuted ? unmuteAudioLabel : muteAudioLabel}
              />
            </Tooltip>

            {/* Reconnect */}
            <Tooltip title={reconnectLabel}>
              <Button
                type="text"
                size="small"
                icon={<RefreshCw size={16} />}
                onClick={handleReconnect}
                disabled={connectionState === 'connecting'}
                className="text-gray-400 hover:text-white"
                aria-label={reconnectLabel}
              />
            </Tooltip>

            {/* Fullscreen */}
            <Tooltip title={isFullscreen ? exitFullscreenLabel : fullscreenLabel}>
              <Button
                type="text"
                size="small"
                icon={isFullscreen ? <Minimize size={16} /> : <Maximize size={16} />}
                onClick={() => {
                  void toggleFullscreen();
                }}
                className="text-gray-400 hover:text-white"
                aria-label={isFullscreen ? exitFullscreenLabel : fullscreenLabel}
              />
            </Tooltip>
          </Space>
        </div>
      )}

      {/* VNC canvas container */}
      <div className="flex-1 relative bg-black overflow-hidden">
        {connectionState === 'connecting' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-slate-950/60 z-10 pointer-events-none">
            <Loader2 className="animate-spin motion-reduce:animate-none" size={32} />
            <span className="text-white text-sm">{connectingToDesktopLabel}</span>
          </div>
        )}

        {(connectionState === 'error' || connectionState === 'disconnected') && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 z-10">
            <Unplug size={36} className="text-gray-500" />
            <span className="text-gray-400">
              {connectionState === 'error' ? failedToConnectLabel : statusConfig.disconnected.text}
            </span>
            <Button size="small" onClick={handleReconnect}>
              {reconnectLabel}
            </Button>
          </div>
        )}

        <div
          ref={canvasContainerRef}
          className="w-full h-full"
          style={{ touchAction: 'none', userSelect: 'none' }}
          onDragStart={(e) => {
            e.preventDefault();
          }}
        />
      </div>
    </div>
  );
}

export default KasmVNCViewer;
