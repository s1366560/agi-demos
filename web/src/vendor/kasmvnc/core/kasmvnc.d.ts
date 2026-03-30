/**
 * Type declarations for vendored KasmVNC noVNC fork
 *
 * KasmVNC uses a proprietary fork of noVNC with additional features:
 * - WebP/QOI encoding support
 * - Extended mouse button mapping
 * - Custom protocol extensions
 */

declare module '@/vendor/kasmvnc/core/rfb.js' {
  export interface RFBOptions {
    wsProtocols?: string[];
    shared?: boolean;
  }

  export interface Credentials {
    password: string;
    username?: string;
  }

  export interface RFBEventDetail {
    detail: unknown;
  }

  export interface ConnectEvent extends RFBEventDetail {
    // eslint-disable-next-line @typescript-eslint/no-empty-object-type
    detail: {};
  }

  export interface DisconnectEvent extends RFBEventDetail {
    detail: {
      clean: boolean;
      reason?: string;
    };
  }

  export interface CredentialsRequiredEvent extends RFBEventDetail {
     
    detail: Record<string, never>;
  }

  export interface DesktopNameEvent extends RFBEventDetail {
    detail: {
      name: string;
    };
  }

  export interface ClipboardEvent extends RFBEventDetail {
    detail: {
      text: string;
    };
  }

  export interface WebSocketLike {
    close(): void;
  }

  /**
   * KasmVNC RFB (Remote Framebuffer) client
   *
   * Main class for establishing and managing VNC connections.
   * Constructor takes (targetElement, touchInputElement, url, options).
   */
  export default class RFB {
    constructor(
      target: HTMLElement,
      touchInput: HTMLTextAreaElement,
      url: string,
      options?: RFBOptions
    );

    // Public properties
    scaleViewport: boolean;
    resizeSession: boolean;
    clipViewport: boolean;
    background: string;
    qualityLevel: number;
    mouseButtonMapper: MouseButtonMapper;

    // Internal state (accessed for cleanup)
    _rfbConnectionState: '' | 'connecting' | 'connected' | 'disconnected';
    _sock: WebSocketLike | null;

    // Public methods
    disconnect(): void;
    sendCredentials(credentials: Credentials): void;
    addEventListener(event: 'connect', handler: (e: ConnectEvent) => void): void;
    addEventListener(event: 'disconnect', handler: (e: DisconnectEvent) => void): void;
    addEventListener(
      event: 'credentialsrequired',
      handler: (e: CredentialsRequiredEvent) => void
    ): void;
    addEventListener(event: 'desktopname', handler: (e: DesktopNameEvent) => void): void;
    addEventListener(event: 'clipboard', handler: (e: ClipboardEvent) => void): void;
    addEventListener(event: string, handler: (e: RFBEventDetail) => void): void;
  }
}

declare module '@/vendor/kasmvnc/core/mousebuttonmapper.js' {
  /**
   * Mouse button mapper for KasmVNC
   *
   * Maps physical mouse buttons to X VNC button codes.
   */
  export interface XVNCButtons {
    LEFT_BUTTON: number;
    MIDDLE_BUTTON: number;
    RIGHT_BUTTON: number;
    BACK_BUTTON: number;
    FORWARD_BUTTON: number;
  }

  export const XVNC_BUTTONS: XVNCButtons;

  export default class MouseButtonMapper {
    set(buttonIndex: number, vncButtonCode: number): void;
  }
}
